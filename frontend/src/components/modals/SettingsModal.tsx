import { useState, useEffect, useCallback } from 'react'
import { getDocumentsDetailed, deleteAllDocuments, getHealth } from '../../services/api'
import type { DocumentRecord, Schemas } from '../../services/api'
import { Dialog, HoldButton, Lens } from '../../design/prism'
import type { AddToast } from '../chat/types'
// One version for the app and its API (backend/src/core/config.py APP_VERSION; a test keeps them equal)
import { version } from '../../../package.json'

type Tab = 'general' | 'documents' | 'health'

const TABS: { value: Tab; label: string }[] = [
  { value: 'general', label: 'General' },
  { value: 'documents', label: 'Documents' },
  { value: 'health', label: 'System' },
]

const formatSize = (bytes: number) => {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

const formatDate = (isoString: string) => (isoString ? new Date(isoString).toLocaleString() : 'Unknown')

interface SettingsModalProps {
  onClose: () => void
  addToast: AddToast
  onDocumentsChanged: () => void
  onClearConversation: () => void
  onSignOutEverywhere: () => void
}

export default function SettingsModal({ onClose, addToast, onDocumentsChanged, onClearConversation, onSignOutEverywhere }: SettingsModalProps) {
  const [activeTab, setActiveTab] = useState<Tab>('general')
  const [docs, setDocs] = useState<DocumentRecord[]>([])
  const [health, setHealth] = useState<Schemas['Health'] | null>(null)
  const [healthFailed, setHealthFailed] = useState(false)
  const [isLoadingDocs, setIsLoadingDocs] = useState(false)

  // Load health data on mount
  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealthFailed(true))
  }, [])

  const loadDetailedDocs = useCallback(async () => {
    setIsLoadingDocs(true)
    try {
      const data = await getDocumentsDetailed()
      setDocs(data.documents || [])
    } catch {
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
    try {
      await deleteAllDocuments()
      addToast('All documents deleted', 'success')
      setDocs([])
      onDocumentsChanged()
    } catch {
      addToast('Failed to delete documents', 'error')
    }
  }

  return (
    <Dialog title="Settings" onClose={onClose} width="660px">
      <div className="s-tabs">
        <Lens label="Settings section" options={TABS} value={activeTab} onChange={setActiveTab} />
      </div>

      {activeTab === 'general' && (
        <div className="s-row">
          <div>
            <b>Clear conversation</b>
            <span>Delete the current conversation from the server and start a new thread.</span>
          </div>
          <button
            type="button"
            className="p-btn p-btn--tonal"
            onClick={() => {
              onClearConversation()
              onClose()
            }}
          >
            Clear conversation
          </button>
        </div>
      )}

      {activeTab === 'general' && (
        <div className="s-row">
          <div>
            <b>Sign out everywhere</b>
            <span>Sign out on every device and browser, this one too. Each is signed out when it next reloads, and within 30 minutes at most.</span>
          </div>
          <button type="button" className="p-btn p-btn--tonal" onClick={onSignOutEverywhere}>
            Sign out everywhere
          </button>
        </div>
      )}

      {activeTab === 'documents' && (
        <>
          {isLoadingDocs ? (
            <p className="s-empty" role="status"><i className="p-beam" aria-hidden="true" /></p>
          ) : docs.length === 0 ? (
            <p className="s-empty">No documents in your library.</p>
          ) : (
            <div className="s-table-wrap">
              <table className="s-table">
                <thead>
                  <tr>
                    <th>File</th>
                    <th>Size</th>
                    <th>Passages</th>
                    <th>Added</th>
                  </tr>
                </thead>
                <tbody>
                  {docs.map((d) => (
                    <tr key={d.id ?? d.filename}>
                      <td title={d.filename}>{d.filename}</td>
                      <td className="p-mono">{formatSize(d.size_bytes)}</td>
                      <td className="p-mono">{d.chunks}</td>
                      <td>{formatDate(d.uploaded_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="s-row">
            <div>
              <b>Delete all documents</b>
              <span>Removes every document and its passages from your library. This cannot be undone.</span>
            </div>
            <HoldButton onConfirm={handleClearAll} disabled={docs.length === 0}>Hold to delete all</HoldButton>
          </div>
        </>
      )}

      {/* The health check is public, so it reports the status and nothing else */}
      {activeTab === 'health' && (
        <div className="s-metrics">
          <div className="s-metric" data-tone={health?.status === 'ok' ? 'ok' : healthFailed ? 'bad' : undefined}>
            <b>{health?.status === 'ok' ? 'Running' : healthFailed ? 'Unreachable' : 'Checking'}</b>
            <span>Backend</span>
          </div>
          <div className="s-metric">
            <b className="p-mono">{version}</b>
            <span>Version</span>
          </div>
        </div>
      )}
    </Dialog>
  )
}
