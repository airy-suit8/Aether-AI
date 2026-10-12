"""
evaluation/evaluate.py — measure the real pipeline on a labelled dataset (T3).

Run from backend/:
  python -m src.evaluation.evaluate --label baseline
  python -m src.evaluation.evaluate --label baseline --retrieval-only    (embedding calls only)

What it does
  1. Reads the dataset (one JSON object per line) and ingests the documents beside it through
     the app's own ingestion, into a temporary store: the app's database and vector store are
     never opened.
  2. Asks every question through the app's own pipeline (pipeline/rag.py), once per mode.
  3. Scores the answers, writes docs/evaluation/<label>.json, and rebuilds docs/evaluation.md
     from every result in that folder, so runs can be compared side by side.

A dataset line
  {"id": "q01", "question": "...", "expected_answer": "...", "source": "handbook.pdf", "page": 3}
  {"id": "u01", "question": "...", "answerable": false}
An answerable line may give "pages": [3, 4] in place of "page", and "contains": "a phrase" that
the right chunk must include (for files without pages). The documents are the files in the
"documents" folder next to the dataset, or the folder given with --documents.

Nothing is defaulted. A line that cannot be read, a document that is missing, or a judge reply
that cannot be parsed stops the run with an error. "How each number is computed" is written
into the report itself (REPORT_NOTES below).
"""

import argparse
import json
import re
import statistics
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from langchain_core.output_parsers import StrOutputParser

from src.core.config import BACKEND_DIR, settings
from src.db.database import create_user, init_db
from src.llm import llm_client
from src.pipeline import rag
from src.pipeline.documents import ingest_document
from src.prompts.prompt_templates import JUDGE_CORRECTNESS_PROMPT, JUDGE_FAITHFULNESS_PROMPT, format_context

DEFAULT_DATASET = Path(__file__).parent / "dataset.jsonl"
RESULTS_DIR = BACKEND_DIR.parent / "docs" / "evaluation"
REPORT_FILE = BACKEND_DIR.parent / "docs" / "evaluation.md"
MODES = ("default", "hybrid")


class EvaluationError(Exception):
    """The run cannot produce an honest number, so it stops instead of guessing one."""


# ── The dataset ───────────────────────────────────────────────────────────────

def _problem(item: Any, seen: set) -> Optional[str]:
    if not isinstance(item, dict):
        return "not a JSON object"
    required = ["id", "question"] + (["expected_answer", "source"] if item.get("answerable", True) else [])
    for field in required:
        if not isinstance(item.get(field), str) or not item[field].strip():
            return f'"{field}" is missing or empty'
    if item["id"] in seen:
        return f'the id "{item["id"]}" is used twice'
    return None


def load_dataset(path: Path) -> List[Dict[str, Any]]:
    """Read and check the dataset. Each item gets "answerable" (bool) and "pages" (a list)."""
    path = Path(path)
    if not path.is_file():
        raise EvaluationError(
            f"No dataset at {path}. Write one question per line (the format is at the top of "
            f"src/evaluation/evaluate.py) and put its documents in a 'documents' folder beside it."
        )
    items, seen = [], set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError as e:
            raise EvaluationError(f"{path.name}, line {number}: not valid JSON ({e})") from e
        problem = _problem(item, seen)
        if problem:
            raise EvaluationError(f"{path.name}, line {number}: {problem}")
        seen.add(item["id"])
        item["answerable"] = bool(item.get("answerable", True))
        item["pages"] = list(item.get("pages") or ([item["page"]] if "page" in item else []))
        items.append(item)
    if not items:
        raise EvaluationError(f"{path.name} has no questions")
    return items


# ── Retrieval: was the right chunk found, and how high? ──────────────────────

def _squash(text: str) -> str:
    return " ".join(text.lower().split())


