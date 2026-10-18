"""AdProof Verifier specialist agent."""
from agents._worker_main import build

agent = build("verifier")

if __name__ == "__main__":
    agent.run()
