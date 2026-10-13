"""
evaluation/export_feedback.py — answers rated "not helpful", as candidate questions for the
evaluation dataset (Sprint 8, item 5; audit 7.18).

Run from backend/:
  python -m src.evaluation.export_feedback
  python -m src.evaluation.export_feedback --output some/folder/candidates.jsonl

Each thumbs-down turn becomes one line in the shape of a dataset.jsonl line (see evaluate.py),
with what only a person can say left empty, and what the app answered beside it:
  {"id": "fb17", "question": "...", "expected_answer": "", "source": "", "page": null,
   "answer_given": "...", "sources_given": [...], "mode": "hybrid", "asked_at": "..."}
Nothing is added to the dataset. To use a line, fill in the expected answer and the source
and page (or set "answerable": false), remove the *_given, mode and asked_at fields, and copy
it into dataset.jsonl yourself. The file is written afresh each time.

The lines hold users' questions, so they are written under the data folder at the project
root, which git ignores, and never printed or logged: the command says only how many it wrote
and where.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.config import DATA_DIR, settings
from src.db.database import get_turns_rated

DEFAULT_OUTPUT = DATA_DIR / "feedback_candidates.jsonl"
NOT_HELPFUL = -1


def candidate(turn: Dict[str, Any]) -> Dict[str, Any]:
    """A dataset line to be labelled, for one turn rated not helpful."""
    return {
        "id": f"fb{turn['id']}",
        "question": turn["question"],
        "expected_answer": "",
        "source": "",
        "page": None,
        "answer_given": turn["answer"],
        "sources_given": [{k: s.get(k) for k in ("source", "page", "score")} for s in turn["sources"]],
        "mode": turn["mode"],
        "asked_at": turn["created_at"],
    }


def export(output: Path) -> int:
    """Write every thumbs-down turn to output as one JSON line each. Returns how many."""
    lines: List[str] = [json.dumps(candidate(t), ensure_ascii=False) for t in get_turns_rated(NOT_HELPFUL)]
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return len(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Write the answers rated not helpful as candidate dataset lines.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"the file to write (default: {DEFAULT_OUTPUT}); it holds users' questions")
    args = parser.parse_args(argv)
    if not Path(settings.db_path).is_file():
        print(f"No database at {settings.db_path}.", file=sys.stderr)
        return 1
    count = export(args.output)
    print(f"Wrote {count} candidate{'' if count == 1 else 's'} to {args.output}. "
          "Label them before copying any into dataset.jsonl.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
