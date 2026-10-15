# Threats

Who could misuse Aether AI, what each of them can reach, the worst they could realistically do,
and what stops them. Known gaps are listed as gaps: an admitted gap beats a hidden one. It answers
the whiteboard question "what happens if this actor behaves maliciously?". The reasons behind
each control are in [DECISIONS.md](DECISIONS.md) (D-numbers); the paths in [FLOW.md](FLOW.md).

Written on 15 Oct 2026 from the code, the tests named below, `project_report.md` chapter 6 and
`AUDIT_REPORT_2.md`, and updated for the four branches waiting to be merged (marked **[new]**).

## What is protected

- Each user's documents, their passages and vectors, their kept PDFs **[new]**, conversations and ratings.
- The accounts, and the sessions signed in with them.
- The model keys (`GOOGLE_API_KEY`, `OPENAI_API_KEY` **[new]**) and the quota they pay for.
- The server's processor, memory and disk.

**Trusted:** the computer the server runs on and whoever runs it. Everything under `data/` (the
database, the vector store, the kept PDFs, the reranking model) is stored unencrypted.

## Entry points

| Entry point | Who reaches it |
|---|---|
| `POST /auth/register`, `/auth/login`, `/auth/refresh`, `GET /health`, `GET /shared/{token}` | anyone who can reach the server |
| every other `/api/v1/` route | a signed-in user, for their own data |
| an uploaded file | its uploader; its text then reaches the model, and a PDF reaches pdfium **[new]** and pdf.js **[new]** |
| the model's answer | everyone who reads the conversation, including through a share link |
| the downloads the app makes: the reranking model from Hugging Face **[new]**; answers from Gemini, Ollama or an OpenAI-compatible service **[new]** | set by the owner in `backend/.env`, never by a user |

---

## 1. Someone on the network without an account

| They try | What stops them | Evidence |
|---|---|---|
| Create an account | `AETHER_INVITE_CODE`: once set, registration needs the code (empty by default, D-035) | `tests/integration/test_sign_in.py::test_registration_needs_the_invite_code_once_one_is_set` |
| Guess passwords | 10 sign-ins a minute per address; bcrypt hashes | `tests/integration/test_api_routes.py::test_every_api_route_has_a_limit` |
| Find out which names have accounts | A sign-in for an unknown name still checks a password, so it takes as long | `test_sign_in.py::test_a_login_for_an_unknown_name_still_checks_a_password` |
| Read a shared conversation | Only with its link: 192 random bits, never logged, withdrawable; it shows the turns and their cited passages, nothing of whose they are, and no page viewer **[new]** (D-045) | `tests/integration/test_sharing.py` |
| Read the API's pages to map the server | Off with `AETHER_ENVIRONMENT=production` | `tests/integration/test_exposure.py` |
| Learn about the server from errors | A server error gives a reference, never a traceback or a path | `test_exposure.py` |

**Gap:** both `AETHER_INVITE_CODE` and `AETHER_ENVIRONMENT=production` must be set before anyone
else can reach the server; their defaults keep the owner's own setup working.

## 2. A signed-in user who is malicious

| They try | What stops them | Evidence |
|---|---|---|
| Read, search or delete another user's documents, passages or conversations | Every query is filtered by the tenant id from the verified token; another user's id is a 404 (D-028) | `tests/integration/test_tenant_isolation.py`, `test_tenants.py` |
| Download another user's PDF, or its passages, by changing the id in `/documents/{id}/file` or `/passages/{n}` **[new]** | `get_document(user_id, id)` checks ownership first: 404 | `tests/integration/test_document_files.py::test_only_its_owner_gets_the_file_or_its_passages` |
| Make a kept PDF land outside its folder with a crafted file name **[new]** | The path is built from the tenant id and the integer document id only, never the uploaded name (D-059) | `pipeline/documents.py` (`original_path`) |
| Keep using a stolen session | The access token lasts 30 minutes; the refresh token is in an httpOnly, `SameSite=Strict` cookie sent only to `/api/v1/auth`, recorded on the server, and revoked by signing out, or everywhere (D-029, D-042) | `test_sign_in.py` |
| Run up the model bill or slow everyone down | 30 questions a minute, 10 uploads a minute, 120 requests a minute on any other route, per user (D-030) | `test_api_routes.py` |
| Fill the disk or the memory | Uploads streamed with a 50 MB cap, checked before reading; caps on unpacked size, rows, passages and documents per user (D-031) | `tests/integration/test_upload_limits.py` |
| Tie up the processor with scans **[new]** | At most 100 pages read by OCR per file, and 200 per user in any hour, both checked before any page is read; each page is a turn of its own, so another user's scan is read between its pages (D-065, D-073); uploads limited as above | `tests/unit/test_ocr.py::test_a_file_with_too_many_pictures_is_refused_before_any_is_read`, `::test_each_user_has_their_own_hour_of_pages`, `::test_a_short_scan_is_read_between_the_pages_of_a_long_one`, `::test_an_upload_past_its_owner_s_hour_fails_and_another_user_s_does_not` |
| Make the agent reach the network or the disk | Its only tools are the document search, the calculator and the date tool | `agents/tools.py`; `tests/unit/test_calculator.py` |
| Have the calculator burn the processor (`9**9**9`) | Powers are capped and refused in under a second | `test_calculator.py` |

