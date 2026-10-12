# Demo checklist — Aether AI on the office network

One page to follow before and during a demonstration. It replaces a rehearsal that only you can do (Sprint 7, item 6). Every setting below goes in `backend\.env` unless it says otherwise; restart the backend after changing it.

## The day before

1. **A billed Gemini key.** The free tier allowed 20 requests a day when the error log was read (audit finding B10), and one question costs two or three model calls plus one embedding. Put the billed key in `backend\.env` as `GOOGLE_API_KEY=` and check its quota page in Google AI Studio. `[OWNER: which key and tier Netweb provides]`
2. **Close the two open doors** (README, "Running it where other people can reach it"):
   - `AETHER_INVITE_CODE=<a code>`: only people you give the code to can create an account.
   - `AETHER_ENVIRONMENT=production`: turns off `/docs`, `/redoc` and `/openapi.json`.
   - Leave `AETHER_COOKIE_SECURE` off unless the app is served over HTTPS; on plain HTTP it would stop a reload from keeping anyone signed in.
3. **Build the app once** and run one server: `cd frontend`, `npm run build`, then start only the backend; the app is at http://localhost:8000/.
4. **Check the documents you may show.** Upload only documents your mentor has approved for this API tier. `[OWNER: the documents allowed, agreed with the mentor (item 5)]`
5. **Run the checks**, so a failure is found the day before, not in the room: `npm run e2e` in `frontend\` (the whole journey with fake models, about 20 seconds) and `python -m pytest` in `backend\`.

## On the office network, before the audience arrives

The office network may intercept HTTPS with its own certificate. In July 2026 `backend\logs\errors.log` recorded `CERTIFICATE_VERIFY_FAILED ... self-signed certificate in certificate chain` (finding B10): the backend could not reach Gemini at all.

1. Start the backend, sign in, and upload a small text file. If it reaches **Ready**, Gemini is reachable: skip to the next section.
2. If the upload fails and `errors.log` shows `CERTIFICATE_VERIFY_FAILED`, add the organisation's root certificate. **Never turn certificate checking off.**
   1. Ask IT for the organisation's root CA certificate as a Base-64 (PEM) `.cer` file, or export it from Windows: `certmgr.msc`, Trusted Root Certification Authorities, the organisation's certificate, All Tasks, Export, "Base-64 encoded X.509". `[OWNER: the certificate's name, from IT]`
   2. Make one bundle of the usual certificates plus that one (Command Prompt, in the project folder):
      ```bat
      .venv\Scripts\python -c "import certifi; print(certifi.where())"
      copy /b "<the path it printed>" + "C:\certs\org-root.cer" "C:\certs\aether-ca-bundle.pem"
      ```
   3. In the backend's window, before starting it: `set SSL_CERT_FILE=C:\certs\aether-ca-bundle.pem`. The Gemini client reads this variable (it is not a `backend\.env` setting). `setx SSL_CERT_FILE C:\certs\aether-ca-bundle.pem` makes it permanent for new windows.
   4. Start the backend again and repeat step 1.
3. Ask one real question and note how long the answer takes. The first real run took about 23 seconds per answer (SPRINT_PLAN.md, Sprints 0 and 1); quota or availability errors now give one clear message after a short retry (Sprint 5).

## What to show

Use the approved documents. `[OWNER: the questions, written for those documents]` A good order:

1. **A plain factual question** whose answer is on a known page. Point at the source card: file, page, similarity, the passage.
2. **A follow-up** that only makes sense after the first ("and who does that?"). It is understood because the conversation is remembered.
3. **A question the documents cannot answer.** The answer is a refusal with no sources, not an invention. (The refusal threshold is still uncalibrated, 0.3: an unrelated question may get an answer marked "Uncertain". Say so if asked.)
4. **Hybrid mode** on a question with an exact code or name in it.
5. **Agent mode**: a date or arithmetic question about the document ("how many days from the last inspection to today?"). The "Tools used" row shows what ran.
6. **Reload the page**: still signed in, the conversation and its sources are back; open an older thread from the rail.
7. **Stop** a long answer: the question goes back into the box, nothing is saved.
8. **Rate an answer**, and open Settings to show the library and the version.

## If the network fails

1. Play the recorded walkthrough. `[OWNER: record it on the office network with the billed key, and keep it on the laptop]`
2. Show the interface working offline with fake models (no key, no network, no real data): in `backend\`, `..\.venv\Scripts\python tests\e2e_server.py --answer-from chunks`, then open http://127.0.0.1:8765/. Say that the answers are from a test model: they quote the passage they were given.
3. Show the evidence instead of the live answer: `npm run e2e` (the journey and its accessibility check in a real browser), the test suite, `SPRINT_PLAN.md` (what was proved, sprint by sprint) and the two audit reports.
