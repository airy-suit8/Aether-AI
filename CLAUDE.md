# Aether AI — instructions for Claude sessions

Aether AI is a multi-tenant RAG chatbot built as internship work: FastAPI, LangChain, Google Gemini, ChromaDB, SQLite and JWT auth in `backend/`; a React and Vite app in `frontend/`. The owner reviews work as pull requests.

## Where the plan is

- `SPRINT_PLAN.md` is the roadmap. Its Status table says which sprint is next. Do one sprint per session and stop at its end, unless the owner's prompt names more than one.
- When the prompt names several sprints, do them in the order given. Each gets its own branch and its own pull request; start a later sprint's branch from the earlier sprint's branch, and say in its pull request which earlier ones it contains. Finish a sprint completely (checks pass, its "Done when" list is met or each gap is stated, the Status table is updated, the pull request is open) before starting the next. Commit and push after every task, so nothing is lost if the session ends early. If a sprint cannot be finished, stop there and say why; do not start the next.
- `AUDIT_REPORT.md` holds the findings the plan cites (B1, R4, S3 and so on), with file, line, evidence and intended fix. Do not edit it.
- In `SPRINT_PLAN.md`, tick a seam-checklist box only when a passing test proves it, and update the Status table at the end of a sprint.
- `DESIGN.md` is the design language (Prism) and its rules. Every screen uses it. Any change to the interface must use the tokens and components in `frontend/src/design/` and follow those rules; do not add another styling approach, a UI kit or a font.

## Rules that do not change

- **No secrets, no real model calls.** There is no Gemini key outside the owner's machine. Never add one, never commit a `.env`, never call Google or any model or embedding API from tests or checks. Use the fakes in `backend/tests/fakes.py`.
- **Tests touch no real data.** They use the temp database, temp vector store and temp log folder that `backend/tests/conftest.py` sets up, and must run with no API key present.
- **Never commit runtime data:** `backend/aether.db*`, `backend/vector_store/`, `backend/logs/`, `.venv/`.
- **Python 3.12.** Dependencies are pinned in `backend/requirements.txt` and `backend/requirements-dev.txt`. Upgrade one at a time and say why.
- **Docker work is deferred.** Do not start it until the owner asks.
- **Smallest change that does the task.** Match the existing style. No refactoring beyond what a task needs, except in the sprint whose purpose is the restructure.

## How to work

- Work on a branch from `main`: the one your session was given, or `claude/sprint-N`. Never push to `main`. Say the branch's name in the plan's Status table.
- If the sprint has a "Decisions already made" list in `SPRINT_PLAN.md`, follow it.
- One commit per task. The message says what changed and why, and cites the finding id.
- Before finishing, run and paste the summary lines of:
  - `cd backend && python -m pytest`
  - `cd frontend && npm ci && npm run lint && npm run build` (and `npm test` once it exists)
- Do not weaken a test to make it pass. If something fails and cannot be fixed, say so.
- Open a pull request into `main`. Its description lists: what the sprint achieved; a table of task, commit and how it was verified; the test and build results; what was not verified; what the owner must do locally; and anything in the plan found to be wrong.

## The owner's machine

Windows, with the project in a folder whose path contains spaces. `start.bat` must keep working there, and nothing may assume a Unix shell.
