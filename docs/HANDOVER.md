# Handover

Where things stand right now. Read this first, every session; add a new entry on top at the end
of it. Never rewrite an old entry. Also read first: [FLOW.md](FLOW.md), [THREAT.md](THREAT.md), and the Status table of
[SPRINT_PLAN.md](../SPRINT_PLAN.md). The reasons for everything are in [DECISIONS.md](DECISIONS.md).

---

## Latest session: 2026-10-15, evening

**Done**
- Merged into `main` at the owner's request, without the quiz (their choice): the five branches (`2d3953d`); then two fixes, each on its own branch: `start.bat` ignores a `PYTHON` variable already set on the computer (`5c43db9`, D-069), and toasts sit above the dock so they never cover the question box (`949d0fb`, D-070). All pushed.
- `start.bat --packages-only` run on the owner's computer: `npm ci` (291 packages, pdf.js among them, 0 vulnerabilities) and the backend's packages into `.venv`; both copies kept for the next comparison.
- The owner's app restarted from `main`: backend on 8000, frontend on 5173 (started by hand, outside `start.bat`).
- Worktrees removed and their merged local branches deleted; the branches remain on GitHub.

**In progress**
- Nothing. The quiz was not taken; the questions were asked, and the rule stands for the next merge.

**Broken or risky**
- The owner said they could not see the question box. It was not reproduced at any window size; toasts covering it is the one cause found, and fixed. If it still happens, a screenshot and the window size are needed.
- `.wt/openai` is left behind: a process holds it. Delete `.wt` when nothing uses it.
- Node 24.11 is below what jsdom and three test-only packages ask for (24.15): `npm ci` warns; the app is not affected.
- Unchanged from the entry below: the "best accuracy" answer; the PDF to upload again; the reranking model not pinned; no per-user OCR quota; Ollama not starting by itself.

**Next**
- Owner: refresh the page and check the question box; upload `13003-64313-1-PB.pdf` again; from now on start the app with `start.bat` (stop the servers started by hand first).
- Owner: the Sprint 4 test set; the data question (S11); the Sprint 9 decisions.

**Do not touch**
- As below.

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
