"""Eval harness skeleton.

For each question in questions.jsonl:
  1. Run the gold SQL on the read-only role to get the expected result.
  2. Ask the agent (POST /ask) and compare its answer to the expected result.
  3. Write per-question results + aggregate accuracy to evals/results/.

Comparison logic (numeric tolerance, set equality, citation checks) is implemented in week 3.
"""

import json
from pathlib import Path

QUESTIONS = Path(__file__).parent / "questions.jsonl"


def load_questions() -> list[dict]:
    return [json.loads(line) for line in QUESTIONS.read_text().splitlines() if line.strip()]


if __name__ == "__main__":
    qs = load_questions()
    print(f"Loaded {len(qs)} eval questions. Scoring not implemented yet.")
