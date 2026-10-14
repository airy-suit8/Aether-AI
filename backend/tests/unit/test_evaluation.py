"""
The evaluation harness (T3): it asks the real pipeline, scores from labels, uses a judge that is
not the answering model, and stops instead of filling in a number it could not measure.
"""

import json

import pytest

from src.core.config import settings
from src.evaluation import evaluate
from src.evaluation.evaluate import EvaluationError
from src.llm import llm_client
from helpers import DOC_TEXT

CANTEEN_TEXT = "Lunch is served in the canteen at noon. The canteen is closed on Sundays."

QUESTIONS = [
    {"id": "q1", "question": "How often is the Zephyr turbine blade inspection?", "expected_answer": "Every 90 days.",
     "source": "zephyr_manual.txt", "page": 1, "contains": "every 90 days"},
    {"id": "q2", "question": "When is lunch served in the canteen?", "expected_answer": "At noon.",
     "source": "canteen.txt"},
    {"id": "u1", "question": "Quantum chromodynamics lagrangian?", "answerable": False},
]


@pytest.fixture
def dataset(tmp_path):
    """A dataset file with its documents folder beside it."""
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "zephyr_manual.txt").write_text(DOC_TEXT, encoding="utf-8")
    (documents / "canteen.txt").write_text(CANTEEN_TEXT, encoding="utf-8")
    path = tmp_path / "dataset.jsonl"
    path.write_text("\n".join(json.dumps(q) for q in QUESTIONS) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def judge_model(monkeypatch):
    monkeypatch.setattr(settings, "judge_model", "a-judge-model")


def run(dataset, **kwargs):
    return evaluate.run(dataset, dataset.parent / "documents", "test", log=lambda line: None, **kwargs)


# ── The whole run, through the real pipeline ──────────────────────────────────

def test_run_asks_the_real_pipeline_and_scores_it(dataset, judge_model, fake_llm, monkeypatch):
    monkeypatch.setattr(settings, "answer_from", "summary")  # the pipeline with its summary step
    # Seam checklist: "Evaluation: the harness imports and calls the real pipeline"
    models_asked = []

    def get_llm(**kwargs):
        models_asked.append(kwargs.get("model"))
        return fake_llm

    monkeypatch.setattr(llm_client, "get_llm", get_llm)
    result = run(dataset)

    for mode in ("default", "hybrid"):
        totals = result["modes"][mode]
        assert (totals["answerable"], totals["unanswerable"]) == (2, 1)
        assert totals["hit_at_k"] == 1.0 and totals["mrr"] == 1.0
        assert totals["answerable_refused"] == 0.0
        assert totals["correctness"] == 1.0 and totals["faithfulness"] == 1.0
    # Dense search finds nothing close to the off-topic question, so the threshold refuses it
    assert result["modes"]["default"]["unanswerable_refused"] == 1.0
    assert {"retrieve", "summarize", "answer"} <= result["modes"]["default"]["stages"].keys()

    # The pipeline's own prompts ran on the chunk retrieved from the ingested document...
    assert any("Focused Summary:" in p and "blade inspection every 90 days" in p for p in fake_llm.prompts)
    # ...and the answers were scored by the judge model, against the expected answer and the chunks
    judged = [p for p in fake_llm.prompts if "Verdict (JSON):" in p]
    assert any("Every 90 days." in p for p in judged) and any("<document source=" in p for p in judged)
    assert "a-judge-model" in models_asked and None in models_asked
    assert len(judged) == models_asked.count("a-judge-model")

    assert [(q["id"], q["mode"]) for q in result["questions"]][:3] == [("q1", "default"), ("q2", "default"), ("u1", "default")]
    assert all("answer" not in q and "question" not in q for q in result["questions"])  # no document text is saved


def test_a_judge_reply_that_is_not_a_score_stops_the_run(dataset, judge_model, fake_llm):
    fake_llm.judge_reply = "The answer looks fine to me."
    with pytest.raises(EvaluationError, match="could not be read as a score"):
        run(dataset)


@pytest.mark.parametrize("judge,message", [("", "AETHER_JUDGE_MODEL is not set"), (settings.llm_model, "not a measurement")])
def test_the_judge_must_be_another_model(dataset, fake_llm, monkeypatch, judge, message):
    monkeypatch.setattr(settings, "judge_model", judge)
    with pytest.raises(EvaluationError, match=message):
        run(dataset)
    assert fake_llm.prompts == []  # stopped before anything was asked


def test_retrieval_only_asks_no_model(dataset, fake_llm):
    result = run(dataset, retrieval_only=True)
    assert fake_llm.prompts == []
    totals = result["modes"]["default"]
    assert totals["hit_at_k"] == 1.0 and totals["unanswerable_refused"] == 1.0
    assert totals["correctness"] is None and totals["faithfulness"] is None
    assert result["settings"]["judge_model"] == ""
    assert result["threshold"]["answerable_lowest"] > result["threshold"]["threshold"] > result["threshold"]["unanswerable_highest"]


def test_a_document_named_by_the_dataset_must_exist(dataset):
    (dataset.parent / "documents" / "canteen.txt").unlink()
    with pytest.raises(EvaluationError, match="canteen.txt"):
        run(dataset, retrieval_only=True)


# ── The dataset ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,message", [
    ('{"id": "q1", "question": "Q?"', "line 1: not valid JSON"),
    ('{"id": "q1", "question": "Q?", "source": "a.txt"}', 'line 1: "expected_answer" is missing'),
    ('{"id": "q1", "question": "Q?", "expected_answer": "A"}', 'line 1: "source" is missing'),
    ('{"id": "u1", "question": "Q?", "answerable": false}\n\n{"id": "u1", "question": "R?", "answerable": false}', "line 3: the id"),
    ("[1, 2]", "line 1: not a JSON object"),
    ("\n\n", "has no questions"),
])
def test_a_bad_dataset_is_refused_with_its_line(tmp_path, text, message):
    path = tmp_path / "dataset.jsonl"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(EvaluationError, match=message):
        evaluate.load_dataset(path)


