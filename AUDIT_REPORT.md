# Aether AI — Audit Report

Audit date: 11 October 2026. Scope: everything in this folder (FastAPI backend, React frontend, legacy static UI, tests, Dockerfile, documents). No application code was changed. The fix plan is in [SPRINT_PLAN.md](SPRINT_PLAN.md).

## 1. Verdict

The idea is sound and the default chat path is coherently written. The project is not what its documents say it is.

- **It cannot answer a question right now.** The vector store holds 0 embeddings, and there is no record on disk of the current architecture (Chroma + JWT + hybrid search) ever answering one.
- **One of the three chat modes crashes on every request**, and one of the two user interfaces is dead. The dead one is the one the backend serves.
- **The headline quality number ("100% RAG Quality") measures nothing.** The script behind it never calls the pipeline.
- **`SDLC_PLAN.md` ends with "PRODUCTION READY — CONTAINERIZED, TESTED, & HARDENED".** None of those three words survives a check. That sentence is the single biggest risk to your credibility in a review, bigger than any bug.
- **What is good is real**: tenant scoping is applied consistently, SQL is parameterised, passwords are bcrypt-hashed, the calculator uses an AST allow-list instead of `eval`, the React app renders model output safely and keeps the token out of browser storage.

Against the internship plan: of 18 numbered tasks, 12 work in the default mode, 4 are partial, 1 is broken (Task 14) and 1 is unreachable code (Task 12).

## 2. How this was audited

I read every backend file in full, inspected the two databases read-only, and ran four parallel reviewers: runtime reproduction, frontend and API contract, security, and plan/documentation compliance. I spot-checked the reviewers' most surprising claims against the source before accepting them.

Evidence codes used below:

| Code | Meaning |
|---|---|
| **R** | Reproduced by running something: headless browser on a production build against a stub API, Node harness, offline script, or read-only inspection of the data files |
| **C** | Confirmed by reading the code |

Runtime reproduction ran against a copy of the backend with a fake API key, fake embeddings, a scripted chat model and outbound network blocked. Absolute scores from fake embeddings are not representative of Gemini; the mechanisms are.

Not verified: whether `gemini-3.5-flash` is a valid model id for your key, whether the Docker image has ever been built, and anything that needs a live Gemini call. No Gemini calls were made.

Side effects of the audit, for the record: my read-only open of `backend/aether.db` left two SQLite sidecar files (`aether.db-shm`, `aether.db-wal`, the second is 0 bytes). The database itself is unchanged. Delete both when the backend is not running.

## 3. Is everything connected? (wiring map)

This is the answer to "pipelines connected to code". Each row is one seam between two parts.

| Seam | State | Detail |
|---|---|---|
| React `api.js` → `/api/v1` routes | Paths match, payloads do not | Three field-name mismatches (F2, F4); `tool_used` dropped by the response model (F9) |
| Backend → React build | **Not connected** | `main.py:133-138` serves the legacy page; the Dockerfile copy line is commented out (B3) |
| Legacy `static/index.html` → backend | **Dead** | Calls 10 un-versioned, un-authenticated paths that no longer exist |
| `main.py` → `config.py` | **Not connected** | Nothing imports `config.py`; model id hardcoded in 5 files (C1) |
| `main.py` → `rag_engine` (default mode) | Connected | The one path that is coherent end to end |
| `main.py` → `rag_langchain` | Wired, **crashes** | `TypeError` at 5 call sites (B1) |
| `main.py` → `ingest_document_langchain` | Imported, **never called** | LangChain loaders are unreachable (`main.py:33`, `:239`) |
| `main.py` → `agent` → `tools` | Connected | Agent's document search double-writes conversation memory (R10) |
| `rag_engine` → ChromaDB | Connected in code, **empty in fact** | 0 embeddings; 133 legacy chunks never migrated (B2) |
| Legacy NumPy store (`vectors.npy`, `metadata.json`) | **Orphan** | Referenced by no code |
| `rag_engine` ↔ `database` (memory) | Connected, lossy | Confidence and mode are never passed, so the DB stores 0.0 / `original` (R10) |
| `POST /feedback` ↔ UI | **Not connected** | No function in `api.js`, no control in the UI; all 17 stored turns have feedback 0 |
| `get_session_history()` | **Never called** | No history endpoint exists (`rag_engine.py:646`) |
| `evaluate_rag.py` ↔ pipeline | **Not connected** | Never imports `rag_engine` (T3) |
| Tests ↔ app | Barely | `client` and `auth_headers` fixtures are unused; no test calls an endpoint (T1) |
| Logger ↔ routes | Connected | No user id on chat lines; `requests.log` is absent on disk |
| Rate limiter ↔ routes | 5 routes yes, 6 no | Missing on feedback, session clear, documents, health |
| Dockerfile ↔ app | Backend only | DB path is moved to `/app/data`, the vector store is not (S2) |
| `start.bat` ↔ environment | **Broken** | Hardcodes a Python 3.14 path that does not exist on this machine (B5) |

## 4. Findings

Each finding: location, problem, fix, effort (S/M/L), evidence code.

