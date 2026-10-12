# Aether AI — Second Audit Report

Audit date: 13 October 2026, after Sprints 0 to 6, on the branch `sprint-7`. It runs the prompt in the appendix of [AUDIT_REPORT.md](AUDIT_REPORT.md) against the code as it is. The first report is not edited; this one says, for each of its findings, whether it is **fixed**, **open** or **changed**, with the test or file that shows it, and adds new findings with ids starting **N**. Small findings were fixed in this sprint, one commit each with its test; the rest are listed with the reason.

## 1. Verdict

The system the first audit could not get to answer a question is now one connected, tested application. Every chat mode works end to end with fake models in the test suite and with the real Gemini key on the owner's machine (SPRINT_PLAN.md, Sprints 1 to 5). Of the first audit's 64 numbered findings (B, R, S, F, T, C, D), 50 are fixed, 12 are partly fixed or changed, and 2 are open (S11, which documents may be uploaded, and D4, Docker). What remains of each partly fixed one waits on something outside the code: a dataset and its measurements, the owner, the mentor, or the deferred Docker work.

- **What still blocks a claim of quality is measurement, not code.** The evaluation harness calls the real pipeline (Sprint 4), but there is no dataset, so there is no measured number: the refusal threshold is still the uncalibrated 0.3, and whether the summary step helps is unknown (T3, R1, R4).
- **Two real defects were found and fixed here.** A document removed while it was still being read stayed searchable (N2), and every 429 reply had a different shape from every other error and no `Retry-After` (N1).
- **What is open on security is known and written down**: refresh tokens are not revoked on the server (N5, Sprint 8 item 4), the app is served over plain HTTP, and the documents allowed on the free tier are not yet agreed (S11).

## 2. How this was audited

Every backend module and every frontend source file was read; the earlier sprints' evidence in SPRINT_PLAN.md was checked against the tests it names. Where a claim could be run, it was run, against temp stores and the fake models of `backend/tests/fakes.py`, with no API key and no network call to Google:

- the whole test suite (`pytest`, 587 tests), the frontend tests (82), and the browser journey (`npm run e2e`) with its axe checks;
- the two rate limits, driven past their limit, to read the 429 replies (N1);
- the removal of a document while it is read, through the background task (N2);
- Chroma's filtered search over collections with identical vectors, in a scratch probe (N4);
- `pip-audit` and `npm audit`; Lighthouse on the signed-in chat page;
- a script comparing the class names in the markup with the stylesheets (F15).

Evidence codes, as in the first report: **R** reproduced by running something, **C** confirmed by reading the code.

Not verified: anything on Windows or on the office network, anything that needs a live Gemini call, and a Docker build (deferred).

## 3. Is everything connected? (wiring map)

| Seam | State | Evidence |
|---|---|---|
| Web app (`api.ts`) → `/api/v1` routes | Connected, typed from the schema | `src/services/api-schema.ts` (generated, checked in CI), `api.contract.test.ts` |
| Backend → web app | Connected: the build is served at `/` and at the app's own paths | `main.py` (`SinglePageApp`), `test_frontend_serving.py` |
| Everything → `core/config.py` | Connected; nothing else reads the environment | `test_no_orphans.py::test_only_core_config_reads_the_environment` |
| Routes → pipeline, four modes | Connected | `test_e2e.py` (all modes), `test_reply_models.py` |
| LangChain loaders → ingestion | Connected behind `AETHER_DOCUMENT_LOADER` | `test_documents.py::test_upload_with_the_langchain_loader_cites_pages_from_one` |
| Agent → tools | Connected | `test_agent.py` |
| Pipeline → ChromaDB (cosine, per tenant) | Connected | `test_vector_store.py`, `test_search.py`, `test_tenants.py` |
| Pipeline ↔ database (memory) | Connected, with confidence, mode, sources and tool | `test_memory.py`, `test_sessions.py` |
| Feedback ↔ web app | Connected, by turn id | `test_feedback.py`, `ChatLayout.test.tsx`, the journey |
| Conversations ↔ web app (thread list, reload) | Connected | `test_sessions.py`, `ChatLayout.test.tsx`, the journey |
| Evaluation harness ↔ pipeline | Connected; no dataset to run it on | `test_evaluation.py::test_run_asks_the_real_pipeline_and_scores_it` |
| Tests ↔ app | Connected: every route is called by a test | `test_no_orphans.py::test_every_route_has_a_test_that_calls_it` |
| Loggers ↔ routes | Connected; `requests.log`, `uploads.log`, `errors.log`, `auth.log` are written | `test_api_routes.py` (log tests) |
| Rate limiter ↔ routes | Every route | `test_api_routes.py::test_every_api_route_has_a_limit` |
| Dockerfile ↔ app | **Not connected** (deferred by the owner) | D4 |
| `start.bat` ↔ environment | Connected: the project's `.venv`, both servers | `start.bat` |

