"""Guards for the test harness itself: no real data, no real model."""

import os
import tempfile

import database
import logger
import rag_engine
from fakes import HashingEmbeddings


def test_stores_point_at_temp_dirs():
    tmp = tempfile.gettempdir()
    assert str(database.DB_PATH).startswith(tmp)
    assert str(rag_engine.STORE_DIR).startswith(tmp)
    assert str(logger.LOGS_DIR).startswith(tmp)


def test_no_real_gemini_key_in_tests():
    assert os.environ["GOOGLE_API_KEY"] == ""
    assert isinstance(rag_engine._get_embeddings(), HashingEmbeddings)
