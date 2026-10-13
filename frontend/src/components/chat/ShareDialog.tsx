import { useEffect, useState } from 'react'
import { getSharing, shareSession, stopSharing } from '../../services/api'
import { Dialog, Field } from '../../design/prism'
import type { AddToast } from './types'

/** The address of a shared conversation's page. */
export const sharedLink = (token: string) => `${window.location.origin}/shared/${token}`

interface ShareDialogProps {
  sessionId: string
  onClose: () => void
  addToast: AddToast
}

/**
 * ShareDialog — make, copy and withdraw the link to one conversation. Anyone who has the link
 * can read that conversation and the passages it cites, signed in or not; nothing else.
 */
export default function ShareDialog({ sessionId, onClose, addToast }: ShareDialogProps) {
  // undefined while the server is asked whether it is shared; null when it is not
  const [token, setToken] = useState<string | null | undefined>(undefined)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    getSharing(sessionId)
      .then((state) => { if (!cancelled) setToken(state.token ?? null) })
      .catch(() => { if (!cancelled) setToken(null) })
    return () => { cancelled = true }
  }, [sessionId])

  const act = async (work: () => Promise<{ token?: string | null }>, failed: string) => {
    setBusy(true)
    try {
      setToken((await work()).token ?? null)
    } catch (err) {
      addToast(err instanceof Error ? err.message : failed, 'error')
    } finally {
      setBusy(false)
    }
  }

  const copy = async () => {
    if (!token) return
    try {
      await navigator.clipboard.writeText(sharedLink(token))
      addToast('Link copied', 'success')
    } catch {
      // No clipboard access (an insecure page, or permission refused): the link is selectable in the field
      addToast('Could not copy. Select the link and copy it yourself.', 'error')
    }
  }

  return (
    <Dialog title="Share this conversation" onClose={onClose}>
      <div className="x-share">
        <p>
          Anyone with the link can read this conversation and the passages it cites, without signing in.
          They cannot ask questions, and they see nothing else of yours.
        </p>
        {token === undefined ? (
          <p className="p-hint" role="status">Checking</p>
        ) : token ? (
          <>
            <Field
              label="Link"
              value={sharedLink(token)}
              onChange={() => {}}
              readOnly
              onFocus={(e) => e.currentTarget.select()}
              hint="New questions you ask here appear on it too."
            />
            <div className="x-share__actions">
              <button type="button" className="p-btn p-btn--filled" onClick={copy}>Copy link</button>
              <button type="button" className="p-btn" disabled={busy} onClick={() => act(() => stopSharing(sessionId), 'Could not stop sharing')}>
                Stop sharing
              </button>
            </div>
          </>
        ) : (
          <div className="x-share__actions">
            <button type="button" className="p-btn p-btn--filled" disabled={busy} onClick={() => act(() => shareSession(sessionId), 'Could not share the conversation')}>
              Create link
            </button>
            <span className="p-hint">Not shared. You can withdraw the link at any time.</span>
          </div>
        )}
      </div>
    </Dialog>
  )
}
