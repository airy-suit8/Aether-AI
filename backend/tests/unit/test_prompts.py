"""Prompts must not carry an instruction to ignore the other rules (S6)."""

from pathlib import Path

import rag_engine
import rag_langchain

BACKEND_DIR = Path(__file__).resolve().parents[2]


def test_rag_prompts_have_no_override_rule():
    for prompt in (rag_engine.RAG_PROMPT, rag_langchain.RAG_PROMPT):
        assert "OVERRIDE" not in prompt.template
        assert "ignoring other rules" not in prompt.template


def test_backend_source_has_no_override_rule():
    for path in BACKEND_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "IMPORTANT OVERRIDE" not in text, path.name
        assert "Amit Ganatra" not in text, path.name
