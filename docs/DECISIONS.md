# Decisions

Every meaningful decision behind Aether AI as it stands, with its reason. Code shows what changed;
this file says why, so a settled question is not argued again and any choice can be defended:
"why X and not Y?"

**How entries were written.** From the record, not from memory: the commit messages, the "Decisions
already made" lists in [SPRINT_PLAN.md](../SPRINT_PLAN.md), the findings in
[AUDIT_REPORT.md](../AUDIT_REPORT.md) (ids such as B4, R7, S2), the design table in
[project_report.md](../project_report.md) (section 2.5), the comments in the code, and the
measurements made on 15 Oct 2026. Where a reason was never written down, the entry says so.

**Adding an entry.** Before a non-trivial change, copy the template at the end, number it next,
and fill it in. Record the rejected options: they are the best part of the log. Never rewrite an
old entry; when a decision is reversed, add a new one that says which it replaces.

Entries marked **(not merged)** are on the branches `rerank`, `pdf-viewer`,
`openai-compatible` and `ocr`, waiting for the owner.

---

## Before the audit

### D-001 The stack: FastAPI, LangChain, Gemini, ChromaDB, SQLite, JWT; React and Vite
- **Date:** before 11 Oct 2026 · not recorded
- **Chosen:** the stack the internship plan names.
- **Why:** not recorded when chosen. The audit kept it and asked for a restructure, not a rewrite; later work depends on parts of it: FastAPI's OpenAPI schema is what the frontend's types are generated from (D-037), and SQLite and Chroma run inside the one backend process, with no second service to start on Windows (D-007).
- **Revisit if:** several machines must serve one library (SQLite and an embedded Chroma are one-machine stores).

---

## Sprint 0 and 1: safe to change, working end to end (11 Oct 2026)

### D-002 Runtime data never enters git
- **Date:** 2026-10-11
- **Context:** the project had no history; a database, vectors, logs and a code dump sat beside the code (D1, D2, D3).
- **Chosen:** `git init`, with `aether.db*`, `vector_store/`, `logs/`, `data/` and `.env` ignored before the first commit; `.dockerignore` with the same.
- **Why:** user data and keys must not be pushed, even to a private repository; every later change must be reversible.
- **Evidence:** `.gitignore`, `.dockerignore`; commits 989ae9b, 6b7a384.

### D-003 A virtual environment on Python 3.12, every dependency pinned
- **Date:** 2026-10-11
- **Context:** the app shared a global site-packages with TensorFlow and torch and took over 40 s to import (S12).
- **Options:** 1) keep the global install 2) a venv with pinned versions
- **Chosen:** 2, with `requirements-dev.txt` for the tools; one upgrade per commit, with its reason.
- **Why:** a fresh clone must start the same way every time; `pip-audit` needs exact versions to check.
- **Trade-off:** upgrades are manual.
- **Evidence:** `backend/requirements.txt`; commit 4e9831c.

### D-004 The backend refuses to start without JWT_SECRET; the environment wins over .env
- **Date:** 2026-10-11
- **Context:** tokens could be signed with a default secret, and `load_dotenv(override=True)` let a file overrule the environment (B4, S1).
- **Chosen:** a startup error naming the fix; `override=False`.
- **Why:** a guessable secret lets anyone forge a sign-in.
- **Evidence:** `core/config.py` (`require_jwt_secret`); `tests/unit/test_startup.py`.

### D-005 Route handlers are plain functions; the stream is a plain generator
- **Date:** 2026-10-11
- **Context:** async handlers called blocking code (Gemini, Chroma, SQLite, bcrypt); on Windows a streamed answer arrived only when it was finished, and one slow request stalled the others (B11).
- **Options:** 1) make every call async 2) `def` routes, which FastAPI runs in a thread pool
- **Chosen:** 2. The upload route is the one exception: it reads the body itself, as a stream, and hands blocking work to the thread pool.
- **Why:** the libraries are blocking; wrapping them is less code and less risk than rewriting them.
- **Trade-off:** concurrency is bounded by the thread pool.
- **Evidence:** `api/routes_documents.py` (header comment); commit 1e8e934.

### D-006 Errors are an error event, not answer text
- **Date:** 2026-10-11
- **Context:** a failed stream sent its error as tokens, so it was shown and saved as an answer (B9).
- **Chosen:** a `{"type": "error"}` event, and a non-200 status for a failed agent.
- **Evidence:** `api/schemas.py` (`ErrorEvent`); commit 4ebbbc4.

