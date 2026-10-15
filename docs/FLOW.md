# Flow

How execution travels through Aether AI: where each path starts, which function calls which, in
what order, and where it can fail. Read it before changing a path, and update it in the same
commit when a path changes. The reasons behind each step are in [DECISIONS.md](DECISIONS.md)
(D-numbers below).

Paths are `file` → `function`, from the folder `backend/` or `frontend/src/`. Steps marked
**[new]** are on the branches waiting to be merged (`rerank`, `pdf-viewer`,
`openai-compatible`, `ocr`).

## Contents

1. Entry points
2. Startup
3. Every request, before its route
4. Signing in, and staying signed in
5. Uploading a document
6. Asking a question (the streamed answer)
7. Agent mode
8. Building a model, and when a model fails
9. Showing a source in its document **[new]**
10. Conversations: history, rating, sharing
11. Removing documents
12. The page: from a click to the screen
13. Commands run by hand

---

## 1. Entry points

| Entry point | Started by | What it is |
|---|---|---|
| `start.bat` | double-click, or `start.bat --packages-only` | Installs the packages whose lists changed since the last install (`package-lock.json`, `requirements.txt`, compared with a copy kept beside the packages) (D-068); starts Ollama when the settings use it and it does not answer (`python -m src.ollama_ready`, D-071); then opens the two servers below |
| `main.py` → `create_app()` | `python -m uvicorn main:app` from `backend/` (`start.bat`) | The API, and the built page at `/` |
| `src/ollama_ready.py` | `python -m src.ollama_ready [--wait 30]`, from start.bat | Exit 3 when the settings use Ollama, on this computer, and it does not answer at `/api/version` (D-071) |
| `src/reembed.py` | `python -m src.reembed [--apply]` | Re-embeds stored passages after the embedding model changes |
| `src/maintenance.py` | `python -m src.maintenance [--apply]` | Finds passages and records that disagree |
| `src/evaluation/evaluate.py` | `python -m src.evaluation.evaluate` | Measures answer quality on a dataset |
| `src/evaluation/export_feedback.py` | `python -m src.evaluation.export_feedback` | Writes thumbs-down answers as candidate test questions |
| `frontend/src/main.tsx` | the browser loading `index.html` | The page: `BrowserRouter` → `AuthProvider` → `App` |

`tests/test_no_orphans.py` fails if a module is reachable from none of these.

## 2. Startup

```
main.py  create_app()
  ├─ settings.require_jwt_secret()         core/config.py      stops here without JWT_SECRET (D-004)
  ├─ RequestMiddleware, CORS, rate limiter api/middleware.py, api/deps.py
  ├─ routers: routes_auth, routes_chat, routes_documents, routes_health
  └─ mount_frontend(dist)                  SinglePageApp: unknown non-/api/ paths get index.html (D-038)

main.py  lifespan()  (runs once, when the server starts)
  ├─ setup_logging()                       core/logging.py     four JSON log files in logs/
  ├─ init_db()                             db/database.py      creates the tables if missing
  ├─ migrate_chunks_to_tenants()           pipeline/documents.py   files old passages under tenant ids (D-028)
  ├─ recover_interrupted_uploads()         pipeline/documents.py   marks uploads cut short by a restart as failed
  ├─ store.embedding_model_changed()       vectordb/vector_store.py  warns if the embedding model changed (D-047)
  └─ reranker.warm() in a thread [new]     retrieval/reranker.py   loads the reranking model in the background
```

Nothing opens a store or needs a key at import time (D-021): the database, the vector store and
the models are opened on first use.

**Where it fails:** no `JWT_SECRET` stops the start, on purpose. A reranking model that cannot be
downloaded only logs a warning **[new]**.

## 3. Every request, before its route

```
RequestMiddleware.__call__        api/middleware.py   a request id; security headers and CSP on the reply (outermost: added last)
  → CORSMiddleware                main.py             only the origins in settings.allowed_origins
  → SlowAPIASGIMiddleware         api/deps.py         rate_limit_key(): the user id from the token, else the address (D-030)
  → route
      → get_current_user()        api/deps.py         decode_access_token() → user_for(): 401 if expired, forged, or the user is gone
```

Routes are plain `def`, run in FastAPI's thread pool (D-005); the upload route is the one `async`
route, because it reads the body itself.

## 4. Signing in, and staying signed in

