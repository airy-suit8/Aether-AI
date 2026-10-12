import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Aperture, Cite, ClarityRing, Lens, SourceCard, Threads } from './prism'
import type { ClarityState, FieldState, SourceView } from './prism'
import './demo.css'

/**
 * A self-playing bench: it asks a question, searches, streams an answer and lets the sources
 * disperse into the margin. Sample data only; nothing here talks to the backend.
 * Used on the landing page and in the design lab.
 */

interface Scenario {
  label: string
  question: string
  answer: string
  confidence: number
  state: ClarityState
  sources: SourceView[]
}

type ScenarioKey = 'grounded' | 'uncertain' | 'refused'

const SCENARIOS: Record<ScenarioKey, Scenario> = {
  grounded: {
    label: 'Grounded',
    question: 'What does the maintenance schedule require for the Zephyr turbine?',
    answer:
      'The schedule requires a blade inspection every 90 days [1]. Inspections are carried out by the Orion field team [1] and logged in the Halcyon register [2]. A vibration reading above 4.5 mm/s triggers an unscheduled teardown [3].',
    confidence: 0.82,
    state: 'grounded',
    sources: [
      { source: 'zephyr_manual.pdf', page: 12, score: 0.84, snippet: 'The Zephyr turbine maintenance schedule requires a blade inspection every 90 days. The inspection is carried out by the Orion field team.' },
      { source: 'halcyon_register.xlsx', page: 1, score: 0.77, snippet: 'Inspection HR-2291 · Turbine Zephyr-4 · Team Orion · Logged 14 March · Result pass · Next due 12 June.' },
      { source: 'vibration_limits.docx', page: 4, score: 0.71, snippet: 'Readings above 4.5 mm/s RMS at the main bearing require the unit to be withdrawn from service for an unscheduled teardown.' },
    ],
  },
  uncertain: {
    label: 'Uncertain',
    question: 'Who signs off a teardown?',
    answer: 'The documents suggest the field team lead reviews a teardown with the site engineer [1], but none of them states who signs it off.',
    confidence: 0.47,
    state: 'uncertain',
    sources: [
      { source: 'vibration_limits.docx', page: 5, score: 0.52, snippet: 'Following teardown, the field team lead reviews findings with the site engineer before the unit returns to service.' },
    ],
  },
  refused: {
    label: 'Not found',
    question: 'What is the boiling point of mercury?',
    answer: 'I could not find this in your documents.',
    confidence: 0,
    state: 'refused',
    sources: [],
  },
}

type DemoMode = 'default' | 'hybrid' | 'agent'

const MODES: { value: DemoMode; label: string }[] = [
  { value: 'default', label: 'Default' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'agent', label: 'Agent' },
]

/** Split an answer into words and citation markers, so each can arrive on its own. */
type Token = { kind: 'word'; text: string } | { kind: 'cite'; n: number; first: boolean }

function tokenize(answer: string): Token[] {
  const tokens: Token[] = []
  const seen = new Set<number>()
  for (const part of answer.split(/(\[\d+\])/)) {
    const cite = part.match(/^\[(\d+)\]$/)
    if (cite) {
      const n = Number(cite[1])
      tokens.push({ kind: 'cite', n, first: !seen.has(n) })
      seen.add(n)
    } else {
      // Leading whitespace stays with the word, so text after a citation keeps its space
      for (const word of part.match(/\s*\S+\s*/g) ?? []) tokens.push({ kind: 'word', text: word })
    }
  }
  return tokens
}

type Phase = 'idle' | 'retrieving' | 'streaming' | 'done'