### D-007 ChromaDB inside the backend, with cosine distance
- **Date:** 2026-10-11 (cosine), kept 2026-10-12
- **Options:** 1) the earlier NumPy and JSON store 2) Chroma as its own server 3) Chroma as a library
- **Chosen:** 3, with the collection made for cosine distance (R1).
- **Why:** one collection filtered by tenant, persistent on disk, no second process on Windows. The `pip-audit` advisories for chromadb 1.5.9 are in its HTTP server, which this app never starts.
- **Trade-off:** one machine only (D-001).
- **Evidence:** `vectordb/vector_store.py`; report section 2.5.

### D-008 A file already in the library is refused, by its hash
- **Date:** 2026-10-11
- **Why:** reading it again stored every passage twice and crowded the top results with copies (R6).
- **Changed by:** D-060 (a PDF whose file was not kept is accepted again, to keep its file).
- **Evidence:** `api/routes_documents.py` (`_accept_upload`).

### D-009 Docker is deferred
- **Date:** 2026-10-11 · the owner's decision
- **Why:** the owner asked for it to wait. `.dockerignore` stays, so an image built by hand cannot contain secrets.
- **Revisit if:** the owner asks.

### D-010 Tests need no key and touch no real data
- **Date:** 2026-10-11
- **Chosen:** fake models (`tests/fakes.py`), a temp database, store and log folder (`tests/conftest.py`); `GOOGLE_API_KEY` and `OPENAI_API_KEY` set empty in the test process.
- **Why:** tests that call a model cost money, fail with the network, and could read or damage the owner's data (T2, C3).
- **Evidence:** `tests/conftest.py`; commit 716850d.

---

## Sprint 2: the safety net (11 Oct 2026)

### D-011 A known defect gets its test before its fix
- **Date:** 2026-10-11
- **Chosen:** each defect a later sprint fixes got a test of the correct behaviour, marked `xfail(strict=True)` with its finding id; the fixing sprint removed the mark.
- **Why:** the fix is then proven by a test written before anyone knew how it would be done.
- **Evidence:** commit 377b6af.

### D-012 The API's schema is snapshotted, and a change to it must be reviewed
- **Date:** 2026-10-11
- **Why:** a field renamed on one side broke the other twice (B7, F4); the snapshot is also what the frontend's types are generated from (D-037).
- **Evidence:** `tests/openapi_snapshot.json`, `tests/test_openapi_snapshot.py`.

### D-013 Ruff with its default rules only, until after the restructure
- **Date:** 2026-10-11
- **Why:** style rule families would have buried the Sprint 3 restructure's diff in reformatting.

### D-014 A design language of the project's own (Prism)
- **Date:** 2026-10-11 · approved by the owner
- **Options:** 1) a UI kit 2) a design language with its own tokens and components
- **Chosen:** 2: one font, CSS tokens, components in `frontend/src/design/`; no UI kit, no second styling approach.
- **Why:** a look of its own, and one set of rules every screen follows.
- **Evidence:** `DESIGN.md`.

---

## Sprint 3: restructure and connect (12 Oct 2026)

### D-015 One configuration class, the only reader of the environment
- **Date:** 2026-10-12
- **Why:** model ids and limits were copied into several files and drifted apart (C1).
- **Evidence:** `core/config.py`; `tests/test_no_orphans.py::test_only_core_config_reads_the_environment` and `::test_each_model_id_is_written_in_exactly_one_place`.

### D-016 One factory for the chat model and one for embeddings
- **Date:** 2026-10-12
- **Why:** five copies had no timeout and no output cap (C2, S4); with one factory each, every caller gets the same limits, and the tests replace two functions to fake every model.
- **Evidence:** `llm/llm_client.py` (`get_llm`), `embeddings/embedder.py` (`get_embeddings`).

### D-017 One pipeline that yields events
- **Date:** 2026-10-12
- **Options:** 1) keep the three copies (plain, streamed, LangChain) 2) one generator of events; the plain route collects them
- **Chosen:** 2.
- **Why:** three copies had already diverged; one path means one place to fix.
- **Evidence:** `pipeline/rag.py` (`events`, `answer`).

