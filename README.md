# Aether AI

A multi-user document question-answering assistant (retrieval-augmented generation). You upload documents, ask questions, and get answers with citations to the passages they came from.

- **Backend** (`backend/`): FastAPI, LangChain, Google Gemini or models on your own computer through Ollama (chat and embeddings), ChromaDB (vectors), SQLite (users, documents, conversations), JWT login.
- **Frontend** (`frontend/`): React 19 + Vite, in TypeScript. **This is the real user interface.** There is no other UI; the old page in `backend/static/` has been removed.

Project status and history: [AUDIT_REPORT.md](AUDIT_REPORT.md) lists what was found in the October 2026 audit, [SPRINT_PLAN.md](SPRINT_PLAN.md) is the plan being worked through, and [SDLC_PLAN.md](SDLC_PLAN.md) is an older log kept for history.

## What you need

- **Python 3.12** (from python.org; on Windows the `py` launcher is installed with it)
- **Node.js 20.19+ or 22.12+** (includes `npm`)
- A **Google Gemini API key** for real answers, or **Ollama** to run the models on your own computer (see "Models on your own computer"; tests need neither)

## Setup on Windows (once)

**Keep the project in a short folder path**, such as `C:\Projects\Aether-AI`. Windows limits a file path to 260 characters unless long-path support is turned on, and it is off by default. `npm ci` and `pip install` create deeply nested folders, so in a long path they can fail with "file not found" or "path too long" errors. Spaces in the path are fine.

Run these in **Command Prompt** from the project folder (the one containing this README).

1. Create a virtual environment in the project folder and install the backend:

   ```bat
   py -3.12 -m venv .venv
   .venv\Scripts\python -m pip install --upgrade pip
   .venv\Scripts\python -m pip install -r backend\requirements-dev.txt
   ```

2. Install the frontend packages:

   ```bat
   cd frontend
   npm ci
   cd ..
   ```

3. Create your settings file and fill it in:

   ```bat
   copy backend\.env.example backend\.env
   .venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(64))"
   ```

   Open `backend\.env` in a text editor. Put your Gemini key after `GOOGLE_API_KEY=` and paste the long random string printed above after `JWT_SECRET=`. The backend refuses to start without `JWT_SECRET`. Never commit `backend\.env`.

4. If you have an older copy of this project, delete the folder `backend\vector_store\` once (with the backend stopped). The vector store now uses cosine distance, and that setting only applies when the store is first created. Older stores hold no usable data (the audit found them empty), so nothing is lost; upload your documents again.

## Run on Windows

Double-click `start.bat` (or run it from Command Prompt). It opens two windows, one for the backend on port 8000 and one for the frontend on port 5173. Then open **http://localhost:5173**, register a user, upload a document and ask a question about it.

To stop, close the two windows titled "Aether AI backend" and "Aether AI frontend".

Before it starts them, `start.bat` installs the packages again when their lists have changed since the last install: `frontend\package-lock.json` (with `npm ci`) and `backend\requirements.txt` (with pip, into the project's `.venv` only). So after a `git pull` or a merge that adds a package, running it is enough; close the two windows first, since a running server keeps its files in use. `start.bat --packages-only` installs what changed and starts nothing.

To start the two parts by hand instead, use two Command Prompt windows:

```bat
REM window 1: backend
cd backend
..\.venv\Scripts\python -m uvicorn main:app --port 8000

REM window 2: frontend
cd frontend
npm run dev
```

### One server instead of two

The backend also serves the built React app at **http://localhost:8000/** (the API stays under `/api/v1/`). Build it once, then start only the backend:

```bat
cd frontend
npm run build
cd ..\backend
..\.venv\Scripts\python -m uvicorn main:app --port 8000
```

Rebuild and restart the backend after changing frontend code. Without a build, `http://localhost:8000/` shows a page explaining these two options.

## Models on your own computer (Ollama)