```
Page: App.tsx (on load)  → refreshSession() → POST /auth/refresh   (the httpOnly cookie, if any)
                        → getMe()          → GET  /auth/me

POST /api/v1/auth/login           api/routes_auth.py  login()
  get_user_by_username()          db/database.py
  verify_password()               core/security.py    checked even for an unknown name, so both failures take as long
  _signed_in()
    tokens_for(user)              core/security.py    access token (30 min) + refresh token (7 days)
    record_refresh_token()        db/database.py      so it can be revoked (D-042)
    _set_refresh_cookie()                             httpOnly cookie, path limited to the auth routes (D-029)

Page: services/api.ts  send()  every later call: Authorization: Bearer <access token>
  on a 401: renewToken() → POST /auth/refresh once → repeat the call; if that fails, sign out to the start page
```

**Where it fails:** a refresh token issued before Sprint 8, revoked, or of a deleted user is
refused (401), and the user signs in again.

## 5. Uploading a document

```
Page: ChatLayout.tsx handleUpload() → uploadDocument() (api.ts) → POST /api/v1/upload

api/routes_documents.py  upload_document()                         async; the token is checked first (D-031)
  _receive_upload()          stream the multipart body to a temp file, refused past 50 MB; sha256 as it goes
  _accept_upload()  (thread pool)
    type, empty file, library quota
    check_duplicate_document()   db/database.py: same hash already in the library?
      already read, a PDF, no file kept → keep_original() and reply 202 "ready": nothing read [new] (D-060)
      otherwise → 409 duplicate (D-008)
    accept_document()            pipeline/documents.py: record "processing"
  reply 202 {document_id}; then, after the reply:
  _read_in_background()  (thread pool, FastAPI background task) (D-032)
    finish_document()                         pipeline/documents.py
      ingest_document()
        load_document(owner)                  ingestion/loader.py   by extension (native or LangChain loaders)
          _parse_pdf()                        pypdf: text page by page
            pages with no text → ocr.read_pages(owner)  [new]  ingestion/ocr.py (D-065)
              _reserve(): the pages count against the owner's last hour, or the file is refused (D-073)
              each page in a turn of its own, in the order asked (_Turns): pypdfium2 draws it at
              200 dpi → RapidOCR reads it; one page at a time for the whole server (D-066, D-073)
          _parse_docx() / _parse_text() / _parse_tabular()
        split_documents()                     chunking/chunker.py   1000-character passages, 150 overlap;
                                                                     chunk_id, chunk_index (from 1), total_chunks
        store.add_documents(tenant, chunks)   vectordb/vector_store.py: tenant_id on each; embeds them (get_embeddings)
      set_document_status("ready")            db/database.py
      delete_document() for an older file of the same name (D-027)
    keep_original()  [new]                    pipeline/documents.py: a PDF moves to data/files/<tenant>/<id>.pdf (D-059)
    on error: fail_document() → status "failed" with a message the user can read; its passages removed
    finally: the temp file is deleted
Page: getDocument() every second until "ready" or "failed", then a toast
```

**Where it fails:** a file over 50 MB, too many passages or pages read by OCR (100 in a file, 200
for a user in an hour), a PDF with no words even for OCR, the embedding model busy (429/503: "upload
it again in a minute") or not set up (Ollama not running, model not installed, a model not named for
an OpenAI-compatible service **[new]**). A restart while a file is read marks it failed at the next
start.

## 6. Asking a question (the streamed answer)

This is the core path. `POST /chat` (not streamed) runs the same pipeline through `rag.answer()`,
which collects the events.

