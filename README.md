# Aether AI

[![CI](https://github.com/airy-suit8/Aether-AI/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/airy-suit8/Aether-AI/actions/workflows/ci.yml?query=branch%3Amain)

Ask questions about your own documents and get answers that cite the exact passages they came from. Aether AI is a multi-user retrieval-augmented generation (RAG) app: a FastAPI backend with LangChain, ChromaDB and SQLite, and a React + TypeScript web app.

## What it does

- **Answers with citations.** Each statement in an answer is tied to a numbered source. Click one to see the passage on its PDF page, marked, or among its neighbours in any other file.
- **Reads PDF, Word, text, CSV and Excel files**, scanned PDFs included: pages that are pictures are read by OCR on your own computer.
- **Asks about one document or several.** Pick them in *Search in*, or name them in the question ("the 13003 pdf", "the paper by Hardik Kumar").
- **Finds the right passage.** A search by meaning, then a reranking model on your computer that keeps the passages that answer best, with the passages either side of the best hits and the section of the paper each one is in.
- **Says how sure it is.** Each answer is marked *Grounded*, *Uncertain* or *Not in your documents*, and a question the documents cannot answer is refused instead of guessed.
- **Two answer modes.** *Default* answers from your documents; *Agent* can also calculate and work with dates, and shows each step it took.
- **Models of your choice.** Google Gemini, models on your own computer through Ollama (then nothing leaves the machine), or any service that speaks OpenAI's API.
- **Separate accounts.** Each user's documents, searches and conversations are kept apart, and tests check it.
- **Conversations you can keep and share.** Threads, ratings, the cost of each answer, and a read-only link to a conversation.

## Contents

- [Quick start (Windows)](#quick-start-windows)
- [Using the app](#using-the-app)
- [Choosing the models](#choosing-the-models)
- [Running it for other people](#running-it-for-other-people)
- [Where data is kept](#where-data-is-kept)
- [For developers](#for-developers)
- [Project documents](#project-documents)

## Quick start (Windows)

### What you need

- **Python 3.12** (from python.org; on Windows the `py` launcher comes with it)
- **Node.js 24.15 or later** (22.22 or later also works); `npm` comes with it
- A **Google Gemini API key**, or **Ollama** to run the models on your own computer (see [Models on your own computer](#models-on-your-own-computer-ollama)). The tests need neither.

**Keep the project in a short folder path**, such as `C:\Projects\Aether-AI`. Windows limits a path to 260 characters unless long paths are turned on, and `npm ci` and `pip install` create deeply nested folders; in a long path they fail with "file not found" or "path too long". Spaces in the path are fine.

### Install (once)

In **Command Prompt**, from the project folder (the one with this README):

1. The backend, in a virtual environment in the project folder:

   ```bat
   py -3.12 -m venv .venv
   .venv\Scripts\python -m pip install --upgrade pip
   .venv\Scripts\python -m pip install -r backend\requirements-dev.txt
   ```

2. The frontend:

   ```bat
   cd frontend
   npm ci
   cd ..
   ```

3. Your settings file:

   ```bat
   copy backend\.env.example backend\.env
   .venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(64))"
   ```

   Open `backend\.env`. Put your Gemini key after `GOOGLE_API_KEY=` (or set up Ollama instead), and paste the long random string printed above after `JWT_SECRET=`: the backend refuses to start without it. Never commit `backend\.env`.

### Run

Double-click `start.bat`. It opens two windows, the backend on port 8000 and the frontend on port 5173. Open **http://localhost:5173**, register, upload a document and ask a question about it. To stop, close the two windows ("Aether AI backend" and "Aether AI frontend").

Before starting them, `start.bat`:

- installs the packages again when their lists have changed since the last install (`frontend\package-lock.json` with `npm ci`, `backend\requirements.txt` with pip into `.venv`), so after a `git pull` running it is enough; close the two windows first, since a running server keeps its files in use. `start.bat --packages-only` installs what changed and starts nothing;
- starts Ollama and waits for it, when your settings use Ollama and it is not running.

<details>
<summary>Starting the two parts by hand, or as one server</summary>

Two Command Prompt windows:

```bat
REM window 1: backend
cd backend
..\.venv\Scripts\python -m uvicorn main:app --port 8000

REM window 2: frontend
cd frontend
npm run dev
```

Or one server: the backend also serves the built web app at **http://localhost:8000/** (the API stays under `/api/v1/`). Build it, then start only the backend; build again after changing frontend code.

```bat
cd frontend
npm run build
cd ..\backend
..\.venv\Scripts\python -m uvicorn main:app --port 8000
```

</details>

## Using the app

### Asking a question

Type a question in the box at the foot of the page. The answer appears as it is written; **Stop** ends it, and nothing of a stopped or failed answer is saved: the question goes back into the box, with **Retry**.

- **Default** searches your documents and writes the answer from the passages it found, citing them as [1], [2].
- **Agent** can also use a calculator and a date tool, and chain them with the document search ("find the paper's best accuracy, then subtract it from 100"). It is slower, needs a model that can use tools, and lists each step above its answer.

Under each answer, its sources, and how well the passages matched the question:

| Label | Meaning |
|---|---|
| *Grounded* | The passages found match the question well: their average similarity is at or above the line for the embedding model in use (0.5 for `nomic-embed-text`, 0.6 for Gemini's; `AETHER_GROUNDED_AT` sets your own). |
| *Uncertain* | They match less well; check the sources. |
| *Not in your documents* | A refusal: no passage was close enough to send to the model (`AETHER_CONFIDENCE_THRESHOLD`, 0.3), or the model found that the passages do not answer the question. |

The model is told to answer only from the passages, to say when they do not answer the question, and to treat a figure in a paper's introduction or literature review as another study's, not the paper's own.

### Asking about particular documents

A question searches every document in your library unless you say otherwise:

- **Search in**, beside the answer mode (shown once you have two documents): *All documents*, every file of one kind (*Every PDF*, *Every Word file*), or the documents you tick. Documents are listed by their title, read from their first page. The choice holds for the questions that follow.
- **Name it in the question**: by the first words of its title, when the question calls it a document or asks who wrote it ("Who are the authors of Classification of…?"); by an author on its first page ("the paper by Hardik Kumar"); by the number or two words of its file name ("the 13003 pdf", "the Recos letter"); or by its kind ("in the PDF"). A question about a subject is not narrowed because a title shares its words.

Under an answer that did not search everything, a line says what it searched and why, so a wrong guess shows. A question about a document's title, authors, affiliations, e-mail addresses or ORCID ids reads each document's first passage, where a paper names its own authors (not its reference list); one about "both" or "each" document reads each one's best passages.

### Seeing a source in its document

Click a source card to pin it open, then **Show on p. 20** (a PDF) or **Show in the document** (any other file). A PDF opens on the cited page, drawn in the browser, with the passage marked on it; *Open the whole PDF* opens it in the browser's own viewer at that page. A Word, text or spreadsheet passage is shown with the passages either side of it.

PDFs are kept as uploaded, in `data\files\`, so their pages can be shown; a document's file goes when the document does. A PDF added before 15 Oct 2026 was not kept: upload the same file again and it is kept, without being read twice.

### Scanned PDFs

A PDF page with no text (a scan, a photo of a page) is read by OCR on this computer's processor, with the models that come with RapidOCR: nothing is downloaded and nothing leaves the machine. It takes 1 to 2 seconds a page.

- A file with more than 100 such pages is refused (`AETHER_OCR_MAX_PAGES`), and each user may have 200 pages read in any hour (`AETHER_OCR_PAGES_PER_HOUR`; the count starts again when the server restarts).
- When two people's scans are read at once their pages take turns, so a short scan is not stuck behind a long one.
- OCR reads the words, not the layout: tables and two-column pages come out line by line, and a scanned page cannot have its passage marked in the page viewer.
- `AETHER_OCR=false` turns it off; a scan is then refused.

### Conversations and sharing

Every question and answer is saved with its sources. Each conversation has its own address (`/chat/<id>`); the rail lists them, newest first, and each can be renamed in place or deleted with two clicks. *New thread* starts a new one and keeps the old.

**Share** in the top bar makes a link to the open conversation (`/shared/<token>`). Anyone with the link can read it and the passages it cites, without signing in; they cannot ask questions and see nothing else of yours, not even whose it is. Questions you ask later appear on it too. **Stop sharing**, or deleting the conversation, withdraws the link at once. The link is the only key, so treat it like the conversation itself; it is never written to the logs.

### What an answer cost

Under each answer a quiet line says how long it took and how many tokens the model reported ("4.2 s, 1,240 tokens"); opening it lists each stage. The same numbers are written to `backend\logs\requests.log`. They are not priced: prices change, and the app does not know your tier.

### Signing in

Passwords are 8 characters to 72 bytes. Usernames use A to Z, digits, hyphens and underscores, and their case does not matter. A sign-in lasts 30 minutes and renews itself while the app is open, through a cookie page scripts cannot read, so a reload keeps you signed in; a week without use signs you out. *Sign out* revokes that browser's sign-in; Settings, *Sign out everywhere*, revokes them all.

## Choosing the models

The app needs two models: one that writes answers and one that turns text into vectors for the search (embeddings). By default both are Google Gemini's; either can run elsewhere.

### Models on your own computer (Ollama)

With [Ollama](https://ollama.com) there is no API key and no usage limit, and with both models local your documents never leave the machine. Answers take longer than with Gemini on most computers; how long depends on the graphics card.

1. Install Ollama, then download the two default models:

   ```bat
   ollama pull qwen3.5:4b
   ollama pull nomic-embed-text
   ```

   `qwen3.5:4b` (3.4 GB; Ollama 0.40 or later) writes the answers and can use tools, which Agent mode needs; the app turns its thinking off (`AETHER_OLLAMA_THINK=false`), which made answers several times slower. On an older Ollama, `qwen2.5:7b` (4.7 GB) works too. `nomic-embed-text` (0.3 GB) makes the vectors.

2. Add two lines to `backend\.env`:

   ```
   AETHER_LLM_PROVIDER=ollama
   AETHER_EMBEDDING_PROVIDER=ollama
   ```

   `GOOGLE_API_KEY` can then stay empty. Another model: `AETHER_LLM_MODEL=` or `AETHER_EMBEDDING_MODEL=` with its Ollama name. Either line also works alone: a local chat model with Gemini's embeddings keeps your documents as they are, but still needs the key.

3. If you already have documents and changed the embedding model, read them again once, with the backend stopped:

   ```bat
   cd backend
   ..\.venv\Scripts\python -m src.reembed
   ..\.venv\Scripts\python -m src.reembed --apply
   ```

   Vectors from two embedding models cannot be compared, so until this has run the app does not search or add documents, and says why. The first command only reports; `--apply` embeds every stored passage again, keeping its text and place, so nothing is uploaded again. If it stops part-way, the store is left as it was. Going back to Gemini needs the same step.

If Ollama is not running, a question is answered with "Ollama is not running" (`start.bat` starts it for you); a model that is not installed is named with the command that installs it.

### Any OpenAI-compatible service

The models can also come from any service that speaks OpenAI's API. In `backend\.env`:

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

There is no default model: set `AETHER_LLM_MODEL` (and `AETHER_EMBEDDING_MODEL` with `AETHER_EMBEDDING_PROVIDER=openai`). A service that makes no embeddings can still answer while Gemini or Ollama keeps the search. For a model that thinks before it answers, such as `qwen3.5:4b` through Ollama's or LM Studio's address, add `AETHER_OPENAI_REASONING_EFFORT=none`: a three-word answer took 6 tokens with it and 2,973 without. If the service cannot be reached, refuses the key or lacks the model, the answer says which. Tried here: Ollama's `/v1` address; the others are the services' own addresses and were not tried.

### Reranking

Each search finds 20 passages; then a small model on this computer, `Xenova/ms-marco-MiniLM-L-6-v2` (88 MB), reads the question with each and keeps the five that answer it best. The search compares meanings; the reranker judges answers, so a paper's own result is put ahead of a cited study's that uses the same words.

It is downloaded from Hugging Face once, into `data\models\`, then works offline in about half a second a question. Its files are pinned to one version and checked against their checksums before use, so a change on Hugging Face cannot swap them. If it cannot be loaded, answers use the search's own order and `backend\logs\errors.log` says why. `AETHER_RERANK_MODEL=` (empty) turns it off; `AETHER_RERANK_CANDIDATES` changes how many passages it reads.

## Running it for other people

Before anyone else can open the app (an office network, a shared machine), add to `backend\.env`:

```
AETHER_ENVIRONMENT=production
AETHER_INVITE_CODE=<a code you give to the people who may register>
```

`production` turns off the API pages (`/docs`, `/redoc`, `/openapi.json`). With an invite code, signing up needs it; empty (the default), anyone who can open the page can register. Add `AETHER_COOKIE_SECURE=true` once the app is served over HTTPS.

- **Uploads** are accepted at once and read in the background; the library shows *Reading* until the passages are stored, then how many there are, or why the file could not be read. A file may be up to 50 MB, and is refused as soon as it passes that; a Word or Excel file may unpack to 200 MB, a CSV or workbook may have 100,000 rows, a document may make 5,000 passages, and each user may keep 100 documents. Each refusal says which limit was reached.
- **Rate limits.** Every route has one, per signed-in user (or per address without a sign-in): sign-up, sign-in, upload and chat their own, everything else 120 requests a minute. The counts start again when the server restarts.
- **Errors.** When something fails on the server the app shows a short message with a reference, such as `Reference: 3f2a9c81d0b4`; the same reference is on the matching line of `backend\logs\errors.log`, with the full error, and in every response's `X-Request-ID` header. The logs hold one JSON object per line and never the text of a question or a password.
- **Gemini's limits.** A call refused for quota or availability is tried three times in all, waiting 2 then 4 seconds, and then the app says the service is busy. A free-tier key allows only a few questions a day; for a demo, use a billed key. On a network that inspects HTTPS, add the organisation's root certificate to the machine's trust store rather than turning certificate checks off.

Every setting, with its default, is listed in [`backend/.env.example`](backend/.env.example).

## Where data is kept

All of these are created on first run, and git ignores them:

| Path | Contents |
|---|---|
| `backend/.env` | Your API key and JWT secret |
| `data/aether.db` | Users, document records, conversations (`AETHER_DB_PATH`) |
| `data/vector_store/` | The passages of every document and their vectors (`AETHER_VECTOR_STORE_DIR`) |
| `data/files/` | Uploaded PDFs, kept to show their pages (`AETHER_FILES_DIR`) |
| `data/models/` | The reranking model (`AETHER_MODEL_DIR`) |
| `backend/logs/` | Request, sign-in, upload and error logs (`AETHER_LOG_DIR`) |

If a database and a vector store made before Sprint 5 are still in `backend/` and nothing is in `data/` yet, the backend keeps using them and says so in `backend/logs/errors.log`. To move them, stop the backend and move both into `data/`.

Each user's passages are filed under a random tenant id, not the user's number, because a new database hands the same numbers out again.

**Housekeeping.** With the backend stopped, `..\.venv\Scripts\python -m src.maintenance` (from `backend`) lists the passages no document accounts for and the documents marked ready that have none. It deletes nothing; `--apply` deletes exactly what it listed.

**Where your text goes.** With Ollama for both models, nothing leaves the machine. With Gemini or an OpenAI-compatible cloud service, uploaded text and questions are sent to that service. Do not upload confidential documents until you have agreed with your mentor which documents and which service are allowed.

Agreed with the mentor: [OWNER: which documents may be uploaded, on which API tier, and the date agreed (finding S11)]

## For developers

### Run the tests

```bat
cd backend
..\.venv\Scripts\python -m pytest
..\.venv\Scripts\python -m pytest --cov
```

The tests use a fake embedding model, a fake chat model, a temporary database and a temporary vector store: they need no API key, call no model service, and never touch `data\`.

`backend\tests\openapi_snapshot.json` is the API contract. After changing a route or a request or response model on purpose, refresh it, review the diff, and regenerate the web app's API types from it (a renamed field then shows up as a type error wherever the app uses it):

```bat
..\.venv\Scripts\python -m pytest tests\test_openapi_snapshot.py --update-openapi-snapshot
cd ..\frontend
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

**The browser journey** walks through the whole app in Chromium: sign up, upload, ask, reload, a second thread, a rating, removing the document and signing out, with an accessibility check (axe) at desktop and phone width. It builds the app and starts its own backend with fake models on temporary stores, so it needs no key and touches none of your data. Install its browser once, then run it:

```bat
cd frontend
npx playwright install chromium
npm run e2e
```

It uses the Python in `.venv` (or `AETHER_PYTHON`), on port 8765.

The same checks run on GitHub for every push and pull request ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)); they need no secrets.

### macOS and Linux

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
(cd frontend && npm ci)
cp backend/.env.example backend/.env    # then fill in GOOGLE_API_KEY and JWT_SECRET
(cd backend && ../.venv/bin/python -m uvicorn main:app --port 8000) &
(cd frontend && npm run dev)
```

### How the backend is laid out

`backend/main.py` builds the app (`create_app()`); its startup sets up the logs and the database tables. Everything else is under `backend/src/`:

| Package | What it holds |
|---|---|
| `core/` | `config.py` (every setting; the only code that reads the environment or `.env`), `security.py` (passwords and sign-in tokens), `logging.py` |
| `api/` | `schemas.py` (request and response models), `deps.py` (the current user, the rate limiter), `middleware.py` (request id, security headers), `errors.py`, and one router per resource: `routes_auth`, `routes_chat`, `routes_documents`, `routes_health` |
| `db/` | `database.py`: SQLite for users, document records and conversations |
| `ingestion/` | `loader.py` reads PDF, Word, text, CSV and Excel files; `ocr.py` reads the pages that are pictures |
| `chunking/` | `chunker.py`: overlapping passages |
| `embeddings/`, `llm/` | the factories for the embedding model and the chat model (Gemini, Ollama or OpenAI-compatible) |
| `vectordb/` | `vector_store.py`: ChromaDB on disk |
| `retrieval/` | `retriever.py` (dense, BM25 and hybrid search, the follow-up rewrite), `reranker.py`, `scope.py` (which documents a question searches), `sections.py` (the section of its paper each passage is in) |
| `prompts/` | `prompt_templates.py`: every prompt, once |
| `memory/` | `conversation.py`: each conversation's history |
| `pipeline/` | `rag.py`: the one question-answering pipeline (modes `default` and `agent` in the app; `hybrid` and `langchain` through the API); `documents.py`: upload, list, delete |
| `agents/` | `agent.py` and `tools.py`: the agent, the calculator and the date tool |
| `evaluation/` | `evaluate.py` measures the pipeline on labelled questions; `export_feedback.py` turns answers rated "not helpful" into questions to label |
| `maintenance.py`, `reembed.py`, `ollama_ready.py` | housekeeping and re-embedding (both above), and the check `start.bat` runs to see whether Ollama answers |

Code imports by absolute path from `backend/` (`from src.core.config import settings`), so run every command from `backend`. Every setting has a default in `src/core/config.py` and can be set in `backend\.env` or the environment with the `AETHER_` prefix; the environment wins. The **no-orphan check** (`tests/test_no_orphans.py`, also its own CI step) fails if a module is imported by nothing, a route has no test, anything but `config.py` reads the environment, a model id is written twice, or a setting is missing from `.env.example`.

How a request travels through these files is in [docs/FLOW.md](docs/FLOW.md).

### Measuring answer quality

`python -m src.evaluation.evaluate` asks labelled questions through the real pipeline and reports how well it retrieved and answered. It reads the documents into a temporary store, so your data is not touched, but it does call the models.

1. Put the documents in `backend\src\evaluation\documents\`.
2. Write `backend\src\evaluation\dataset.jsonl`, one question per line, including some the documents cannot answer:

   ```json
   {"id": "q01", "question": "What is the notice period?", "expected_answer": "30 days.", "source": "handbook.pdf", "page": 12}
   {"id": "u01", "question": "What is the boiling point of mercury?", "answerable": false}
   ```

   `page` can be `"pages": [12, 13]`; for a file without pages, give `"contains": "a phrase from the right passage"`.
3. From `backend`:

   ```bat
   ..\.venv\Scripts\python -m src.evaluation.evaluate --label baseline --retrieval-only
   ..\.venv\Scripts\python -m src.evaluation.evaluate --label baseline
   ```

   `--retrieval-only` measures retrieval and the refusal threshold with embedding calls only. The full run also writes every answer and has a second model score it: set `AETHER_JUDGE_MODEL` to a model other than the one that answers. `--pause 6` waits between questions if you hit a rate limit.

Each run is saved as `docs\evaluation\<label>.json`, and `docs\evaluation.md` shows every saved run side by side. To compare two settings, run once with each and a different label; for example `AETHER_ANSWER_FROM=summary` (summarise the passages first, then answer: two model calls) against the default, `chunks` (answer straight from the passages and cite them).

`python -m src.evaluation.export_feedback` writes every answer rated *Not helpful* to `data\feedback_candidates.jsonl`, in the dataset's shape with the expected answer left empty, ready to label.

## Project documents

| Document | What it is |
|---|---|
| [SPRINT_PLAN.md](SPRINT_PLAN.md) | The roadmap; its Status table says what is done and what is next |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Every decision, with the options weighed, the reason, and what was given up |
| [docs/FLOW.md](docs/FLOW.md) | How each request travels between files and functions, and where it can fail |
| [docs/THREAT.md](docs/THREAT.md) | Who could misuse the app, what stops them, and the known gaps |
| [docs/HANDOVER.md](docs/HANDOVER.md) | Where things stand now |
| [DESIGN.md](DESIGN.md) | Prism, the design language every screen uses |
| [project_report.md](project_report.md) | The project report |
| [AUDIT_REPORT.md](AUDIT_REPORT.md), [AUDIT_REPORT_2.md](AUDIT_REPORT_2.md) | The October 2026 audits and their findings |
| [SDLC_PLAN.md](SDLC_PLAN.md) | An older log, kept for history |

## Credits

Built by Tirth Ganatra during an internship at Netweb Software, Vadodara.
