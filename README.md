# Aether AI

A multi-user document question-answering assistant (retrieval-augmented generation). You upload documents, ask questions, and get answers with citations to the passages they came from.

- **Backend** (`backend/`): FastAPI, LangChain, Google Gemini (chat and embeddings), ChromaDB (vectors), SQLite (users, documents, conversations), JWT login.
- **Frontend** (`frontend/`): React 19 + Vite. **This is the real user interface.** There is no other UI; the old page in `backend/static/` has been removed.

Project status and history: [AUDIT_REPORT.md](AUDIT_REPORT.md) lists what was found in the October 2026 audit, [SPRINT_PLAN.md](SPRINT_PLAN.md) is the plan being worked through, and [SDLC_PLAN.md](SDLC_PLAN.md) is an older log kept for history.

## What you need

- **Python 3.12** (from python.org; on Windows the `py` launcher is installed with it)
- **Node.js 20.19+ or 22.12+** (includes `npm`)
- A **Google Gemini API key** for real answers (tests do not need one)

## Setup on Windows (once)

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

Frontend checks:

```bat
cd frontend
npm run lint
npm run build
```

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

## Where data is kept

All of these are created on first run and are ignored by git:

| Path | Contents |
|---|---|
| `backend/.env` | Your API key and JWT secret |
| `backend/aether.db` | Users, uploaded-document records, conversations |
| `backend/vector_store/` | Document chunks and their embeddings |
| `backend/logs/` | Request, upload and error logs |

Uploaded text and questions are sent to Google's Gemini API. Do not upload confidential documents until you have agreed with your mentor which documents and which API tier are allowed.