```
Page: ChatLayout.tsx handleSend() → sendChatStream() (api.ts) → POST /api/v1/chat/stream
                                     {question, session_id, mode, document_ids?}

api/routes_chat.py  chat_stream()
  question length; _check_scope() → scope.check_chosen(): 400 before the stream if no chosen document is ready
  generate_stream()  (a plain generator: Starlette runs it in a worker thread)
    for event in rag.events(...):  yield "data: {json}\n\n"

pipeline/rag.py  events(user_id, question, session_id, mode, document_ids)
  mode "agent" → _agent_events()  (section 7)
  1. memory.format_history()                     memory/conversation.py: the last turns of this session
     if there is history: rewrite_question()     retrieval/retriever.py: a follow-up becomes a standalone question (one model call)
  2. scoping.resolve(user, question, document_ids)   retrieval/scope.py (D-050)
       documents_of(user): each ready document, its kind, title and opening words (from passage 1)
       chosen ids → "chosen"; else _named() (title words, author, file-name word or number) → "named";
       else _of_kind() ("the PDF") → "kind"; else all.  Also: each (both/each), front_matter (authors, ORCID)
  3. retrieve(mode, user, query, scope)
       get_tenant_id(user)                       db/database.py
       _search(mode, tenant, query, k, ids)      once, or once per document for an "each" question
         pool = 20 when a reranker is set [new], else top_k (5)
         default:   retriever.search()           → store.similarity_search(): cosine, filtered by tenant and documents
                                                    (exact comparison when Chroma's index comes back short, D-043)
         hybrid:    retriever.search_hybrid()    dense + search_bm25(), fused by rank, scored by cosine (D-022)
         langchain: UserRetriever.invoke()       a LangChain retriever over the same dense search (D-018)
         reranker.rerank(query, hits, k)  [new]  retrieval/reranker.py: the cross-encoder keeps the best k (D-054)
       front-matter question → store.first_passages(): each document's passage 1, marked added "start" (D-051)
       chunk window → store.passages_around() for the two best hits, marked added "neighbour" (D-052)
       _in_reading_order()                       documents by their best hit, passages in document order
  4. no hits → refusal "No documents have been uploaded yet"
     confidence = mean similarity of the hits found (not of those added)
     best similarity < settings.confidence_threshold (0.3) → refusal, no model call (D-023)
  5. _report_injection_patterns()                prompts: log passages that read like instructions; sent unchanged (D-033)
  6. _generate()                                 answer_from "chunks" (default, D-053):
       CITED_RAG_PROMPT | get_llm() | parser .stream()   prompts/prompt_templates.py: format_context(numbered, titles)
       → yields {"type": "token"} events as the model writes
     (answer_from "summary": SUMMARIZE_PROMPT, then RAG_PROMPT: two calls)
  7. _answer_sources()                           the passages the answer cites as [n]; none for a refusal
  8. memory.add_turn() → save_conversation()     db/database.py: the turn, saved only after the last token (D-039)
  9. yield {"type": "done", sources, confidence, turn_id, usage, scope, grounded_at [new]}
       grounded_at = settings.grounded_line(): the "Grounded" line for this embedding model (D-058)

Page: onToken → the answer grows on screen; onDone → answered() → the message with its sources (section 12)
```

**Where it fails:** the model is busy (429/503 after three tries: one error event, MODEL_BUSY) or
not set up (`setup_problem()`: Ollama not running, a model not installed, a key refused, a service
out of reach **[new]**): an error event, nothing saved. Closing the stream (Stop) ends the
generator before step 8: no turn is saved. A question near the documents' subject but not answered
in them passes the threshold and relies on the model to say so (D-057). A small model can quote a
cited study's figure as the paper's own (D-054).

## 7. Agent mode

```
pipeline/rag.py  _agent_events()
  agents/agent.py  run_agent(user, question, session, search_documents=…)
    tools: calculator_wrapper (agents/tools.py calculator), datetime_wrapper (datetime_tool),
           document_search_wrapper → search_documents(query)
                                       → rag.answer(..., save_turn=False, document_ids=scope.ids)  (section 6, without saving)
    create_agent(get_llm(tool_temperature), tools, AGENT_SYSTEM_PROMPT)   langchain.agents
    history from memory → agent.invoke(messages, recursion_limit=12)
    → {answer, sources, confidence (lowest of its searches; none if it searched nothing), tool_used, steps}
  the answer is sent word by word, then memory.add_turn(), then the done event with steps and usage
```

**Where it fails:** a model that cannot use tools (gemma3:4b; or an OpenAI-compatible model
without tools **[new]**) gets a message naming the fix. A loop that keeps calling tools stops at
the recursion limit and lists the calls it made.

## 8. Building a model, and when a model fails

```
llm/llm_client.py  get_llm(temperature, model)           (D-016)
  settings.llm_provider:
    "gemini" → GeminiChat(...)              needs GOOGLE_API_KEY; the Google client's own retries off
    "ollama" → OllamaChat(...)              num_ctx 8192, thinking off (D-049), keep_alive 30m
    "openai" → OpenAICompatibleChat(...)  [new]  openai_url, OPENAI_API_KEY or "none", model named or ModelSetupError,
                                                 reasoning_effort when set (D-063, D-064)
  each mixes in RetryWhenUnavailable: 429 and 5xx (Ollama: 429 and 503) tried again after 2 s, 4 s (3 attempts, D-034);
  a stream is not retried once its first piece is out

embeddings/embedder.py  get_embeddings()  the same three providers; OpenAI-compatible embeddings without tiktoken [new]

errors, read by every route:
  is_unavailable(e)   quota or availability, from Google, Ollama or openai [new] errors   → 503 MODEL_BUSY
  setup_problem(e)    something the owner must fix, in words for the person who asked    → 503 with that message
```