### D-018 LangChain mode stays, as a real second strategy
- **Date:** 2026-10-12
- **Why:** the internship plan requires it (Tasks 14 and 15). It uses a real LangChain retriever object and an LCEL chain, and shares the prompts, memory, sources and events with the other modes. No copied code.
- **Evidence:** `retrieval/retriever.py` (`UserRetriever`), `pipeline/rag.py` (`_search`, `_generate`).

### D-019 One `mode` field instead of four flags
- **Date:** 2026-10-12
- **Why:** four booleans allowed combinations that meant nothing (F9). An unknown field is now refused (422), so an old client is not silently answered in the default mode.
- **Evidence:** `api/schemas.py` (`ChatRequest`).

### D-020 The no-orphan check runs with the tests
- **Date:** 2026-10-12
- **Why:** it fails when a module is imported by nothing, a route is called by no test, the environment is read outside the config, or a model id is written twice: the unconnected code the audit found (the connection rule).
- **Evidence:** `tests/test_no_orphans.py`.

### D-021 Importing a module does nothing: an app factory with a startup hook
- **Date:** 2026-10-12
- **Why:** tables and folders were created at import, so a test or a script touched real data by importing (C3).
- **Evidence:** `main.py` (`create_app`, `lifespan`).

---

## Sprint 4: retrieval quality (12 Oct 2026)

### D-022 Hybrid search fuses dense and keyword results by rank, scores by similarity
- **Date:** 2026-10-12
- **Options:** 1) dense only 2) BM25 only 3) Reciprocal Rank Fusion of both
- **Chosen:** 3; each hit keeps its cosine similarity, so one threshold works in every mode (R2, R3). BM25's idf is never negative (rank_bm25's was zero or below for a word in half the chunks, so a user with one or two chunks got no keyword hits).
- **Why:** each search finds what the other misses: exact codes and names for BM25, paraphrases for dense.
- **Evidence:** `retrieval/retriever.py` (`search_hybrid`, `_Bm25`); `tests/unit/test_search.py`.

### D-023 Refuse below a similarity threshold, before asking the model
- **Date:** 2026-10-12
- **Options:** 1) let the model decide 2) a threshold on the best passage's cosine similarity
- **Chosen:** 2, at 0.3, uncalibrated.
- **Why:** a refusal that needs no model call costs nothing and cannot be talked out of.
- **Trade-off:** 0.3 never refuses anything with the local embedding model; see D-058.
- **Evidence:** `pipeline/rag.py` (`events`); `tests/unit/test_search.py`.

### D-024 Citations as [1], [2] in the text, not a JSON answer
- **Date:** 2026-10-12
- **Why:** a JSON answer cannot be streamed word by word.
- **Evidence:** `prompts/prompt_templates.py` (`CITED_RAG_PROMPT`), `pipeline/rag.py` (`cited_numbers`).

### D-025 Text files: UTF-8, or UTF-16 with a byte-order mark; nothing guessed
- **Date:** 2026-10-12
- **Options:** 1) guess the encoding (charset-normalizer) 2) accept two encodings and refuse the rest with a message
- **Chosen:** 2.
- **Why:** charset-normalizer read a Windows-1252 French sentence as UTF-16 Chinese characters.
- **Evidence:** `tests/unit/test_parsers.py`.

### D-026 The agent may not answer from the model's own knowledge; dates and sums are done in Python
- **Date:** 2026-10-12
- **Why:** a model counts days wrongly, and "use your own knowledge" let it answer without the documents (R11). An agent answer that searched no document shows no confidence.
- **Evidence:** `agents/tools.py`; `tests/unit/test_datetime_tool.py`, `tests/integration/test_agent.py`.

### D-027 Every passage carries its document's id
- **Date:** 2026-10-12
- **Why:** documents were known only by file name, so one could not be deleted alone, and a changed file of the same name was stored beside the old one (R7). Now: `DELETE /documents/{id}`, and a file of the same name replaces the earlier one once it is read.
- **Evidence:** `pipeline/documents.py` (`finish_document`); `tests/integration/test_documents.py`.

---

## Sprint 5: hardening (12 Oct 2026)

### D-028 The vector store is keyed by a random tenant id, not the user's number
- **Date:** 2026-10-12
- **Context:** a new database hands out user numbers 1, 2, 3 again, so a new user could see an old user's passages (S2).
- **Chosen:** a random tenant id on each user record; a startup migration re-files old chunks, safe to run twice, and gives no chunk to a user without a record for it.
- **Evidence:** `pipeline/documents.py` (`migrate_chunks_to_tenants`); `tests/integration/test_tenants.py`.