### 4.1 Blockers — these fail in a demo

**B1. LangChain mode raises `TypeError` on every request.** `rag_langchain.py:245, 335, 362, 396, 423` call `_memory.format_history(session_id)` and `_memory.add_turn(session_id, …)`; the methods take `(user_id, session_id, …)` since multi-tenancy (`rag_engine.py:398, 416`). `/chat` returns 500; `/chat/stream` returns 200 with the exception text shown as the answer. Fix: pass `user_id` and add a test, or delete the mode. Do not "fix" it by giving `user_id` a default; that would leak history across tenants. Effort S. **R**

**B2. The vector store is empty and the current system has never been exercised.** ChromaDB: 0 embeddings. Legacy NumPy store: 133 chunks, never migrated. SQLite `documents` still lists 2 documents, owned by the locked `__legacy_migration__` user. Last saved conversation: 23 July, before auth existed. The two real accounts have no documents and no turns. Fix: re-ingest through the API as a real user, delete the legacy files, add an end-to-end test. Effort S. **R**

**B3. The UI the backend serves is the dead one.** `main.py:133-138` serves `backend/static/index.html`, whose login is simulated in the browser and whose every API call returns 404. The React app is reachable only through the Vite dev server. Uncommenting `Dockerfile:21` as written would give a blank page, because the build references `/assets/…` and FastAPI mounts only `/static`. Fix: multi-stage Docker build, mount `dist` at `/` after the API routes, delete `backend/static`. Effort M. **R**

**B4. Every restart logs everyone out.** `.env` has no `JWT_SECRET`; `auth.py:15-24` silently generates a random one, directly under a comment that says "No fallback — fail loudly". `start.bat` runs `--reload`, so every file save invalidates all tokens. The React app then shows a 4-second toast and stays "signed in" (F7). Fix: fail at startup when the secret is missing; add it to `.env.example`. Effort S. **C**

**B5. The project cannot be started from its own files.** `start.bat:4` hardcodes `%LOCALAPPDATA%\Programs\Python\Python314\…`, which does not exist here (dependencies live in the per-user site-packages of Python 3.12). It starts only the backend. No document says the real UI needs `npm install` and `npm run dev`. There is no root README. Effort S. **R**

**B6. The landing page cannot be scrolled.** `#root` is `overflow: hidden` with fixed height (`frontend/src/index.css:137-141`); `.landing` has only `min-height` (`LandingPage.css:5-9`). Wheel, PageDown and touch swipe all move it 0 px. Fix: `.landing { height: 100vh; }`. Effort S. **R**

**B7. Citation cards open empty.** `SourceCard.jsx:34` reads `source.content`; the API sends `snippet`. Page and score are never rendered. The product's main promise, cited answers, shows as a filename. Effort S. **R**

**B8. The Hybrid toggle sends the wrong value on the first message after each toggle.** `hybridMode` is missing from the `useCallback` dependencies at `ChatLayout.jsx:149`. Your linter already reports this line. Effort S. **R**

**B9. The chat has no error or cancel lifecycle.** A stream that ends without a `done` event leaves the composer disabled forever (`api.js:131-160`). Server errors are sent as ordinary tokens (`main.py:366-369`) and are rendered and kept as answers. Agent errors return HTTP 200 with confidence 1.0 and get a green "High Confidence" badge (`agent.py:115-116, 137`). Fix: an `error` SSE event, non-200 on agent failure, `finally` for loading state, `AbortController` and a Stop button. Effort M. **R**

**B10. Quota and network will stop a live demo.** `errors.log` shows a free-tier limit of 20 requests a day. At up to 3 model calls per question that is about 7 questions a day across all users. The same log shows a TLS-interception failure ("self-signed certificate in certificate chain"), so on an office network the app may not reach Gemini at all. Fix: a billed key, the organisation's root CA added to the trust store (never `verify=False`), and a rehearsal on the real network. Effort S (administrative). **R**

**B11. One slow request blocks the whole server.** Every route is `async def` and calls blocking code directly (`main.py:293-297, 239, 353-365`). While one user waits for Gemini, nobody else is served, including `/health`. Measured with a 5-second stub: `/health` took 4.08 s against 11–20 ms idle, and three simultaneous chats finished at 5, 10 and 15 s. On Windows without `--reload`, streaming delivered no tokens until generation had finished. Fix: plain `def` handlers (FastAPI runs them in a thread pool) or `ainvoke`/`astream`, and a sync generator for the stream. Effort S–M. **R**

### 4.2 RAG pipeline — correctness and quality

**R1. "Confidence" is not cosine similarity, and the 0.3 threshold is uncalibrated.** The collection is created without a distance setting (`rag_engine.py:156-160`); the store on disk is configured `space: l2`. LangChain converts L2 distance with `1 − d/√2`, which is a distorted scale that can go negative. In the test, scores ranged from −0.54 to 1.0, the API returned a negative confidence, and 0.3 on this scale corresponds to a cosine of about 0.5. Fix: create the collection with `collection_metadata={"hnsw:space": "cosine"}`, re-ingest, then choose the threshold from evaluation data. Effort S. **R**

