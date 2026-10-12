"""
Known defects: each test here states the correct behaviour and is marked xfail(strict=True) with
the finding id from AUDIT_REPORT.md. The sprint that fixes a defect removes its mark and moves
the test beside the code's other tests; strict means a fix that lands without removing the mark
fails the suite, so the list stays honest.

To see the real failures:  python -m pytest tests/test_known_defects.py --runxfail

None are open. Sprint 4 fixed the last twenty: hybrid search (R3, tests/unit/test_search.py),
parsing (R9, tests/unit/test_parsers.py) and the sources of a refused answer (R5,
tests/integration/test_sources.py).
"""

import pytest


def known(reason):
    return pytest.mark.xfail(strict=True, reason=reason)