Instead of Gemini, the app can use models that run on this computer through [Ollama](https://ollama.com): no API key and no usage limits, and with both models local your documents never leave the machine. Answers take longer than with Gemini on most computers; how long depends on the graphics card.

1. Install Ollama, then download the two default models:

   ```bat
   ollama pull qwen3.5:4b
   ollama pull nomic-embed-text
   ```

   `qwen3.5:4b` (3.4 GB; needs a recent Ollama, 0.40 or later) writes the answers and can use tools, which agent mode needs. It can also think before it answers; the app turns that off (`AETHER_OLLAMA_THINK=false`), since thinking made answers several times slower. On an older Ollama, `qwen2.5:7b` (4.7 GB) works too. `nomic-embed-text` (0.3 GB) turns passages and questions into vectors for the search.

2. Add two lines to `backend\.env`:

   ```
   AETHER_LLM_PROVIDER=ollama
   AETHER_EMBEDDING_PROVIDER=ollama
   ```

   `GOOGLE_API_KEY` is then not used and can stay empty. For another model, add `AETHER_LLM_MODEL=` or `AETHER_EMBEDDING_MODEL=` with its name in Ollama, for example `AETHER_LLM_MODEL=gemma3:4b`. A model that cannot use tools still answers in Default, Hybrid and LangChain modes; in agent mode the app says it cannot. Either line can also be used alone: a local chat model with Gemini's embeddings keeps your documents as they are, but still needs the key.

3. If you already have documents, read them again with the new embedding model, once, with the backend stopped:

   ```bat
   cd backend
   ..\.venv\Scripts\python -m src.reembed
   ..\.venv\Scripts\python -m src.reembed --apply
   ```

   Vectors made by two embedding models cannot be compared, so until this has run the app does not search or add documents, and says why. The first command only reports; `--apply` embeds every stored passage again and keeps its text and where it came from, so nothing has to be uploaded again. If it stops part-way, the store is left as it was. Going back to Gemini needs the same step, and spends Gemini quota on every passage.

4. Start the app as usual. Ollama must be running: if it is not, a question is answered with "Ollama is not running", and a model that is not installed is named with the command that installs it.

Each embedding model spreads its similarity scores differently, so the line at which an answer reads as *Grounded* is set for each one: 0.5 for `nomic-embed-text` (measured on real papers: questions about them averaged 0.40 to 0.78, unrelated questions 0.38 to 0.48) and 0.6 for Gemini's. `AETHER_GROUNDED_AT` sets your own. The refusal threshold (`AETHER_CONFIDENCE_THRESHOLD`, 0.3) is not raised for `nomic-embed-text`: short questions about the documents scored as low as unrelated ones, so a higher line refused real questions. For another embedding model, measure both (see "Measuring answer quality").

## Any OpenAI-compatible service

The models can also come from any service that speaks OpenAI's API: OpenAI itself, Groq, OpenRouter, LM Studio on this computer, or Ollama's own `/v1` address. In `backend\.env`:

```
AETHER_LLM_PROVIDER=openai
AETHER_OPENAI_URL=https://api.groq.com/openai/v1
OPENAI_API_KEY=<the service's key; leave it out for LM Studio or Ollama>
AETHER_LLM_MODEL=<a model id the service lists>
```

| Service | `AETHER_OPENAI_URL` | Key |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` (the default) | needed |
| Groq | `https://api.groq.com/openai/v1` | needed |
| OpenRouter | `https://openrouter.ai/api/v1` | needed |
| LM Studio | `http://localhost:1234/v1` | none |
| Ollama | `http://127.0.0.1:11434/v1` | none |

There is no default model: every service names its own, so set `AETHER_LLM_MODEL` (and `AETHER_EMBEDDING_MODEL` with `AETHER_EMBEDDING_PROVIDER=openai`). Not every service makes embeddings; one that does not can answer while Gemini or Ollama keeps the search (leave `AETHER_EMBEDDING_PROVIDER` as it is). Changing the embedding model needs `python -m src.reembed --apply`, as above. For a model that thinks before it answers, such as `qwen3.5:4b` through Ollama's or LM Studio's address, add `AETHER_OPENAI_REASONING_EFFORT=none`: a three-word answer took 6 tokens with it and 2,973 without. OpenAI's other models refuse that setting.

If the service cannot be reached, refuses the key, or does not have the model, the answer says which, and what to set. Tried here: Ollama's `/v1` address, for answers in every mode (agent mode's tools too) and for embeddings. The other addresses are the services' own; they were not tried.

## Asking about particular documents

A question searches every document in your library unless you say otherwise. There are two ways:

- **Search in**, beside the answer mode (shown once you have two documents): choose *All documents*, every file of one kind (*Every PDF*, *Every Word file*), or tick the documents to search. Documents are listed by their title, read from their first page, with the file name under it. The choice holds for the questions that follow.
- **Name it in the question.** By the first words of its title, when the question calls it a document or asks who wrote it ("Who are the authors of Classification of…?", "the Automated Post-Disaster paper"); by an author on its first page ("the paper by Hardik Kumar"); by the number or two words of its file name ("the 13003 pdf", "the Recos letter"); or by its kind ("in the PDF", "the Word files"). A question about a subject is not narrowed because a title shares its words.

Under each answer that did not search everything, a line says what it searched and why, so a wrong guess shows. A question about a document's title, authors, affiliations, e-mail addresses or ORCID ids reads each document's first passage, where a paper names its own authors (not its reference list); one about "both" or "each" document reads each one's best passages. Each source says where it is: the page of a PDF, or "passage 3 of 42" in a file without pages.

## Scanned PDFs

A PDF page with no text in it (a scan, a photo of a page) is read by OCR on this computer's processor, with the models that come with RapidOCR: nothing is downloaded and nothing leaves the machine. It takes about 1 to 2 seconds a page, so a scanned paper is ready within a minute; a file with more than 100 such pages (`AETHER_OCR_MAX_PAGES`) is refused, since it would take minutes. Pages that have text are read as before. `AETHER_OCR=false` turns it off, and a scan is then refused as it was before. OCR reads the words, not the layout: tables and two-column pages come out line by line, and a scanned page cannot have its passage marked in the page viewer, since the page holds no text to mark.

## Seeing a source in its document

Click a source card under an answer to pin it open, then **Show on p. 20** (a PDF) or **Show in the document** (any other file). A PDF opens on the cited page, drawn in the browser, with the passage marked on it; *Open the whole PDF* opens it in the browser's own viewer at that page. A Word, text or spreadsheet passage is shown with the passages either side of it.

PDFs are kept as uploaded, in `data/files/`, so their pages can be shown; a document's file goes when the document does. PDFs added before 15 Oct 2026 were not kept: upload the same file again and it is kept for its document, without being read twice. Answers saved before that date do not say which passage they cite, so their cards have no button.

## Reranking

Each search finds 20 passages; then a small model on this computer, `Xenova/ms-marco-MiniLM-L-6-v2` (88 MB), reads the question with each passage and keeps the five that answer it best. A search compares meanings; the reranker judges answers, so a paper's own result is put ahead of a cited study's that uses the same words. It is downloaded from Hugging Face once, the first time the backend starts, into `data/models/`; after that it works offline, on the processor, in about half a second a question. If it cannot be downloaded, answers use the search's own order and `backend/logs/errors.log` says why. `AETHER_RERANK_MODEL=` (empty) turns it off; `AETHER_RERANK_CANDIDATES` changes how many passages it reads.

## Run the tests

```bat
cd backend
..\.venv\Scripts\python -m pytest
```

The tests use a fake embedding model and a fake chat model, a temporary database and a temporary vector store. They need no API key, make no calls to Google, and do not touch `backend\aether.db` or `backend\vector_store\`.

Tests marked `xfail` describe known defects that a later sprint fixes (see `backend\tests\test_known_defects.py`); they are expected to fail and do not fail the run.

With per-file coverage:

```bat
..\.venv\Scripts\python -m pytest --cov
```

`backend\tests\openapi_snapshot.json` is the API contract. If you change a route or a request or response model on purpose, refresh it and review the diff:

```bat
..\.venv\Scripts\python -m pytest tests\test_openapi_snapshot.py --update-openapi-snapshot
```

The web app's API types are generated from that snapshot (`frontend/src/services/api-schema.ts`), so after refreshing it, regenerate them; a renamed field then shows up as a type error wherever the app uses it:

```bat
cd frontend
npm run api-types
```

Frontend checks:

```bat
cd frontend
npm run lint
npm run typecheck
npm test
npm run build
```

`npm run build` runs the type check first.

The browser journey walks through the whole app in Chromium: sign up, upload, ask, reload, a
second thread, a rating, removing the document and signing out, with an accessibility check
(axe) on the start page, the chat and settings at desktop and phone width. It builds the app
and starts its own backend with fake models on temp stores (`backend/tests/e2e_server.py`), so
it needs no API key and touches none of your data. Once, install the browser it uses; then run
it:

```bat
cd frontend
npx playwright install chromium
npm run e2e
```

It runs the backend with the Python in `.venv` at the project root (or set `AETHER_PYTHON` to
another one), on port 8765.

The same checks run on GitHub for every push and pull request (`.github/workflows/ci.yml`). They need no secrets.

## macOS and Linux

The same steps, with these commands:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
(cd frontend && npm ci)
cp backend/.env.example backend/.env    # then fill in GOOGLE_API_KEY and JWT_SECRET
(cd backend && ../.venv/bin/python -m uvicorn main:app --port 8000) &
(cd frontend && npm run dev)
```