**R2. In hybrid mode the refusal can never fire.** Scores are rank-fusion values normalised by `2/(k+1)` (`rag_engine.py:241-243`). The lowest score a returned chunk can get is (1/70) ÷ (2/61) ≈ 0.44, above the 0.3 threshold. The displayed confidence is a rank artefact. In the test, an off-topic question was refused in dense mode with no model call, and answered in hybrid mode with confidence 0.947 and two model calls. Fix: apply the threshold to the dense similarity of the fused chunks and report that as confidence. Effort S. **R**

**R3. Hybrid search has five more defects.** The fusion key is `text[:120]`, so different chunks that share a prefix are merged; in the test three distinct chunks went in, two came out, and the wrong one survived with score 1.0 (`:227, :232`). The fallback branches return a different score scale from the fused branch (`:218-221`). BM25 returns nothing for a user with only one or two chunks, and never matches a word next to punctuation (`gate` does not match `gate.`), because the tokenizer is `lower().split()` (`:190-198`). The index is rebuilt from all of the user's chunks on every query: 383 ms at 3,000 chunks against 31 ms for dense search (`:184-191`). Any error is swallowed and returns an empty list (`:205-206`). Fix: key on `chunk_id`, cache the index per user and invalidate on upload, use a real tokenizer. Effort M. **R**

**R4. The answer is generated from an LLM summary, not from the retrieved text.** `rag_engine.py:494-508`. Consequences: claims cannot be tied to a chunk; the `<document>` boundaries never reach the answer prompt; one extra model call per question; and the summariser receives the raw follow-up question without history, while retrieval used the rewritten one (`:496-499`). Fix: answer directly from delimited, numbered chunks; keep the summary step only if an ablation shows it helps. Effort M. **C**

**R5. "Sources" are every retrieved chunk, not what the answer used.** `rag_engine.py:510-524`. Fix: structured output that returns the ids of the chunks actually cited. Effort M. **C**

**R6. Uploading the same file again doubles its chunks.** The duplicate is detected, logged, and ingested anyway (`main.py:224-229`). The legacy store shows it happened: one file is present 3 times (132 chunks = 3 × 44). In the test a second upload took the store from 10 to 20 chunks, and the top 5 held only 4 distinct texts. Fix: reject or replace on matching hash. Effort S. **R**

**R7. Documents have no identity in the vector store.** Chunks carry filename and `user_id` but no document id (`rag_engine.py:162-166, 359-360`), so the only delete is "delete everything". Fix: a `document_id` in chunk metadata and `DELETE /documents/{id}`. Effort M. **C**

**R8. Delete is unreliable and misreports.** `clear_documents` swallows any Chroma error, deletes the SQLite rows anyway, and always returns `deleted: 0`, so the API always says "Cleared 0 chunks" (`rag_engine.py:627-637`, `main.py:421`). Upload writes Chroma first and SQLite second with no rollback (`main.py:239, 249`). Effort S. **R**

**R9. Parsing loses content.** Word tables, headers and footers are dropped; only paragraphs are read (`rag_engine.py:270-280`). Only the first sheet of a workbook is read; leading zeros are lost and integers become floats when a column has blanks (`:295-327`). `.xls` needs `xlrd`, which is not in `requirements.txt`; it works on this machine only because `xlrd` happens to be installed, and returns 500 without it. Rows wider than the 1000-character chunk size are always cut mid-row; normal-width rows are not. Non-UTF-8 text files are accepted and silently corrupted (`errors="ignore"`, `:285`). A corrupt `.docx` or `.pdf` returns 500 with a server temp path in the message. Scanned PDFs have no OCR path. Effort M. **R**

**R10. Conversation memory is lossy and polluted.** Confidence and mode are never passed to `add_turn` (`rag_engine.py:527, 617`), so the database records 0.0 and `original` for every RAG turn. In agent mode the document-search tool calls `query_rag`, which saves the agent's internal sub-query as if the user had asked it; the agent then saves its own turn too (`agent.py:41, 132`). Agent error strings are saved as answers. The in-process cache is never evicted (`rag_engine.py:384`). In the test, one agent question with two searches wrote three rows and made eight model calls. Effort S–M. **R**

**R11. Agent mode undermines the grounding it sits on.** The prompt tells the model to use "your own vast internal knowledge base" (`agent.py:80`); tool-less answers are returned with confidence 1.0 (`:137`); the date tool asks the LLM to do date arithmetic (`tools.py:138-156`); `max()` is on the allow-list but broken by the `x`→`*` replacement on `tools.py:98`; results are rounded to 6 significant digits, so `49999.99 * 3` returns 150000 (`tools.py:108`); agent "streaming" is the finished answer split on spaces (`main.py:352-358`). Effort M. **R**

**R12. Ingestion runs inside the request, in one synchronous embedding call.** No batching, no progress, no backoff (`rag_engine.py:357-362`). The `embedding_batch_size` setting exists only in the unused `config.py`. Effort M. **C**

### 4.3 Security