**Gaps:**
- **Several accounts still mean several hours' worth of OCR.** Signing up is open, and the hourly
  count is kept in memory, so it starts again when the server restarts (D-073). Other users' scans
  take turns with theirs rather than waiting behind them, but each one finishes later.
- **Rate-limit counts start again** when the server restarts (N9).

## 3. A malicious document

Anyone who can get a file into a user's library, including the user themself.

| It tries | What stops it | Evidence |
|---|---|---|
| Tell the model to ignore its rules ("prompt injection") | Passages are fenced in `<document>` tags they cannot close; file names are escaped; the prompts say documents are data; matches are logged (D-033). The model can still be misled: this lowers the risk, it does not remove it | `tests/integration/test_injection_and_names.py` |
| Have the answer carry data away through an image address, or run a script | Answers are Markdown with no images and no raw HTML; links open in a new tab with `noopener noreferrer`; the content-security policy allows no remote script, style or image | `ChatLayout.test.tsx`; `test_exposure.py::test_the_policy_allows_no_remote_script_style_or_image` |
| A zip bomb in a Word or Excel file | The unpacked size is capped at 200 MB | `test_upload_limits.py` |
| A crafted PDF attacking the readers **[new]** | pypdf is pure Python. pdfium (native code) reads only pages with no text, for OCR, and it ships in a pinned pypdfium2. pdf.js 6.3.289 runs in the owner's own browser, and the policy forbids `eval`, which the last serious pdf.js flaw (CVE-2024-4367, fixed in 4.2.67) needed. A user is only ever shown their own PDFs; shared pages have no viewer | `services/pdf.ts`; `api/middleware.py` (`CONTENT_SECURITY_POLICY`) |

**Gap:** a crafted PDF could still exploit an unknown flaw in pdfium, which runs inside the server
process. Turning OCR off (`AETHER_OCR=false`) keeps pdfium from reading uploads at all.

## 4. The model

| Risk | What limits it | Evidence |
|---|---|---|
| It invents an answer | Below the similarity threshold the question is refused without asking it (D-023); the prompt says to refuse when the passages do not answer; the answer cites its passages, and the ring shows how close they were | `tests/unit/test_search.py` |
| It takes a cited study's result for the paper's own | The prompt says results cited as [7] belong to the cited work (D-051). **Not solved:** qwen3.5:4b still did it on the owner's paper (D-054) | SPRINT_PLAN.md, "Reranking and confidence lines" |
| It loops on tool calls and bills without end | The agent stops at 12 steps (D-026) | `tests/integration/test_agent.py` |

## 5. The services and downloads the app depends on

| Risk | What limits it | Evidence |
|---|---|---|
| Documents and questions leave the machine | With Ollama for both models, nothing does (D-046). With Gemini or an OpenAI-compatible cloud service **[new]**, the passages and the question are sent to it | README, "Models on your own computer" |
| A key leaks | Keys live only in `backend/.env`, which git ignores; the test suite blanks both keys; no log line reads them | `.gitignore`; `tests/conftest.py` |
| A user points the app at an address of their choosing (SSRF) | No user input chooses an address: `AETHER_OPENAI_URL` and `AETHER_OLLAMA_URL` are the owner's settings **[new]** | `core/config.py` |
| A swapped reranking model | Pinned: one commit of its repository, and each of its five files checked against its sha256 before it is loaded; a file that differs is refused and the search's own order answers (D-072, D-055). It runs in onnxruntime as data, not code | `tests/unit/test_reranker.py::test_a_file_that_is_not_the_one_pinned_is_refused_and_the_search_order_used` |
| A vulnerable package | Versions pinned; `pip-audit` (15 Oct 2026: only chromadb 1.5.9, in its HTTP server, which this app never runs) and `npm audit` (0) | `backend/requirements.txt`, `frontend/package-lock.json` |

**Gaps:**
- **Which documents may go to a cloud model, on which tier,** is not yet agreed with the mentor (S11).
- **A reranking model named in `AETHER_RERANK_MODEL` that is not pinned** is still fetched by
  name, as fastembed finds it. The default model is pinned (D-072).

## 6. Someone with the computer, or on the network path

| Risk | Status |
|---|---|
| Reading `data/` (documents, conversations, kept PDFs) | **Gap:** stored unencrypted; protected only by the computer's own accounts |
| Reading tokens and passwords on the office network | **Gap:** plain HTTP. Serve over HTTPS and set `AETHER_COOKIE_SECURE=true` (`docs/demo-checklist.md`) |
| Reading `backend/.env` | **Gap:** a plain file; protected only by the computer's own accounts |

---

## Keeping this file true

Add a row when a change opens an entry point (a route, an upload type, a download, a setting that
names an address), or changes who can reach one. Move a gap to a control only with the test that
proves it, and say which in its evidence column.