## How the backend is laid out

`backend/main.py` is the entry point: it builds the app (`create_app()`), and its lifespan hook sets up the log files and the database tables when the server starts. Everything else is in packages under `backend/src/`:

| Package | What it holds |
|---|---|
| `core/` | `config.py` (every setting, the only place that reads the environment or `.env`), `security.py` (passwords and login tokens), `logging.py` |
| `api/` | `schemas.py` (request and response models), `deps.py` (current user, rate limiter), `middleware.py` (request id and security headers), `errors.py` (what a server error tells the client), and one router per resource: `routes_auth`, `routes_chat`, `routes_documents`, `routes_health` |
| `db/` | `database.py`: SQLite for users, document records and conversations |
| `ingestion/` | `loader.py`: reads PDF, DOCX, text, CSV and Excel files (native parsers, or LangChain's loaders when `AETHER_DOCUMENT_LOADER=langchain`) |
| `chunking/` | `chunker.py`: splits documents into overlapping chunks |
| `embeddings/`, `llm/` | the one factory for the Gemini embedding model and the one for the chat model |
| `vectordb/` | `vector_store.py`: ChromaDB on disk, opened on first use |
| `retrieval/` | `retriever.py`: dense, BM25 and hybrid search, the follow-up rewrite, and a LangChain retriever |
| `prompts/` | `prompt_templates.py`: every prompt, once |
| `memory/` | `conversation.py`: conversation history per user and session |
| `pipeline/` | `rag.py`: the one question-answering pipeline (modes `default`, `hybrid`, `langchain`, `agent`); `documents.py`: ingest, list, delete |
| `agents/` | `agent.py` and `tools.py`: the tool-calling agent, the calculator and the date-time tool |
| `evaluation/` | `evaluate.py`: measures the pipeline on labelled questions (see "Measuring answer quality" below); `export_feedback.py`: answers rated "not helpful", as questions to label |
| `maintenance.py` | Reports chunks and document records that do not match, and removes them when asked (see "Where data is kept") |
| `reembed.py` | Embeds every stored passage again after the embedding model changes (see "Models on your own computer") |

**Import style.** Code imports by absolute path from `backend/`, for example `from src.core.config import settings`. Run every command from the `backend` folder: `python -m uvicorn main:app`, `python -m pytest` and `python -m src.evaluation.evaluate` all put that folder on Python's path (`pytest.ini` sets `pythonpath = .` for the tests).

**Settings.** Every tunable has a default in `src/core/config.py` and can be overridden by an environment variable or a line in `backend\.env` with the `AETHER_` prefix, for example `AETHER_TOP_K=8` or `AETHER_LLM_MODEL=...`. Environment variables win over `.env`. `GOOGLE_API_KEY` and `JWT_SECRET` keep their usual names.

**The no-orphan check** (`backend\tests\test_no_orphans.py`, also its own CI step) fails if a module under `src/` is imported by nothing, if a route has no test that calls it, if anything but `core/config.py` reads the environment, or if a model id is written anywhere else.

## Measuring answer quality

`python -m src.evaluation.evaluate` asks a set of labelled questions through the real pipeline and reports how well it retrieved and answered. It ingests the documents into a temporary store, so your own database and vector store are not touched, but it does call the models (Gemini's, or Ollama's when it is set).

1. Put the documents in `backend\src\evaluation\documents\`.
2. Write `backend\src\evaluation\dataset.jsonl`, one question per line:

   ```json
   {"id": "q01", "question": "What is the notice period?", "expected_answer": "30 days.", "source": "handbook.pdf", "page": 12}
   {"id": "u01", "question": "What is the boiling point of mercury?", "answerable": false}
   ```

   `source` is the file that holds the answer and `page` the page (or `"pages": [12, 13]`). For files without pages, give `"contains": "a phrase from the right passage"` instead. Include questions the documents cannot answer, marked `"answerable": false`.
3. Run it from `backend`:

   ```bat
   ..\.venv\Scripts\python -m src.evaluation.evaluate --label baseline --retrieval-only
   ..\.venv\Scripts\python -m src.evaluation.evaluate --label baseline
   ```

   `--retrieval-only` measures retrieval and the refusal threshold with embedding calls only. The full run also generates every answer and has a second model score it, so set `AETHER_JUDGE_MODEL` in `backend\.env` to a model other than the one that answers. `--pause 6` waits between questions if you hit a rate limit.

Each run is saved as `docs\evaluation\<label>.json`, and `docs\evaluation.md` is rebuilt to show every saved run side by side, with a section explaining how each number is computed.

**Questions from feedback.** `..\.venv\Scripts\python -m src.evaluation.export_feedback` writes every answer rated "Not helpful" to `data\feedback_candidates.jsonl` (or `--output <file>`), one line per answer in the dataset's shape: the question, with `expected_answer`, `source` and `page` left empty, and the answer and sources the app gave beside them. Nothing is added to `dataset.jsonl` by itself: label a line, remove its `answer_given`, `sources_given`, `mode` and `asked_at` fields, and copy it in. The file holds users' questions, so it stays in `data\`, which git ignores; the command prints only how many lines it wrote.

To compare two settings, run it once for each with a different label. For example, `AETHER_ANSWER_FROM=chunks` in `backend\.env` makes the app write its answer straight from the retrieved passages and cite them as [1], [2], with no summary step (one model call per answer, not two). The default stays `summary` until a run shows which is better.

## Running it where other people can reach it

Before anyone else can open the app (an office network, a shared machine), add this line to `backend\.env`:

```
AETHER_ENVIRONMENT=production
```

It turns off the API pages (`/docs`, `/redoc`, `/openapi.json`), which list every route to anyone who asks. Everything else works the same.

Two more settings are worth setting there:

- `AETHER_INVITE_CODE=<a code>`: registering then needs that code, typed into the "Invite code" field of the sign-up form. Give it only to the people who should have an account. Left empty (the default), anyone who can open the page can register.
- `AETHER_COOKIE_SECURE=true`, but only once the app is served over HTTPS: it keeps the sign-in cookie off plain HTTP.

**Uploads.** An upload is accepted at once and read in the background: the library shows it as "Reading" until its passages are stored, and the app says how many it made, or why the file could not be read. A file still being read when the backend stops is marked as not read when it starts again; upload it again. A file may be up to 50 MB (`AETHER_MAX_UPLOAD_BYTES`); it is written to disk as it arrives and refused as soon as it passes the limit, and the sign-in is checked before any of it is read. A Word or Excel file may unpack to at most 200 MB, a CSV or workbook may have at most 100,000 rows, a document may make at most 5,000 passages, and each user may keep 100 documents (`AETHER_MAX_UNPACKED_BYTES`, `AETHER_MAX_TABLE_ROWS`, `AETHER_MAX_CHUNKS_PER_DOCUMENT`, `AETHER_MAX_DOCUMENTS_PER_USER`). Each refusal says which limit was reached.

**Rate limits.** Every route has one: requests that carry a valid sign-in count against that user, and the rest against their address, so people behind one office proxy do not share an allowance. Sign-up, sign-in, upload and chat have their own limits; everything else allows 120 requests a minute (`AETHER_RATE_LIMIT_DEFAULT`). The counts are kept in the server's memory and start again when it restarts.

**Conversations.** Every question and answer is saved with the sources shown beside it. Each conversation has its own address (`/chat/<id>`) and the rail lists them all, newest first; reloading the page keeps you signed in on the same one, and `/chat` opens the most recent. "New thread" starts a new conversation and keeps the old one; Settings, "Clear conversation" deletes the current one from the server. Stop ends a streamed answer, and nothing of a stopped or failed answer is saved: its question goes back into the box, with Retry. Each thread in the rail can be renamed in place, or deleted with two clicks ("Delete?", then again).

**Sharing a conversation.** "Share" in the top bar makes a link to the conversation that is open (`/shared/<token>`). Anyone who has the link can read that conversation and the passages it cites, without signing in; they cannot ask questions, and they see nothing else of yours, not even whose conversation it is. Questions you ask afterwards appear on it too. "Stop sharing" withdraws the link at once, and so does deleting the conversation; sharing again makes a new link. The token in the link is the only key, so treat the link like the conversation itself: it is never written to the logs.

**What an answer cost.** Under each new answer a quiet line says how long it took and how many tokens the model reported, for example "4.2 s, 1,240 tokens"; opening it lists each stage (search, summary, answer; or the agent and each document search). The same numbers are written to `backend\logs\requests.log`. They are not priced: prices change, and the app does not know your tier. An agent answer also lists its steps above it: each tool, what it was asked and the start of what it returned.

**Signing in.** Passwords are 8 characters to 72 bytes (72 letters, fewer with accents or symbols). Usernames use the letters A to Z, digits, hyphens and underscores, and their case does not matter: `Tirth` and `tirth` are the same account. A sign-in lasts 30 minutes and renews itself while the app is open, through a cookie that page scripts cannot read, so reloading the page keeps you signed in; a week without use signs you out. Signing out revokes that browser's sign-in on the server; Settings, "Sign out everywhere" revokes every one of yours, and each other browser is signed out when it next reloads, or within 30 minutes. Sign-ins from before Sprint 8 are not recorded on the server, so everyone signs in once more after that upgrade. Sign-ups, sign-ins and refused tokens are written to `backend\logs\auth.log`, never with a password.

When Gemini is over its quota or unavailable, each model call is tried three times in all, waiting 2 and then 4 seconds (`AETHER_LLM_MAX_ATTEMPTS`, `AETHER_LLM_RETRY_SECONDS`), and then the app says "The AI service is busy or over its usage limit right now. Please try again in a minute." Other errors are not retried. A free-tier key allows only a few questions a day; for a demo, use a billed key, and on an office network that inspects HTTPS, add the organisation's root certificate to the machine's trust store rather than turning certificate checks off.

When something fails on the server, the app shows a general message with a reference, for example `Reference: 3f2a9c81d0b4`. The same reference is on the matching line of `backend\logs\errors.log`, with the full error. Every response also carries it in an `X-Request-ID` header. The log files hold one JSON object per line, with the user's id and the request's reference, and never the text of a question.

## Where data is kept

All of these are created on first run and are ignored by git:

| Path | Contents |
|---|---|
| `backend/.env` | Your API key and JWT secret |
| `data/aether.db` | Users, uploaded-document records, conversations (`AETHER_DB_PATH` moves it) |
| `data/vector_store/` | Document chunks and their embeddings (`AETHER_VECTOR_STORE_DIR`) |
| `data/models/` | The reranking model, downloaded once (`AETHER_MODEL_DIR`) |
| `data/files/` | Uploaded PDFs, kept to show their pages (`AETHER_FILES_DIR`) |
| `backend/logs/` | Request, upload and error logs (`AETHER_LOG_DIR`) |

Before Sprint 5 the database and the vector store were kept in `backend/aether.db` and `backend/vector_store/`. If they are still there and nothing is in `data/` yet, the backend keeps using them and says so in `backend/logs/errors.log`. To move them, stop the backend and move both into a `data` folder in the project folder; nothing else needs to change.

Each user's chunks are filed under a random tenant id from their user record, not under the user's number, because a new database hands the same numbers out again. A store made before this change is re-filed when the backend starts; this is safe to run any number of times and deletes nothing.

**Housekeeping.** With the backend stopped, `..\.venv\Scripts\python -m src.maintenance` (from `backend`) lists the chunks no document accounts for (left by an earlier database, for example) and the documents listed as ready that have no chunks. It deletes nothing; `--apply` deletes exactly what it listed. A document still being read, or one that failed, is left alone.

Uploaded text and questions are sent to Google's Gemini API. Do not upload confidential documents until you have agreed with your mentor which documents and which API tier are allowed.

Agreed with the mentor: [OWNER: which documents may be uploaded, on which API tier, and the date agreed (finding S11)]

## Credits

Built by Tirth Ganatra during an internship at Netweb Software, Vadodara.