export default function DemoBench({ onPhase }: { onPhase?: (phase: FieldState) => void }) {
  const [mode, setMode] = useState<DemoMode>('default')
  const [scenarioKey, setScenarioKey] = useState<ScenarioKey>('grounded')
  const [question, setQuestion] = useState(SCENARIOS.grounded.question)
  const [phase, setPhase] = useState<Phase>('idle')
  const [shown, setShown] = useState(0)
  const [active, setActive] = useState<number | null>(null)
  const [threadEpoch, setThreadEpoch] = useState(0)

  const benchRef = useRef<HTMLDivElement>(null)
  const answerRef = useRef<HTMLParagraphElement>(null)
  const citeRefs = useRef<Record<number, HTMLButtonElement | null>>({})
  const cardRefs = useRef<Record<number, HTMLButtonElement | null>>({})
  const timers = useRef<number[]>([])

  const scenario = SCENARIOS[scenarioKey]
  const tokens = useMemo(() => tokenize(scenario.answer), [scenario])

  const clearTimers = useCallback(() => {
    timers.current.forEach((id) => {
      clearTimeout(id)
      clearInterval(id)
    })
    timers.current = []
  }, [])

  const play = useCallback((key: ScenarioKey, asked?: string) => {
    clearTimers()
    citeRefs.current = {}
    cardRefs.current = {}
    setScenarioKey(key)
    setQuestion(asked ?? SCENARIOS[key].question)
    setActive(null)
    setShown(0)
    setThreadEpoch(0)
    setPhase('retrieving')
    timers.current.push(
      window.setTimeout(() => {
        setPhase('streaming')
        timers.current.push(window.setInterval(() => setShown((count) => count + 1), 58))
      }, 1300),
    )
  }, [clearTimers])

  // The stream ends when every token is on screen; the sources then disperse, and the
  // threads are drawn once the cards have landed (measuring earlier would catch them mid-flight).
  useEffect(() => {
    if (phase !== 'streaming' || shown < tokens.length) return
    clearTimers()
    setPhase('done')
    timers.current.push(window.setTimeout(() => setThreadEpoch((epoch) => epoch + 1), 820 + scenario.sources.length * 110))
  }, [phase, shown, tokens.length, scenario.sources.length, clearTimers])

  useEffect(() => {
    const id = setTimeout(() => play('grounded'), 700)
    return () => {
      clearTimeout(id)
      clearTimers()
    }
  }, [play, clearTimers])

  useEffect(() => {
    onPhase?.(phase === 'done' ? 'idle' : phase)
  }, [phase, onPhase])

  const stop = () => {
    clearTimers()
    setPhase('done')
  }

  const getPairs = useCallback(
    () =>
      scenario.sources.map((_, i) => ({
        n: i + 1,
        from: citeRefs.current[i + 1],
        to: cardRefs.current[i + 1],
        edge: answerRef.current,
      })),
    [scenario],
  )

  const busy = phase === 'retrieving' || phase === 'streaming'

  return (
    <section className="p-pane demo-stage" aria-label="Live demonstration with sample data">
      <div className="demo-bench" ref={benchRef}>
        <article>
          <h2 className="demo-question">{question}</h2>
          <div className="demo-status">
            {phase === 'retrieving' || phase === 'idle' ? (
              <span className="demo-retrieving" role="status">
                <i className="p-beam" aria-hidden="true" />
                {phase === 'idle' ? 'Ready' : 'Searching 3 documents'}
              </span>
            ) : (
              <ClarityRing value={scenario.confidence} state={scenario.state} />
            )}
            <span className="p-mono">{mode} mode</span>
          </div>
          <p className="p-answer" aria-live="polite" ref={answerRef}>
            {tokens.slice(0, shown).map((token, index) =>
              token.kind === 'word' ? (
                <span key={`${scenarioKey}-${index}`} className="p-word">{token.text}</span>
              ) : (
                <Cite
                  key={`${scenarioKey}-${index}`}
                  n={token.n}
                  active={active === token.n}
                  onActivate={setActive}
                  innerRef={token.first ? (el) => { citeRefs.current[token.n] = el } : undefined}
                />
              ),
            )}
          </p>
        </article>

        <aside className="demo-margin" aria-label="Sources">
          <p className="p-eyebrow">{phase === 'done' && scenario.sources.length === 0 ? 'No sources' : 'Evidence'}</p>
          {phase === 'done' &&
            scenario.sources.map((source, i) => (
              <SourceCard
                key={`${scenarioKey}-${i}`}
                n={i + 1}
                source={source}
                order={i}
                dispersing
                active={active === i + 1}
                onActivate={setActive}
                innerRef={(el) => { cardRefs.current[i + 1] = el }}
              />
            ))}
        </aside>

        {threadEpoch > 0 && <Threads containerRef={benchRef} getPairs={getPairs} active={active} epoch={threadEpoch} />}
      </div>

      <div className="demo-dock">
        <Lens label="Answer mode" options={MODES} value={mode} onChange={setMode} />
        <Aperture
          busy={busy}
          placeholder="Try a question (sample data)"
          onSend={(text) => play(scenarioKey, text)}
          onStop={stop}
        />
        <div className="demo-replay">
          <span className="p-eyebrow">Play a case</span>
          {Object.entries(SCENARIOS).map(([key, item]) => (
            <button key={key} type="button" className={`p-btn${key === scenarioKey ? ' p-btn--tonal' : ''}`} onClick={() => play(key as ScenarioKey)}>
              {item.label}
            </button>
          ))}
        </div>
      </div>
    </section>
  )
}