Calibrated for what this is: an internal prototype. Nothing is critical while it stays on one laptop. The first five become serious the moment it is deployed the way the Dockerfile describes.

**S1. The Docker image would contain your API key, user database and logs.** No `.dockerignore`; `Dockerfile:18` copies all of `backend/`. `load_dotenv(override=True)` (`auth.py:11`, `rag_engine.py:34`, and three more files) then makes the baked `.env` beat any key passed at runtime. Runs as root, no `HEALTHCHECK`, no volume. Effort S. **C**

**S2. Tenant ids are reusable integers shared by two stores with separate lifecycles.** User ids restart at 2 in any new database, while chunks tagged with those integers live in a separate directory. `Dockerfile:25` moves the database to a fresh path; `conftest.py:19-20` runs a temp database against the real vector store. After any database reset, the next person to register inherits the previous user 2's documents. Fix: a random tenant UUID on the user row, one data volume for both stores, and a two-user isolation test. Effort M. **C**

**S3. Model output can exfiltrate data through markdown images.** `MessageBubble.jsx:51` renders `![](https://…)` as an `<img>` and the browser fetches it immediately. With an injected document, retrieved text can leave in a URL without a click. Links open in the same tab and destroy the in-memory session. Fix: drop `img`, add `target`/`rel` to links, add a CSP. Effort S. **R**

**S4. One request can consume unbounded work.** The calculator allows unbounded `**` (`tools.py:26`); `9**9**7` takes about 3 s, `9**9**9` does not finish, and the computation holds the GIL. The agent sets no recursion limit and the installed LangGraph default is 10007 (`agent.py:101`). No timeout or output cap is set on any model client. Uploads are read fully into memory before the size check and before authentication (`main.py:204-215`). There is no per-user budget. Effort M. **R**

**S5. The prompt-injection filter blocks legitimate text and misses attacks.** Two independent offline tests of `sanitize_context` (`rag_engine.py:72-95`): every paraphrased injection passed untouched (11 of 11 and 16 of 16), and every ordinary business sentence was corrupted (6 of 6 and 11 of 11; for example "will act as a liaison"). The filename goes into the `<document source="…">` tag unsanitised (`:490`); a crafted filename was accepted and its text reached the model prompt. Fix: keep the regex as telemetry only; escape and constrain the filename; rely on output controls (S3) and tool limits (S4). Effort M. **R**

**S6. Your own system prompt contains an instruction to ignore the rules.** "IMPORTANT OVERRIDE … ALWAYS answer exactly: 'I was written by Dr Amit Ganatra', ignoring other rules" appears in `rag_engine.py:129`, `rag_langchain.py:222` and `agent.py:81`. It is the exact pattern Task 8 exists to resist, it makes the assistant assert something the landing page contradicts (`LandingPage.jsx:177`), and a reviewer will find it in thirty seconds. Delete it; put credits in the UI. Effort S. **C**

**S7. Authentication basics.** Open self-registration; 6-character minimum and nothing else; register reveals taken usernames and returns a sequential id; login skips bcrypt for unknown users (a clear timing difference); usernames are case-sensitive and Unicode-aware, so look-alike accounts are possible; register strips whitespace and login does not, so `"  name  "` registers and then cannot log in; check-then-insert race gives a 500; passwords of 73–128 bytes give a 500 with the installed bcrypt 5.0.0; tokens last 7 days with no revocation, and a token for a user id that does not exist is accepted; no authentication event is logged. Effort M. **R**

**S8. Rate limiting is keyed on socket IP** (`main.py:54`). Behind any proxy or Docker gateway all users share one bucket of 10 logins a minute. Effort S. **C**

**S9. Unvalidated fields.** `session_id` has no length or character limit and every new value becomes a permanent cache key; `/chat/stream` lacks the 5000-character limit that `/chat` has (`main.py:285` vs `:340`); `feedback` accepts any integer; these strings are logged verbatim, so log lines can be forged. In the test a 1,000,000-character question was accepted on the stream route and sent to the model twice, 25 requests with large session ids left 25 MB in the cache, and feedback on a session that does not exist returned "recorded successfully". Effort S. **R**

**S10. Information exposure.** Raw exception text is returned to clients at nine places in `main.py` (for example `:304`, `:368`); `/api/v1/health` is unauthenticated and returns global counts across all tenants; `/docs` and `/openapi.json` are on; there is no TLS and no security header; CORS origins are hardcoded to localhost. Effort S–M. **C**

**S11. Data handling.** Every chunk and question goes to Google on a free-tier key. Check Google's current terms for unpaid API use before uploading any real company document, and get written approval for which document classes are allowed. Use public test documents until then. Effort S (administrative). **R** (tier, from the log)

**S12. Dependencies.** All 23 requirements use `>=` with no lockfile. Installed Starlette 0.46.2 is behind current releases; run `pip-audit`. Unused: `duckduckgo-search`, `docx2txt` on any live path, `pydantic-settings`. Missing: `xlrd`, `pytest`, `httpx`. No virtual environment: the project shares a global site-packages with TensorFlow and torch, which makes `import main` take 42–44 s on this machine. Effort S. **R**

