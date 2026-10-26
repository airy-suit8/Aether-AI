# Handover

Where things stand right now. Read this first, every session; add a new entry on top at the end
of it. Never rewrite an old entry. Also read first: [FLOW.md](FLOW.md), [THREAT.md](THREAT.md), and the Status table of
[SPRINT_PLAN.md](../SPRINT_PLAN.md). The reasons for everything are in [DECISIONS.md](DECISIONS.md).

---

## Latest session: 2026-10-26

**Done**
- The history of `main` was rewritten at the owner's request: every commit id changed, and the ids these documents cite were updated to the new ones. The tag `eval-baseline` was moved to its new commit. The old work branches on GitHub were deleted; all their work is in `main`. A backup of the history as it was is kept outside the repository: `D:\Desktop\Tirth Ganatra\Tirth\Tirth\Aether-AI-history-backup-2026-10-25.bundle`.
- The Status table update of 25 Oct is part of `main` now.
- No code changed: only documents.

**In progress**
- Nothing.

**Broken or risky**
- A copy of the repository made before 26 Oct has the old history. Save its local changes, then `git fetch` and `git reset --hard origin/main`, or clone again.
- Pull requests #1 to #7 on GitHub still list their commits as they were; GitHub does not let a pull request's commits be changed.
- Unchanged: "the best accuracy" is answered with 84% only 3 times in 21; the owner's npm (11.6.1) is older than CI's (11.19.0).

**Next**
- Owner: commit or drop the `SDLC_PLAN.md` edit (uncommitted since 15 Oct); delete `.wt`; optionally `gh auth login` and Node 24.21 or later.
- Owner: the Sprint 4 test set; the data question (S11); the Sprint 9 decisions; the `[OWNER: ...]` places in the report.

**Do not touch**
- As below.

---

## Latest session: 2026-10-25

**Done**
- `SPRINT_PLAN.md`'s Status table brought up to date: the rows for Sources in their place, Any OpenAI-compatible service and Scanned PDFs say they were merged on 15 Oct (they read as waiting); new rows for Decisions, flow and threats (15 Oct), the four follow-ups and fewer choices in the dock (16 Oct), and CI green again (16 Oct). Missed on 16 Oct; done now. Documentation only.
- Nothing else changed between 16 and 25 Oct: `main` stayed at `e55f889`, no branch was pushed.

**In progress**
- Nothing.

**Broken or risky**
- GitHub moved `ubuntu-latest` to Ubuntu 26 on 19 Oct; this branch's push is CI's first run since (its result is on GitHub).
- Unchanged: "the best accuracy" is answered with 84% only 3 times in 21; the owner's npm (11.6.1) is older than CI's (11.19.0); the quiz was waived for the 16 Oct merges.

**Next**
- Owner: commit or drop the `SDLC_PLAN.md` edit (uncommitted since 15 Oct); delete `.wt` (`four`, `openai`) when nothing uses it; optionally `gh auth login` and Node 24.21 or later.
- Owner: the Sprint 4 test set; the data question (S11); the Sprint 9 decisions; the `[OWNER: ...]` places in the report.
- Next fix to consider: find a paper's own results for "best" or "highest" questions.

**Do not touch**
- As below.

---

## Latest session: 2026-10-16, afternoon

**Done**
- The chat page offers Default and Agent, and every answer is streamed (`2978cdd`, D-075); merged into `main` (`f412523`) at the owner's request, without the quiz. LangChain answers as Default does; Hybrid, measured against Default on the 20 questions with the reranker on, put the answering passage at the same rank on every question (19 of 20 in the five kept, 11 first). The API still takes all four modes and `POST /chat`.
- **CI was red on every push from `a5f2de1` (15 Oct, the PDF viewer) to `f412523`**, unseen until the owner's failure mails: the Frontend and Browser journey jobs stopped at `npm ci`, because the lock file lacked `@emnapi/core` and `@emnapi/runtime` (npm 11.6.1 here accepts it, CI's npm 11.19.0 does not). So lint, the type check, the frontend tests and the journey did not run in CI for those commits; they had passed here. Fixed by writing the lock with npm 11.19.0 (`a425fd6`, D-076); CI passed all three jobs on that branch, the first green run since 15 Oct. Merged into `main` with this entry.
- GitHub CLI 2.102.0 installed for the owner's user at their request (winget, no admin), not logged in.
- The owner uploaded `13003-64313-1-PB.pdf` again: it is document 6 now, with its PDF kept for the page viewer.

**In progress**
- Nothing.