## 4. The first audit's findings, now

### 4.1 Blockers

| Id | Now | Evidence |
|---|---|---|
| B1 LangChain mode crashes | Fixed | `test_langchain_mode.py`; `test_e2e.py` runs it |
| B2 Empty store, never exercised | Fixed for the code: every mode runs end to end in tests and ran on the owner's machine with the real key. The owner's own store has no searchable document until one is uploaded (SPRINT_PLAN.md, Sprint 5, "a correction") | `test_e2e.py` |
| B3 The backend serves the dead UI | Fixed for `uvicorn`; the Dockerfile still ships no UI (D4, deferred) | `test_frontend_serving.py`; `backend/static/` deleted |
| B4 Restarts log everyone out | Fixed: the backend refuses to start without `JWT_SECRET` | `test_startup.py::test_backend_refuses_to_start_without_jwt_secret` |
| B5 Cannot be started from its own files | Fixed | `start.bat`, README |
| B6 Landing page cannot scroll | Fixed (the redesign; the page is in normal flow) | `frontend/src/index.css`; the journey scrolls nothing sideways at 360 px |
| B7 Citation cards open empty | Fixed: file, page, score and passage | `ChatLayout.test.tsx` ("sends a question and shows the streamed answer with its source card") |
| B8 Hybrid toggle stale | Fixed: one mode in the request | `ChatLayout.test.tsx` ("passes the Hybrid mode to the request") |
| B9 No error or cancel lifecycle | Fixed: an `error` event, a missing `done` is an error, Stop closes the stream and nothing is saved, Retry | `api.test.ts`, `test_stream_closed.py`, `ChatLayout.test.tsx` |
| B10 Quota and network | Changed: quota and availability errors are retried and reported in one message; `docs/demo-checklist.md` covers the billed key and the root certificate. **Open** until the owner has a billed key and has tried the office network | `test_model_retries.py`, `test_model_unavailable.py` |
| B11 One slow request blocks the server | Fixed | `test_concurrency.py` |

### 4.2 RAG pipeline