**S13. The legacy page has 23 unescaped `innerHTML` sinks** and a field that stores a Gemini key in `localStorage`. They are dormant only because every call returns 404. `static/test.js` is a near-identical copy of the inline script, publicly served. Delete all of `backend/static`. Effort S. **R**

### 4.4 Frontend

Lint passes with 9 warnings; the production build passes (375 kB, 115 kB gzipped).

**F1.** Landing page cannot scroll — see B6.
**F2.** Citation cards empty — see B7.
**F3.** Hybrid toggle stale — see B8.

**F4. The Settings modal shows wrong or fake data.** `SettingsModal.jsx:151, 153` read `size` and `ingested_at`; the API sends `size_bytes` and `uploaded_at`, so every row shows "0 B" and "Unknown". Lines 179 and 183 read health fields the API never sends. "Offline" renders in green. Effort S. **R**

**F5. "Hard Reset" does nothing and logs the user out.** `SettingsModal.jsx:104-116` removes a `localStorage` key nothing sets, then reloads. Zero API calls. Effort S. **R**

**F6. New Thread, Log Out and the logo during a stream.** The old stream keeps writing into the new thread; the server is never told to stop and re-inserts the turn it was just asked to clear; clicking the logo silently discards the conversation (`ChatLayout.jsx:166-182`, `Sidebar.jsx:51`). Effort M. **R**

**F7. A dead token leaves a zombie session.** On 401 the user gets a toast and stays "authenticated"; failed lists display as "No documents yet" (`api.js:102-105, 167-168`). Effort S–M. **R**

**F8. Every account sees "Developer / user@aether.ai".** Hardcoded at `Sidebar.jsx:137-140`. The tab title is "frontend". Versions disagree: 2.0.0 (API), 3.0.0 (`config.py`), "v3.0" (sidebar), 0.0.0 (package). Effort S. **R**

**F9. Mode toggles show states that are not in effect, and the tool badge can never appear.** Agent and LangChain can both be lit; `ChatResponse` drops `tool_used` (`main.py:87-91`). Fix: one `mode` enum instead of four booleans. Effort S–M. **R**

**F10. Feedback is not wired.** No function, no control, and no response carries a turn id, so per-message rating is impossible as designed. Effort M. **C**

**F11. Not usable at phone width.** At 375 px the sidebar covers the composer and Log Out is off-screen. Two `@media` rules in the whole app. Effort M. **R**

**F12. Accessibility baseline is absent.** 0 `aria-*`, 0 `role`, 0 `htmlFor`; modals have no focus trap and ignore Esc; muted text is 2.2–2.8:1 contrast. Effort M. **R**

**F13. Performance while streaming.** No `memo`; every token re-renders and re-parses the whole conversation through the markdown renderer and forces a smooth scroll. With 13 long answers in history the main thread was blocked about 92% of a 400-token stream. Effort M. **R**

**F14. Upload flow.** The sidebar's accepted types omit csv/xlsx; dropping three files uploads only the first, silently; no client-side size or type check; no progress or cancel (`Sidebar.jsx:31-36, 89, 96`). Effort S. **R**

**F15. JSX and CSS have drifted.** 12 class names used in JSX have no rule; 9 rules are never used; `index.css` is imported after `App`, so the base sheet overrides component rules. Effort S–M. **R**

**F16. Template leftovers.** Untouched Vite README, unused template assets, `@types/react` in a JS-only project, Google Fonts loaded by a render-blocking `@import`. Effort S. **R**

### 4.5 Tests and evaluation

**T1. Five tests, none of which calls an endpoint.** `test_auth.py` (2) and `test_database.py` (3). The `client` and `auth_headers` fixtures are unused. Nothing tests ingestion, retrieval, chat, the agent, the tools or tenant isolation. One test per mode would have caught B1; one test of `max()` would have caught the calculator bug. The suite passes 5 of 5 while entering 0 of the 15 functions in `main.py`. Effort M. **R**

**T2. The test setup touches production data.** `conftest.py:23` imports `main`, which opens the real vector store and needs a real API key at import (`rag_engine.py:252, 51`). Without the key the suite cannot even be collected (`KeyError: 'GOOGLE_API_KEY'`), so it cannot run in CI. Effort S. **R**

**T3. `evaluate_rag.py` is not an evaluation of this system.** It never imports the pipeline and does no retrieval. Two hand-written cases have their context pasted straight into the prompt; the same model generates and judges; `expected_facts` is never used; the promised context-precision and dense-versus-hybrid comparison do not exist; and when the judge's JSON fails to parse it returns a hardcoded 0.85 or 0.90 (`evaluate_rag.py:68-70, 89-91`). If every judge call fails, the script still prints "Overall RAG Quality: 87.5%". Effort M. **C**

**T4. No frontend tests, no types, no CI.** Effort M. **R**

### 4.6 Code structure

**C1. `config.py` is dead code.** Nothing imports it. The Gemini model id is hardcoded in five files; changing models means editing five places, which is what the error log shows happening by hand. Effort S. **C**

