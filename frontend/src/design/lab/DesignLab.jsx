import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AmbientField, Aperture, Cite, ClarityRing, Lens, PrismMark, PrismRoot, SourceCard, Threads } from '../prism'
import './lab.css'

/**
 * Design lab: every Prism component with sample data, and one live bench that plays the
 * whole sequence (ask, retrieve, stream, disperse). Nothing here talks to the backend.
 */

const SCENARIOS = {
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

const THEMES = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
]

const MODES = [
  { value: 'default', label: 'Default' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'agent', label: 'Agent' },
]

const ROLES = [
  { name: 'Surface', token: '--p-surface', note: 'Content sits here' },
  { name: 'Surface 2', token: '--p-surface-2', note: 'One step up' },
  { name: 'Surface 3', token: '--p-surface-3', note: 'Controls at rest' },
  { name: 'Primary', token: '--p-primary', on: '--p-on-primary', note: 'The one colour for "act"' },
  { name: 'Primary soft', token: '--p-primary-soft', on: '--p-on-primary-soft', note: 'Selected, tonal' },
  { name: 'Grounded', token: '--p-ok-soft', on: '--p-ok', note: 'Status, with a label' },
  { name: 'Uncertain', token: '--p-warn-soft', on: '--p-warn', note: 'Status, with a label' },
  { name: 'Failed', token: '--p-bad-soft', on: '--p-bad', note: 'Status, with a label' },
]