Tests replace `get_llm` and `get_embeddings` with the fakes in `tests/fakes.py` (D-010), and
`reranker._load` and `ocr._load` with fakes too **[new]**.

## 9. Showing a source in its document [new]

```
Page: MessageBubble.tsx  a source card pinned open, whose source names its document_id and passage
  → "Show on p. 20" / "Show in the document" → onOpenSource(source, n)
ChatLayout.tsx  openSource() → <SourceViewer source n />

components/chat/SourceViewer.tsx
  getPassage(document_id, passage) → GET /api/v1/documents/{id}/passages/{n}?around=1
      api/routes_documents.py get_passage(): get_document() (404 if not yours or not ready)
        → store.passages_at(tenant, id, [n-1, n, n+1]) → {kind, passages, original: has_original(), items}
  if kind is pdf and original:
      getDocumentFile(id) → GET /api/v1/documents/{id}/file
        get_document_file(): FileResponse of data/files/<tenant>/<id>.pdf, inline; 404 with how to keep it
      services/pdf.ts drawPage(bytes, page, canvas, width)   pdf.js, loaded on first use (D-061)
        page.render() on the canvas; page.getTextContent() → each text piece and its box
      passageMatch.ts piecesOfPassage(pieces, passage text)  runs of 3 words, at least 6 long
      → marks over the canvas, as shares of the page, so they follow the dialog's width
      ResizeObserver: drawn again when the dialog grows a quarter wider
  else: the passage among its neighbours, the cited one marked; for a PDF without its file,
        a note that uploading the same file again keeps it (D-060)
```

**Where it fails:** a scanned page has no text to mark ("could not be marked on this page");
a PDF uploaded before 15 Oct 2026 has no file until it is uploaded again; answers saved before
that date carry no passage number, so their cards have no button.

## 10. Conversations: history, rating, sharing

```
GET  /sessions                       routes_chat.list_sessions()      → get_sessions(): the rail's thread list
GET  /sessions/{id}/messages         session_messages()               → get_session_turns() + grounded_at [new]
PATCH / DELETE /sessions/{id}        rename_conversation(), delete_conversation()
POST /feedback {turn_id, 1|-1|0}     submit_feedback()                → update_conversation_feedback()
POST /sessions/{id}/share            share_conversation()             → share_session(): a 192-bit token, never logged (D-045)
GET  /shared/{token}  (no sign-in)   shared_conversation()            → get_shared_session() → the turns, nothing of whose
```

Page: `ChatLayout.tsx` loads a thread when the URL's thread id changes (the effect around
`getSessionMessages`). The fix for an empty thread on reload in development is there **[new]**
(D-062).

## 11. Removing documents

```
DELETE /documents/{id}    delete_one_document() → pipeline/documents.py delete_document()
                            store.delete_document_chunks() → delete_document_record() → the kept PDF [new]
DELETE /documents         delete_documents() → clear_documents()
                            store.delete_user_chunks() → clear_user_documents() → data/files/<tenant>/ [new]
```

Passages go first: if that fails, the record stays, so the list still matches the store.

## 12. The page: from a click to the screen

```
main.tsx → App.tsx  routes: / and /login (start page), /chat/:threadId and /settings (workspace),
                    /shared/:token (SharedPage)
ChatLayout.tsx     the workspace's state: messages, threads, documents, "Search in", the open source [new]
  ├─ Sidebar.tsx         threads and the library (upload, remove)
  ├─ ChatWindow.tsx      the conversation
  │    └─ MessageBubble.tsx   one answer: clarityOf() (Grounded / Uncertain, by the server's grounded_at [new]),
  │                           ScopeNote, the answer as Markdown with [n] chips, SourceCards, "Show on p. N" [new]
  ├─ ChatComposer.tsx    the question box, the answer mode, ScopePicker ("Search in"), Stream
  ├─ SettingsModal.tsx, ShareDialog.tsx, SourceViewer.tsx [new]
services/api.ts    every call: send() adds the token, renews it once on a 401, turns errors into messages;
                   types from api-schema.ts, generated from the backend's schema (D-036)
design/prism.tsx   the components every screen is built from (DESIGN.md)
```

## 13. Commands run by hand

```
python -m src.reembed [--apply]       store.embedding_model_changed() → store.reembed(): each passage again, in batches of 64,
                                      into a rebuild that replaces the store only when complete (D-047)
python -m src.maintenance [--apply]   passages with no record, records with no passages; deletes only with --apply
python -m src.evaluation.evaluate     rag.retrieve() and rag.answer() over dataset.jsonl; a judge model scores answers
```
