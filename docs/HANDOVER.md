# Handover

Where things stand right now. Read this first, every session; add a new entry on top at the end
of it. Never rewrite an old entry. Also read first: [FLOW.md](FLOW.md), [THREAT.md](THREAT.md), and the Status table of
[SPRINT_PLAN.md](../SPRINT_PLAN.md). The reasons for everything are in [DECISIONS.md](DECISIONS.md).

---

## Latest session: 2026-10-15

**Done**
- Merged into `main` today (`7101726`): models on this computer through Ollama; document scope ("Search in", documents named in a question, papers read as papers, the answer from cited passages).
- On branches, tested and pushed, **not merged**, each built on the one before:
  1. `rerank`: a local reranker; the Grounded line set for each embedding model (D-054 to D-058).
  2. `pdf-viewer`: PDFs kept, the page viewer with the passage marked; the fix for an empty thread on reload in development (D-059 to D-062).
  3. `openai-compatible`: any service that speaks OpenAI's API (D-063, D-064).
  4. `ocr`: scanned PDF pages read by OCR (D-065, D-066).
  5. `decisions-flow`: `docs/DECISIONS.md`, `FLOW.md`, `THREAT.md`, this file; the quiz rule; `start.bat` installs packages again when their lists change (D-068).
- Last full checks, on `ocr`: 779 backend tests (99% coverage), 139 frontend tests, the browser journey; the viewer looked at in a browser under the dev server and under the built app with the content-security policy (no violations); `pip-audit` and `npm audit` clean except chromadb's known advisory.

**In progress**
- The quiz before the merge: 8 questions asked on 15 Oct 2026, not yet answered.

**Broken or risky**
- The owner's question "the best accuracy of the maternal health paper" is still answered wrong by qwen3.5:4b (it quotes a cited study's 97.03%; the paper's own is 84%) (D-054).
- The owner's existing PDF (`13003-64313-1-PB.pdf`) has no kept file: upload it again after the merge for the page viewer (D-060).
- The reranking model is downloaded by name, not a pinned version (THREAT.md, section 5).
- OCR has no per-user quota (THREAT.md, section 2).
- Ollama did not start on its own after the computer restarted; it was started by hand from `%LOCALAPPDATA%\Programs\Ollama\ollama app.exe`.
- The owner's two app servers on ports 8000 and 5173 were started by hand, not by `start.bat`. Stop them before running `start.bat`, or its `npm ci` meets files in use.

**Next**
- Owner: answer the quiz; when passed, from the project folder `git merge --no-ff decisions-flow` (it holds all five), `git push`, close the server windows, run `start.bat` (it reinstalls once), upload the PDF again.
- Owner: the Sprint 4 test set (3 to 5 documents you may share, 30 to 50 questions with their answers); it is what every remaining calibration waits for.
- Owner: the data question with the mentor (S11); the two Sprint 9 decisions.
- After the merge: delete the `.wt` folders in the project.

**Do not touch**
- `backend/.env` (never print or copy it), `backend/aether.db*`, `backend/vector_store/`, `data/`, `backend/logs/`.
- `AUDIT_REPORT.md` (the baseline; never edited).
- Docker (deferred until the owner asks).
- `main`: no pushes; the owner merges.