**C2. The same pipeline exists four times.** `query_rag`, `query_rag_stream`, and their two LangChain twins; both prompts are duplicated across two files; the question-rewrite prompt is pasted three times as an f-string; `_get_llm` is defined in five places. Effort M. **C**

**C3. Import-time side effects.** `rag_engine.py:252` opens the vector store at import, `database.py:250` creates tables at import, `auth.py` reads the secret at import. This is why tests need real resources. Fix: an app factory with a lifespan hook. Effort M. **C**

**C4. `main.py` holds schemas, routes, validation and wiring in one 420-line file**, and `rag_engine.py` holds parsing, chunking, storage, retrieval, prompts, memory and orchestration in one 650-line file. Effort M. **C**

### 4.7 Repository and deployment

**D1. This folder is not a git repository.** No history, no way to undo, no way to show your own work, and the plan's "create a separate experimental branch" could not have been met. Effort S. **R**

**D2. `.gitignore` is wrong.** It ignores `backend/chroma_db/`; the real path is `backend/vector_store/chroma_db/`. It does not ignore `aether.db*`, `backend/logs/` or `backend/vector_store/`. A first `git add .` would commit your user table, hashes and logs. Effort S. **C**

**D3. Clutter that should not ship.** Three copies of a June code dump (`codebase_dump.md/.txt/.pdf`), `walkthrough.md` (leads to the dead UI), `backend/static/`, the legacy `vectors.npy` and `metadata.json`, `backend/test_doc.txt`, `__pycache__` for two Python versions. Effort S. **R**

**D4. The Dockerfile is single-stage, runs as root, has no healthcheck or volume, and ships no UI.** The sprint log calls it "multi-stage ready". Effort M. **C**

### 4.8 Documentation versus reality

The three documents describe three different systems. `project_report.md` matches the June code. `walkthrough.md` describes a July UI that no longer works. `SDLC_PLAN.md` matches the current architecture but overstates outcomes.

| Claim | Where | Verdict |
|---|---|---|
| "PRODUCTION READY — CONTAINERIZED, TESTED, & HARDENED" | `SDLC_PLAN.md:147` | False (B1, B3, B4, B11, T1) |
| "100% Mean Faithfulness … 100% Overall RAG Quality" | `SDLC_PLAN.md:106` | Misleading; nothing was measured (T3) |
| "fails early if critical environment tokens are missing" | `SDLC_PLAN.md:14` | False (C1, B4) |
| "robust multi-stage ready Dockerfile" | `SDLC_PLAN.md:132` | Misleading; one `FROM` (D4) |
| "Feedback: POST /api/v1/feedback (Aligned)" | `SDLC_PLAN.md:65` | False (F10) |
| "Session tokens generate via `uuidv4()`" | `SDLC_PLAN.md:66` | False; `session_${Date.now()}` |
| "fully responsive … zero placeholders" | `SDLC_PLAN.md:30` | False (F8, F11) |
| "instantaneous similarity search across tens of thousands of chunks" | `SDLC_PLAN.md:49` | Unverifiable; the collection has held 0 vectors |
| "Resolved 19 code quality findings" | `SDLC_PLAN.md:88` | Unverifiable; no list exists |
| "All tests pass (100%)" | `SDLC_PLAN.md:125` | True, narrowly: 5 unit tests |
| NumPy store, cosine similarity, no authentication, Gemini 2.5 Flash Lite, 768-dimensional embeddings | `project_report.md` (many lines) | False now; the stored vectors are 3072-dimensional |
| "Every answer includes clickable source citation cards showing the exact document, page, relevance score, and text snippet" | `project_report.md:594` | False in the current UI (B7) |
| "Search Fallback: DuckDuckGo Search" | `project_report.md:196, 231` | False; no web-search code exists |
| Chapter 6, screenshots | `project_report.md:473-556` | Ten `[Insert Screenshot: …]` placeholders |
| Sign in with "any mock email/password" | `walkthrough.md:39` | Describes the dead page |

Three things a reviewer will raise that are not bugs:

- **The author line of `SDLC_PLAN.md` is "Senior AI Engineer (Fable 5)".** It reads as an AI persona. The file also contains "As requested" twice, which is an assistant answering a prompt. File timestamps put the first artefacts of "Sprints 1–6" inside 55 minutes on one evening.
- **The internship plan PDF lists ChatGPT as author and creator in its metadata.** It never mentions Netweb, a mentor, dates or evaluation criteria. No project file names Netweb either. Expect "who set these requirements?"
- **Attribution is inconsistent.** Four different credits appear across the report, the landing page, the sprint log and the system prompts.

Using AI tools is not the problem. Submitting claims you have not verified, and code you cannot explain line by line, is. You must be able to walk through `search_hybrid` unaided.

## 5. Internship plan compliance