### D-029 A short access token in the page's memory; a refresh token in an httpOnly cookie
- **Date:** 2026-10-12
- **Options:** 1) one long-lived token in `localStorage` 2) short access token in memory and a refresh cookie
- **Chosen:** 2 (30 minutes and 7 days).
- **Why:** a script injected into the page cannot read an httpOnly cookie, and a reload still keeps the user signed in (S7).
- **Evidence:** `core/security.py`, `api/routes_auth.py`; `tests/integration/test_sign_in.py`.

### D-030 Rate limits per signed-in user, and a default on every route
- **Date:** 2026-10-12
- **Why:** limits by address put everyone behind one office router in one bucket, and routes without a limit could be hammered (S8).
- **Evidence:** `api/deps.py` (`rate_limit_key`); `tests/integration/test_api_routes.py`.

### D-031 Uploads are streamed to disk with a hard cap, after the token is checked
- **Date:** 2026-10-12
- **Why:** the whole file was read into memory before anything was checked, so anyone could send gigabytes (S4). Unpacked size of Word and Excel files, rows, passages and documents per user are capped too.
- **Evidence:** `api/routes_documents.py` (`_receive_upload`, `_capped`); `tests/integration/test_upload_limits.py` (a 60 MB upload is refused with 0 bytes read).

### D-032 Uploads are read in the background, with a status
- **Date:** 2026-10-12
- **Options:** 1) read inside the upload request 2) a job queue 3) FastAPI's background tasks and a status column
- **Chosen:** 3.
- **Why:** a large file held the request open for minutes (R12); a queue is a new service to run, for one user's uploads.
- **Trade-off:** a restart loses a file being read; it is marked failed at startup (`recover_interrupted_uploads`).
- **Evidence:** `api/routes_documents.py` (`_read_in_background`).

### D-033 The injection filter only logs; passages reach the model unchanged
- **Date:** 2026-10-12
- **Options:** 1) cut matched phrases out 2) log them, and fence documents in tags they cannot close
- **Chosen:** 2.
- **Why:** tests showed the pattern list missed every paraphrased injection and corrupted ordinary sentences ("will act as a liaison") (S5).
- **Evidence:** `tests/integration/test_injection_and_names.py`.

### D-034 Three attempts with growing waits; the client library's own retries off
- **Date:** 2026-10-12
- **Why:** during the Gemini outage of 12 Oct 2026 the client's six retries held a request for about 60 s; now a long outage is one clear message in under 2 s. Only quota and availability errors (429, 5xx) are retried (B10).
- **Evidence:** `llm/llm_client.py` (`RetryWhenUnavailable`); `tests/integration/test_model_unavailable.py`.

### D-035 Registration is open unless an invite code is set
- **Date:** 2026-10-12
- **Why:** closed by default would have locked the owner out of their own setup; `AETHER_INVITE_CODE` closes it before others can reach the app.

---

## Sprint 6: the frontend (12 Oct 2026)

### D-036 TypeScript, with the API's types generated from the schema
- **Date:** 2026-10-12
- **Options:** 1) hand-written types 2) none 3) generated from `openapi_snapshot.json`
- **Chosen:** 3; CI fails when the generated file differs.
- **Why:** a field renamed on one side then fails the build on the other, the cause of B7 and F4.
- **Evidence:** `frontend/src/services/api-schema.ts`, `api.contract.test.ts`.

### D-037 Only five new frontend dependencies; no state or data-fetching library
- **Date:** 2026-10-12
- **Why:** React state and one request wrapper are enough for an app this size; every dependency is code nobody here reads.
- **Changed by:** D-061 (pdf.js, for the page viewer).

### D-038 Real paths, served by the backend too
- **Date:** 2026-10-12
- **Chosen:** `/`, `/login`, `/chat/:threadId`, `/settings`, `/shared/:token`; a path outside `/api/` that matches no file gets `index.html`, and an unknown `/api/` path stays a JSON 404.
- **Why:** a thread can be linked and reloaded.
- **Evidence:** `main.py` (`SinglePageApp`); `tests/integration/test_frontend_serving.py`.

### D-039 Server-sent events over fetch, not WebSockets
- **Date:** 2026-10-12
- **Why:** one request per answer, through the same sign-in and rate limits as every other route; closing the stream is the Stop signal, and a stream closed early saves no turn.
- **Evidence:** `api/routes_chat.py` (`chat_stream`); `tests/integration/test_stream_closed.py`.

