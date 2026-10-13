// The browser journey (e2e/): `npm run e2e` builds the app, then Playwright starts the backend
// with fake models on stores of its own (backend/tests/e2e_server.py), serving that build, and
// walks through it in Chromium; afterwards e2e/check-feedback-export.js reads that backend's
// feedback export. Works on Windows from a folder whose path has spaces: every path is quoted,
// and no Unix shell is needed.
import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'
import { backend, journeyData, python } from './e2e/backend.js'

const PORT = 8765

export default defineConfig({
  testDir: 'e2e',
  globalTeardown: './e2e/check-feedback-export.js',
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
    command: `"${python()}" "${path.join(backend, 'tests', 'e2e_server.py')}" --port ${PORT} --data-dir "${journeyData}"`,
    cwd: backend,
    url: `http://127.0.0.1:${PORT}/api/v1/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
})
