# Aether AI — Sprint Plan

Written 11 October 2026 from [AUDIT_REPORT.md](AUDIT_REPORT.md). Finding ids (B1, R4, S3, …) refer to that report. Sizes are rough estimates for one person working full days; adjust them after Sprint 1.

## Status

| Sprint | State | Evidence |
|---|---|---|
| 0 Make it safe to change | Done, merged 11 Oct 2026 (PR #1) | See below |
| 1 Make it work end to end | Done, merged 11 Oct 2026 (PR #1) | See below |
| 2 Safety net | Done, merged 12 Oct 2026 | See below |
| Design: Prism on every screen | Done, merged 12 Oct 2026 together with Sprint 2 | [DESIGN.md](DESIGN.md) |
| 3 Restructure and connect | Done, in review (branch `sprint-3`) | See below |
| 4 and 5 | Not started; 4 is next | |
| 6 Frontend rebuild | Visual redesign done early; engineering items remain | See Sprint 6 |
| 7 Ship and document | Docker items deferred at the owner's request (11 Oct 2026) | |

Evidence for Sprints 0 and 1, checked on the owner's Windows machine against the merged code:

- A fresh virtual environment built only from the pinned requirements installs cleanly; `pytest` gives 79 passed with no API key present.
- `npm ci`, `npm run lint` (0 errors) and `npm run build` pass on a fresh checkout.
- A real `uvicorn` server on Windows serves the built React app at `/`, streams tokens as they are produced (one per second in the test, not in a lump), answers `/health` in 0.23 s during a stream, and returns 429 on the tenth failed login.
- With the real Gemini key and temp stores: a PDF uploaded as 11 chunks (cosine, 3072 dimensions); two questions were answered correctly with page citations; a Gemini 503 outage was reported through the new error event.

What that real run showed, to act on in later sprints:

- **The 0.3 threshold does nothing with real embeddings.** An unrelated question scored 0.50; real questions scored 0.67 to 0.80. Calibrate in Sprint 4; expect a cutoff near 0.6.
- **A refused answer still lists five sources and a 49% confidence.** Fix with the calibration.
- **It is slow:** about 23 s per answer and 27 s to the first streamed token, from two model calls in sequence. Sprint 4 item 6 decides whether the summary step stays.
- **An exact match scores 1.0000002**, which makes LangChain print a warning containing the chunk text. Clamp scores to 0..1 in Sprint 4.

Sprint 2 and the redesign were merged as one, and the combined code was checked on the owner's Windows machine first: `ruff` clean; `pytest` 283 passed and 21 xfailed with 90% coverage (every core module at 92% or above); `npm ci`, lint (0 errors), `npm test` 26 passed, and build. Two assertions in `ChatLayout.test.jsx` were updated for the new interface: the answer mode is a radio group, and a source card shows its passage and pins open on click. The redesign itself was checked in a real browser against a backend running fake models: sign-up, upload, ask, sources, settings, dark, light and 390 px.

Evidence for Sprint 2, checked on Linux:

- `python -m pytest`: 283 passed, 21 xfailed, with no API key. The same result in a fresh Python 3.12 virtual environment built only from `requirements-dev.txt` with neither `GOOGLE_API_KEY` nor `JWT_SECRET` set.
- `ruff check .`: all checks passed (rules E4, E7, E9 and F, set in `backend/ruff.toml`).
- Coverage (`python -m pytest --cov`): rag_engine 99%, rag_langchain 92%, agent 98%, tools 99%, auth 93%, database 100%, main 99%; total 90%. CI fails if any of these seven drops below 70%.
- Frontend: `npm ci`, `npm run lint` (0 errors), `npm test` (26 passed) and `npm run build` pass on Node 22 and Node 24. `npm audit`: 0 vulnerabilities.
- The net works: with the Sprint 1 LangChain `user_id` fix reverted, 10 tests fail; with the `user_id` filter removed from the dense vector search, 14 tests fail. Both changes were then restored.
- Known defects are strict xfails in `backend/tests/test_known_defects.py`, each naming its finding id. The fixing sprint removes the mark.

What Sprint 2 found, to act on later:

- **LangChain PDF pages start at 0** (new): `load_document_langchain` keeps PyPDFLoader's 0-based `page`, so it would cite "p. 0". The loader is not reachable from the API today (`ingest_document_langchain` had no caller once its unused import was removed), so this is for the Sprint 3 no-orphan decision. Strict xfail.
- **A corrupt PDF gives 500 without a path; a corrupt DOCX gives 500 with the temp path.** The audit said both leak the path. Strict xfail for both (R9).
- **Requests that fail validation never reach the rate limiter**, so 422s do not count towards a limit. Harmless for login today (no password is checked); keep it in mind for Sprint 5 item 3.

Evidence for Sprint 3, checked on Linux (Python 3.12, Node 22):

- `python -m pytest`: 307 passed, 20 xfailed, with no API key and no `JWT_SECRET` in the environment. The same in a fresh virtual environment built only from `requirements-dev.txt`.
- `ruff check .`: all checks passed. Coverage: 99% in total; every module in the CI list at 90% or above.
- Frontend: `npm ci`, `npm run lint` (0 errors), `npm test` (26 passed), `npm run build`.
- The OpenAPI snapshot's only change is the chat request: three booleans out, one `mode` field in.
- `python -m uvicorn main:app` from `backend/` starts without a Gemini key and answers `/health`; the lifespan hook created only the database and the log folder.
- `grep -rn "gemini-" backend/src` returns two lines, both in `core/config.py`: the chat model id and the embedding model id. Each id is written once.

What Sprint 3 changed that later sprints should know:

- **The LangChain loaders are wired in** behind `load_document()`, chosen by `AETHER_DOCUMENT_LOADER` (`native` by default). Their 0-based PDF page is fixed. Sprint 4 item 9 (parsing) should decide whether one loader set can go.
- **`langchain-community` is still a dependency**, and still prints its deprecation warning, because the LangChain loaders live only there. No standalone package provides PyPDFLoader, Docx2txtLoader, TextLoader or CSVLoader yet.
- **One strict xfail is gone** (LangChain PDF pages from 0, fixed here); 20 remain, all for Sprints 4 and 5.
- **The agent uses `langchain.agents.create_agent`** (`langchain==1.3.11`). At the step limit it raises; the agent catches that and gives the old answer.
- **Model calls now have a 120 s timeout and an 8192-token output cap; embeddings a 60 s timeout.** Not yet checked against the real API.

## How these sprints differ from the ones in SDLC_PLAN.md

The old sprint log recorded what was written. These sprints record what was proven.

- **A sprint is done when its checks pass, not when its code exists.** Every sprint below ends with a "Done when" list of things you can run and show.
- **Nothing is marked complete without evidence.** A test name, a command and its output, or a screenshot.
- **One commit per task**, with a message that says what and why. The git history is your proof of work.
- **Order matters.** Sprint 0 makes everything after it reversible. Sprint 2 builds the safety net that makes the Sprint 3 restructure safe. Do not reorder those.

## The connection rule

You asked that every piece of code be logically connected to the rest. The audit found 19 seams; 10 were broken, dead or unconnected. Three mechanisms keep them connected from now on. Each is built in the sprint shown and then runs on every commit.

| Mechanism | What it guarantees | Built in |
|---|---|---|
| **End-to-end test** (`tests/integration/test_e2e.py`): register → login → upload → ask → cited answer → history → delete | The whole chain works, with a fake model and fake embeddings | Sprint 1, extended every sprint |
| **Generated API types**: FastAPI's OpenAPI schema → TypeScript types for the frontend | Frontend and backend cannot disagree on a field name again (the cause of B7 and F4) | Sprint 2 (schema snapshot), Sprint 6 (types) |
| **No-orphan check**: a script that fails if any module is imported by nothing, any route is called by nothing, or any config value is read from anywhere but `core/config.py` | No dead `config.py`, no unreachable loaders, no unused endpoints | Sprint 3 |

Seam checklist. Tick each when its test exists and passes.

- [x] UI call → route: every function in the API client has a matching route and a contract test (`frontend/src/services/api.contract.test.js` checks each call against `backend/tests/openapi_snapshot.json`)
- [x] Route → service: every route has a test that reaches the service layer
- [x] Service → vector store: ingest then search returns the ingested text
- [x] Service → database: a chat turn is saved with its real confidence and mode
- [x] Tenant isolation: user B cannot read, search or delete user A's data (both directions, including history and feedback, since Sprint 2)
- [x] Every chat mode: default, hybrid and agent each answer in the end-to-end test
- [x] Config: the model id appears in exactly one place (`tests/test_no_orphans.py::test_each_model_id_is_written_in_exactly_one_place`; the no-orphan check also fails if anything but `core/config.py` reads the environment)
- [x] Backend → UI: `GET /` returns the built React app
- [ ] Docker: `docker compose up` passes the same end-to-end test (deferred with the Docker work)
- [ ] Evaluation: the harness imports and calls the real pipeline

---

## Sprint 0 — Make it safe to change (about 1 day)

**Goal:** every later change is reversible, and nothing private can leak by accident.

1. `git init`. Before the first commit, fix `.gitignore`: add `backend/aether.db*`, `backend/logs/`, `backend/vector_store/`, `data/`, `logs/`, `.pytest_cache/`. (D1, D2)
2. Delete: the three `codebase_dump.*` files, `walkthrough.md`, `backend/static/`, `backend/vector_store/vectors.npy` and `metadata.json`, `backend/test_doc.txt`, all `__pycache__`. Remove the `/` and `/static` routes for now. (D3, S13, B3)
3. Create a virtual environment on Python 3.12. Today the app shares a global site-packages with TensorFlow and torch, which makes it take over 40 seconds to import. Pin `requirements.txt` to the versions that work; add `requirements-dev.txt` with `pytest`, `httpx`, `ruff`, `pip-audit`. Add `xlrd` or drop `.xls`. Remove `duckduckgo-search`. Run `pip-audit` and upgrade what it flags. (S12, R9)
4. Add `JWT_SECRET` to `.env` and `.env.example`. Make `auth.py` refuse to start without it. Change every `load_dotenv(override=True)` to `override=False`. (B4, S1)
5. Add `.dockerignore`: `.env`, `*.db*`, `vector_store/`, `logs/`, `__pycache__/`, `.pytest_cache/`, `tests/`. (S1)
6. Delete the "IMPORTANT OVERRIDE" rule from all three prompts. (S6)
7. Replace `start.bat` with one that uses the venv and starts both backend and frontend. Write a root `README.md` with exact setup and run steps. (B5)
8. In `SDLC_PLAN.md`, replace the status line and the author line. Strike the claims the audit marked false. Keep the file as history.

**Done when**
- `git log` shows the commits and `git status` is clean with `aether.db` and logs untracked.
- A fresh clone plus the README steps starts the app on a machine that has only Python 3.12 and Node.
- Starting the backend without `JWT_SECRET` exits with a clear error.
- `grep -r "Amit Ganatra" backend` returns nothing.

## Sprint 1 — Make it work end to end (about 3 days)

**Goal:** one person can register, upload a document, ask a question and see a cited answer, in the UI the backend serves. Fix the blockers; do not redesign anything yet.

Backend
1. Fix LangChain mode at its five call sites, or delete the mode and its toggle. Decide now; Sprint 3 keeps only one pipeline either way. (B1)
2. Make handlers non-blocking: plain `def` routes for the blocking paths, or `run_in_threadpool`, and a sync generator for the stream. On Windows without `--reload` the current stream delivers nothing until generation ends. (B11)
3. Create the Chroma collection with cosine distance. Delete the old empty store. (R1)
4. Add `tool_used` to `ChatResponse`. Add a `{"type": "error"}` SSE event and stop sending errors as tokens. Return a non-200 status when the agent fails. (B9, F9)
5. `clear_documents`: stop swallowing errors, return the real count. Reject an upload whose hash already exists for that user. (R8, R6)
6. Pass confidence and mode to `add_turn`. Stop the agent's document-search tool from writing its own turn. (R10)
7. Calculator: fix the `x` replacement on `tools.py:98`, cap the exponent, stop rounding results to 6 significant digits. Pass `recursion_limit` to the agent. (R11, S4)
8. Add the 5000-character limit to `/chat/stream`; constrain `session_id` and `feedback` in the Pydantic models. (S9)

Frontend
9. `SourceCard`: read `snippet`, show page and score. (B7)
10. `SettingsModal`: use `size_bytes` and `uploaded_at`; remove the two fields the API does not send; make "Hard Reset" call the API or remove it. (F4, F5)
11. Add `hybridMode` to the dependency list; fix the other two `exhaustive-deps` warnings. (B8)
12. `.landing { height: 100vh; }`. (B6)
13. Stream handling: parse the trailing buffer, treat a missing `done` as an error, reset loading in `finally`, handle the new `error` event. On 401, log out and say "Session expired". (B9, F7)
14. Show the real username; set the page title. (F8)

Serving
15. Build the React app and mount `frontend/dist` at `/` after the API routes. (B3)

Test
16. Write `test_e2e.py` with a fake embedding model and a fake chat model injected. It registers, logs in, uploads a small text file, asks a question in each mode, checks the answer cites that file, and deletes the document. Tests must use a temp database and a temp vector store. (T1, T2)

**Done when**
- `pytest` passes, including the end-to-end test in default, hybrid and agent modes.
- Opening `http://localhost:8000/` shows the React app, and a real question against a real uploaded document returns an answer with a readable citation. Save a screenshot.
- Sending two requests at once shows both progressing.
- The database shows a saved turn for a real user, with a non-zero confidence.

## Sprint 2 — Safety net (about 3 days)

**Goal:** tests that describe today's behaviour, so the restructure in Sprint 3 cannot break things silently.

1. Fixtures: fake model, fake embeddings, temp database, temp vector store, an authenticated client. No test may touch real data or need a real key. (T2)
2. API tests for every route: success, 401 without a token, 422 on bad input, the rate limit.
3. Tenant isolation: two users, each uploads; neither can search, list or delete the other's data. (S2)
4. Unit tests: each parser (PDF, DOCX with a table, CSV, XLSX), the chunker, `search_hybrid` fusion, the calculator (including `max()` and a large power), conversation memory.
5. Frontend: `vitest` for the SSE reader (split chunks, missing `done`, error event) and one component test for the chat layout. (T4)
6. Snapshot the OpenAPI schema into the repo and fail the test when it changes without the snapshot being updated.
7. CI on every push: `ruff`, `pytest`, `npm run lint`, `npm test`, `npm run build`.

Notes added after Sprints 0 and 1:

- Items 1 and 3 and the calculator part of item 4 were largely delivered in Sprint 1 (`tests/conftest.py`, `tests/fakes.py`, `test_e2e.py`, `test_calculator.py`). Complete them; do not rewrite them.
- **Known defects get a test now.** Where the audit found a defect that a later sprint fixes (fusion key R3, BM25 on tiny or punctuated text R3, DOCX tables R9, first sheet only R9, non-UTF-8 text R9), write the test for the correct behaviour and mark it `xfail(strict=True)` with the finding id. The fixing sprint then removes the mark.
- **Ruff:** the default rule set only (pyflakes and pycodestyle errors), with line length ignored. Fix what it flags in one commit. Do not turn on style rule families before the Sprint 3 restructure; they would bury that diff.
- **Coverage:** add `pytest-cov` to `requirements-dev.txt`.
- **Frontend advisories:** run `npm audit fix` for the three build-time advisories (nanoid, postcss, source-map-js) and confirm lint and build still pass.
- **README:** note that Windows long-path support is off by default, so the project should live in a short folder path.

**Done when**
- CI is green on a fresh clone with no secrets configured.
- Coverage of the backend is reported and above 70% on the pipeline, auth and database modules.
- Reverting the Sprint 1 fix for LangChain mode (or the isolation filter) makes a test fail. Try it once to prove the net works.

## Sprint 3 — Restructure and connect (about 4 days)

**Goal:** the folder structure from the audit report (section 6), one configuration source, one pipeline. Behaviour does not change; the Sprint 2 tests prove it.

Move one package per commit, running the tests after each.

Decisions already made for this sprint (do not reopen them):

- **Structure, not behaviour.** The 283 backend tests and 26 frontend tests must pass at the end, changed only where an import path, a patched name or the new request shape forces it. The 21 strict xfails stay xfail.
- **Entry point.** `backend/main.py` stays, and `python -m uvicorn main:app` run from `backend/` must keep working, because `start.bat`, the README and CI use it. The code moves under `backend/src/` in the layout from section 6 of the audit report.
- **Config.** The existing `Settings` class moves to `core/config.py` and is the only place a tunable or a data path is read. `JWT_SECRET` stays required; environment variables still win over `.env`.
- **Factories.** One LLM factory and one embeddings factory, each with a request timeout, and an output cap on the LLM. `tests/conftest.py` patches those two points for every mode.
- **LangChain mode stays**, because the internship plan requires it. It becomes a second strategy inside the one pipeline that genuinely differs (a real LangChain retriever object, an LCEL chain) and shares prompts, memory, sources and the event stream. No copied code.
- **LangChain loaders:** either wire them in behind the ingestion interface with the 0-based page fixed and tested, or remove them and say why. No unreachable code.
- **No work at import time.** `main.py` becomes an app factory with a lifespan hook.
- **One `mode` field** (`default`, `hybrid`, `agent`, `langchain`) replaces the four booleans. Update `api.js`, `ChatLayout.jsx`, the frontend tests, the API tests and the OpenAPI snapshot together. Streaming stays a choice of route.
- **Deprecations:** clear them only if it can be done with pinned, audited packages and no behaviour change; otherwise explain what blocks it.
- **No-orphan check** runs in CI. `frontend/design-lab.html` is a deliberate development-only entry point.
- **CI:** update the per-module coverage list to the new paths, keeping the 70% floor.
- **The interface's look does not change.** `DESIGN.md` is the rulebook; the frontend is touched only for the `mode` field.

1. `core/config.py`: the existing `Settings` class, now imported everywhere. Model id, chunk size, top-k, threshold, origins, limits and paths are read from it and nowhere else. (C1)
2. `llm/llm_client.py` and `embeddings/embedder.py`: one factory each, with timeout and output cap set. Remove the other four copies. (C2, S4)
3. `prompts/prompt_templates.py`: every prompt, once, including the question-rewrite prompt as a real template.
4. `ingestion/loader.py`, `chunking/chunker.py`, `vectordb/vector_store.py`, `retrieval/retriever.py`, `memory/conversation.py`: split `rag_engine.py` along these lines.
5. `pipeline/rag.py`: one implementation that yields events; the non-streaming endpoint collects them. Delete the three duplicates. (C2)
6. `api/`: schemas, dependencies and one router file per resource. `main.py` becomes an app factory with a lifespan hook that opens the stores; no work at import time. (C3, C4)
7. `agents/`, `db/`, `evaluation/`.
8. Replace the four boolean flags with one `mode` field: `default`, `hybrid`, `agent`. (F9)
9. Write the no-orphan check and add it to CI.
10. Clear the two deprecations the test run reports: `create_react_agent` has moved out of `langgraph.prebuilt`, and `langchain-community` (used for the document loaders) is being retired.

**Done when**
- All Sprint 2 tests pass unchanged except for import paths.
- The no-orphan check passes: no unimported module, no uncalled route.
- `grep -rn "gemini-" backend/src` returns one line.
- Importing any module does not open a database or need an API key.

## Sprint 4 — Retrieval quality and an honest evaluation (about 5 days)

**Goal:** know how good the system is, with numbers you measured. This sprint is the core of the internship's technical value.

Build the measurement first
1. Choose 3–5 real, non-confidential documents of different kinds. Write 30–50 questions with the expected answer and the page or section that contains it. Include 8–10 questions the documents cannot answer. Store as `evaluation/dataset.jsonl`.
2. Rewrite the harness to call the real pipeline. Report retrieval metrics (hit@5, MRR) from the labelled sections; answer faithfulness and correctness using a judge that is a different model from the generator; refusal accuracy on the unanswerable questions; latency and token count per stage. Fail loudly on a parse error; no default scores. (T3)
3. Record the baseline before changing anything.

Then improve, one change at a time, re-running the harness after each
4. Calibrate the confidence threshold from the baseline score distribution. Apply it to dense similarity in every mode. (R1, R2)
5. Hybrid: fuse on `chunk_id`, cache the BM25 index per user and invalidate on upload, use a real tokenizer. (R3)
6. Ablation: answer from the retrieved chunks directly versus through the summary step. Keep whichever measures better; if it is close, drop the summary for the latency. (R4)
7. Numbered chunks in the prompt and structured output that returns the cited numbers, so sources are the chunks actually used. (R5)
8. `document_id` in chunk metadata; `DELETE /documents/{id}`; re-upload replaces. (R7)
9. Parsing: DOCX tables, headers and footers; every sheet of a workbook, read as text so leading zeros survive; row-aware splitting for wide rows; encoding detection for text files; a 422 without a server path for corrupt files; a clear message for scanned PDFs. (R9)
10. Agent: remove "use your own knowledge" from the prompt, no confidence badge for answers with no retrieval, do date arithmetic in Python. (R11)

**Done when**
- `python -m src.evaluation.evaluate` prints a results table and writes it to `docs/evaluation.md`.
- The table shows baseline against final, and dense against hybrid, on the same dataset.
- Every unanswerable question is refused in every mode.
- You can explain each number and how it was computed.

## Sprint 5 — Hardening and API completion (about 4 days)

**Goal:** safe to put on an office network, and an API the new frontend can be built against.

Security
1. Random tenant UUID per user as the vector-store key; both stores under one `data/` directory. (S2)
2. Closed registration (invite code or allow-list), a longer password minimum, a 72-byte check, ASCII case-insensitive usernames, identical trimming on register and login, constant-time login, 30–60 minute tokens with refresh, tokens rejected when the user no longer exists, logged auth events. (S7)
3. Rate limits keyed by user id on authenticated routes; a default limit on every route. (S8)
4. Upload: stream to disk with a hard cap, authenticate first, check uncompressed size of zip-based formats, cap rows and chunks, a per-user document quota. (S4)
5. Generic client errors with a correlation id; structured logs with user id and without question text; `/health` returns status only; docs endpoints off outside development; security headers and a CSP. (S10)
6. Demote the regex filter to telemetry; escape and constrain filenames in the prompt. (S5)

API
7. `GET /auth/me`. `GET /sessions` and `GET /sessions/{id}/messages`. Stop deleting history on New Thread. (F8, Task 5)
8. Return a `turn_id` with every answer; `POST /feedback` takes it. (F10)
9. Background ingestion with a status endpoint. (R12)
10. Retry with backoff and a friendly message on quota errors. (B10)
11. Re-run `pip-audit`. `chromadb` 1.5.9 had advisories with no fixed release on 11 Oct 2026; upgrade when one exists.

**Done when**
- Tests cover: login as a second user after a database reset sees no old data; a 100-character password is rejected with a 422; a 60 MB upload is rejected without being read into memory; `9**9**9` returns an error in under a second.
- A page refresh keeps the user signed in and restores the conversation.
- The OpenAPI snapshot is updated and reviewed.

## Sprint 6 — Frontend rebuild (about 5 days)

**Goal:** a frontend you would be glad to demo, built against the Sprint 5 API. You said you are willing to change it; this is where to do it, not earlier.

Done early, on 11 October 2026: the visual redesign. Every screen now uses the Prism design language (see [DESIGN.md](DESIGN.md)); the old stylesheets are gone. That work also covered, for the current API, part of item 3 (Stop on the client), item 6 (one mode selector), item 7 (no remote images, links in a new tab, scroll only at the bottom) and most of item 8 (responsive layout, dialog semantics, labels, reduced motion). What remains below is the engineering: TypeScript and generated types, a router, history and threads, feedback, per-claim citations, the keyboard and screen-reader pass, and the Playwright journey. Any new UI must follow DESIGN.md.


1. TypeScript. Generate API types from the OpenAPI schema; one request wrapper that handles 401, 429 and errors uniformly. (T4, F7)
2. A router: landing, login, chat with a thread id in the URL, settings.
3. Chat lifecycle: Stop button with `AbortController`, error state with retry, the question restored on failure, no stale-stream writes into a new thread. (B9, F6)
4. Citations as the centrepiece: numbered markers in the answer, a side panel with the cited passage, page and score. (B7, R5)
5. Thread list with history; per-document management with upload progress and delete; feedback thumbs. (F10, F14)
6. One mode selector instead of four toggles; a visible tool trace for agent answers. (F9)
7. Markdown: no remote images, links open in a new tab. Memoised messages; scroll only when the user is at the bottom. (S3, F13)
8. Responsive from 360 px with an off-canvas sidebar; dialog semantics, focus trap, labels, contrast at 4.5:1, reduced-motion support. (F11, F12)
9. Tests: the stream reader, the chat page, and one Playwright run of the full journey.

**Done when**
- The Playwright journey passes in CI against the real backend with fake models.
- Lighthouse accessibility is 95 or above on the chat page; the app is usable at 375 px.
- No field name is typed by hand in the frontend; a renamed backend field breaks the TypeScript build.

## Sprint 7 — Ship and document (about 3 days)

**Goal:** something a mentor can run with one command, and documents that match it.

Items 1 and 2 (Docker) are deferred at the owner's request, 11 Oct 2026. Do not start them until asked. The `.dockerignore` from Sprint 0 stays, so an image built by hand cannot contain secrets.

1. Multi-stage Dockerfile (Node build, then Python runtime), non-root user, healthcheck. `docker-compose.yml` with one data volume. (D4, S1)
2. Run the end-to-end test against the container in CI.
3. Rewrite the project report for the system as it is: problem, requirements mapped to the plan, architecture diagram, design decisions with the alternatives you rejected and why, the evaluation method and results from Sprint 4, security model, limitations, future work, real screenshots. Name Netweb Software, your mentor and the dates.
4. Settle one attribution and use it everywhere.
5. Decide the data question with your mentor: which documents may be uploaded, on which API tier. Put the answer in the README. (S11)
6. Rehearse the demo on the office network with the billed key, with the organisation's root CA installed if needed. Prepare a recorded fallback. (B10)
7. Re-run the audit prompt from the appendix of `AUDIT_REPORT.md` and fix what it finds.

**Done when**
- `docker compose up` on a clean machine gives a working app at one URL, and data survives a restart.
- Every statement in the report can be traced to a test, a measured number or a file.
- You can answer the ten reviewer questions in section 9 of the audit report without notes.

---

## Suggested order and total

| Sprint | Size | Depends on |
|---|---|---|
| 0 Make it safe to change | 1 day | — |
| 1 Make it work end to end | 3 days | 0 |
| 2 Safety net | 3 days | 1 |
| 3 Restructure and connect | 4 days | 2 |
| 4 Retrieval quality and evaluation | 5 days | 3 |
| 5 Hardening and API completion | 4 days | 3 |
| 6 Frontend rebuild | 5 days | 5 |
| 7 Ship and document | 3 days | 4, 6 |

About 28 working days. If time is short, the order to cut from the end is: Sprint 6 down to items 1, 3, 4 and 8; then Sprint 5 down to items 1, 2, 7 and 8. Do not cut Sprints 0, 1, 2 or 4.
