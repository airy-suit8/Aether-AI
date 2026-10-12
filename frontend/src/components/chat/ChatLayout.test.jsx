import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ChatLayout from './ChatLayout'
import { AuthProvider } from '../../services/AuthContext'
import * as api from '../../services/api'

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal()),
  getDocuments: vi.fn(),
  sendChatStream: vi.fn(),
  sendChat: vi.fn(),
  uploadDocument: vi.fn(),
  clearSession: vi.fn(),
}))

const SOURCE = {
  source: 'zephyr_manual.txt',
  page: 1,
  score: 0.834,
  snippet: 'The Zephyr turbine maintenance schedule requires a blade inspection every 90 days.',
}

function renderChat() {
  const addToast = vi.fn()
  render(
    <AuthProvider>
      <ChatLayout onNavigateHome={vi.fn()} addToast={addToast} />
    </AuthProvider>,
  )
  return { addToast }
}

async function ask(question) {
  const user = userEvent.setup()
  await user.type(screen.getByPlaceholderText(/ask anything/i), `${question}{Enter}`)
  return user
}

describe('ChatLayout', () => {
  beforeEach(() => {
    vi.mocked(api.getDocuments).mockResolvedValue({ documents: ['zephyr_manual.txt'], count: 1 })
    vi.mocked(api.sendChatStream).mockReset()
  })

  it('sends a question and shows the streamed answer with its source card', async () => {
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onToken, onDone }) => {
      onToken('The blades are inspected ')
      onToken('**every 90 days**.')
      onDone({ type: 'done', sources: [SOURCE], confidence: 0.81 })
    })
    renderChat()
    expect(await screen.findAllByText('zephyr_manual.txt')).not.toHaveLength(0)  // sidebar document list

    const user = await ask('How often are the blades inspected?')

    expect(api.sendChatStream).toHaveBeenCalledTimes(1)
    expect(api.sendChatStream.mock.calls[0][0]).toMatchObject({
      question: 'How often are the blades inspected?', mode: 'default',
    })
    expect(screen.getByText('How often are the blades inspected?')).toBeTruthy()

    // The answer is rendered as Markdown
    const bold = await screen.findByText('every 90 days')
    expect(bold.tagName).toBe('STRONG')

    // One source card in the margin with file, page, score and the passage; a click pins it open
    const card = screen.getByText('Sources').parentElement
    expect(within(card).getByText('zephyr_manual.txt')).toBeTruthy()
    expect(within(card).getByText('p. 1')).toBeTruthy()
    expect(within(card).getByText('0.83')).toBeTruthy()
    expect(within(card).getByText(SOURCE.snippet)).toBeTruthy()
    const source = within(card).getByRole('button')
    expect(source.getAttribute('aria-expanded')).toBe('false')
    await user.click(source)
    expect(source.getAttribute('aria-expanded')).toBe('true')

    // The composer is usable again
    expect(screen.getByPlaceholderText(/ask anything/i).disabled).toBe(false)
  })

  it('shows a stream error as a toast and keeps no partial answer', async () => {
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onToken, onError }) => {
      onToken('Half an ')
      onError(new Error('The connection closed before the answer was complete. Please try again.'))
    })
    const { addToast } = renderChat()
    await ask('Will this fail?')

    expect(addToast).toHaveBeenCalledWith('The connection closed before the answer was complete. Please try again.', 'error')
    expect(screen.queryByText(/Half an/)).toBeNull()
    expect(screen.queryByText('Sources')).toBeNull()
    expect(screen.getByPlaceholderText(/ask anything/i).disabled).toBe(false)
  })

  it('passes the Hybrid mode to the request', async () => {
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onDone }) => onDone({ sources: [], confidence: 0 }))
    renderChat()
    const user = userEvent.setup()
    // The answer mode is one radio group now, not four toggle buttons
    await user.click(screen.getByRole('radio', { name: /hybrid/i }))
    await ask('Hybrid please')
    expect(api.sendChatStream.mock.calls[0][0].mode).toBe('hybrid')
  })
})
