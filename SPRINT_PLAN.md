# Aether AI — Sprint Plan

Written 11 October 2026 from [AUDIT_REPORT.md](AUDIT_REPORT.md). Finding ids (B1, R4, S3, …) refer to that report. Sizes are rough estimates for one person working full days; adjust them after Sprint 1.

## Status

| Sprint | State | Evidence |
|---|---|---|
| 0 Make it safe to change | Done, merged 11 Oct 2026 (PR #1) | See below |
| 1 Make it work end to end | Done, merged 11 Oct 2026 (PR #1) | See below |
| 2 Safety net | Done, merged 12 Oct 2026 | See below |
| Design: Prism on every screen | Done, merged 12 Oct 2026 together with Sprint 2 | [DESIGN.md](DESIGN.md) |
| 3 Restructure and connect | Done, merged 12 Oct 2026 (PR #3) | See below |
| 4 Retrieval quality and evaluation | In progress. Every code item is merged (12 Oct 2026). What is left is the measuring: the dataset, the baseline, the threshold value and the summary comparison wait for the owner's documents and Gemini quota | See below |
| 5 Hardening and API completion | Done, merged 13 Oct 2026 (from the branch `confident-bell-h8c2ct`) | See below |
| 6 Frontend rebuild | Visual redesign done early; engineering items remain. **This is the next sprint**: Sprint 5 is merged, and the decisions for it are written | See "Decisions already made" under Sprint 6 |
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
- **Model calls now have a 120 s timeout and an 8192-token output cap; embeddings a 60 s timeout.** Checked against the real API on Windows (below). The chat model still retries six times, so a dead connection can hold a request for several minutes; set that with the error handling in Sprint 5.

Sprint 3 on the owner's Windows machine, on the branch and again on the merged code in the project folder:

- `ruff` clean; `pytest` 307 passed and 20 xfailed (308 with the log test below), 99% coverage; `npm run lint` (0 errors), `npm test` 26 passed, and build.
- A real `uvicorn` server with fake models: register, login, upload, chat in all four modes, streaming in three, feedback, clear, delete and the login rate limit. Tokens arrived one per second as produced, and `/health` answered in 0.46 s during a stream. A request that still sends an old flag (`use_hybrid`) is now a 422.
- With the real Gemini key and temp stores: one upload and one streamed question, answered correctly with its source (confidence 0.74). So the embedding client rebuilt with a timeout, and the chat model's timeout and output cap, work against the real API.
- The existing database, vector collection and `.env` are read unchanged: the restarted app reported the same 2 documents and 45 chunks as before.
- **Found here and fixed: `requests.log` was never written** (the audit noted the file was absent). The logger was named `requests`, which is also the HTTP library's logger and already has a handler, so the setup skipped it and chat lines reached neither a file nor the terminal. The three loggers are now `aether.requests`, `aether.uploads` and `aether.errors`, and a test reads the chat line back from the file.

Sprint 4 so far (branch `sprint-4`, done on the owner's Windows machine, 12 Oct 2026):

| Item | State | Proof |
|---|---|---|
| 1 Dataset | Waiting for the owner: 3 to 5 non-confidential documents and 30 to 50 labelled questions | The format is in the README, "Measuring answer quality" |
| 2 Harness (T3) | Done | `tests/unit/test_evaluation.py` (30 tests); the seam checklist's evaluation box |
| 3 Baseline | Not run: needs the dataset. The tag `eval-baseline` marks the commit to measure it on (the new harness, the old pipeline) | |
| 4 Threshold (R1, R2) | Half done: the threshold and the confidence now use cosine similarity in every mode. The value is still 0.3, uncalibrated | `tests/unit/test_search.py` |
| 5 Hybrid search (R3) | Done | `tests/unit/test_search.py` |
| 6 Summary step or not (R4) | The switch exists (`AETHER_ANSWER_FROM`); the comparison is not run | `tests/integration/test_sources.py` |
| 7 Cited sources (R5) | Done behind that switch; a refusal lists no sources in every case | `tests/integration/test_sources.py` |
| 8 Document identity (R7) | Done: every chunk carries its document's id; `DELETE /documents/{document_id}`; a changed file of the same name replaces the earlier one; the library has a remove control per document | `tests/integration/test_documents.py`, `ChatLayout.test.jsx`; checked in a browser |
| 9 Parsing (R9) | Done | `tests/unit/test_parsers.py`, `tests/unit/test_chunker.py` |
| 10 Agent (R11) | Done: no answers from the model's own knowledge, date arithmetic in Python, no confidence for an answer that searched no document | `tests/integration/test_agent.py`, `tests/unit/test_datetime_tool.py`, `tests/unit/test_prompts.py` |

- `python -m pytest`: 421 passed, 0 xfailed, 99% coverage, with no API key. `ruff check .` clean. All twenty strict xfails are fixed and their tests moved beside the code's other tests. Frontend: lint 0 errors, `npm test` 30 passed, build.
- The API changed in three places, each reviewed in the OpenAPI snapshot's diff: `confidence` may be null, the upload response gained `document_id` and `replaced`, and `DELETE /documents/{document_id}` is new.
- A real `uvicorn` server with fake models: register, login, upload, chat in all four modes, streaming, feedback, delete and the login rate limit.
- With the real Gemini key and temp stores: a Word file whose facts are in a table and a CSV of part codes were ingested. Hybrid search gave the same similarities as dense search (0.71 and 0.61). "Who inspects the blades, and how often?" was answered from the table. With `AETHER_ANSWER_FROM=chunks`, the answer was "The code for the rotor bearing is 0420 [1]. It is located in bin C3 [1].", with the leading zero kept and only the cited chunk listed as a source.

What Sprint 4 found, and where the plan was wrong:

- **Encoding detection is not safe, so it was not built (item 9).** `charset-normalizer` 3.4 read "Le café est fermé." saved as Windows-1252 as UTF-16 Chinese characters, and a longer French sample as cp775 ("cafķ"). Text and CSV files are read as UTF-8, or UTF-16 with a byte-order mark; anything else is refused with a message saying how to re-save it.
- **Inline `[1]` citations, not structured output (item 7).** A JSON answer could not be streamed word by word.
- **The summary step stays the default until it is measured (item 6).** One real answer written from chunks took 18 s; one through the summary took 57 s on the same afternoon, but Gemini was returning 503s, so that is not a measurement.
- **An unrelated question still scored 0.55** against two small documents (answerable ones scored 0.71 to 0.78). The 0.3 threshold refuses nothing; the harness's suggested threshold will set it once there is a dataset.
- **A Gemini outage holds a request for about 60 s before the error**, because the chat model retries six times. For Sprint 5 item 10.
- **`--retrieval-only` needs no model calls**, only embeddings: hit@5, MRR, the dense-against-hybrid comparison and the threshold can be measured on the free tier. Correctness and faithfulness need about four model calls per question and mode.

Sprint 5, checked on Linux (Python 3.12, Node 22), on the branch `confident-bell-h8c2ct`:

| Item | Proof |
|---|---|
| 1 Tenant ids, one `data/` folder (S2) | `tests/integration/test_tenants.py`: a user registered after a database reset gets the old owner's id and sees none of their data, in all four modes (keyed by user id instead, all four fail); a store built the Sprint 4 way is searchable after the startup migration, which is safe to run twice and gives no chunk to a user without a record for it; the old default paths are still used, with a note |
| 2 Sign-up and sign-in (S7) | `tests/integration/test_sign_in.py` (30 tests), including the "done when" 100-character password (422) |
| 3 Rate limits (S8) | `tests/integration/test_api_routes.py`: two users on one address each get their own allowance; every route has a limit |
| 4 Upload limits (S4) | `tests/integration/test_upload_limits.py`, including the "done when" 60 MB upload, sent straight to the app over ASGI: with its size declared it is refused with 0 bytes read; without, after 51 MB, with a 3 MB peak in Python memory |
| 5 Errors, logs, health, API pages, headers (S10) | `tests/integration/test_exposure.py`, and the log tests in `test_api_routes.py` |
| 6 Injection filter as telemetry, file names (S5) | `tests/unit/test_prompts.py`, `tests/integration/test_injection_and_names.py` |
| 7 `/auth/me`, `/sessions`, New thread keeps history (F8) | `tests/integration/test_sessions.py`; `App.test.jsx` and `ChatLayout.test.jsx`; the browser check below |
| 8 `turn_id` and feedback by turn (F10) | `tests/integration/test_feedback.py` |
| 9 Background ingestion (R12) | `tests/integration/test_documents.py` (status route, restart recovery), every content limit reported in the status |
| 10 Retries and one clear message (B10) | `tests/unit/test_model_retries.py`, `tests/integration/test_model_unavailable.py`: a long outage is a 503 with the message in under 2 s, not about 60 s |
| 11 `pip-audit` | Run on 12 Oct 2026: `chromadb` 1.5.9 is still the only package flagged (PYSEC-2026-311, -3813, -3814, -3815), and 1.5.9 is still its latest release, so there is nothing to upgrade to. All four are in Chroma's HTTP server (its `/api/v2` routes and its RBAC provider); this app opens Chroma as an embedded `PersistentClient` and never runs that server. `npm audit`: 0 vulnerabilities |

- `python -m pytest`: 566 passed, with neither `GOOGLE_API_KEY` nor `JWT_SECRET` set. `ruff check .` clean. Coverage 99%; every module in the CI list at 95% or above. Frontend: `npm ci`, `npm run lint` (0 errors; the one warning is the old one in `AuthContext.jsx`), `npm test` 51 passed, `npm run build`.
- The OpenAPI snapshot was refreshed in each commit that changed the API, and each diff reviewed: new routes `/auth/refresh`, `/auth/logout`, `/auth/me`, `/sessions`, `/sessions/{id}/messages` and `GET /documents/{id}`; the upload reply is now 202 `{document_id, filename, status, replaces, message}`; `ChatResponse.turn_id`; feedback takes `{turn_id, feedback}`; `Token.expires_in`; `UserRegister.invite_code`.
- A real `uvicorn` server with fake models and the built app, in Chromium (Playwright): sign up, upload (read in the background), ask; reload: still signed in, the conversation and its sources back, the real name in the rail; New thread, reload: the earlier conversation is still there; sign out, reload: signed out. No content-security-policy violation in the console; the only console errors are the two expected 401s from asking `/auth/refresh` while signed out. Every response carried the security headers and a request id.

What Sprint 5 found, and where the plan was wrong:

- **The test client cannot show that an upload is not read into memory**: it reads a request body whole before the app sees it. The 60 MB test calls the app over ASGI directly, with a body made as it is read.
- **A failed insert held SQLite's write lock**: `create_user` left its connection open when the insert failed, and the next write waited and failed with "database is locked". Found by the race test; fixed. Two tokens made in the same second were also identical; each now has an id.
- **A refresh token is not revoked on the server.** Sign-out removes the cookie; an access token already issued works until it expires (30 minutes at most). A stolen refresh cookie would work for a week. A token table would close that; it is not built.
- **Two defaults stay open so the owner's setup keeps working**: registration (decision 8) and the API pages (`AETHER_ENVIRONMENT` is `development` unless set). Both must be set before the app is reachable by anyone else; the README says how.
- **Rate-limit counts live in the server's memory**, as before, and start again at a restart. A request that fails validation still never reaches a route's own limiter.
- **DESIGN.md placed "cancelling on the server" in Sprint 5**, but the plan's items do not include it, and it was not done: Stop still only ends the reply on the screen.
- **A store at the old path is used, not moved.** Moving the owner's `backend/aether.db` and `backend/vector_store/` into `data/` is left to the owner (README, "Where data is kept").
- **Chunks no record accounts for are kept, unsearchable**, by decision 1. There is no tool to remove them; the startup log counts them.

Sprint 5 on the owner's Windows machine, before and after the merge (13 Oct 2026):

- On the branch and again on the merged code in the project folder: `ruff` clean; `pytest` 566 passed, 99% coverage, no API key; `npm run lint` (0 errors), `npm test` 51 passed, and build.
- The new code was started twice on a copy of the owner's database before the real one was touched: every earlier user unchanged and given a tenant id, the same ids on the second start, the conversation history kept, and the new routes (refresh, `/auth/me`, upload status, sessions, feedback by turn) walked with fake models. The database was backed up first, to `.backups/before-sprint-5/` (ignored by git).
- A real `uvicorn` server with fake models and the built app, in Chromium: sign up, an upload read in the background, ask; reload: still signed in, with the conversation, its sources and the library back; New thread; remove a document. The only console error was the expected 401 from asking `/auth/refresh` while signed out.
- With the real Gemini key and temp stores: an upload was ready in 4 s, and a hybrid streamed question was answered correctly with its source (confidence 0.74) and could be read back for a reload.
- The owner's database was then upgraded in place by the first start: 4 users with tenant ids, 17 conversation turns kept. The stores are still at `backend/aether.db` and `backend/vector_store/`; the startup logs a note about the new default (`data/` at the project root) each time.
- **A correction to earlier evidence in this file.** "The same 2 documents and 45 chunks as before" (Sprint 3) was read from `/health`, which counted database records. Those two records date from June 2026, belong to the locked `__legacy_migration__` user, and have no vectors: the old vector store was deleted on 11 Oct 2026 to recreate it with cosine distance, and `backend/vector_store/` has been empty since. No account has a searchable document on this machine until one is uploaded. Nothing was lost in Sprints 3 to 5; the count was never evidence of searchable data.
- Anyone signed in before the merge must sign in again: tokens now carry the tenant id. Passwords are unchanged.

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
- [x] Evaluation: the harness imports and calls the real pipeline (`tests/unit/test_evaluation.py::test_run_asks_the_real_pipeline_and_scores_it`)

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

Decisions already made for this sprint (do not reopen them; say so in the pull request if one turns out to be wrong):

1. **Existing data must survive.** The owner has a database and a vector store made by today's code, with chunks keyed by the integer `user_id` and, since Sprint 4, a `document_id`. Item 1 needs a migration that runs at startup and is safe to run twice, with a test that builds a store the old way and reads it the new way. Never delete or recreate a store to make a change easier.
2. **Moving the stores under `data/` is a change of default only.** `AETHER_DB_PATH`, `AETHER_VECTOR_STORE_DIR` and `AETHER_LOG_DIR` keep working, and a store found at the old default path is still used (with a logged note) rather than silently starting empty.
3. **Every API change is made on both sides in one commit**: the route, the OpenAPI snapshot (refresh it and review the diff), `frontend/src/services/api.js`, and the contract test. A change that breaks the snapshot test or the no-orphan check is not finished.
4. **Item 7 changes what New Thread does**: it starts a new session and keeps the old one. The interface work for restoring a conversation after a refresh follows `DESIGN.md`; no new styling approach. A thread list in the rail is Sprint 6, not this sprint: here it is enough that a refresh restores the current conversation.
5. **Item 8 replaces "the most recent message in the session"** as the target of feedback with a `turn_id`. Keep the feedback values as they are (1, -1, 0).
6. **Item 10**: the chat model retries six times today, which held a request for about 60 s during a Gemini outage on 12 Oct 2026. Set retries and the timeout in `core/config.py`, retry only quota and availability errors, and return one clear message. Test it with the fake model raising those errors; no real calls.
7. **Item 9 (background ingestion)** uses FastAPI's own background tasks and a status column on the document record. No queue, no new service, no new dependency.
8. **Registration (item 2)**: closed by an invite code from `core/config.py` (`AETHER_INVITE_CODE`); empty means registration is open, which is today's behaviour and stays the default so the owner's setup keeps working.
9. **Leave alone**: the evaluation harness and its metrics, the `answer_from` default, the confidence threshold value, and the Docker items. They wait for measurements or for the owner.
10. **Dependencies**: add none unless an item cannot be done without it; say why in the commit. `pip-audit` (item 11) is run and reported, and an upgrade is one commit per package.

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

Decisions already made for this sprint (do not reopen them; say so in the pull request if one turns out to be wrong):

1. **The look does not change.** Every screen keeps the Prism design; `DESIGN.md` is the rulebook. New interface (thread list, feedback, citation markers, retry) is built from the tokens and components in `frontend/src/design/`. No UI kit, no CSS framework, no new font, no second styling approach. Add a screenshot of each new piece to `docs/design/` and a row for it in `DESIGN.md`'s component table.
2. **New dependencies are these five and no others**: `typescript`, `openapi-typescript`, `react-router`, `@playwright/test` and `@axe-core/playwright`. No state library and no data-fetching library: React state and the one request wrapper are enough for an app this size.
3. **TypeScript everywhere under `frontend/src`**, tests included, with `strict: true`. `npm run typecheck` (`tsc --noEmit`) is added to the scripts, to `npm run build` and to CI. No `any` and no `@ts-ignore` without a comment saying why. The 51 existing tests are converted, not weakened or dropped.
4. **API types are generated from `backend/tests/openapi_snapshot.json`** with `openapi-typescript`, into one committed file. No server and no network are needed to generate them. CI regenerates the file and fails if it differs from the committed one, so a renamed backend field breaks the TypeScript build.
5. **The backend may change only to make those types useful**, in `src/api/schemas.py` and the routes' declarations. Ten routes have an untyped reply in the schema today (register, logout, health, the document list, the detailed list, both deletes, feedback, clear session and the chat stream), and `sources` is an untyped list in `ChatResponse` and `Turn`. Give each a model, including one for a source and one for each stream event (`token`, `done`, `error`), so that all of them appear in the schema. Field names and values on the wire stay exactly as they are. Refresh the snapshot and review its diff, as the project rules say.
6. **One request wrapper** replaces the repeated fetch code in `api.js`. On a 401 it asks `/auth/refresh` once and repeats the request; if that fails it signs the user out to the start page with a message. On a 429 it says to wait, using `Retry-After` when present. On any other error it shows the server's `detail`, which for a server error already ends with its reference id.
7. **Real paths, not hash paths**: `/` (start page), `/login` (the start page with the sign-in sheet open), `/chat` and `/chat/:threadId` (the thread id is the `session_id`), and `/settings` (the chat with the settings sheet open). The backend must then serve the built app for those paths: in `main.py`, a request outside `/api/` that matches no file returns `index.html`; an unknown path under `/api/` stays a JSON 404. Test both in `tests/integration/test_frontend_serving.py`.
8. **Threads**: the rail lists the user's conversations from `GET /sessions` (title and date), newest first, with the open one marked `aria-current`. Choosing one loads `GET /sessions/{id}/messages` and puts its id in the URL. Renaming and deleting a thread are not in this sprint: there is no route for either.
9. **Feedback**: thumbs up and down on each answer that has a `turn_id`, sent with `POST /feedback`; pressing the chosen one again clears it (value 0). The chosen value is restored after a reload from `Turn.feedback`, which `GET /sessions/{id}/messages` already returns.
10. **Citation markers**: when an answer's sources carry a `number` (the server's `AETHER_ANSWER_FROM=chunks` mode), each `[n]` in the answer becomes a `Cite` chip tied to source card n, by hover and by keyboard. When they do not (the default), the answer and its sources are shown as today. Do not change the server's default: it waits for the Sprint 4 measurement. Test both cases.
11. **Stop and retry (item 3)**: closing the stream is the only signal the server gets, and no cancel route is added. Prove with a backend test that a stream closed early saves no turn. On the client, a reply that fails or is stopped leaves the question in the composer with a Retry action, and a reply that finishes after its thread was left is discarded, not written into the thread now open.
12. **Agent answers (item 6)** show which tools ran, from `tool_used`, as a labelled row. A step-by-step trace would need a new server response and is not in this sprint.
13. **The Playwright journey** lives in `frontend/e2e/` and runs with `npm run e2e`: sign up, upload, wait until ready, ask, see the sources, reload and find the conversation back, start a second thread, return to the first from the thread list, rate an answer, remove the document, sign out. It starts its own servers through Playwright's `webServer`: the backend with the fake models from `backend/tests/fakes.py` (put the launcher in `backend/tests/`) on temp stores, serving the built app. It must work on Windows from a folder whose path has spaces, with no Unix shell. Add it to CI with Chromium only.
14. **Accessibility gate**: inside the journey, run axe on the start page, the chat and the settings sheet at 1280 px and at 375 px, and fail on any serious or critical violation. Measure the Lighthouse accessibility score of the chat page once and report it in the pull request; if it cannot be run in the session, say so and the owner's machine will measure it.
15. **Performance (item 7)**: an answer already on screen must not re-render or re-parse its Markdown while a later answer streams. Prove it with a test that counts renders.
16. **Leave alone**: the evaluation harness, `answer_from`, the confidence threshold and `GROUNDED_AT`, the Docker items, and every backend behaviour not named above. `frontend/design-lab.html` keeps working.

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
