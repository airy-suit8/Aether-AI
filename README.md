# Aether AI

A multi-user document question-answering assistant (retrieval-augmented generation). You upload documents, ask questions, and get answers with citations to the passages they came from.

- **Backend** (`backend/`): FastAPI, LangChain, Google Gemini (chat and embeddings), ChromaDB (vectors), SQLite (users, documents, conversations), JWT login.
- **Frontend** (`frontend/`): React 19 + Vite, in TypeScript. **This is the real user interface.** There is no other UI; the old page in `backend/static/` has been removed.

Project status and history: [AUDIT_REPORT.md](AUDIT_REPORT.md) lists what was found in the October 2026 audit, [SPRINT_PLAN.md](SPRINT_PLAN.md) is the plan being worked through, and [SDLC_PLAN.md](SDLC_PLAN.md) is an older log kept for history.

## What you need

- **Python 3.12** (from python.org; on Windows the `py` launcher is installed with it)
- **Node.js 20.19+ or 22.12+** (includes `npm`)
- A **Google Gemini API key** for real answers (tests do not need one)

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
| `evaluation/` | `evaluate.py`: measures the pipeline on labelled questions (see "Measuring answer quality" below) |

**Import style.** Code imports by absolute path from `backend/`, for example `from src.core.config import settings`. Run every command from the `backend` folder: `python -m uvicorn main:app`, `python -m pytest` and `python -m src.evaluation.evaluate` all put that folder on Python's path (`pytest.ini` sets `pythonpath = .` for the tests).

**Settings.** Every tunable has a default in `src/core/config.py` and can be overridden by an environment variable or a line in `backend\.env` with the `AETHER_` prefix, for example `AETHER_TOP_K=8` or `AETHER_LLM_MODEL=...`. Environment variables win over `.env`. `GOOGLE_API_KEY` and `JWT_SECRET` keep their usual names.

**The no-orphan check** (`backend\tests\test_no_orphans.py`, also its own CI step) fails if a module under `src/` is imported by nothing, if a route has no test that calls it, if anything but `core/config.py` reads the environment, or if a model id is written anywhere else.

## Measuring answer quality

`python -m src.evaluation.evaluate` asks a set of labelled questions through the real pipeline and reports how well it retrieved and answered. It ingests the documents into a temporary store, so your own database and vector store are not touched, but it does call Gemini.

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

**Conversations.** Every question and answer is saved with the sources shown beside it. "New thread" starts a new conversation and keeps the old one; Settings, "Clear conversation" deletes the current one from the server. Reloading the page keeps you signed in and shows your latest conversation again.

**Signing in.** Passwords are 8 characters to 72 bytes (72 letters, fewer with accents or symbols). Usernames use the letters A to Z, digits, hyphens and underscores, and their case does not matter: `Tirth` and `tirth` are the same account. A sign-in lasts 30 minutes and renews itself while the app is open, through a cookie that page scripts cannot read, so reloading the page keeps you signed in; a week without use signs you out. Sign-ups, sign-ins and refused tokens are written to `backend\logs\auth.log`, never with a password.

When Gemini is over its quota or unavailable, each model call is tried three times in all, waiting 2 and then 4 seconds (`AETHER_LLM_MAX_ATTEMPTS`, `AETHER_LLM_RETRY_SECONDS`), and then the app says "The AI service is busy or over its usage limit right now. Please try again in a minute." Other errors are not retried. A free-tier key allows only a few questions a day; for a demo, use a billed key, and on an office network that inspects HTTPS, add the organisation's root certificate to the machine's trust store rather than turning certificate checks off.

When something fails on the server, the app shows a general message with a reference, for example `Reference: 3f2a9c81d0b4`. The same reference is on the matching line of `backend\logs\errors.log`, with the full error. Every response also carries it in an `X-Request-ID` header. The log files hold one JSON object per line, with the user's id and the request's reference, and never the text of a question.

## Where data is kept

All of these are created on first run and are ignored by git:

| Path | Contents |
|---|---|
| `backend/.env` | Your API key and JWT secret |
| `data/aether.db` | Users, uploaded-document records, conversations (`AETHER_DB_PATH` moves it) |
| `data/vector_store/` | Document chunks and their embeddings (`AETHER_VECTOR_STORE_DIR`) |
| `backend/logs/` | Request, upload and error logs (`AETHER_LOG_DIR`) |

Before Sprint 5 the database and the vector store were kept in `backend/aether.db` and `backend/vector_store/`. If they are still there and nothing is in `data/` yet, the backend keeps using them and says so in `backend/logs/errors.log`. To move them, stop the backend and move both into a `data` folder in the project folder; nothing else needs to change.

Each user's chunks are filed under a random tenant id from their user record, not under the user's number, because a new database hands the same numbers out again. A store made before this change is re-filed when the backend starts; this is safe to run any number of times and deletes nothing.

Uploaded text and questions are sent to Google's Gemini API. Do not upload confidential documents until you have agreed with your mentor which documents and which API tier are allowed.
