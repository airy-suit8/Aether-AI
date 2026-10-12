import { useCallback, useState } from 'react'
import type { FormEvent } from 'react'
import { useLocation, useMatch, useNavigate } from 'react-router'
import { useAuth } from '../../services/AuthContext'
import { login, register } from '../../services/api'
import { AmbientField, Dialog, Field, Lens, PrismMark } from '../../design/prism'
import type { FieldState, PrismStyle, Theme } from '../../design/prism'
import DemoBench from '../../design/DemoBench'

const THEMES: { value: Theme; label: string }[] = [
  { value: 'system', label: 'System' },
  { value: 'dark', label: 'Dark' },
]

const STEPS = [
  { n: '01', title: 'Add', text: 'Drop in a PDF, a Word file, a spreadsheet or a note. It is split into passages.', node: 'var(--p-ink)' },
  { n: '02', title: 'Index', text: 'Each passage becomes a vector, so the search is by meaning and not only by words.', node: 'var(--p-s1)' },
  { n: '03', title: 'Refract', text: 'Your question pulls out the passages closest to it. Hybrid mode adds keyword search.', node: 'var(--p-s3)' },
  { n: '04', title: 'Read', text: 'The answer is written from those passages, and each one is shown beside it.', node: 'var(--p-s5)' },
]

const USERNAME_RULE = /^[A-Za-z0-9_-]{3,50}$/

/**
 * LandingPage — the start page. The product demonstrates itself with sample data, then
 * explains the path a document takes, and opens the sign-in sheet.
 */
interface LandingPageProps {
  theme?: Theme
  onTheme?: (theme: Theme) => void
}

/** Where to go after signing in: the workspace page that sent the user here, or the chat. */
function destination(state: unknown): string {
  const from = typeof state === 'object' && state !== null && 'from' in state ? state.from : null
  return typeof from === 'string' && from.startsWith('/') && from !== '/login' ? from : '/chat'
}