def test_a_missing_dataset_says_how_to_make_one(tmp_path):
    with pytest.raises(EvaluationError, match="No dataset at"):
        evaluate.load_dataset(tmp_path / "nothing.jsonl")


# ── The arithmetic ────────────────────────────────────────────────────────────

def _hit(source, page, text="some text"):
    return {"text": text, "meta": {"source": source, "page": page}, "score": 0.5}


def test_a_chunk_is_right_by_file_page_and_phrase():
    item = {"source": "a.pdf", "pages": [3, 4], "contains": "Net   30 days"}
    hits = [_hit("b.pdf", 3), _hit("a.pdf", 2), _hit("a.pdf", 4, "other"), _hit("a.pdf", 4, "Payment is net 30\ndays.")]
    assert [evaluate.is_relevant(h, item) for h in hits] == [False, False, False, True]
    assert evaluate.first_relevant_rank(hits, item) == 4
    assert evaluate.first_relevant_rank(hits[:3], item) is None
    assert evaluate.first_relevant_rank(hits, {"source": "a.pdf", "pages": []}) == 2  # no page given: the file is enough


def test_hit_at_k_and_mrr():
    def record(rank):
        return {"answerable": True, "rank": rank, "refused": False, "best_score": 0.5, "stages": {}}

    totals = evaluate.summarise([record(1), record(3), record(None), record(6)], k=5)
    assert totals["hit_at_k"] == 0.5                                   # ranks 1 and 3 are inside the top 5
    assert totals["mrr"] == round((1 + 1 / 3 + 0 + 1 / 6) / 4, 3)
    assert totals["correctness"] is None and totals["unanswerable_refused"] is None  # nothing to average


def test_stage_totals_are_medians_and_means():
    def record(seconds, tokens_in):
        return {"answerable": False, "refused": True, "best_score": 0.1,
                "stages": {"answer": {"seconds": seconds, "input_tokens": tokens_in, "output_tokens": 10}}}

    stage = evaluate.summarise([record(1.0, 100), record(2.0, 200), record(9.0, 300)], k=5)["stages"]["answer"]
    assert stage == {"median_seconds": 2.0, "mean_input_tokens": 200.0, "mean_output_tokens": 10.0}


