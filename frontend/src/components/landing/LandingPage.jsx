import React, { useState } from 'react'
import { useAuth } from '../../services/AuthContext'
import ShinyText from '../reactbits/ShinyText'
import DotPattern from '../reactbits/DotPattern'
import { login, register } from '../../services/api'
import './LandingPage.css'

/**
 * LandingPage — Hero page with glassmorphism, animated RAG pipeline visualization,
 * feature cards, and a glowing CTA to enter the chat.
 */
export default function LandingPage({ onStartChat }) {
  const { isAuthenticated, login: setAuth } = useAuth()
  const [showModal, setShowModal] = useState(false)
  const [isLoginView, setIsLoginView] = useState(true)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const handleStartClick = () => {
    if (isAuthenticated) {
      onStartChat()
    } else {
      setShowModal(true)
    }
  }

  const handleAuth = async (e) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)
    try {
      if (isLoginView) {
        const data = await login(username, password)
        setAuth(data.access_token)
        onStartChat()
      } else {
        await register(username, password)
        const data = await login(username, password)
        setAuth(data.access_token)
        onStartChat()
      }
    } catch (err) {
      const msg = typeof err === 'string' ? err : err?.message || String(err || 'Authentication failed')
      setError(msg)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="landing" id="landing-view">
      {/* Ambient background effects */}
      <div className="landing-bg-orb landing-orb-1" />
      <div className="landing-bg-orb landing-orb-2" />
      <div className="landing-bg-orb landing-orb-3" />
      <DotPattern width={20} height={20} cx={1} cy={1} cr={1} />

      {/* Navigation */}
      <nav className="landing-nav glass-strong">
        <div className="landing-brand">
          <div className="brand-icon">✦</div>
          <span className="brand-name">Aether AI</span>
        </div>
        <div className="landing-nav-links">
          <a href="#features">Features</a>
          <a href="#pipeline">How It Works</a>
        </div>
        <button className="btn btn-primary btn-sm" onClick={handleStartClick}>
          {isAuthenticated ? 'Launch App →' : 'Sign In'}
        </button>
      </nav>

      {/* Hero Section */}
      <section className="hero">
        <div className="hero-badge fade-in">
          <span className="hero-badge-dot" />
          RAG-Powered Knowledge Assistant
        </div>
        <h1 className="hero-title fade-in-up">
          Your Private Knowledge,
          <br />
          <ShinyText text="Intelligently Unlocked" className="hero-title-accent" speed={4} />
        </h1>
        <p className="hero-subtitle fade-in-up" style={{ animationDelay: '0.1s' }}>
          Upload documents. Ask questions. Get precise, source-cited answers
          grounded in your data — powered by Google Gemini and a 3-step RAG pipeline.
        </p>
        <div className="hero-actions fade-in-up" style={{ animationDelay: '0.2s' }}>
          <button className="btn btn-primary btn-lg hero-cta" onClick={handleStartClick}>
            <span>{isAuthenticated ? 'Start Chatting' : 'Log In to Start'}</span>
            <span className="cta-arrow">→</span>
          </button>
          <a href="#pipeline" className="btn btn-secondary btn-lg">
            See How It Works
          </a>
        </div>

        {/* Floating stat cards */}
        <div className="hero-stats fade-in-up" style={{ animationDelay: '0.3s' }}>
          <div className="stat-card glass">
            <div className="stat-value">3-Step</div>
            <div className="stat-label">RAG Chain</div>
          </div>
          <div className="stat-card glass">
            <div className="stat-value">Gemini</div>
            <div className="stat-label">LLM Engine</div>
          </div>
          <div className="stat-card glass">
            <div className="stat-value">LCEL</div>
            <div className="stat-label">Pipeline</div>
          </div>
          <div className="stat-card glass">
            <div className="stat-value">ReAct</div>
            <div className="stat-label">Agent</div>
          </div>
        </div>
      </section>

      {/* Pipeline Visualization */}
      <section className="pipeline-section" id="pipeline">
        <h2 className="section-title">How Aether AI Works</h2>
        <p className="section-subtitle">A three-step sequential chain: Retrieve → Summarize → Generate</p>
        <div className="pipeline-flow">
          {[
            { num: '01', icon: '📄', title: 'Upload & Ingest', desc: 'PDF, DOCX, TXT, MD → parsed, chunked (1000 chars), embedded via Gemini Embedding-001' },
            { num: '02', icon: '🔍', title: 'Retrieve', desc: 'Question embedded → cosine similarity search → top-5 most relevant chunks retrieved' },
            { num: '03', icon: '📋', title: 'Summarize', desc: 'Raw chunks condensed into a focused summary, removing noise and irrelevant details' },
            { num: '04', icon: '✨', title: 'Generate', desc: 'Gemini produces a precise answer with confidence scoring and source citations' },
          ].map((step, i) => (
            <React.Fragment key={step.num}>
              <div className="pipeline-step glass" style={{ animationDelay: `${i * 0.1}s` }}>
                <div className="step-num">{step.num}</div>
                <div className="step-icon">{step.icon}</div>
                <h3 className="step-title">{step.title}</h3>
                <p className="step-desc">{step.desc}</p>
              </div>
              {i < 3 && <div className="pipeline-connector">→</div>}
            </React.Fragment>
          ))}
        </div>
      </section>

      {/* Features Grid */}
      <section className="features-section" id="features">
        <h2 className="section-title">Built for Intelligence</h2>
        <p className="section-subtitle">Production-grade features under the hood</p>
        <div className="features-grid">
          {[
            { icon: '🤖', title: 'ReAct Agent', desc: 'LangGraph-powered multi-step reasoning with calculator, datetime, and document search tools' },
            { icon: '🧠', title: 'Conversation Memory', desc: 'SQLite-backed multi-turn memory that persists across server restarts' },
            { icon: '🛡️', title: 'Injection Protection', desc: 'Regex sanitization + prompt guards prevent malicious document attacks' },
            { icon: '📊', title: 'Confidence Scoring', desc: 'Cosine similarity-based scoring with 0.3 threshold to prevent hallucinations' },
            { icon: '⚡', title: 'Streaming Responses', desc: 'Real-time SSE token-by-token streaming for instant feedback' },
            { icon: '⛓️', title: 'Dual Pipeline', desc: 'Custom RAG engine + LangChain LCEL pipeline — switch modes on the fly' },
          ].map(f => (
            <div key={f.title} className="feature-card glass">
              <div className="feature-icon">{f.icon}</div>
              <h3 className="feature-title">{f.title}</h3>
              <p className="feature-desc">{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Footer CTA */}
      <section className="cta-section">
        <div className="cta-glow" />
        <h2 className="cta-title">Ready to unlock your knowledge?</h2>
        <button className="btn btn-primary btn-lg hero-cta" onClick={handleStartClick}>
          {isAuthenticated ? 'Launch Aether AI →' : 'Log In to Start →'}
        </button>
      </section>

      <footer className="landing-footer">
        <p>Built by <strong>Tirth Ganatra</strong> • Powered by Google Gemini • Guided by Dr. Amit Ganatra</p>
      </footer>

      {/* Auth Modal */}
      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal glass-strong" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{isLoginView ? 'Welcome Back' : 'Create Account'}</h3>
              <button className="btn-icon" onClick={() => setShowModal(false)}>✕</button>
            </div>
            
            <form className="auth-form" onSubmit={handleAuth}>
              {error && <div className="auth-error">{error}</div>}
              
              <div className="form-group">
                <label>Username</label>
                <input 
                  type="text" 
                  value={username} 
                  onChange={e => setUsername(e.target.value)} 
                  required 
                  className="glass-input"
                  placeholder="Enter username"
                />
              </div>
              
              <div className="form-group">
                <label>Password</label>
                <input 
                  type="password" 
                  value={password} 
                  onChange={e => setPassword(e.target.value)} 
                  required 
                  className="glass-input"
                  placeholder="Enter password"
                />
              </div>
              
              <button type="submit" className="btn btn-primary btn-block" disabled={isLoading}>
                {isLoading ? 'Processing...' : (isLoginView ? 'Sign In' : 'Register')}
              </button>
            </form>
            
            <div className="auth-switch">
              {isLoginView ? "Don't have an account? " : "Already have an account? "}
              <button className="btn-link" onClick={() => setIsLoginView(!isLoginView)}>
                {isLoginView ? 'Sign Up' : 'Log In'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
