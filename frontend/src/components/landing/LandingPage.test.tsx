import { createRef } from 'react'
import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
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