def is_relevant(hit: Dict[str, Any], item: Dict[str, Any]) -> bool:
    """A chunk counts when it is from the labelled file, on a labelled page (if any are given)
    and holds the labelled phrase (if one is given)."""
    if hit["meta"].get("source") != item["source"]:
        return False
    if item["pages"] and hit["meta"].get("page") not in item["pages"]:
        return False
    return not item.get("contains") or _squash(item["contains"]) in _squash(hit["text"])


def first_relevant_rank(hits: List[Dict[str, Any]], item: Dict[str, Any]) -> Optional[int]:
    """The 1-based position of the first right chunk, or None when none was retrieved."""
    return next((rank for rank, hit in enumerate(hits, 1) if is_relevant(hit, item)), None)


# ── The judge: a model that did not write the answer ─────────────────────────

def require_judge() -> None:
    if not settings.judge_model:
        raise EvaluationError(
            "AETHER_JUDGE_MODEL is not set. Answers must be scored by a model other than "
            f"{settings.llm_model}; set it in backend/.env, or pass --retrieval-only."
        )
    if settings.judge_model == settings.llm_model:
        raise EvaluationError(
            f"AETHER_JUDGE_MODEL is {settings.judge_model}, the model that writes the answers. "
            "A model scoring its own answers is not a measurement; choose another."
        )


def parse_score(reply: str) -> float:
    """The "score" in the judge's JSON reply. Raises when there is none: no default scores."""
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    try:
        score = json.loads(match.group(0))["score"]
    except (AttributeError, ValueError, KeyError, TypeError) as e:
        raise EvaluationError(f"The judge's reply could not be read as a score: {reply[:200]!r}") from e
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
        raise EvaluationError(f"The judge gave a score that is not a number from 0 to 1: {score!r}")
    return float(score)


def judge(prompt, **inputs: str) -> float:
    llm = llm_client.get_llm(temperature=settings.tool_temperature, model=settings.judge_model)
    return parse_score((prompt | llm | StrOutputParser()).invoke(inputs))


# ── One question ──────────────────────────────────────────────────────────────

def ask(user_id: int, item: Dict[str, Any], mode: str, retrieval_only: bool) -> Dict[str, Any]:
    """Put one question through the real pipeline in one mode and score what came back."""
    trace = rag.Trace()
    if retrieval_only:
        with trace.stage("retrieve"):
            trace.hits = rag.retrieve(mode, user_id, item["question"])
        # What the threshold alone would do; no model is asked
        trace.refused = max((h["score"] for h in trace.hits), default=0.0) < settings.confidence_threshold
        answer = ""
    else:
        # A session of its own, so no earlier question arrives as conversation history
        answer = rag.answer(user_id, item["question"], session_id=f"eval-{uuid.uuid4().hex}", mode=mode, trace=trace)["answer"]

    record = {
        "id": item["id"], "mode": mode, "answerable": item["answerable"],
        "best_score": round(max((h["score"] for h in trace.hits), default=0.0), 4),
        "refused": trace.refused, "stages": trace.stages,
    }
    if item["answerable"]:
        record["rank"] = first_relevant_rank(trace.hits, item)
        if not retrieval_only:
            # A refusal of an answerable question is a wrong answer; it makes no claim to check
            record["correctness"] = 0.0 if trace.refused else judge(
                JUDGE_CORRECTNESS_PROMPT, question=item["question"], expected=item["expected_answer"], answer=answer)
            if not trace.refused:
                record["faithfulness"] = judge(JUDGE_FAITHFULNESS_PROMPT, context=format_context(trace.hits), answer=answer)
    return record


# ── Totals ────────────────────────────────────────────────────────────────────

def _mean(values: Iterable[float]) -> Optional[float]:
    values = list(values)
    return round(sum(values) / len(values), 3) if values else None


