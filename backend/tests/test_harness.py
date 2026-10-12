"""Guards for the test harness itself: no real data, no real model."""

import os
import tempfile

import rag_engine
from fakes import HashingEmbeddings
from src.core.config import settings
from src.embeddings import embedder


def test_stores_point_at_temp_dirs():
    tmp = tempfile.gettempdir()
    assert str(settings.db_path).startswith(tmp)
    assert str(rag_engine.STORE_DIR).startswith(tmp)
    assert str(settings.log_dir).startswith(tmp)


def test_no_real_gemini_key_in_tests():
    assert os.environ["GOOGLE_API_KEY"] == ""
    assert isinstance(embedder.get_embeddings(), HashingEmbeddings)
