"""Prompts must not carry an instruction to ignore the other rules (S6)."""

from pathlib import Path

from src.prompts import prompt_templates

BACKEND_DIR = Path(__file__).resolve().parents[2]


def test_rag_prompts_have_no_override_rule():
    for prompt in (prompt_templates.RAG_PROMPT, prompt_templates.SUMMARIZE_PROMPT, prompt_templates.REWRITE_PROMPT):
        assert "OVERRIDE" not in prompt.template
        assert "ignoring other rules" not in prompt.template


def test_backend_source_has_no_override_rule():
    for path in [*BACKEND_DIR.glob("*.py"), *(BACKEND_DIR / "src").rglob("*.py")]:
        text = path.read_text(encoding="utf-8")
        assert "IMPORTANT OVERRIDE" not in text, path.name
        assert "Amit Ganatra" not in text, path.name
