"""
tests/e2e_server.py — the backend for the browser journey (frontend/e2e), with fake models.

Runs the real app, serving the built web app (frontend/dist), on stores in a temp folder and with
the fake embeddings and chat model from fakes.py: the journey needs no API key, touches no real
data, and makes no call to Google. The temp folder is removed when the server stops.

Playwright starts it (frontend/playwright.config.js). By hand, from backend/:

    python tests/e2e_server.py --port 8765

Settings a developer's backend/.env may hold that would change the journey (an invite code, a
production environment, HTTPS-only cookies) are set here for this process only.
"""

import argparse
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # backend/, for main and src
sys.path.insert(0, str(HERE))         # tests/, for fakes


def main() -> None:
    parser = argparse.ArgumentParser(description="Aether AI backend with fake models, for the browser journey")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    data = Path(tempfile.mkdtemp(prefix="aether_e2e_"))
    atexit.register(shutil.rmtree, data, ignore_errors=True)
    # Before any app module is imported: environment variables win over backend/.env
    os.environ.update({
        "AETHER_DB_PATH": str(data / "aether.db"),
        "AETHER_VECTOR_STORE_DIR": str(data / "vector_store"),
        "AETHER_LOG_DIR": str(data / "logs"),
        "JWT_SECRET": "used-only-by-the-browser-journey",
        "GOOGLE_API_KEY": "",  # set but empty, so a real key in backend/.env is not read
        "AETHER_INVITE_CODE": "",
        "AETHER_ENVIRONMENT": "development",
        "AETHER_COOKIE_SECURE": "false",
        "AETHER_ANSWER_FROM": "summary",
    })

    from fakes import HashingEmbeddings, ScriptedChatModel
    from src.embeddings import embedder
    from src.llm import llm_client

    embedder.get_embeddings = lambda: HashingEmbeddings()
    model = ScriptedChatModel(stream_delay=0.01)  # answers arrive word by word, as from a real model
    llm_client.get_llm = lambda **kwargs: model

    import uvicorn
    from main import app

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
