"""AdProof Remediator specialist agent."""
from agents._worker_main import build

agent = build("remediator")

if __name__ == "__main__":
    agent.run()
