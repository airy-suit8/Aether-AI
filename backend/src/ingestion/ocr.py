"""
ingestion/ocr.py — read the text of PDF pages that are pictures (scans, photos), on the processor.

pypdfium2 draws each page at OCR_DPI and RapidOCR reads the picture with the PP-OCRv6 models that
come inside its package (ONNX: no download, no GPU). On a scanned paper it read every line with its
spaces, in 1 to 2 s a page; the models RapidOCR 1.x shipped ran English words together
("suitableforthemodels"), which search cannot use. It is loaded on first use (a second).

The processor is shared, so (D-073):
  - pages are read one at a time (pdfium may not be called from two threads at once), and each
    page is a turn of its own, given in the order asked: a long scan no longer holds OCR for its
    whole length, and a second upload's pages are read between its pages, not after all of them;
  - each user may have settings.ocr_pages_per_hour pages read in any hour; a file that would pass
    that is refused before any of it is read. The count is kept in memory: a restart clears it.
"""

import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from typing import Deque, Dict, List, Optional, Tuple

from src.core.config import settings

OCR_DPI = 200
HOUR = 3600.0

_engine = None


class OcrLimitReached(Exception):
    """A user's pages read by OCR in the last hour, with this file's, would pass the limit."""

    def __init__(self, used: int, asked: int, limit: int):
        super().__init__(f"{used} pages read in the last hour, {asked} more asked, {limit} allowed")
        self.used, self.asked, self.limit = used, asked, limit


class _Turns:
    """One page at a time, in the order the turns were asked for (a ticket queue: a plain lock
    lets the thread that just let go take it straight back)."""

    def __init__(self):
        self._changed = threading.Condition()
        self._issued = 0
        self._serving = 0

    @contextmanager
    def turn(self):
        with self._changed:
            ticket = self._issued
            self._issued += 1
            self._changed.wait_for(lambda: self._serving == ticket)
        try:
            yield
        finally:
            with self._changed:
                self._serving += 1
                self._changed.notify_all()


_turns = _Turns()
_used_lock = threading.Lock()
_used: Dict[str, Deque[Tuple[float, int]]] = defaultdict(deque)  # owner -> (when, pages), oldest first


def _reserve(owner: str, pages: int) -> None:
    """Count these pages against the owner's hour, or raise OcrLimitReached and count nothing."""
    now = time.monotonic()
    with _used_lock:
        spent = _used[owner]
        while spent and now - spent[0][0] >= HOUR:
            spent.popleft()
        used = sum(count for _, count in spent)
        if used + pages > settings.ocr_pages_per_hour:
            raise OcrLimitReached(used, pages, settings.ocr_pages_per_hour)
        spent.append((now, pages))


def _load():
    """The OCR engine. RapidOCR is imported here: importing it takes a second."""
    from rapidocr import RapidOCR
    return RapidOCR(params={"Global.log_level": "error"})


def read_pages(file_path: str, page_numbers: List[int], owner: Optional[str] = None) -> Dict[int, str]:
    """The text OCR finds on these pages of a PDF (numbered from 1), a line for each line of text it
    found, in reading order; "" for a page where it found none. With an owner, the pages count
    against their hourly limit first (OcrLimitReached)."""
    global _engine
    import numpy as np
    import pypdfium2 as pdfium

    if owner is not None:
        _reserve(owner, len(page_numbers))
    texts: Dict[int, str] = {}
    pdf = None
    try:
        for number in page_numbers:
            with _turns.turn():  # every call into pdfium and the engine happens inside a turn
                if _engine is None:
                    _engine = _load()
                if pdf is None:
                    pdf = pdfium.PdfDocument(file_path)
                # Closed here, inside the turn: left to the garbage collector, pdfium would be
                # called from whichever thread collects them
                page = pdf[number - 1]
                bitmap = page.render(scale=OCR_DPI / 72)
                picture = bitmap.to_pil().convert("RGB")
                bitmap.close()
                page.close()
                texts[number] = "\n".join(_engine(np.array(picture)).txts or ())
        return texts
    finally:
        if pdf is not None:
            with _turns.turn():
                pdf.close()
