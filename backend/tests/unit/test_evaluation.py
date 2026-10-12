"""The evaluation harness runs end to end with the fake model (it is rewritten in Sprint 4, T3)."""

from src.evaluation import evaluate


def test_benchmark_runs_and_prints_the_aggregate(fake_llm, capsys):
    evaluate.run_rag_benchmark()
    out = capsys.readouterr().out
    assert "AGGREGATE EVALUATION METRICS" in out
    assert any("Context:" in p and "Question:" in p for p in fake_llm.prompts)
