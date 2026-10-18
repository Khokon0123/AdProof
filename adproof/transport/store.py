"""Small SQLite store: audit ownership, idempotency, seen messages. Private; never committed."""
from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

TTL_S = 24 * 3600


class Store:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript("""
            CREATE TABLE IF NOT EXISTS audits(audit_id TEXT PRIMARY KEY, owner TEXT NOT NULL, request_key TEXT,
              payload_hash TEXT, input_json TEXT, report_json TEXT, status TEXT, repaired INTEGER DEFAULT 0,
              created REAL);
            CREATE INDEX IF NOT EXISTS audits_req ON audits(owner, request_key);
            CREATE TABLE IF NOT EXISTS seen(key TEXT PRIMARY KEY, created REAL);
            """)
            # Startup: anything left running was interrupted; never auto-repeat external calls.
            self._db.execute("UPDATE audits SET status='WORKFLOW_INTERRUPTED' WHERE status='RUNNING'")
            self._db.execute("DELETE FROM audits WHERE created < ?", (time.time() - TTL_S,))
            self._db.commit()

    @staticmethod
    def payload_hash(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def first_time(self, key: str) -> bool:
        with self._lock:
            try:
                self._db.execute("INSERT INTO seen(key, created) VALUES(?, ?)", (key, time.time()))
                self._db.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def find_request(self, owner: str, request_key: str) -> Optional[tuple[str, str, Optional[str], str]]:
        with self._lock:
            return self._db.execute("SELECT audit_id, payload_hash, report_json, status FROM audits WHERE owner=? "
                                    "AND request_key=?", (owner, request_key)).fetchone()

    def start(self, audit_id: str, owner: str, request_key: str, payload_hash: str, input_json: str) -> None:
        with self._lock:
            self._db.execute("INSERT INTO audits(audit_id, owner, request_key, payload_hash, input_json, status, "
                             "created) VALUES(?,?,?,?,?, 'RUNNING', ?)",
                             (audit_id, owner, request_key, payload_hash, input_json, time.time()))
            self._db.commit()

    def finish(self, audit_id: str, report_json: str, status: str, repaired: bool = False) -> None:
        with self._lock:
            self._db.execute("UPDATE audits SET report_json=?, status=?, repaired=MAX(repaired, ?) WHERE audit_id=?",
                             (report_json, status, int(repaired), audit_id))
            self._db.commit()

    def get(self, audit_id: str, owner: str) -> Optional[dict]:
        """Only the owner (the ASI:One sender who started it) can read an audit."""
        with self._lock:
            row = self._db.execute("SELECT audit_id, input_json, report_json, status, repaired, created FROM audits "
                                   "WHERE audit_id=? AND owner=?", (audit_id, owner)).fetchone()
        if not row:
            return None
        return dict(zip(("audit_id", "input_json", "report_json", "status", "repaired", "created"), row))