---

## Sprints 7 and 8 (12 and 13 Oct 2026)

### D-040 The second audit is its own file; the first is never edited
- **Date:** 2026-10-12
- **Why:** the first audit is the baseline every fix is measured against.
- **Evidence:** `AUDIT_REPORT_2.md`.

### D-041 What an answer cost is shown in seconds and tokens, never money
- **Date:** 2026-10-12
- **Why:** prices change, and the app does not know the owner's tier.

### D-042 Refresh tokens are recorded, and can be revoked everywhere
- **Date:** 2026-10-13
- **Why:** a refresh token was valid until it expired, even after signing out (N5). Tokens issued before the table existed are treated as revoked, so everyone signed in once more.
- **Evidence:** `db/database.py` (`refresh_tokens`); `tests/integration/test_sign_in.py`.

### D-043 A search that comes back short is finished by comparing every passage
- **Date:** 2026-10-13
- **Context:** Chroma's filtered index search returned nothing for a just-stored passage in 2 of 3 full test runs on Windows (N4).
- **Chosen:** when the index returns fewer than k hits and the tenant has more passages, compare the tenant's passages one by one.
- **Trade-off:** slower for that search; a tenant with fewer than k passages costs one count.
- **Evidence:** `vectordb/vector_store.py` (`similarity_search`, `_exact_search`).

### D-044 The start page argues with evidence and shows no sample data
- **Date:** 2026-10-13 · the owner's decision
- **Why:** the owner does not want sample answers there; the claim-to-evidence lines were kept, as bold traced lines, at their request.
- **Evidence:** `frontend/src/components/landing/WhyDifferent.tsx`.

### D-045 A conversation is shared by an unguessable link, read-only
- **Date:** 2026-10-13
- **Why:** sharing without accounts for the reader; 192 random bits cannot be guessed, the token is never logged, and the owner can withdraw it. The page shows the conversation and its cited passages, nothing of whose it is.
- **Evidence:** `tests/integration/test_sharing.py`.

---

## Models on this computer, and document scope (15 Oct 2026)

### D-046 Ollama as a second provider, chosen separately for answers and for embeddings
- **Date:** 2026-10-15
- **Context:** the Gemini free tier failed most questions (429 and 503); the owner already had Ollama.
- **Options:** 1) more Gemini keys 2) billing 3) Ollama on this computer
- **Chosen:** 3, with `AETHER_LLM_PROVIDER` and `AETHER_EMBEDDING_PROVIDER`.
- **Why:** no quota, no key, documents stay on the machine. Several keys to dodge one quota were advised against: quotas are per project, and evading them risks the account.
- **Trade-off:** answers depend on the computer's graphics card; Ollama must be running.
- **Evidence:** `llm/llm_client.py`, `embeddings/embedder.py`; `tests/unit/test_local_models.py`.

### D-047 The store records which embedding model made its vectors, and refuses to mix two
- **Date:** 2026-10-15
- **Why:** vectors from two models cannot be compared, and mixing them gives wrong answers with no error. `python -m src.reembed --apply` reads every stored passage again; an interrupted rebuild leaves the store as it was.
- **Evidence:** `vectordb/vector_store.py` (`embedding_model_changed`, `reembed`); `tests/unit/test_embedding_model_change.py`.

### D-048 qwen3.5:4b is the default Ollama chat model
- **Date:** 2026-10-15
- **Options:** qwen2.5:7b, gemma3:4b, qwen3.5:4b (llama2 and codellama:13b were ruled out: an old short-context model, and a code model)
- **Chosen:** qwen3.5:4b.
- **Why:** on the owner's papers it answered 5 of 6 questions right, against 3 of 6 for qwen2.5:7b, which did not fit the graphics card and ran partly on the processor; gemma3:4b cannot use tools, so agent mode fails with it.
- **Revisit if:** a larger card, or a model that gets the "best accuracy" question right.
- **Evidence:** `core/config.py` (`OLLAMA_LLM_MODEL`); SPRINT_PLAN.md, "Document scope".

### D-049 Ollama's thinking is off by default
- **Date:** 2026-10-15
- **Why:** qwen3.5 thinks silently before answering unless told not to: the same one-line answer took 21 s with it and 3 s without.
- **Evidence:** `core/config.py` (`ollama_think`).

