# Aether AI — the web app

The interface of Aether AI: React 19 and Vite, in TypeScript, styled with the Prism design
language (`../DESIGN.md`). It talks only to the backend's API under `/api/v1`; setting up and
running the whole project is in the root `README.md`.

## Pages

| Path | What it shows |
|---|---|
| `/` | The start page |
| `/login` | The start page with the sign-in sheet open |
| `/chat` | The most recent conversation, or a new one |
| `/chat/:threadId` | One conversation (the thread id is its `session_id`) |
| `/settings` | The workspace with the settings sheet open |

## Where things are

| Folder | What is in it |
|---|---|
| `src/services/` | `api.ts`, the one client for the backend, and its request wrapper; `api-schema.ts`, the API types generated from `../backend/tests/openapi_snapshot.json` (do not edit it by hand); the sign-in state |
| `src/components/` | The pages and their parts: the start page, the workspace (rail, conversation, composer), settings |
| `src/design/` | Prism: tokens, components (`prism.tsx`), the self-playing demo, and the design lab (`/design-lab.html` in development) |
| `e2e/` | The browser journey (Playwright), with its accessibility checks |

## Commands

Run them here, in `frontend/`.

| Command | What it does |
|---|---|
| `npm ci` | Install the exact versions in `package-lock.json` |
| `npm run dev` | The development server on http://localhost:5173, passing `/api/v1` to the backend on port 8000 |
| `npm run api-types` | Regenerate `src/services/api-schema.ts` after the backend's schema snapshot changed |
| `npm run lint` | oxlint |
| `npm run typecheck` | TypeScript, for the app, its tests and the journey |
| `npm test` | The unit and component tests (Vitest) |
| `npm run build` | Type check, then build into `dist/`, which the backend serves at `/` |
| `npm run e2e` | Build, then walk the whole app in Chromium against a backend with fake models (once before: `npx playwright install chromium`) |

## Credits

Built by Tirth Ganatra during an internship at Netweb Software, Vadodara.
