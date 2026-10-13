import type { ToastType } from '../chat/types'

export interface Toast {
  id: number
  message: string
  type: ToastType
}

/**
 * ToastContainer — short signals at the foot of the page.
 * The dot carries the tone; the message carries the meaning.
 */
export default function ToastContainer({ toasts }: { toasts: Toast[] }) {
  return (
    <div className="p-toasts" role="status" aria-live="polite">
      {toasts.map(t => (
        <div key={t.id} className="p-toast" data-tone={t.type}>
          {t.message}
        </div>
      ))}
    </div>
  )
}
