"""Turn fetched bytes into safe, frozen inputs: page text snapshots and model-ready images."""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup
from PIL import Image, ImageSequence, UnidentifiedImageError

from ..domain.models import FrozenImage

MAX_TEXT_CHARS = 30_000
MAX_PIXELS = 16_000_000
MAX_SIDE = 8192
Image.MAX_IMAGE_PIXELS = MAX_PIXELS  # PIL raises on bombs above this


class ContentError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace(" ", " ")).strip()


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    url: str
    text: str
    content_sha256: str
    truncated: bool


def html_to_snapshot(url: str, body: bytes) -> Snapshot:
    if body[:5] == b"\x89PNG\r" or body[:3] == b"\xff\xd8\xff":
        raise ContentError("NOT_HTML", "The landing page URL returned an image, not a page.")
    soup = BeautifulSoup(body.decode("utf-8", errors="replace"), "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "template", "iframe", "svg"]):
        tag.decompose()
    text = normalize(soup.get_text(" "))
    if not text:
        raise ContentError("EMPTY_PAGE", "The landing page has no readable text.")
    truncated = len(text) > MAX_TEXT_CHARS
    text = text[:MAX_TEXT_CHARS]
    digest = sha256(text.encode())
    return Snapshot(snapshot_id=f"snap_{digest[:12]}", url=url, text=text, content_sha256=digest, truncated=truncated)


def quote_in_source(quote: str, source_text: str) -> bool:
    """A cited quote must literally occur in the frozen normalized source text (case-insensitive)."""
    q = normalize(quote).lower().strip(" .\"'“”")
    return len(q) >= 3 and q in normalize(source_text).lower()


def freeze_image(body: bytes, source_url: str) -> tuple[FrozenImage, bytes]:
    if body.lstrip()[:1] == b"<":
        raise ContentError("NOT_AN_IMAGE", "The image URL returned HTML, not an image.")
    try:
        img = Image.open(io.BytesIO(body))
        fmt = (img.format or "").upper()
        if fmt not in ("PNG", "JPEG"):
            raise ContentError("UNSUPPORTED_IMAGE", f"Only PNG and JPEG are supported (got {fmt or 'unknown'}).")
        if getattr(img, "is_animated", False) or sum(1 for _ in ImageSequence.Iterator(img)) > 1:
            raise ContentError("UNSUPPORTED_IMAGE", "Animated images are not supported.")
        w, h = img.size
        if w * h > MAX_PIXELS or max(w, h) > MAX_SIDE:
            raise ContentError("IMAGE_TOO_LARGE", f"Image is {w}x{h}; limit is 16 MP and 8192 px per side.")
        img.load()
    except Image.DecompressionBombError as exc:
        raise ContentError("IMAGE_TOO_LARGE", "Image exceeds the decompression limit.") from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise ContentError("INVALID_IMAGE", "The file is not a valid PNG or JPEG image.") from exc
    clean = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
    out = io.BytesIO()
    clean.save(out, format="PNG")  # re-encode: drops EXIF/text metadata
    model_bytes = out.getvalue()
    return FrozenImage(source_image_sha256=sha256(body), model_input_sha256=sha256(model_bytes),
                       source_url=source_url, width=w, height=h, source_format=fmt), model_bytes
