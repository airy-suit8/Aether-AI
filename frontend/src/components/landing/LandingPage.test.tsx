import { createRef } from 'react'
import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import LandingPage from './LandingPage'
import ChatWindow from '../chat/ChatWindow'
import { AuthProvider } from '../../services/AuthContext'

function renderLanding() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <AuthProvider>
        <LandingPage />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('the start page', () => {
  it('argues for the product with five claims, each with its evidence, and no sample data', () => {
    const { container } = renderLanding()
    const why = screen.getByRole('region', { name: 'Five claims, and what stands behind each.' })
    expect(within(why).getAllByRole('listitem')).toHaveLength(5)
    const evidence = within(why).getByRole('complementary', { name: 'Evidence' })
    expect(evidence.querySelectorAll('.l-proof')).toHaveLength(5)
    expect(within(why).getByText('It shows where every answer came from.')).toBeTruthy()
    expect(within(evidence).getByText('Beside every answer')).toBeTruthy()

    // Nothing pretends to be a conversation: no sample question, no demo controls
    const text = container.textContent ?? ''
    for (const gone of ['sample', 'Play a case', 'Try a question', 'zephyr', 'Grounded', 'Built by']) {
      expect(text.toLowerCase()).not.toContain(gone.toLowerCase())
    }
    expect(screen.queryByPlaceholderText(/question/i)).toBeNull()
  })

  it('lights the evidence of the claim that is pointed at, and quietens the others', async () => {
    renderLanding()
    const user = userEvent.setup()
    const cards = () => [...document.querySelectorAll('.l-proof')].map((card) => card.getAttribute('data-active'))
    expect(cards()).toEqual(['false', 'false', 'false', 'false', 'false'])

    // Focus, so the keyboard lights a claim's evidence as a pointer does
    const marker = screen.getByRole('button', { name: 'Evidence 2: Not found, said plainly' })
    fireEvent.focus(marker)
    expect(cards()).toEqual(['false', 'true', 'false', 'false', 'false'])
    expect(document.querySelector('.l-claims')?.getAttribute('data-dim')).toBe('true')
    expect(marker.closest('li')?.getAttribute('data-active')).toBe('true')

    fireEvent.blur(marker)
    expect(cards()).toEqual(['false', 'false', 'false', 'false', 'false'])

    await user.hover(document.querySelectorAll('.l-proof')[4])  // pointing at a card lights its claim
    expect(document.querySelectorAll('.l-claim')[4].getAttribute('data-active')).toBe('true')
  })

  describe('the trace, when the section is first seen', () => {
    let seen: (() => void) | null = null

    beforeEach(() => {
      vi.useFakeTimers()
      // jsdom has no IntersectionObserver: this one reports the section as seen when the test says so
      vi.stubGlobal('IntersectionObserver', class {
        constructor(callback: IntersectionObserverCallback) {
          seen = () => callback([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver)
        }
        observe() {}
        disconnect() {}
      })
    })

    afterEach(() => {
      vi.useRealTimers()
      vi.unstubAllGlobals()
      vi.restoreAllMocks()
      seen = null
    })

    // jsdom lays nothing out: put the evidence to the right of the claims, as a wide screen does,
    // so that there is room for the threads
    const wideScreen = () => vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
      const left = this.classList.contains('l-proof') ? 800 : 0
      return { x: left, y: 0, left, top: 0, right: left + 500, bottom: 40, width: 500, height: 40, toJSON: () => ({}) } as DOMRect
    })

    const lit = () => [...document.querySelectorAll('.l-proof')].map((card) => card.getAttribute('data-active') === 'true')
    const only = (n: number) => [1, 2, 3, 4, 5].map((k) => k === n)
    const threads = () => [...document.querySelectorAll('.p-threads path')].map((path) => path.getAttribute('data-drawn') === 'true')
    const firstDrawn = (n: number) => [1, 2, 3, 4, 5].map((k) => k <= n)

    it('draws each thread in turn, lighting its claim and evidence, then rests with all five drawn', () => {
      wideScreen()
      renderLanding()
      act(() => seen?.())
      for (const n of [1, 2, 3, 4, 5]) {
        act(() => { vi.advanceTimersByTime(n === 1 ? 0 : 720) })
        expect(threads()).toEqual(firstDrawn(n))
        expect(lit()).toEqual(only(n))
        expect(document.querySelectorAll('.l-claim')[n - 1].getAttribute('data-active')).toBe('true')
      }
      act(() => { vi.advanceTimersByTime(900) })
      expect(threads()).toEqual(firstDrawn(5))
      expect(lit()).toEqual(only(0))
      expect(document.querySelector('.l-claims')?.getAttribute('data-dim')).toBe('false')
    })

    it('draws nothing until the claims are on screen', () => {
      wideScreen()
      renderLanding()
      act(() => { vi.advanceTimersByTime(5000) })
      expect(threads()).toEqual(firstDrawn(0))
      expect(lit()).toEqual(only(0))
    })

    it('hands over to the reader the moment they point at a claim', () => {
      wideScreen()
      renderLanding()
      act(() => seen?.())
      act(() => { vi.advanceTimersByTime(720) })
      expect(lit()).toEqual(only(2))

      fireEvent.pointerEnter(document.querySelectorAll('.l-claim')[4])
      expect(lit()).toEqual(only(5))
      expect(threads()).toEqual(firstDrawn(5))  // every thread is there for them to follow
      act(() => { vi.advanceTimersByTime(5000) })  // the trace does not take it back
      expect(lit()).toEqual(only(5))
      fireEvent.pointerLeave(document.querySelectorAll('.l-claim')[4])
      expect(lit()).toEqual(only(0))
    })

    it('does not start once the reader has already pointed at something', () => {
      wideScreen()
      renderLanding()
      fireEvent.focus(screen.getByRole('button', { name: 'Evidence 3: One account, one library' }))
      act(() => seen?.())
      act(() => { vi.advanceTimersByTime(5000) })
      expect(lit()).toEqual(only(3))
    })

    it('traces nothing on a narrow screen, where the evidence is below the claims and no thread is drawn', () => {
      renderLanding()
      expect(threads()).toEqual([])
      act(() => seen?.())
      for (const wait of [0, 720, 720, 5000]) {
        act(() => { vi.advanceTimersByTime(wait) })
        expect(lit()).toEqual(only(0))
      }
    })
  })

  it('still opens the sign-in sheet', async () => {
    renderLanding()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Start asking' }))
    expect(await screen.findByRole('dialog')).toBeTruthy()
  })
})

describe('the empty workspace', () => {
  function renderEmpty(hasDocuments: boolean) {
    return render(
      <ChatWindow messages={[]} streamingText="" streamingPhase="" isLoading={false} streamRef={createRef<HTMLDivElement>()}
        hasDocuments={hasDocuments} onSuggest={vi.fn()} />,
    )
  }

  it('says what to do next, and does not repeat the start page headline', () => {
    const { container, unmount } = renderEmpty(false)
    expect(screen.getByRole('heading', { name: 'Add a document to begin.' })).toBeTruthy()
    expect(container.textContent).not.toMatch(/white light|spectrum/i)
    unmount()

    renderEmpty(true)
    expect(screen.getByRole('heading', { name: 'What do you want to know?' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Summarise the main points' })).toBeTruthy()
  })
})