| Id | Now | Evidence |
|---|---|---|
| R1 Not cosine; uncalibrated 0.3 | Cosine fixed. **Open**: the threshold is still 0.3, waiting for a dataset (an unrelated question scored 0.55 in the real run of 12 Oct) | `test_vector_store.py::test_collection_uses_cosine_distance` |
| R2 Hybrid can never refuse | Fixed: the threshold is applied to dense similarity in every mode | `test_search.py::test_an_off_topic_question_is_refused_in_every_mode_without_asking_the_model` |
| R3 Five hybrid defects | Fixed | `test_search.py` |
| R4 Answer from a summary | Changed: `AETHER_ANSWER_FROM=chunks` answers from numbered chunks. **Open**: the default stays `summary` until the comparison is measured | `test_sources.py` |
| R5 Sources are every chunk | Fixed in `chunks` mode (the cited chunks, now tied to the answer's `[n]` in the interface); a refusal lists none in every mode. In the default mode the sources are the retrieved passages, one per page | `test_sources.py`, `ChatLayout.test.tsx` (citation markers) |
| R6 Same file twice doubles chunks | Fixed: a 409 | `test_documents.py::test_reupload_of_same_file_is_rejected` |
| R7 No document identity | Fixed | `test_documents.py` |
| R8 Delete misreports | Fixed | `test_documents.py::test_delete_returns_the_real_chunk_count` |
| R9 Parsing loses content | Fixed: tables, every sheet as text, wide rows, clear messages for unreadable files. Changed: text that is not UTF-8 is refused with a message, because detection was measured as unsafe. **Open**: no OCR for scanned PDFs (they get a message) | `test_parsers.py`, `test_chunker.py` |
| R10 Memory lossy and polluted | Fixed; the cache that was never evicted is now bounded (this sprint, 8a983de) | `test_memory.py`, `test_conversation_memory.py::test_the_cache_keeps_only_the_most_recently_used_sessions` |
| R11 Agent undermines grounding | Fixed: no own-knowledge answers, date arithmetic in Python, no confidence without a search, calculator fixed. Changed: the agent's answer is still sent word by word after it is finished; since Sprint 6 it is saved only once sent | `test_agent.py`, `test_datetime_tool.py`, `test_calculator.py`, `test_stream_closed.py` |
| R12 Ingestion inside the request | Fixed: read in the background, with a status | `test_documents.py::test_an_upload_is_accepted_at_once_and_read_after_the_reply` |

### 4.3 Security

| Id | Now | Evidence |
|---|---|---|
| S1 Docker image would hold secrets | Fixed for secrets (`.dockerignore`, `override=False`). The image itself is still the old one (D4, deferred) | `.dockerignore`, `core/config.py` |
| S2 Reusable tenant ids | Fixed: random tenant ids, migrated at startup, both stores under `data/` | `test_tenants.py` |
| S3 Images can carry data out | Fixed (Sprint 1 and the redesign); **had no test**, now has one (53e0631) | `ChatLayout.test.tsx` ("loads no image an answer names…"), `test_exposure.py` (CSP) |
| S4 Unbounded work | Fixed | `test_calculator.py`, `test_agent.py::test_agent_loop_is_bounded`, `test_model_factories.py`, `test_upload_limits.py` |
| S5 Injection filter blocks good text | Fixed: telemetry only; file names cleaned and escaped | `test_prompts.py`, `test_injection_and_names.py` |
| S6 Override in the system prompt | Fixed | `grep -r OVERRIDE backend/src` finds nothing |
| S7 Authentication basics | Fixed, except revocation: see N5 | `test_sign_in.py` |
| S8 Limits keyed by address | Fixed: by user when signed in; every route has a limit. Counters are in memory (N9) | `test_api_routes.py` |
| S9 Unvalidated fields | Fixed | `test_validation.py` |
| S10 Information exposure | Fixed: errors carry a reference, not the exception; `/health` says only "ok"; API pages off in production; security headers and a CSP. **Open**: no HTTPS, by deployment | `test_exposure.py` |
| S11 Data handling | **Open**: which documents may be uploaded on which tier needs the mentor (Sprint 7, item 5) | README, `docs/demo-checklist.md` |
| S12 Dependencies | Fixed: pinned, a virtual environment. `pip-audit` (13 Oct 2026): `chromadb` 1.5.9 still has four advisories, all in its HTTP server, which this app does not run; 1.5.9 is still the latest release. `npm audit`: 0 | `requirements.txt` |
| S13 Legacy page | Fixed: deleted | — |

### 4.4 Frontend

| Id | Now | Evidence |
|---|---|---|
| F1, F2, F3 | Fixed (B6, B7, B8) | above |
| F4 Settings shows wrong data | Fixed | `SettingsModal.tsx` (fields from the generated types) |
| F5 "Hard Reset" does nothing | Fixed: removed; "Delete all documents" calls the API, behind a hold | `SettingsModal.tsx` |
| F6 New thread during a stream | Fixed: a reply finishing after its thread was left is discarded; the server saves it to its own thread | `ChatLayout.test.tsx` |
| F7 Zombie session on 401 | Fixed: renewed once, else signed out to the start page with a message | `api.test.ts`, `App.test.tsx` |
| F8 Placeholder user and versions | Fixed: the real name, a real title, one version (2.0.0) shown in Settings (this sprint) | `App.test.tsx`, `test_version.py` |
| F9 Mode toggles | Fixed: one mode; the tools an agent used are shown | `ChatLayout.test.tsx` |
| F10 Feedback not wired | Fixed | `test_feedback.py`, `ChatLayout.test.tsx`, the journey |
| F11 Not usable at phone width | Fixed: checked at 375 and 360 px | the journey |
| F12 No accessibility baseline | Fixed: axe on the main screens at two widths, no serious or critical violation; Lighthouse 100. **Open**: no pass with a real screen reader | the journey; SPRINT_PLAN.md, Sprint 6 |
| F13 Re-render while streaming | Fixed | `rendering.test.tsx` |
| F14 Upload flow | Fixed: every accepted type, several files one after another, a size check first, the stage shown. **Open**: an upload in flight cannot be cancelled | `ChatLayout.test.tsx` |
| F15 Class names and rules drifted | Fixed: every class used in the markup has a rule (checked by script on 13 Oct 2026) | `src/design/*.css` |
| F16 Template leftovers | Fixed: a real README, TypeScript, fonts bundled | `frontend/README.md` |

### 4.5 to 4.7 Tests, structure, repository

| Id | Now | Evidence |
|---|---|---|
| T1 Five tests | Fixed: 587 backend tests, 82 frontend tests, one browser journey; every route has a test | `test_no_orphans.py` |
| T2 Tests touch real data | Fixed | `tests/conftest.py`; CI runs without secrets |
| T3 The evaluation measures nothing | Harness fixed (Sprint 4). **Open**: no dataset, so no result | `test_evaluation.py` |
| T4 No frontend tests, types or CI | Fixed | `.github/workflows/ci.yml` |
| C1 Dead config | Fixed | `test_no_orphans.py` |
| C2 Four pipelines | Fixed: one | `pipeline/rag.py` |
| C3 Work at import | Fixed | `test_startup.py::test_importing_every_module_opens_nothing_and_needs_no_key` |
| C4 Two large files | Fixed: the layout of section 6 of the first report | `backend/src/` |
| D1 No git | Fixed | — |
| D2 Wrong `.gitignore` | Fixed | `.gitignore` |
| D3 Clutter | Fixed: deleted | — |
| D4 Dockerfile | **Open**: deferred at the owner's request (11 Oct 2026) | `Dockerfile` |

### 4.8 Documentation

| Claim (first report, 4.8) | Now |
|---|---|
| `SDLC_PLAN.md`: "PRODUCTION READY…", "100%…", and the others | Changed: the file is marked as a historical log, with each false claim named at its top |
| `project_report.md`: NumPy, no auth, Gemini 2.5 Flash Lite, DuckDuckGo, placeholders | Fixed in this sprint: rewritten for the system as it is (item 3), every claim tied to a test, a file or a recorded measurement |
| `walkthrough.md` | Fixed: deleted |
| Attribution inconsistent | Fixed in this sprint: one sentence everywhere (item 4) |

New documentation drift found and fixed: see N3.

### 5. The internship plan, now

| Task | Then | Now |
|---|---|---|
| 1 Prompt templates | Done | Done: every prompt once, as a template (`prompts/prompt_templates.py`) |
| 2 Structured JSON output | Partial | Done: Pydantic models for every reply, typed in the schema |
| 3 Sequential chain | Done | Done: retrieve → summarise → answer (the default) |
| 4 Conversation memory | Done | Done |
| 5 Chat history UI | Partial | Done: thread list, a conversation per address, survives a reload |
| 6 Source attribution | Partial | Done: file, page, score and passage; cited chunks in `chunks` mode |
| 7 Confidence threshold | Partial | Done in every mode; the value is uncalibrated (R1) |
| 8 Prompt-injection protection | Done (basic) | Changed: the regex is telemetry; documents are delimited and file names escaped; output and tool limits do the rest |
| 9 Calculator tool | Done | Done |
| 10 Date-time tool | Done | Done, with the arithmetic in Python |
| 11 Agent decision layer | Done | Done, as an opt-in mode rather than the default router the plan draws |
| 12 LangChain document loaders | Unreachable | Done, behind `AETHER_DOCUMENT_LOADER` |
| 13 Text splitter | Done | Done |
| 14 RetrievalQA chain | Broken | Done: a LangChain retriever and an LCEL chain in `langchain` mode |
| 15 LCEL refactor | Done | Done |
| 16 Logging | Done in code | Done, written and tested |
| 17 Error handling | Done (basic) | Done |
| 18 Streaming | Done in default mode | Done in every mode (the agent's after it has finished) |

## 6. New findings

| Id | Severity | What and where | Status |
|---|---|---|---|
| N1 | Low | Both rate limits answered 429 with `{"error": "Rate limit exceeded: 10 per 1 minute"}` (slowapi's default handler, `main.py`): the only error without a `detail`, and with no `Retry-After`, so the web app could only say "wait a moment". **R** | Fixed (6f959ad): `api/errors.py::rate_limited` answers `{"detail": "Too many requests. Please wait N seconds…"}` with `Retry-After: N`; `test_api_routes.py` |
| N2 | Medium | A document removed while it was still being read (the library offers Remove on a "Reading" row), or "Delete all" during a reading, lost its record, but the background reading then stored its passages anyway: searchable, with nothing left to delete them by (`pipeline/documents.py::finish_document`). The web app then showed "No such document." as an error. **R** | Fixed (b6d0b4d): the reading checks the record is still there and removes what it stored if not; `test_documents.py::test_a_document_removed_while_it_is_read_leaves_nothing_behind`, `ChatLayout.test.tsx` |
| N3 | Low | Documentation drift: DESIGN.md gave 860 px for the workspace's stacking point (it is 900 px; 860 px is the start page's bench) and still said Prism lived on a branch; the README said a reload shows "your latest conversation" (since Sprint 6 it stays on the one in the address). **C** | Fixed (f21e43f) |
| N4 | Low | Over many identical vectors, Chroma's filtered HNSW search misses chunks of the tenant asked for. The test suite has that shape (most tests upload one file for a new user) and two of four full runs failed on 13 Oct; a probe of 4,000 chunks of 20 repeated vectors missed in 18 of 18 queries, and raising `ef_search` did not help. Real sharing does not: 50 users with the same 40-chunk handbook, or 20 with a 200-chunk one, missed in 0 of 40 queries each. **R** | Not fixed in the app: no realistic case reproduces it. The search tests use a store of their own (Sprint 6, 285554c). Worth re-checking if many users ever share one large document |
| N5 | Medium | A refresh token is not revoked on the server: signing out removes the cookie, but a stolen refresh cookie works for a week (`api/routes_auth.py`). **C** | Open: Sprint 8, item 4 (sign out everywhere) |
| N6 | Low | Times are stored and sent as naive local time (`datetime.now().isoformat()`, `db/database.py`), and a browser reads them as its own local time: wrong for anyone in another time zone. **C** | Not fixed: changing the format changes the meaning of every stored row; one server in one office does not need it yet |
| N7 | Low | Two uploads of the same file at the same moment both pass the duplicate check (it reads, then inserts: `api/routes_documents.py::_accept_upload`). **C** | Not fixed: the web app sends files one at a time, so only a script can hit it; a unique index would need care with failed uploads |
| N8 | Low | The rail lists at most 50 conversations (`GET /sessions` defaults to 50); older ones open only by their address. **C** | Not fixed: paging is new interface work |
| N9 | Low | Rate-limit counts live in the server's memory: they start again at a restart and are not shared between processes. **C** | Not fixed: the app runs as one process (recorded in Sprint 5) |
| N10 | Low | `POST /session/clear` takes a whole chat request, with a `question` field, to delete a conversation (`api/routes_chat.py`). **C** | Not fixed: Sprint 8, item 3 adds `DELETE /sessions/{id}` |
| N11 | Low | The stream carries no `X-Accel-Buffering: no`; behind a buffering proxy such as nginx the tokens would arrive at the end. **C** | Not fixed: no proxy is used; for the Docker work |

## 7. Fixed in this sprint

| Finding | Commit | Test |
|---|---|---|
| N1 | 6f959ad | `test_api_routes.py` (each route's own limit, and the default) |
| N2 | b6d0b4d | `test_documents.py::test_a_document_removed_while_it_is_read_leaves_nothing_behind`; `ChatLayout.test.tsx` |
| R10 (the cache) | 8a983de | `test_conversation_memory.py::test_the_cache_keeps_only_the_most_recently_used_sessions` |
| S3 (its missing test) | 53e0631 | `ChatLayout.test.tsx` |
| N3 | f21e43f | documentation |

## 8. What is done right

Everything section 8 of the first report praised still holds, and the tests now prove it: tenant isolation in both directions for every store and route (`test_tenant_isolation.py`, `test_tenants.py`), parameterised SQL, bcrypt with constant-time sign-in, the calculator's allow-list. Since then:

- **Every seam is pinned by a test that fails when it breaks**: the schema snapshot, the generated types and the contract test between the two halves; the no-orphan check; the browser journey.
- **Claims are recorded with their evidence.** SPRINT_PLAN.md says what each sprint proved and where the plan was wrong, including a correction to its own earlier evidence (Sprint 5).
- **Failures are designed**: a closed stream saves nothing, a failed answer gives its question back, an expired session signs out with a reason, an unreadable file says why, a server error gives a reference instead of a traceback.
- **Accessibility is checked, not assumed**: axe at two widths in CI, Lighthouse 100, a page that fits from 360 px.

## 9. Not verified

- Anything on Windows, including `npm run e2e` from a folder whose path has spaces.
- Any live Gemini call: answer quality, latency and quota were not measured here (the owner's measurements are in SPRINT_PLAN.md).
- A Docker build (deferred).
- A pass with a real screen reader.
- The office network and its certificate.
