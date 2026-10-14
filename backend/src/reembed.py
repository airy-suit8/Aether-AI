"""
reembed.py — read every stored passage again with the configured embedding model.

Run from backend/, with the backend stopped, after changing AETHER_EMBEDDING_PROVIDER or
AETHER_EMBEDDING_MODEL (for example from Gemini to a model in Ollama):
  python -m src.reembed            say which model made the stored passages: nothing is changed
  python -m src.reembed --apply    embed every passage again with the configured model

Passages embedded by one model cannot be searched with another, so after a change the app
refuses to add or search until this has run (vectordb/vector_store.py). Each passage keeps its
id, text and metadata, so nothing has to be uploaded again; only its vector is made anew. The
new vectors replace the old ones only once all of them are made, so a run that fails (Ollama
stopped, a quota reached) leaves the store as it was, and can simply be run again.
"""

import argparse
import sys
from typing import List, Optional

from src.core.config import settings
from src.llm.llm_client import setup_problem
from src.vectordb.vector_store import store


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Embed every stored passage again with the configured embedding model.")
    parser.add_argument("--apply", action="store_true", help="embed them again (without it, nothing is changed)")
    args = parser.parse_args(argv)
    if not store.exists():
        print(f"No vector store at {settings.vector_store_dir}: there is nothing to embed.")
        return 0

    stored, wanted = store.embedding_model(), settings.embedding_label()
    count = store.collection.count()
    print(f"Vector store: {settings.vector_store_dir}")
    print(f"Stored passages: {count}, embedded with {stored}")
    print(f"Configured embedding model: {wanted}")
    if stored == wanted:
        print("\nThey match: nothing to do.")
        return 0
    if not args.apply:
        print("\nNothing was changed. Run again with --apply to embed every passage with the configured model.")
        return 0

    try:
        done = store.reembed(progress=lambda made, total: print(f"  {made} of {total}", flush=True))
    except Exception as e:
        print(f"\nStopped, and the store is as it was: {setup_problem(e) or repr(e)}", file=sys.stderr)
        return 1
    print(f"\nDone: {done} passage{'' if done == 1 else 's'} embedded with {wanted}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
