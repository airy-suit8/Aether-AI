import React, { useState, useEffect, useCallback } from 'react'
import { getDocumentsDetailed, deleteAllDocuments, getHealth } from '../../services/api'
import './SettingsModal.css'

export default function SettingsModal({ onClose, addToast, onDocumentsChanged, onClearConversation }) {
  const [activeTab, setActiveTab] = useState('general')
  const [docs, setDocs] = useState([])
  const [health, setHealth] = useState(null)
  const [isLoadingDocs, setIsLoadingDocs] = useState(false)


  // Load health data on mount
  useEffect(() => {
    getHealth().then(setHealth).catch(() => {})
  }, [])

  const loadDetailedDocs = useCallback(async () => {
    setIsLoadingDocs(true)
    try {
      const data = await getDocumentsDetailed()
      setDocs(data.documents || [])
    } catch (e) {
      addToast('Failed to load document details', 'error')
    } finally {
      setIsLoadingDocs(false)
    }
  }, [addToast])

  // Load detailed docs when opening Documents tab
  useEffect(() => {
    if (activeTab === 'documents') {
      loadDetailedDocs()
    }
  }, [activeTab, loadDetailedDocs])

  const handleClearAll = async () => {
    if (confirm('Are you sure you want to delete all indexed documents from the vector store?')) {
      try {
        await deleteAllDocuments()
        addToast('All documents deleted', 'success')
        setDocs([])
        onDocumentsChanged()
      } catch (e) {
        addToast('Failed to delete documents', 'error')
      }
    }
  }

  const formatSize = (bytes) => {
    if (!bytes) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
  }

  const formatDate = (isoString) => {
    if (!isoString) return 'Unknown'
    return new Date(isoString).toLocaleString()
  }

  return (
    <div className="modal-overlay fade-in" onClick={onClose}>
      <div className="modal-container slide-in-down glass-strong" onClick={e => e.stopPropagation()}>
        
        <aside className="modal-sidebar">
          <div className="modal-sidebar-title">Settings</div>
          <button 
            className={`modal-tab ${activeTab === 'general' ? 'active' : ''}`}
            onClick={() => setActiveTab('general')}
          >
            General
          </button>
          <button 
            className={`modal-tab ${activeTab === 'documents' ? 'active' : ''}`}
            onClick={() => setActiveTab('documents')}
          >
            Documents
          </button>
          <button 
            className={`modal-tab ${activeTab === 'health' ? 'active' : ''}`}
            onClick={() => setActiveTab('health')}
          >
            System Health
          </button>
        </aside>

        <main className="modal-content">
          <header className="modal-header">
            <h2 className="modal-title">
              {activeTab === 'general' && 'General Settings'}
              {activeTab === 'documents' && 'Document Management'}
              {activeTab === 'health' && 'System Health'}
            </h2>
            <button className="btn btn-ghost btn-icon" onClick={onClose}>×</button>
          </header>

          <div className="modal-body">
            
            {/* ── GENERAL TAB ── */}
            {activeTab === 'general' && (
              <div className="settings-pane">
                <div className="setting-row">
                  <div className="setting-info">
                    <div className="setting-label">Clear Conversation</div>
                    <div className="setting-desc">Delete the current conversation from the server and start a new thread.</div>
                  </div>
                  <button 
                    className="btn btn-secondary" 
                    onClick={() => {
                      onClearConversation()
                      onClose()
                    }}
                  >
                    Clear Conversation
                  </button>
                </div>
              </div>
            )}

            {/* ── DOCUMENTS TAB ── */}
            {activeTab === 'documents' && (
              <div className="settings-pane">
                <div className="setting-row header-row">
                  <div className="setting-info">
                    <div className="setting-desc">Review and manage parsed document index chunks in Vector Store.</div>
                  </div>
                  <button className="btn btn-primary" style={{ background: 'var(--error)' }} onClick={handleClearAll} disabled={docs.length === 0}>
                    Clear All Files
                  </button>
                </div>
                
                <div className="docs-table-wrapper">
                  {isLoadingDocs ? (
                    <div className="modal-loading"><span className="spinner" /></div>
                  ) : docs.length === 0 ? (
                    <div className="modal-empty">No documents in vector store.</div>
                  ) : (
                    <table className="docs-table">
                      <thead>
                        <tr>
                          <th>Filename</th>
                          <th>Size</th>
                          <th>Chunks</th>
                          <th>Ingested On</th>
                        </tr>
                      </thead>
                      <tbody>
                        {docs.map((d, i) => (
                          <tr key={i}>
                            <td title={d.filename}>{d.filename}</td>
                            <td>{formatSize(d.size_bytes)}</td>
                            <td>{d.chunks}</td>
                            <td>{formatDate(d.uploaded_at)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>
            )}

            {/* ── HEALTH TAB ── */}
            {activeTab === 'health' && (
              <div className="settings-pane">
                <div className="metrics-grid">
                  <div className="metric-card">
                    <div className="metric-label">System Status</div>
                    <div className="metric-val" style={{ color: health?.status === 'ok' ? 'var(--success)' : 'var(--error)' }}>
                      {health?.status === 'ok' ? 'Active 🟢' : 'Offline 🔴'}
                    </div>
                  </div>
                  <div className="metric-card">
                    <div className="metric-label">Uptime</div>
                    <div className="metric-val">{health?.uptime_seconds ? `${health.uptime_seconds.toFixed(1)}s` : 'Unknown'}</div>
                  </div>
                </div>
              </div>
            )}

          </div>
        </main>
      </div>
    </div>
  )
}