**Broken or risky**
- The quiz was waived for both of today's merges; the rule stands.
- The owner's Node 24.11 ships npm 11.6.1, older than CI's: a lock file it writes can pass here and fail in CI. Check with `npx -y npm@11.19.0 ci --dry-run` before pushing a dependency change, and read CI's result after every push.
- GitHub says `ubuntu-latest` moves to Ubuntu 26 from 19 Oct 2026; CI may need a look after that.
- Unchanged from the entry below: "the best accuracy" is answered with 84% only 3 times in 21 (the search does not find the passage that holds it); OCR's hourly count is kept in memory.

**Next**
- Owner: `gh auth login` in a new terminal to use the GitHub CLI; consider Node 24.21 or later (npm 11.19, as CI); commit or drop the `SDLC_PLAN.md` edit; delete `.wt` when nothing uses it.
- Owner: the Sprint 4 test set; the data question (S11); the Sprint 9 decisions.
- Next fix to consider: find a paper's own results for "best" or "highest" questions.

**Do not touch**
- As below.

---

## Latest session: 2026-10-16

**Done**
- Merged into `main` at the owner's request (`37ca06d`) and pushed: the four follow-ups from `four-follow-ups`.
  1. `start.bat` starts Ollama when the settings use it and it does not answer, waits up to 30 s, and says so if it still does not (`baeb550`, D-071; `src/ollama_ready.py`).
  2. The reranking model is pinned: one commit of its repository, and the sha256 of each of its five files, checked before it is loaded (`3842617`, D-072).
  3. OCR takes turns a page at a time, so another user's scan is read between a long scan's pages, and each user may have 200 pages read by OCR in any hour (`AETHER_OCR_PAGES_PER_HOUR`) (`081c345`, D-073). Also fixed a form-feed character in `backend/.env.example` (`AETHER_FILES_DIR`).
  4. Each passage's tag names the section of its paper it is in, with a rule in the prompt (`933ebb3`, D-074). Measured on a copy of the owner's library with qwen3.5:4b, the three accuracy questions 7 times each with and without: a cited study's figure given as the paper's own 9 of 21 without, 2 of 21 with; the 18 other questions 36 of 36 either way.
- Checks: 820 backend tests passed, with no keys; ruff clean. The frontend was not changed, so its checks were not run. The Ollama check was tried against the real Ollama (answering: exit 0; a closed port: exit 3) and `start.bat`'s new block in a scratch copy for four cases. The pinned model was loaded for real, and offline.
- The temporary copies of the owner's database and vector store that the measurements made were deleted from the system's temp folder.

**In progress**
- Nothing.

**Broken or risky**
- The quiz was asked: 8 questions. The owner said they passed but gave no answers, so nothing was graded; it is recorded as waived by the owner, as on 15 Oct. The rule stands for the next merge.
- "The best accuracy of the maternal health paper" is still not answered with 84%: only 3 of 21 answers give 83.7% or 84%. The search does not bring the passages that hold them (62, 65, 68) for that question; of the paper's own results only passage 69 (82.73%) reaches the model. This is a retrieval problem, the next fix (D-074).
- Not tried on the owner's computer: `start.bat` starting Ollama from stopped, after a restart.
- OCR's hourly count is kept in memory: a restart clears it, and several accounts have several hours' worth (D-073).
- Section headings are found only when they are a usual section name on a line of their own (D-074).
- Commit `933ebb3`'s message says 25 new section tests; there are 24.
- `.wt/openai` is still on disk (not a worktree any more); `.wt/four` was used for this work. Delete `.wt` when nothing uses it.
- Unchanged: Node 24.11 warnings from `npm ci`.

**Next**
- Owner: start the app with `.\start.bat` (it now starts Ollama itself); upload `13003-64313-1-PB.pdf` again if that is not done yet (D-060).
- Owner: answer the quiz if it should be graded; the Sprint 4 test set; the data question (S11); the Sprint 9 decisions. `SDLC_PLAN.md` has the owner's own uncommitted edit.
- Next fix to consider: find a paper's own results for "best" or "highest" questions (the passage with 84% is not found).

**Do not touch**
- As below.

---

## Latest session: 2026-10-15, evening

**Done**
- Merged into `main` at the owner's request, without the quiz (their choice): the five branches (`f0ebfeb`); then two fixes, each on its own branch: `start.bat` ignores a `PYTHON` variable already set on the computer (`0a64e5e`, D-069), and toasts sit above the dock so they never cover the question box (`07623b2`, D-070). All pushed.
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
- Merged into `main` today (`1c44772`): models on this computer through Ollama; document scope ("Search in", documents named in a question, papers read as papers, the answer from cited passages).
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
