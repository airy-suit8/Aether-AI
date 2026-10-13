// After the journey (Playwright's globalTeardown): the answer it rated "Not helpful" must be in
// the feedback export (Sprint 8, item 5, "done when"). Runs `python -m src.evaluation.export_feedback`
// on the journey backend's own database, which holds only the journey's made-up data.
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { backend, journeyData, python } from './backend.js'

// The question whose answer the journey rates Not helpful (QUESTION in journey.spec.ts)
const RATED_DOWN = 'How often is the Zephyr turbine blade inspection?'

export default function checkFeedbackExport() {
  const output = path.join(journeyData, 'feedback_candidates.jsonl')
  execFileSync(python(), ['-m', 'src.evaluation.export_feedback', '--output', output], {
    cwd: backend,
    env: {
      ...process.env,
      AETHER_DB_PATH: path.join(journeyData, 'aether.db'),
      AETHER_VECTOR_STORE_DIR: path.join(journeyData, 'vector_store'),
      AETHER_LOG_DIR: path.join(journeyData, 'logs'),
      GOOGLE_API_KEY: '',
    },
    stdio: 'pipe',
  })
  const lines = readFileSync(output, 'utf8').split('\n').filter(Boolean).map((line) => JSON.parse(line))
  const found = lines.filter((line) => line.question === RATED_DOWN)
  if (found.length !== 1 || found[0].expected_answer !== '' || !found[0].answer_given) {
    throw new Error(`The feedback export should hold the journey's thumbs-down answer once, to be labelled; it holds: ${JSON.stringify(lines)}`)
  }
  console.log(`Feedback export: the journey's thumbs-down answer is there (${lines.length} line${lines.length === 1 ? '' : 's'}).`)
}