export default function LandingPage({ theme = 'system', onTheme = () => {} }: LandingPageProps) {
  const { isAuthenticated, login: setAuth } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  // /login is this page with the sign-in sheet open; signed in, there is nothing to open it for
  const showModal = useMatch('/login') !== null && !isAuthenticated
  const [isLoginView, setIsLoginView] = useState(true)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [fieldErrors, setFieldErrors] = useState<{ username?: string; password?: string }>({})
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [phase, setPhase] = useState<FieldState>('idle')

  const open = (loginView: boolean) => {
    if (isAuthenticated) {
      navigate('/chat')
      return
    }
    setIsLoginView(loginView)
    setError('')
    setFieldErrors({})
    navigate('/login', { state: location.state })
  }

  const closeModal = useCallback(() => navigate('/'), [navigate])

  const switchView = () => {
    setIsLoginView(view => !view)
    setError('')
    setFieldErrors({})
  }

  // Mirrors the server's rules, so a mistake is caught before a request is made
  const validate = (name: string) => {
    const problems: { username?: string; password?: string } = {}
    if (isLoginView) {
      if (!name) problems.username = 'Enter your username'
      if (!password) problems.password = 'Enter your password'
      return problems
    }
    if (!USERNAME_RULE.test(name)) problems.username = '3 to 50 letters, digits, hyphens or underscores'
    if (password.length < 8) problems.password = 'At least 8 characters'
    else if (new TextEncoder().encode(password).length > 72) problems.password = 'Too long: keep it under 72 characters'
    return problems
  }

  const handleAuth = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const name = username.trim()
    const problems = validate(name)
    setFieldErrors(problems)
    setError('')
    if (Object.keys(problems).length > 0) return

    setIsLoading(true)
    try {
      if (!isLoginView) await register(name, password, inviteCode.trim())
      const data = await login(name, password)
      setAuth(data.access_token, name)
      navigate(destination(location.state), { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <>
      <AmbientField state={phase} />
      <div className="l-page" id="landing-view">
        <header className="l-top">
          <span className="x-brand">
            <PrismMark /> Aether
          </span>
          <Lens label="Theme" options={THEMES} value={theme} onChange={onTheme} />
          <button type="button" className="p-btn p-btn--tonal" onClick={() => open(true)}>
            {isAuthenticated ? 'Open workspace' : 'Sign in'}
          </button>
        </header>

        <section className="l-hero">
          <p className="p-eyebrow">Aether AI · a private knowledge assistant</p>
          <h1 className="p-display">
            Ask in white light.
            <br />
            Read the <em>spectrum.</em>
          </h1>
          <p className="l-lede">
            Add your documents and ask questions about them. Every answer shows the passages it came from,
            with the page and a similarity score.
          </p>
          <div className="l-actions">
            <button type="button" className="p-btn p-btn--filled" onClick={() => open(false)}>
              {isAuthenticated ? 'Open workspace' : 'Start asking'}
            </button>
            {!isAuthenticated && (
              <button type="button" className="p-btn" onClick={() => open(true)}>I have an account</button>
            )}
          </div>
        </section>

        <DemoBench onPhase={setPhase} />

        <section className="l-section">
          <p className="p-eyebrow">How it works</p>
          <h2 className="p-h2">One line of light, from your document to your answer.</h2>
          <ol className="l-path">
            {STEPS.map((step) => (
              <li key={step.n} className="l-step" style={{ '--node': step.node } as PrismStyle}>
                <span className="p-mono">{step.n}</span>
                <h3>{step.title}</h3>
                <p>{step.text}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="l-section">
          <p className="p-eyebrow">What you get</p>
          <h2 className="p-h2">Built to be checked, not just believed.</h2>
          <div className="l-trio">
            <article className="p-pane l-card">
              <span className="p-mono">SOURCES</span>
              <h3>Every answer shows its evidence.</h3>
              <p>The file, the page, a similarity score and the passage itself sit beside the answer, so you can check it in seconds.</p>
            </article>
            <article className="p-pane l-card">
              <span className="p-mono">PRIVATE</span>
              <h3>Your library is yours alone.</h3>
              <p>Each account has its own documents and its own conversations.</p>
            </article>
            <article className="p-pane l-card">
              <span className="p-mono">MODES</span>
              <h3>Four ways to answer.</h3>
              <p>Default, Hybrid search, an Agent with a calculator and a calendar, and a LangChain pipeline.</p>
            </article>
          </div>
        </section>

        <footer className="l-foot">
          <span>Built by Tirth Ganatra during an internship at Netweb Software, Vadodara.</span>
          <span>Powered by Google Gemini</span>
        </footer>
      </div>

      {showModal && (
        <Dialog title={isLoginView ? 'Welcome back' : 'Create your account'} onClose={closeModal}>
          <form className="l-form" onSubmit={handleAuth} noValidate>
            <Field
              label="Username"
              value={username}
              onChange={setUsername}
              error={fieldErrors.username}
              hint={isLoginView ? undefined : '3 to 50 letters, digits, hyphens or underscores'}
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
            />
            <Field
              label="Password"
              type="password"
              value={password}
              onChange={setPassword}
              error={fieldErrors.password}
              hint={isLoginView ? undefined : 'At least 8 characters'}
              autoComplete={isLoginView ? 'current-password' : 'new-password'}
            />
            {!isLoginView && (
              <Field
                label="Invite code"
                value={inviteCode}
                onChange={setInviteCode}
                hint="Only if you were given one"
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
              />
            )}
            {error && <p className="p-hint" data-tone="bad" role="alert">{error}</p>}
            <button type="submit" className="p-btn p-btn--filled" disabled={isLoading}>
              {isLoading ? 'One moment' : isLoginView ? 'Sign in' : 'Create account'}
            </button>
            <p className="l-form__switch">
              {isLoginView ? 'New here? ' : 'Already have an account? '}
              <button type="button" className="p-link" onClick={switchView}>
                {isLoginView ? 'Create an account' : 'Sign in'}
              </button>
            </p>
          </form>
        </Dialog>
      )}
    </>
  )
}