/** Split an answer into words and citation markers, so each can arrive on its own. */
function tokenize(answer) {
  const tokens = []
  const seen = new Set()
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

export default function DesignLab() {
  const [theme, setTheme] = useState('system')
  const [mode, setMode] = useState('default')
  const [scenarioKey, setScenarioKey] = useState('grounded')
  const [question, setQuestion] = useState(SCENARIOS.grounded.question)
  const [phase, setPhase] = useState('idle') // idle | retrieving | streaming | done
  const [shown, setShown] = useState(0)
  const [active, setActive] = useState(null)
  const [threadEpoch, setThreadEpoch] = useState(0)

  const benchRef = useRef(null)
  const answerRef = useRef(null)
  const citeRefs = useRef({})
  const cardRefs = useRef({})
  const timers = useRef([])

  const scenario = SCENARIOS[scenarioKey]
  const tokens = useMemo(() => tokenize(scenario.answer), [scenario])

  const clearTimers = useCallback(() => {
    timers.current.forEach((id) => {
      clearTimeout(id)
      clearInterval(id)
    })
    timers.current = []
  }, [])

  const play = useCallback((key, asked) => {
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
      setTimeout(() => {
        setPhase('streaming')
        timers.current.push(setInterval(() => setShown((count) => count + 1), 58))
      }, 1300),
    )
  }, [clearTimers])

  // The stream ends when every token is on screen; the sources then disperse, and the
  // threads are drawn once the cards have landed (measuring earlier would catch them mid-flight).
  useEffect(() => {
    if (phase !== 'streaming' || shown < tokens.length) return
    clearTimers()
    setPhase('done')
    timers.current.push(setTimeout(() => setThreadEpoch((epoch) => epoch + 1), 820 + scenario.sources.length * 110))
  }, [phase, shown, tokens.length, scenario.sources.length, clearTimers])

  useEffect(() => {
    const id = setTimeout(() => play('grounded'), 700)
    return () => {
      clearTimeout(id)
      clearTimers()
    }
  }, [play, clearTimers])

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
  const visible = tokens.slice(0, shown)

  return (
    <PrismRoot theme={theme}>
      <AmbientField state={phase === 'done' ? 'idle' : phase} />
      <div className="lab">
        <header className="lab-top">
          <span className="lab-brand">
            <PrismMark /> Aether
          </span>
          <span className="p-eyebrow lab-top__tag">Prism · design lab</span>
          <Lens label="Theme" options={THEMES} value={theme} onChange={setTheme} />
        </header>

        <section className="lab-hero">
          <p className="p-eyebrow">A design language made of light</p>
          <h1 className="lab-title">
            Ask in white light.
            <br />
            Read the <em>spectrum.</em>
          </h1>
          <p className="lab-lede">
            Every source has its own hue, and every claim carries the hue of the source it came from. Hover a
            citation and its evidence lights up.
          </p>
        </section>

        <section className="p-pane lab-stage" aria-label="Live bench">
          <div className="lab-bench" ref={benchRef}>
            <article className="lab-thread">
              <h2 className="lab-question">{question}</h2>
              <div className="lab-status">
                {phase === 'retrieving' || phase === 'idle' ? (
                  <span className="lab-retrieving" role="status">
                    <i className="lab-beam" aria-hidden="true" />
                    {phase === 'idle' ? 'Ready' : 'Searching 3 documents'}
                  </span>
                ) : (
                  <ClarityRing value={scenario.confidence} state={scenario.state} />
                )}
                <span className="p-mono">{mode} mode</span>
              </div>
              <p className="p-answer" aria-live="polite" ref={answerRef}>
                {visible.map((token, index) =>
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

            <aside className="lab-margin" aria-label="Sources">
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

            {threadEpoch > 0 && (
              <Threads containerRef={benchRef} getPairs={getPairs} active={active} epoch={threadEpoch} />
            )}
          </div>

          <div className="lab-dock">
            <Lens label="Answer mode" options={MODES} value={mode} onChange={setMode} />
            <Aperture
              busy={busy}
              onSend={(text) => play(scenarioKey, text)}
              onStop={stop}
              leading={
                <button type="button" className="p-icon-btn" aria-label="Attach a document">
                  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                    <path d="M10 4v12M4 10h12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                  </svg>
                </button>
              }
            />
            <div className="lab-replay">
              <span className="p-eyebrow">Play a case</span>
              {Object.entries(SCENARIOS).map(([key, item]) => (
                <button key={key} type="button" className={`p-btn${key === scenarioKey ? ' p-btn--tonal' : ''}`} onClick={() => play(key)}>
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </section>

        <section className="lab-section">
          <p className="p-eyebrow">Colour</p>
          <h2>Neutral by default. Colour only when it means something.</h2>
          <div className="lab-swatches">
            {ROLES.map((role) => (
              <div key={role.name} className="lab-swatch" style={{ '--c': `var(${role.token})`, '--on': role.on ? `var(${role.on})` : undefined }}>
                <b>{role.name}</b>
                <span>{role.note}</span>
              </div>
            ))}
          </div>
          <div className="lab-spectrum" role="img" aria-label="The five source hues, equal in lightness">
            {[1, 2, 3, 4, 5].map((n) => (
              <i key={n} style={{ '--c': `var(--p-s${n})` }} />
            ))}
          </div>
          <p className="lab-note">The source spectrum: five hues at one lightness, so no source looks more important than another.</p>
        </section>

        <section className="lab-section">
          <p className="p-eyebrow">Type</p>
          <h2>One typeface that changes weight and width with state.</h2>
          <div className="lab-type">
            <p className="lab-specimen" tabIndex={0}>Aether</p>
            <div className="lab-type__side">
              <p>Mona Sans carries the interface and the answers. Its width opens for display and closes for dense labels. Move the pointer across the page and watch the headline at the top.</p>
              <p className="p-mono">Martian Mono · p. 12 · 0.84 · 1.8 s · 3072 dims</p>
            </div>
          </div>
        </section>

        <section className="lab-section">
          <p className="p-eyebrow">Controls</p>
          <h2>Quiet at rest, alive under the hand.</h2>
          <div className="lab-controls">
            <button type="button" className="p-btn p-btn--filled">Upload a document</button>
            <button type="button" className="p-btn p-btn--tonal">New thread</button>
            <button type="button" className="p-btn">Sign out</button>
            <ClarityRing value={0.82} state="grounded" />
            <ClarityRing value={0.47} state="uncertain" />
            <ClarityRing value={0} state="refused" />
          </div>
        </section>
      </div>
    </PrismRoot>
  )
}
