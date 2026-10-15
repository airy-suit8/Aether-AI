/**
 * Decision 15: an answer already on screen does not re-render, or parse its Markdown again,
 * while a later answer streams. Counted by wrapping the Markdown renderer and the clarity ring
 * (a part of the answer outside its Markdown, so a re-rendered bubble would show there too).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import type { ComponentProps } from 'react'
import ChatLayout from './ChatLayout'
import { AuthProvider } from '../../services/AuthContext'
import * as api from '../../services/api'
import { documentList, done, SOURCE } from '../../test/fixtures'

const counts = vi.hoisted(() => ({ markdown: new Map<string, number>(), clarity: new Map<number, number>() }))
const bump = <K,>(map: Map<K, number>, key: K) => map.set(key, (map.get(key) ?? 0) + 1)

vi.mock('react-markdown', async (importOriginal) => {
  const real = await importOriginal<typeof import('react-markdown')>()
  const Counted = (props: ComponentProps<typeof real.default>) => {
    bump(counts.markdown, String(props.children))
    return <real.default {...props} />
  }
  return { ...real, default: Counted }
})

vi.mock('../../design/prism', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../design/prism')>()
  const ClarityRing = (props: ComponentProps<typeof real.ClarityRing>) => {
    bump(counts.clarity, props.value ?? 0)
    return <real.ClarityRing {...props} />
  }
  return { ...real, ClarityRing }
})

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal()),
  getDocumentsDetailed: vi.fn(),
  getSessions: vi.fn(),
  getSessionMessages: vi.fn(),
  sendChatStream: vi.fn(),
}))

const FIRST = 'The blades are inspected **every 90 days**.'
const tick = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('rendering while an answer streams', () => {
  beforeEach(() => {
    vi.mocked(api.getDocumentsDetailed).mockResolvedValue(documentList([]))
    vi.mocked(api.getSessions).mockResolvedValue({ sessions: [] })
    vi.mocked(api.getSessionMessages).mockImplementation(async (id) => ({ session_id: id, grounded_at: 0.6, turns: [] }))
  })

  it('does not re-render or re-parse an earlier answer', async () => {
    vi.mocked(api.sendChatStream).mockImplementationOnce(async ({ onToken, onDone }) => {
      onToken?.(FIRST)
      onDone?.(done({ sources: [SOURCE], confidence: 0.81, turn_id: 1 }))
    })
    render(<MemoryRouter><AuthProvider><ChatLayout addToast={vi.fn()} /></AuthProvider></MemoryRouter>)
    const user = userEvent.setup()
    await user.type(screen.getByPlaceholderText(/ask anything/i), 'How often?{Enter}')
    expect((await screen.findByText('every 90 days')).tagName).toBe('STRONG')
    await act(tick)
    const before = { markdown: counts.markdown.get(FIRST), clarity: counts.clarity.get(0.81) }
    expect(before.markdown).toBeGreaterThan(0)
    expect(before.clarity).toBeGreaterThan(0)

    // A second answer arrives in twelve pieces, each its own render of the conversation
    let stream: Parameters<typeof api.sendChatStream>[0] | null = null
    let finish = () => {}
    vi.mocked(api.sendChatStream).mockImplementationOnce((options) => new Promise<void>((resolve) => {
      stream = options
      finish = resolve
    }))
    await user.type(screen.getByPlaceholderText(/ask anything/i), 'And who?{Enter}')
    let renderedPieces = 0
    for (let i = 0; i < 12; i++) {
      act(() => stream?.onToken?.(`word${i} `))
      if (document.querySelector('[aria-busy="true"]')?.textContent?.includes(`word${i}`)) renderedPieces += 1
    }
    await act(async () => {
      stream?.onDone?.(done({ sources: [SOURCE], confidence: 0.64, turn_id: 2 }))
      finish()
    })
    expect(await screen.findByText(/word11/)).toBeTruthy()
    await act(tick)

    expect(renderedPieces).toBe(12)  // the stream really did render piece by piece
    expect(counts.markdown.get(FIRST)).toBe(before.markdown)
    expect(counts.clarity.get(0.81)).toBe(before.clarity)
  })
})