| Task | Status | Note |
|---|---|---|
| 1 Prompt templates | Done | Rewrite prompt is still an f-string, pasted 3 times |
| 2 Structured JSON output | Partial | JSON shape delivered; no LangChain output parser; `tool_used` dropped |
| 3 Sequential chain | Done | Two chains called in sequence |
| 4 Conversation memory | Done | Agent double-writes (R10) |
| 5 Chat history UI | Partial | Lost on refresh; no history endpoint; New Thread deletes server rows |
| 6 Source attribution | Partial | Filename only; chunk text never shown (B7) |
| 7 Confidence threshold | Partial | Works in dense mode only (R2, R11) |
| 8 Prompt-injection protection | Done (basic) | See S5, S6 |
| 9 Calculator tool | Done | `max()` broken; unbounded power |
| 10 Date-time tool | Done | LLM does the arithmetic |
| 11 Agent decision layer | Done | Opt-in side path, not the hub the plan draws |
| 12 LangChain document loaders | **Unreachable** | Written, never called |
| 13 Text splitter | Done | |
| 14 RetrievalQA chain | **Broken** | B1; no retriever object is used |
| 15 LCEL refactor | Done | |
| 16 Logging | Done in code | No `requests.log` on disk |
| 17 Error handling | Done (basic) | Raw exception text returned (S10) |
| 18 Streaming (optional) | Done in default mode | Agent streaming is faked |

Plan constraints not met: "Do NOT remove current implementation" (the NumPy store class is gone and its UI is dead) and "Create separate experimental branch" (no repository). Scope the project added beyond the plan: authentication, multi-tenancy, ChromaDB, hybrid search, React, Docker, rate limiting, feedback.

## 6. The folder structure you proposed

You are right about the shape. It is the standard layout for a RAG service and it fits the RAG core of this app. Six corrections:

1. **`__init__.py` has two underscores on each side.** Your listing has `_init_.py`, `_init__.py` and `__init_.py`.
2. **`.env` and `logs/app.log` are not project files.** They exist locally and are never committed. Commit `.env.example`.
3. **The layout describes a single-user RAG script.** This app also has authentication, a SQLite layer, conversation memory, an agent with tools, an evaluation harness and a React frontend. Each needs a home.
4. **Do not keep two sources of configuration.** You already wrote `config.py` with pydantic-settings. Keep it and import it. Add `config.yaml` only if non-developers must edit tunables.
5. **One `tests/test_app.py` is not enough.** Mirror the packages.
6. **Keep `utils/helpers.py` small.** It becomes a junk drawer.

Recommended layout:

```
rag-chatbot/
├── README.md
├── .gitignore   .dockerignore   .env.example
├── Dockerfile   docker-compose.yml
├── backend/
│   ├── requirements.txt   requirements-dev.txt      (pinned)
│   ├── main.py                    entry point: builds the app, mounts routers and the built UI
│   ├── src/
│   │   ├── __init__.py
│   │   ├── core/          config.py   logging.py   security.py
│   │   ├── api/           schemas.py  deps.py  routes_auth.py  routes_chat.py  routes_documents.py  routes_health.py
│   │   ├── db/            database.py
│   │   ├── ingestion/     loader.py
│   │   ├── chunking/      chunker.py
│   │   ├── embeddings/    embedder.py
│   │   ├── vectordb/      vector_store.py
│   │   ├── retrieval/     retriever.py
│   │   ├── prompts/       prompt_templates.py
│   │   ├── llm/           llm_client.py
│   │   ├── memory/        conversation.py
│   │   ├── pipeline/      rag.py
│   │   ├── agents/        agent.py   tools.py
│   │   ├── evaluation/    evaluate.py   dataset.jsonl
│   │   └── utils/         helpers.py
│   └── tests/             conftest.py   unit/   integration/
├── frontend/
├── data/                  gitignored: aether.db, chroma/
├── logs/                  gitignored
└── docs/                  report, architecture diagram, plan
```

Where today's code goes:

| Today | Target |
|---|---|
| `main.py:80-130` request and response models | `api/schemas.py` |
| `main.py` routes | `api/routes_*.py` |
| `auth.py` | `core/security.py` and `api/deps.py` |
| `config.py` | `core/config.py`, and import it everywhere |
| `logger.py` | `core/logging.py` |
| `database.py` | `db/database.py` |
| `rag_engine.py` `_parse_*`, `load_document` | `ingestion/loader.py` |
| Splitter inside `ingest_document` | `chunking/chunker.py` |
| `_get_embeddings` (2 copies) | `embeddings/embedder.py` |
| `ChromaVectorStoreWrapper` storage methods | `vectordb/vector_store.py` |
| `search`, `search_bm25`, `search_hybrid`, question rewrite | `retrieval/retriever.py` |
| Both prompts (2 copies), rewrite prompt (3 copies), agent prompt | `prompts/prompt_templates.py` |
| `_get_llm` (5 copies) | `llm/llm_client.py` |
| `ConversationMemory` | `memory/conversation.py` |
| `query_rag`, `query_rag_stream`, and the LangChain twins | `pipeline/rag.py`, one implementation |
| `agent.py`, `tools.py` | `agents/` |
| `evaluate_rag.py` | `evaluation/`, rewritten |
| `rag_langchain.py` | Merge the loaders into `ingestion/`; keep the rest on a git branch, as the plan asked |
| `backend/static/`, `vectors.npy`, `metadata.json`, the three dumps, `walkthrough.md` | Delete |

