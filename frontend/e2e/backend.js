// Where the journey's backend is and what runs it, for playwright.config.js and the check that
// runs after the journey (check-feedback-export.js). Plain JavaScript: it needs Node.js, whose
// types the project does not install.
import { existsSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
export const backend = path.join(here, '..', '..', 'backend')

/** The journey backend's stores: emptied when it starts, read by the check after the journey. */
export const journeyData = path.join(os.tmpdir(), 'aether-e2e-journey')

/** The Python to run the backend with: AETHER_PYTHON if set, else a virtual environment at the
 *  project root or in backend/ (as the README sets one up), else python on the PATH (CI). */
export function python() {
  if (process.env.AETHER_PYTHON) return process.env.AETHER_PYTHON
  const inVenv = process.platform === 'win32' ? ['Scripts', 'python.exe'] : ['bin', 'python']
  const found = [path.join(backend, '..', '.venv', ...inVenv), path.join(backend, '.venv', ...inVenv)].find(existsSync)
  return found ?? 'python'
}