def test_suggested_threshold_sits_between_the_two_kinds_of_question():
    def record(score, answerable):
        return {"best_score": score, "answerable": answerable}

    records = [record(0.70, True), record(0.80, True), record(0.66, True), record(0.50, False), record(0.45, False)]
    assert evaluate.suggest_threshold(records) == {
        "threshold": 0.58, "correct": 5, "of": 5,
        "answerable_lowest": 0.66, "answerable_median": 0.7, "unanswerable_highest": 0.5, "unanswerable_median": 0.475,
    }
    assert evaluate.suggest_threshold(records[:3]) is None  # no unanswerable question to separate from


@pytest.mark.parametrize("reply,score", [
    ('{"score": 0.5, "reasoning": "half"}', 0.5),
    ('```json\n{"score": 1, "reasoning": "all"}\n```', 1.0),
])
def test_a_judge_score_is_read_from_its_json(reply, score):
    assert evaluate.parse_score(reply) == score


@pytest.mark.parametrize("reply", ["", "Looks right.", '{"reasoning": "no score"}', '{"score": "high"}',
                                   '{"score": 7}', '{"score": true}', '{"score": 0.5'])
def test_a_judge_reply_without_a_usable_score_raises(reply):
    with pytest.raises(EvaluationError):
        evaluate.parse_score(reply)


# ── The report and the command line ───────────────────────────────────────────

def test_the_report_puts_runs_side_by_side(dataset, judge_model, tmp_path):
    results_dir = tmp_path / "results"
    first = evaluate.run(dataset, dataset.parent / "documents", "baseline", retrieval_only=True, log=lambda line: None)
    first["created"] = "2026-01-01T00:00:00"
    evaluate.write_result(first, results_dir)
    evaluate.write_result(evaluate.run(dataset, dataset.parent / "documents", "final run", log=lambda line: None), results_dir)
    assert sorted(p.name for p in results_dir.iterdir()) == ["baseline.json", "final-run.json"]

    report = evaluate.build_report(results_dir)
    assert "| Measure | baseline · default | baseline · hybrid | final run · default | final run · hybrid |" in report
    assert "| hit@5 | 1.00 | 1.00 | 1.00 | 1.00 |" in report
    assert "| Correctness | not measured | not measured | 1.00 | 1.00 |" in report
    assert "no answers (retrieval only)" in report and "a-judge-model" in report
    assert "## How each number is computed" in report


def test_command_line_saves_the_result_and_rebuilds_the_report(dataset, judge_model, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(evaluate, "use_temporary_store", lambda: None)  # stay in the test's stores
    monkeypatch.setattr(evaluate, "RESULTS_DIR", tmp_path / "docs" / "evaluation")
    monkeypatch.setattr(evaluate, "REPORT_FILE", tmp_path / "docs" / "evaluation.md")
    assert evaluate.main(["--label", "smoke", "--dataset", str(dataset), "--modes", "default"]) == 0
    assert (tmp_path / "docs" / "evaluation" / "smoke.json").is_file()
    assert "smoke · default" in (tmp_path / "docs" / "evaluation.md").read_text(encoding="utf-8")
    assert "| hit@5 | 1.00 |" in capsys.readouterr().out


def test_command_line_stops_with_a_message_when_there_is_no_dataset(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(evaluate, "use_temporary_store", lambda: None)
    assert evaluate.main(["--label", "x", "--dataset", str(tmp_path / "missing.jsonl")]) == 1
    assert "Evaluation stopped: No dataset at" in capsys.readouterr().err


def test_the_command_line_run_uses_a_store_of_its_own(monkeypatch):
    before = (settings.db_path, settings.vector_store_dir)
    monkeypatch.setattr(settings, "db_path", settings.db_path)                    # restored after the test
    monkeypatch.setattr(settings, "vector_store_dir", settings.vector_store_dir)
    evaluate.use_temporary_store()
    assert settings.db_path not in before and settings.vector_store_dir not in before
    assert settings.db_path.is_file() and settings.db_path.parent == settings.vector_store_dir.parent
