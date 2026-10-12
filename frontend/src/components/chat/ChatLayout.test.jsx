import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ChatLayout from './ChatLayout'
import { AuthProvider } from '../../services/AuthContext'
import * as api from '../../services/api'

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal()),
  getDocumentsDetailed: vi.fn(),
  deleteDocument: vi.fn(),
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
    vi.mocked(api.getDocumentsDetailed).mockReset()
    vi.mocked(api.getDocumentsDetailed).mockResolvedValue({ documents: [{ id: 7, filename: 'zephyr_manual.txt' }], count: 1 })
    vi.mocked(api.deleteDocument).mockReset()
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

  it('removes one document after a second, confirming click', async () => {
    vi.mocked(api.deleteDocument).mockResolvedValue({ filename: 'zephyr_manual.txt', deleted: 1 })
    const { addToast } = renderChat()
    const user = userEvent.setup()
    const remove = await screen.findByRole('button', { name: 'Remove zephyr_manual.txt' })

    // The first click only arms the button: nothing is deleted yet
    await user.click(remove)
    expect(api.deleteDocument).not.toHaveBeenCalled()
    const confirm = screen.getByRole('button', { name: 'Confirm removing zephyr_manual.txt' })
    expect(confirm.textContent).toBe('Remove?')

    // The second click deletes it by id, says so, and reloads the library
    vi.mocked(api.getDocumentsDetailed).mockResolvedValue({ documents: [], count: 0 })
    await user.click(confirm)
    expect(api.deleteDocument).toHaveBeenCalledWith(7)
    expect(await screen.findByText('No documents yet')).toBeTruthy()
    expect(addToast).toHaveBeenCalledWith('Removed zephyr_manual.txt', 'info')
  })

  it('an armed remove button disarms when focus leaves it', async () => {
    renderChat()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Remove zephyr_manual.txt' }))
    await user.click(screen.getByPlaceholderText(/ask anything/i))
    expect(screen.getByRole('button', { name: 'Remove zephyr_manual.txt' })).toBeTruthy()
    expect(api.deleteDocument).not.toHaveBeenCalled()
  })

  it('says so when a document cannot be removed, and keeps it listed', async () => {
    vi.mocked(api.deleteDocument).mockRejectedValue(new Error('No such document.'))
    const { addToast } = renderChat()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Remove zephyr_manual.txt' }))
    await user.click(screen.getByRole('button', { name: 'Confirm removing zephyr_manual.txt' }))
    expect(addToast).toHaveBeenCalledWith('No such document.', 'error')
    expect(await screen.findByRole('button', { name: 'Remove zephyr_manual.txt' })).toBeTruthy()
  })
})