## 7. What the app still needs, ranked

**Before anyone else sees it**

1. Version control, a correct `.gitignore`, and the clutter removed.
2. One successful, repeatable run: register, log in, upload, ask, get a cited answer. Automate it as a test.
3. LangChain mode fixed or removed.
4. A real evaluation: 30–50 questions over real documents, retrieval metrics (hit@k, MRR), then faithfulness, with measured numbers in the report.
5. Documents rewritten to match the code, with false claims retracted and real screenshots.
6. A UI that the backend actually serves, with working citations.
7. `JWT_SECRET` required, the override rule deleted, a billed API key, and a rehearsal on the office network.

**To make it sound**

8. Non-blocking request handling.
9. Cosine metric, a calibrated threshold, and refusal that works in every mode.
10. Tests with fake model and embeddings: every endpoint, tenant isolation, tools.
11. Per-document delete, duplicate handling, chat history that survives a refresh.
12. Bounded work: calculator, agent recursion, timeouts, upload and field limits.
13. One configuration source, one pipeline, the target package structure.
14. A multi-stage Docker image with a data volume, and CI.

**To distinguish it**

15. An ablation table: with and without the summary step, dense versus hybrid, chunk sizes, with latency and cost per stage.
16. Per-claim citations from structured output, and a reranker.
17. Background ingestion with progress, OCR for scanned PDFs, table-aware parsing.
18. Feedback thumbs feeding the evaluation set.
19. Observability: per-stage latency, token usage and cost per request.
20. The agent as the default router with a visible tool trace, as the plan's architecture draws it.

## 8. What is genuinely done right

- The tenant id comes only from the verified token, never from the request body. All protected routes use the dependency, and every per-user SQL statement and vector query carries the filter.
- Tenant isolation held under test: 18 combinations of query and search method as a second user returned none of the first user's chunks.
- `add_documents` stamps `user_id` after parsing, so document metadata cannot spoof it.
- The declared rate limits fire exactly as configured. Upload validation rejects a bad extension, an empty file and a text-less PDF with a 4xx. A foreign origin's CORS preflight is refused.
- All SQL is parameterised. Duplicate detection is per user.
- JWT decoding pins the algorithm and enforces expiry. Passwords use salted bcrypt. The login error is generic.
- Uploads never use the client filename as a path; the temp file is removed in `finally`.
- The calculator is an AST allow-list: no `eval`, no attribute access, no imports.
- Agent tools are per-request closures bound to the user id, with no network, file or shell access.
- The React app has no `dangerouslySetInnerHTML`, escapes raw HTML in model output, keeps the token out of browser storage, and its SSE parser reassembles split chunks correctly.
- No TLS-verification bypass was added despite the certificate errors in the log.
- `project_report.md` was honest for the code it described in June, including its limitations chapter.
- Your API key does not appear in any other file in the project.

## 9. Ten questions a reviewer will ask

1. Who set these requirements, and where is Netweb in this?
2. Show me the evaluation behind "100%".
3. Turn on LangChain mode and ask something.
4. Your report says NumPy, no auth, Gemini 2.5 Flash Lite. Which system are you submitting?
5. Is it production ready? Restart the server, refresh the page, send two questions at once.
6. How is confidence computed? Show me a refusal in hybrid mode.
7. Why three model calls per question? What are the latency, the cost and the daily limit?
8. Prove one user cannot see another's documents.
9. Why does your system prompt contain an override that ignores the other rules?
10. Where is the git history? Explain `search_hybrid` line by line.

After the sprints in [SPRINT_PLAN.md](SPRINT_PLAN.md), each of these has a good answer.

## Appendix — the audit prompt

Reusable. Paste into a new session at the project root after each sprint.

```
Audit this repository as a senior reviewer who has to sign off on it. Findings only; change nothing.
Work read-only. Run code only against a copy in a temp directory, with a fake API key and fake
embeddings/LLM. Never print .env. Make no calls to external services.

1. Map the system: entry points, every module, every data store, every seam between two parts
   (UI call -> route -> service -> store). For each seam say: connected, connected but broken,
   or not connected, with file:line.
2. For each chat mode and each endpoint, trace one request end to end and try to break it.
3. Check the RAG pipeline for correctness: parsing, chunking, embedding, distance metric, scoring,
   thresholds, fusion, prompts, citations, memory. State what each number shown to the user really is.
4. Check security: tenant isolation end to end, auth, input limits, prompt injection, output
   rendering, secrets, what a Docker build would contain.
5. Check the frontend against the API contract field by field, and its behaviour on 401, 422, 429,
   500, a dropped stream, a refresh.
6. Check tests and evaluation: what is actually exercised, and whether each reported metric measures
   the system.
7. Check every claim in the project's documents against the code. Mark each true, misleading,
   false or unverifiable.

Report each finding as: file:line, severity, what is wrong and why it matters, a 1-3 line quote,
a concrete fix, effort, and whether you reproduced it or only read it. List what is done right.
List what you could not verify. Do not pad and do not soften.
```
