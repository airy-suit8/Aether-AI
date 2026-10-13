// The browser journey (e2e/): `npm run e2e` builds the app, then Playwright starts the backend
// with fake models on temp stores (backend/tests/e2e_server.py), serving that build, and walks
// through it in Chromium. Works on Windows from a folder whose path has spaces: every path is
// quoted, and no Unix shell is needed.
import { defineConfig, devices } from '@playwright/test'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const backend = path.join(here, '..', 'backend')
const PORT = 8765

/** The Python to run the backend with: AETHER_PYTHON if set, else a virtual environment at the
 *  project root or in backend/ (as the README sets one up), else python on the PATH (CI). */
function python() {
  if (process.env.AETHER_PYTHON) return process.env.AETHER_PYTHON
  const inVenv = process.platform === 'win32' ? ['Scripts', 'python.exe'] : ['bin', 'python']
  const found = [path.join(here, '..', '.venv', ...inVenv), path.join(backend, '.venv', ...inVenv)].find(existsSync)
  return found ?? 'python'
}

export default defineConfig({
  testDir: 'e2e',
  // One journey, one backend: the steps depend on each other
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  retries: 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } } }],
  webServer: {
    command: `"${python()}" "${path.join(backend, 'tests', 'e2e_server.py')}" --port ${PORT}`,
    cwd: backend,
    url: `http://127.0.0.1:${PORT}/api/v1/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
})