### D-050 A question searches the documents chosen or named, decided by rules
- **Date:** 2026-10-15
- **Context:** the owner named a paper by its first two words; the app searched everything and answered from reference lists.
- **Options:** 1) only a picker 2) the model works out which documents (bRAG's query construction) 3) a picker plus rules on titles, opening words, file names and kinds
- **Chosen:** 3. Shared words count only when the question refers to a document as one, so a question about a subject is not narrowed because a title shares its words.
- **Why:** no extra model call per question, and every answer says what it searched and why, so a wrong guess shows.
- **Trade-off:** rules miss phrasings they were not written for.
- **Evidence:** `retrieval/scope.py`; `tests/unit/test_scope.py`, `tests/integration/test_document_scope.py`.

### D-051 Questions about authors, titles or ORCID ids read each paper's first passage
- **Date:** 2026-10-15
- **Why:** "authors" matched reference lists best, so the app listed 18 to 20 cited authors; a paper names its own authors at its start. The prompt also says names in a reference list, and results cited as [7], belong to the works cited.
- **Evidence:** `pipeline/rag.py` (`retrieve`), `prompts/prompt_templates.py`.

### D-052 The best hits come with the passages either side, in reading order
- **Date:** 2026-10-15
- **Why:** a passage cut mid-table or mid-argument misleads; Verba reads a window of one either side and orders the context by document, as it runs. Added passages do not count towards the confidence.
- **Evidence:** `pipeline/rag.py` (`_in_reading_order`), `core/config.py` (`chunk_window`).

### D-053 The answer is written from the cited passages by default
- **Date:** 2026-10-15
- **Context:** Sprint 4 left the summary step as the default until it was measured (R4).
- **Chosen:** `AETHER_ANSWER_FROM=chunks`, reversing that.
- **Why:** on the owner's papers the summary dropped exact details (ORCID ids) and doubled the time on a local model. One model call instead of two, and citations that show where each statement came from.
- **Revisit if:** the Sprint 4 evaluation measures the summary as better.

---

## Reranking, confidence, the page viewer, other services, OCR (15 Oct 2026, not merged)

### D-054 Search results are reranked by a small cross-encoder on the processor (not merged)
- **Date:** 2026-10-15 · `rerank`
- **Context:** a search compares meanings one passage at a time; it put a cited study's 94.9% above the paper's own 83.7%, sixth, outside the five read.
- **Options:** 1) no reranker 2) Cohere's rerank API, as kotaemon and bRAG use 3) a local cross-encoder: MiniLM-L-6 (88 MB), MiniLM-L-12, jina-turbo, bge-reranker-base (1 GB)
- **Chosen:** 3, MiniLM-L-6, through fastembed (ONNX: no PyTorch, no GPU). The search finds 20 passages; the reranker keeps the best 5.
- **Why:** measured on 20 questions written from the owner's documents: the answer passage was read for 19 of 20 (18 without), first for 11 (9). MiniLM-L-12 did no better; jina-turbo and bge-reranker-base did worse, bge taking 9 s a question. About 0.5 s for 20 passages. Cohere would send the documents out and needs a key.
- **Trade-off:** an 88 MB download the first time; it did not fix the "best accuracy" answer (the model now quotes 97.03%, another cited study, though the paper's own 84% was read).
- **Revisit if:** the evaluation dataset exists and shows another model better.
- **Evidence:** `retrieval/reranker.py`; `tests/unit/test_reranker.py`, `tests/integration/test_reranking.py`.

### D-055 A reranker that cannot load or fails leaves the search's own order (not merged)
- **Date:** 2026-10-15 · `rerank`
- **Why:** a missing download (no network the first time) must not stop questions being answered. It is logged once, and not tried again until the model id changes.
- **Evidence:** `tests/unit/test_reranker.py::test_a_model_that_cannot_be_loaded_is_tried_once_then_the_search_order_is_used`.

### D-056 The similarity stays the confidence; the reranker's score is not used for it (not merged)
- **Date:** 2026-10-15 · `rerank`
- **Options:** 1) the reranker's score as the confidence 2) the passages' cosine similarity, as before
- **Chosen:** 2.
- **Why:** the reranker scored correct author and ORCID questions very low (they match a name list, not a sentence), so it would have marked right answers Uncertain; saved answers keep one meaning for their number.