def summarise(records: List[Dict[str, Any]], k: int) -> Dict[str, Any]:
    """The totals for one mode. A measure with nothing to average is None, never a made-up value."""
    answerable = [r for r in records if r["answerable"]]
    unanswerable = [r for r in records if not r["answerable"]]
    stage_names = sorted({name for r in records for name in r["stages"]})
    stages = {}
    for name in stage_names:
        rows = [r["stages"][name] for r in records if name in r["stages"]]
        stages[name] = {
            "median_seconds": round(statistics.median(row["seconds"] for row in rows), 3),
            "mean_input_tokens": _mean(row["input_tokens"] for row in rows),
            "mean_output_tokens": _mean(row["output_tokens"] for row in rows),
        }
    return {
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        "hit_at_k": _mean(1.0 if r["rank"] and r["rank"] <= k else 0.0 for r in answerable),
        "mrr": _mean(1.0 / r["rank"] if r["rank"] else 0.0 for r in answerable),
        "unanswerable_refused": _mean(1.0 if r["refused"] else 0.0 for r in unanswerable),
        "answerable_refused": _mean(1.0 if r["refused"] else 0.0 for r in answerable),
        "correctness": _mean(r["correctness"] for r in answerable if "correctness" in r),
        "faithfulness": _mean(r["faithfulness"] for r in answerable if "faithfulness" in r),
        "stages": stages,
    }


