import { useEffect } from 'react'

/**
 * Makes glass catch the pointer.
 *
 * One listener on the Prism root. On each frame it writes the pointer position, in each
 * pane's own coordinates, to --mx / --my on the pane under the pointer and on the panes
 * that contain it; the CSS paints the lit edge and the glint from those two numbers.
 * It also writes --px (0 to 1 across the viewport) on the root for reactive type.
 */
export function usePointerLight(rootRef) {
  useEffect(() => {
    const root = rootRef.current
    if (!root) return undefined

    let frame = 0
    let last = null

    const paint = () => {
      frame = 0
      if (!last) return
      root.style.setProperty('--px', (last.clientX / window.innerWidth).toFixed(3))
      let pane = last.target instanceof Element ? last.target.closest('.p-pane') : null
      while (pane) {
        const rect = pane.getBoundingClientRect()
        pane.style.setProperty('--mx', `${Math.round(last.clientX - rect.left)}px`)
        pane.style.setProperty('--my', `${Math.round(last.clientY - rect.top)}px`)
        pane = pane.parentElement ? pane.parentElement.closest('.p-pane') : null
      }
    }

    const onMove = (event) => {
      last = event
      if (!frame) frame = requestAnimationFrame(paint)
    }

    root.addEventListener('pointermove', onMove, { passive: true })
    return () => {
      root.removeEventListener('pointermove', onMove)
      if (frame) cancelAnimationFrame(frame)
    }
  }, [rootRef])
}