### D-057 The refusal threshold is not raised for the local embedding model (not merged)
- **Date:** 2026-10-15 · `rerank`
- **Context:** the owner was told the 0.3 line "never refuses" and that it should be tuned.
- **Chosen:** keep 0.3.
- **Why:** measured: short real questions ("orcid ids", 0.42) scored below unrelated ones ("who is the prime minister of India", 0.52), so any line that refused the unrelated questions refused real ones too. The model itself says when the passages do not answer.
- **Revisit if:** the evaluation dataset gives a line with no real question below it.

### D-058 The "Grounded" line is set for each embedding model, and sent with every answer (not merged)
- **Date:** 2026-10-15 · `rerank`
- **Context:** the ring showed "Uncertain" for most of the owner's answers: the line, 0.6, was set for Gemini, and nomic-embed-text scores lower (their real answers averaged 0.47 to 0.55).
- **Options:** 1) change the page's constant 2) a line per embedding model, sent by the server
- **Chosen:** 2: 0.5 for nomic-embed-text, 0.6 for Gemini and for models not measured; `AETHER_GROUNDED_AT` overrides.
- **Why:** measured: at 0.5, 28 of 33 questions about the documents read as grounded and none of 6 unrelated ones. The server knows which model searched; the page does not.
- **Trade-off:** questions near the documents' subjects but not answered in them cannot be told apart by similarity at all.
- **Evidence:** `core/config.py` (`GROUNDED_LINES`); `tests/integration/test_grounded_line.py`.

### D-059 PDFs are kept as uploaded, under the owner's tenant id (not merged)
- **Date:** 2026-10-15 · `pdf-viewer`
- **Context:** the upload was deleted once read, so a page could not be shown.
- **Options:** 1) keep every file 2) keep PDFs only 3) render page images at upload
- **Chosen:** 2, in `data/files/<tenant id>/<document id>.pdf`.
- **Why:** only a PDF has pages the browser can draw; a Word file shows its passage among the neighbouring ones instead. Named by ids, so no uploaded name reaches a path. The file goes with its document: removed, replaced or cleared.
- **Trade-off:** disk space; PDFs uploaded before 15 Oct 2026 have no file (see D-060).
- **Evidence:** `pipeline/documents.py` (`keep_original`, `original_path`); `tests/integration/test_document_files.py`.

### D-060 The same PDF uploaded again is kept for its document, not refused (not merged)
- **Date:** 2026-10-15 · `pdf-viewer`
- **Why:** otherwise the owner's existing PDF could never get its page view: the duplicate rule (D-008) refused it. It is not read twice (202, status "ready"); after that it is the usual duplicate.

### D-061 The page is drawn in the browser by pdf.js, and the passage found by runs of its words (not merged)
- **Date:** 2026-10-15 · `pdf-viewer`
- **Options:** 1) the browser's own PDF viewer at `#page=N` (no highlight) 2) page images made on the server 3) pdf.js in the page
- **Chosen:** 3, pdf.js 6.3.289, loaded only when a page is opened; 1 stays as "Open the whole PDF".
- **Why:** only 3 can mark the passage. The server's reader (pypdf) and pdf.js split words differently ("Classi fier"), so the passage is matched by runs of three of its words in order, and only a run of six words or more counts: shorter runs are common phrases.
- **Trade-off:** a 431 kB script and a 1.3 MB worker, fetched only when the viewer opens; a scanned page has no text to mark.
- **Evidence:** `frontend/src/components/chat/passageMatch.ts`, `SourceViewer.tsx`, `services/pdf.ts`.

### D-062 Fixed: a conversation opened by its address showed empty under the development server (not merged)
- **Date:** 2026-10-15 · `pdf-viewer`
- **Cause:** React runs effects twice in development; the cancelled first load, answering first, cleared the mark the second load checks. In the codebase since Sprint 6 (22d1925).
- **Chosen:** only a load that was not cancelled clears the mark; a test reproduces the network order.
- **Evidence:** `ChatLayout.tsx` (the thread-loading effect), `ChatLayout.test.tsx`.

