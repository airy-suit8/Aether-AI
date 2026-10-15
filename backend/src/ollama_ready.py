"""
ollama_ready.py — does this setup need Ollama, and is it answering? Run by start.bat before it
starts the servers, so that a computer that has restarted gets Ollama started again.

  python -m src.ollama_ready             exit 0: Ollama is not needed, or it answers
                                         exit 3: it is needed, on this computer, and does not answer
  python -m src.ollama_ready --wait 30   the same, after waiting up to 30 s for it to answer

Ollama is needed when the chat model or the embeddings come from it (settings.llm_provider,
settings.embedding_provider). One on another computer (AETHER_OLLAMA_URL) cannot be started from
here: that is reported and the exit is 0. It reads the settings the app reads, and asks Ollama's
/api/version, which loads no model.
"""

import argparse
import sys
import time
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from src.core.config import settings

NOT_ANSWERING = 3
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def needed() -> bool:
    return "ollama" in (settings.llm_provider, settings.embedding_provider)


def answering(url: str, timeout: float = 2.0) -> bool:
    """Whether Ollama answers at url (its version route)."""
    try:
        with urlopen(url.rstrip("/") + "/api/version", timeout=timeout) as reply:
            return reply.status == 200
    except (URLError, OSError, ValueError):
        return False


def check(wait: float = 0.0, poll: float = 1.0) -> int:
    """The exit code above, after saying what was found."""
    if not needed():
        return 0
    url = settings.ollama_url
    deadline = time.monotonic() + wait
    while True:
        if answering(url):
            print(f"Ollama is answering at {url}.")
            return 0
        if time.monotonic() >= deadline:
            break
        time.sleep(poll)
    if urlparse(url).hostname not in LOCAL_HOSTS:
        print(f"Ollama does not answer at {url}, on another computer: start it there. "
              "Questions are answered once it runs.")
        return 0
    print(f"Ollama does not answer at {url}.")
    return NOT_ANSWERING


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Does this setup need Ollama, and is it answering?")
    parser.add_argument("--wait", type=float, default=0.0, help="seconds to wait for it to answer")
    return check(parser.parse_args(argv).wait)


if __name__ == "__main__":
    sys.exit(main())
