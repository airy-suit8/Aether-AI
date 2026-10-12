import { useState } from 'react'
import { AmbientField, ClarityRing, Field, HoldButton, Lens, PrismMark, PrismRoot, Switch } from '../prism'
import type { FieldState, PrismStyle, Theme } from '../prism'
import DemoBench from '../DemoBench'
import './lab.css'

/** Design lab: every Prism component with sample data. Nothing here talks to the backend. */

const THEMES: { value: Theme; label: string }[] = [
  { value: 'system', label: 'System' },
  { value: 'dark', label: 'Dark' },
]

const ROLES: { name: string; token: string; on?: string; note: string }[] = [
  { name: 'Surface', token: '--p-surface', note: 'Content sits here' },
  { name: 'Surface 2', token: '--p-surface-2', note: 'One step up' },
  { name: 'Surface 3', token: '--p-surface-3', note: 'Controls at rest' },
  { name: 'Primary', token: '--p-primary', on: '--p-on-primary', note: 'The one colour for "act"' },
  { name: 'Primary soft', token: '--p-primary-soft', on: '--p-on-primary-soft', note: 'Selected, tonal' },
  { name: 'Grounded', token: '--p-ok-soft', on: '--p-ok', note: 'Status, with a label' },
  { name: 'Uncertain', token: '--p-warn-soft', on: '--p-warn', note: 'Status, with a label' },
  { name: 'Failed', token: '--p-bad-soft', on: '--p-bad', note: 'Status, with a label' },
]

export default function DesignLab() {
  const [theme, setTheme] = useState<Theme>('system')
  const [phase, setPhase] = useState<FieldState>('idle')
  const [stream, setStream] = useState(true)
  const [name, setName] = useState('')
  const [held, setHeld] = useState(0)

  return (
    <PrismRoot theme={theme}>
      <AmbientField state={phase} />
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
          <h1 className="p-display">
            Ask in white light.
            <br />
            Read the <em>spectrum.</em>
          </h1>
          <p className="lab-lede">
            Every source has its own hue, and every claim carries the hue of the source it came from. Hover a
            citation and its evidence lights up.
          </p>
        </section>

        <DemoBench onPhase={setPhase} />

        <section className="lab-section">
          <p className="p-eyebrow">Colour</p>
          <h2>Neutral by default. Colour only when it means something.</h2>
          <div className="lab-swatches">
            {ROLES.map((role) => (
              <div key={role.name} className="lab-swatch" style={{ '--c': `var(${role.token})`, '--on': role.on ? `var(${role.on})` : undefined } as PrismStyle}>
                <b>{role.name}</b>
                <span>{role.note}</span>
              </div>
            ))}
          </div>
          <div className="lab-spectrum" role="img" aria-label="The five source hues, equal in lightness">
            {[1, 2, 3, 4, 5].map((n) => (
              <i key={n} style={{ '--c': `var(--p-s${n})` } as PrismStyle} />
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
            <Switch label="Stream" checked={stream} onChange={setStream} />
            <HoldButton onConfirm={() => setHeld((count) => count + 1)}>
              {held ? `Deleted ${held} time${held === 1 ? '' : 's'} · hold again` : 'Hold to delete'}
            </HoldButton>
          </div>
          <div className="lab-controls">
            <ClarityRing value={0.82} state="grounded" />
            <ClarityRing value={0.47} state="uncertain" />
            <ClarityRing value={0} state="refused" />
          </div>
          <div className="lab-form">
            <Field label="Username" value={name} onChange={setName} hint="3 to 50 letters, digits, hyphens or underscores" autoComplete="off" />
          </div>
        </section>
      </div>
    </PrismRoot>
  )
}