### D-063 Any OpenAI-compatible service, through langchain-openai 1.3.2 (not merged)
- **Date:** 2026-10-15 · `openai-compatible`
- **Options:** 1) one integration per service 2) OpenAI's API, which Groq, OpenRouter, LM Studio and Ollama all speak 3) upgrade LangChain to use langchain-openai 1.7
- **Chosen:** 2, with langchain-openai 1.3.2 and openai 2.54.0.
- **Why:** one provider covers five services. 1.3.2 fits langchain-core 1.4.8; 1.3.5 and later would have upgraded LangChain, a change of its own.
- **Trade-off:** only Ollama's `/v1` address was tried; the other services are their documented addresses.
- **Evidence:** `llm/llm_client.py` (`OpenAICompatibleChat`, `_openai_problem`); `tests/unit/test_openai_compatible.py`.

### D-064 That provider has no default model, and its reasoning switch is opt-in (not merged)
- **Date:** 2026-10-15 · `openai-compatible`
- **Why:** every service names its own models, so a default would be wrong for most; an unnamed model is an error that says which setting to set. `reasoning_effort` is sent only when `AETHER_OPENAI_REASONING_EFFORT` is set: "none" stopped qwen3.5 from thinking (6 tokens for a three-word answer instead of 2,973), but OpenAI's other models refuse the field.
- **Evidence:** `embeddings/embedder.py` (`require_model`), `core/config.py`.

### D-065 Scanned pages are read by RapidOCR 3.10 with PP-OCRv6, on the processor (not merged)
- **Date:** 2026-10-15 · `ocr`
- **Options:** 1) Tesseract (a separate program to install on Windows) 2) the vision model in Ollama (slow, and only with Ollama) 3) a cloud OCR service (the pages leave the machine) 4) RapidOCR 1.4.4 5) RapidOCR 3.10
- **Chosen:** 5, with pypdfium2 drawing each page at 200 dpi.
- **Why:** a pip package with its models inside: no install, no download, no GPU. 4 was tried first: it read every character of a test scan but ran English words together ("suitableforthemodelsusedinthisresearch"), which search cannot use. 5 read every line with its spaces but one, at 1 to 1.7 s a page.
- **Trade-off:** layout is lost (tables and two columns come out line by line); 100 pages a file at most (`AETHER_OCR_MAX_PAGES`).
- **Evidence:** `ingestion/ocr.py`, `ingestion/loader.py` (`_parse_pdf`); `tests/unit/test_ocr.py`.

### D-066 Pages are read by OCR one at a time
- **Date:** 2026-10-15 · `ocr`
- **Why:** pdfium may not be called from two threads at once, and two uploads read together would only share the processor.
- **Evidence:** `ingestion/ocr.py` (`_lock`).

### D-067 Four stacked branches, merged by the owner
- **Date:** 2026-10-15
- **Context:** the permission check refused the merge into `main` ("merge without review").
- **Chosen:** each feature on its own branch, each built on the one before (`rerank`, then `pdf-viewer`, `openai-compatible`, `ocr`), all pushed; the owner merges `ocr`, which holds all four, after the quiz.
- **Why:** each can be read and reverted alone; one merge brings all four.

### D-068 start.bat installs packages again when their lists change
- **Date:** 2026-10-15 · `decisions-flow`
- **Context:** it ran `npm ci` only when `node_modules` was missing, and never pip. After the merge, the owner's existing `node_modules` would lack pdf.js and the chat page would fail to load; on another machine the new Python packages (fastembed, langchain-openai, pypdfium2, rapidocr) would be missing. Found while checking the viewer under the built app.
- **Options:** 1) tell the owner to run `npm ci` and pip by hand after each pull 2) install on every start (slow) 3) install when `package-lock.json` or `requirements.txt` differs from a copy kept from the last install
- **Chosen:** 3, comparing byte for byte (`fc /b`); pip only into the project's `.venv`, never the Python on PATH; `--packages-only` to install without starting.
- **Why:** a step the owner has to remember is a step that gets missed, and the failure (a blank page, an import error) does not say what to do.
- **Trade-off:** the first start after this change reinstalls once; `npm ci` fails while a server holds its files, and says to close the window.
- **Evidence:** tested in a scratch copy with stand-in npm and python: first run, nothing changed, each list changed, npm failing then succeeding, no `.venv`.

---

## Template

```
### D-0NN <the decision, in a few words>
- **Date:** YYYY-MM-DD · branch
- **Context:** what made a decision necessary
- **Options:** 1) ... 2) ... 3) ...
- **Chosen:** which, and its settings
- **Why:** the specific reason this one won here (a measurement, a finding id, a test)
- **Trade-off:** what was given up
- **Revisit if:** the condition that would change the decision
- **Evidence:** the file, test or commit that shows it
```