def suggest_threshold(records: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    The cut on the best retrieval score that best separates answerable from unanswerable questions.

    Every midpoint between two neighbouring scores is tried. The cut kept is the one with the most
    questions on the right side (answerable at or above it, unanswerable below it); between
    equally good cuts, the one furthest from any score. None when either kind of question is missing.
    """
    yes = sorted(r["best_score"] for r in records if r["answerable"])
    no = sorted(r["best_score"] for r in records if not r["answerable"])
    scores = sorted(set(yes + no))
    if not yes or not no or len(scores) < 2:
        return None

    def right_side(cut: float) -> int:
        return sum(s >= cut for s in yes) + sum(s < cut for s in no)

    cuts = [(a + b) / 2 for a, b in zip(scores, scores[1:])]
    best = max(cuts, key=lambda cut: (right_side(cut), min(abs(cut - s) for s in scores)))
    return {
        "threshold": round(best, 3),
        "correct": right_side(best),
        "of": len(yes) + len(no),
        "answerable_lowest": yes[0],
        "answerable_median": round(statistics.median(yes), 4),
        "unanswerable_highest": no[-1],
        "unanswerable_median": round(statistics.median(no), 4),
    }


# ── A whole run ───────────────────────────────────────────────────────────────

def run(dataset_path: Path, documents_dir: Path, label: str, modes: Iterable[str] = MODES,
        retrieval_only: bool = False, pause: float = 0.0, log=print) -> Dict[str, Any]:
    """Ingest the documents, ask every question in every mode, and return the result to save."""
    items = load_dataset(dataset_path)
    modes = list(modes)
    if not retrieval_only:
        require_judge()  # before any quota is spent

    documents_dir = Path(documents_dir)
    files = sorted(p for p in documents_dir.iterdir() if p.is_file()) if documents_dir.is_dir() else []
    missing = sorted({i["source"] for i in items if i["answerable"]} - {p.name for p in files})
    if missing:
        raise EvaluationError(f"The dataset names documents that are not in {documents_dir}: {', '.join(missing)}")

    user_id = create_user(f"evaluation_{uuid.uuid4().hex[:12]}", "not-a-password-hash")
    for path in files:
        stats = ingest_document(user_id, str(path), path.name)
        log(f"ingested {path.name}: {stats['pages']} page(s), {stats['chunks']} chunks")

    records = []
    for mode in modes:
        for number, item in enumerate(items, 1):
            records.append(ask(user_id, item, mode, retrieval_only))
            log(f"{mode} {number}/{len(items)} {item['id']}")
            if pause:
                time.sleep(pause)

    return {
        "label": label,
        "created": datetime.now().isoformat(timespec="seconds"),
        "retrieval_only": retrieval_only,
        "dataset": {"file": Path(dataset_path).name, "questions": len(items), "documents": [p.name for p in files]},
        "settings": {
            "llm_model": settings.llm_model, "judge_model": "" if retrieval_only else settings.judge_model,
            "embedding_model": settings.embedding_model, "top_k": settings.top_k,
            "confidence_threshold": settings.confidence_threshold,
            "chunk_size": settings.chunk_size, "chunk_overlap": settings.chunk_overlap,
        },
        "modes": {mode: summarise([r for r in records if r["mode"] == mode], settings.top_k) for mode in modes},
        # From dense scores only: the threshold is applied to dense similarity
        "threshold": suggest_threshold([r for r in records if r["mode"] == "default"]),
        "questions": records,
    }


# ── The report ────────────────────────────────────────────────────────────────

REPORT_NOTES = """## How each number is computed

- **hit@k**: the share of answerable questions for which at least one of the top k retrieved chunks is a right one. A chunk is right when it comes from the file the dataset names, from one of the pages it names (when it names any), and contains the phrase it gives (when it gives one). k is the app's `top_k`.
- **MRR** (mean reciprocal rank): for each answerable question, 1 divided by the position of the first right chunk (1 for first place, 0.5 for second, 0 when none was retrieved), averaged.
- **Unanswerable refused**: the share of questions the documents cannot answer that the app declined to answer. Higher is better.
- **Answerable refused**: the share of questions the documents can answer that the app declined anyway. Lower is better.
- **Correctness**: a judge model compares each answer with the expected answer and gives 1 (every fact), 0.5 (some) or 0 (none, wrong, or declined); a refused answerable question counts 0 without asking the judge. Averaged over the answerable questions.
- **Faithfulness**: the judge model reads the retrieved chunks and the answer and gives the share of the answer's claims the chunks support. Averaged over the answerable questions that were answered.
- **The judge** is a different model from the one that writes the answers. A judge reply that cannot be parsed stops the run; no score is ever filled in.
- **Seconds** are the median per question for each stage. **Tokens** are the mean per question, in and out, summed over the model calls of the stage, as the model reports them.
- **Suggested threshold**: the best retrieval score of each question is taken in dense mode. Every cut between two neighbouring scores is tried; the suggestion is the cut that puts the most questions on the right side (answerable at or above, unanswerable below).
- In a **retrieval-only** run no answer is generated: correctness, faithfulness and model tokens are not measured, and "refused" means the best score fell below the threshold.
"""


def write_result(result: Dict[str, Any], results_dir: Path) -> Path:
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"{re.sub(r'[^A-Za-z0-9._-]+', '-', result['label'])}.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return path


def _show(value: Optional[float], digits: int = 2) -> str:
    return "not measured" if value is None else f"{value:.{digits}f}"


def build_report(results_dir: Path) -> str:
    """The Markdown report for every saved result, oldest first, one column per run and mode."""
    results = sorted((json.loads(p.read_text(encoding="utf-8")) for p in Path(results_dir).glob("*.json")),
                     key=lambda r: r["created"])
    columns = [(r, mode, totals) for r in results for mode, totals in r["modes"].items()]
    stage_names = sorted({name for _, _, totals in columns for name in totals["stages"]})

    def row(title: str, cell) -> str:
        return f"| {title} | " + " | ".join(cell(r, totals) for r, _, totals in columns) + " |"

    def tokens(totals: Dict[str, Any]) -> str:
        used = totals["stages"].values()
        total_in = sum(s["mean_input_tokens"] or 0 for s in used)
        total_out = sum(s["mean_output_tokens"] or 0 for s in used)
        return f"{total_in:.0f} / {total_out:.0f}" if total_in or total_out else "not measured"

    lines = [
        "# Evaluation",
        "",
        "Rebuilt by `python -m src.evaluation.evaluate` (run from `backend/`) from the results in "
        "`docs/evaluation/`. Do not edit it by hand.",
        "",
        "## Results",
        "",
        "| Measure | " + " | ".join(f"{r['label']} · {mode}" for r, mode, _ in columns) + " |",
        "|---|" + "---|" * len(columns),
        row("Questions (answerable + unanswerable)", lambda r, t: f"{t['answerable'] + t['unanswerable']} ({t['answerable']} + {t['unanswerable']})"),
        row(f"hit@{results[0]['settings']['top_k']}" if results else "hit@k", lambda r, t: _show(t["hit_at_k"])),
        row("MRR", lambda r, t: _show(t["mrr"])),
        row("Unanswerable refused", lambda r, t: _show(t["unanswerable_refused"])),
        row("Answerable refused", lambda r, t: _show(t["answerable_refused"])),
        row("Correctness", lambda r, t: _show(t["correctness"])),
        row("Faithfulness", lambda r, t: _show(t["faithfulness"])),
    ]
    for name in stage_names:
        lines.append(row(f"Seconds, {name} (median)", lambda r, t, name=name: _show(t["stages"].get(name, {}).get("median_seconds"))))
    lines += [row("Tokens in / out per question (mean)", lambda r, t: tokens(t)), "", "## Runs", ""]
    lines += [
        "| Run | Date | Questions | Answers by | Judged by | Embeddings | top k | Threshold in use | Chunk size / overlap | Suggested threshold |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        s, t = r["settings"], r["threshold"]
        suggested = (f"{t['threshold']} ({t['correct']} of {t['of']} on the right side; answerable from "
                     f"{t['answerable_lowest']}, unanswerable up to {t['unanswerable_highest']})") if t else "not enough data"
        lines.append(
            f"| {r['label']} | {r['created'][:10]} | {r['dataset']['questions']} | "
            f"{'no answers (retrieval only)' if r['retrieval_only'] else s['llm_model']} | "
            f"{s['judge_model'] or 'not judged'} | {s['embedding_model']} | {s['top_k']} | "
            f"{s['confidence_threshold']} | {s['chunk_size']} / {s['chunk_overlap']} | {suggested} |"
        )
    return "\n".join(lines + ["", REPORT_NOTES])


# ── Command line ──────────────────────────────────────────────────────────────

def use_temporary_store() -> None:
    """Point the app at an empty database and vector store in a temp folder, before either opens."""
    folder = Path(tempfile.mkdtemp(prefix="aether_eval_"))
    settings.db_path = folder / "evaluation.db"
    settings.vector_store_dir = folder / "vector_store"
    init_db()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Measure the RAG pipeline on a labelled dataset.")
    parser.add_argument("--label", required=True, help="a name for this run, for example baseline")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="the questions, one JSON object per line")
    parser.add_argument("--documents", type=Path, help="the folder of documents (default: 'documents' beside the dataset)")
    parser.add_argument("--modes", default=",".join(MODES), help="comma-separated: default, hybrid, langchain")
    parser.add_argument("--retrieval-only", action="store_true", help="measure retrieval only: no answers, no judge")
    parser.add_argument("--pause", type=float, default=0.0, help="seconds to wait between questions (for rate limits)")
    args = parser.parse_args(argv)

    try:
        use_temporary_store()
        result = run(args.dataset, args.documents or args.dataset.parent / "documents", args.label,
                     modes=[m.strip() for m in args.modes.split(",") if m.strip()],
                     retrieval_only=args.retrieval_only, pause=args.pause)
    except EvaluationError as e:
        print(f"Evaluation stopped: {e}", file=sys.stderr)
        return 1

    saved = write_result(result, RESULTS_DIR)
    report = build_report(RESULTS_DIR)
    REPORT_FILE.write_text(report, encoding="utf-8")
    print(report.split("## Runs")[0].split("## Results")[1].strip())
    print(f"\nSaved {saved} and rebuilt {REPORT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
