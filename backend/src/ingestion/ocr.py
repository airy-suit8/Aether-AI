"""
ingestion/ocr.py — read the text of PDF pages that are pictures (scans, photos), on the processor.

pypdfium2 draws each page at OCR_DPI and RapidOCR reads the picture with the PP-OCRv6 models that
come inside its package (ONNX: no download, no GPU). On a scanned paper it read every line with its
spaces, in 1 to 2 s a page; the models RapidOCR 1.x shipped ran English words together
("suitableforthemodels"), which search cannot use. It is loaded on first use (a second), and pages
are read one at a time: pdfium may not be called from two threads at once.
"""

import threading
from typing import Dict, List

OCR_DPI = 200

_lock = threading.Lock()
_engine = None


def _load():
    """The OCR engine. RapidOCR is imported here: importing it takes a second."""
    from rapidocr import RapidOCR
    return RapidOCR(params={"Global.log_level": "error"})


def read_pages(file_path: str, page_numbers: List[int]) -> Dict[int, str]:
    """The text OCR finds on these pages of a PDF (numbered from 1), a line for each line of text it
    found, in reading order; "" for a page where it found none."""
    global _engine
    import numpy as np
    import pypdfium2 as pdfium

    with _lock:
        if _engine is None:
            _engine = _load()
        pdf = pdfium.PdfDocument(file_path)
        try:
            texts = {}
            for number in page_numbers:
                picture = pdf[number - 1].render(scale=OCR_DPI / 72).to_pil().convert("RGB")
                texts[number] = "\n".join(_engine(np.array(picture)).txts or ())
            return texts
        finally:
            pdf.close()
