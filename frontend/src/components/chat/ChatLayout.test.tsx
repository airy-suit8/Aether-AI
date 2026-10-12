import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ChatLayout from './ChatLayout'
import { AuthProvider } from '../../services/AuthContext'
import * as api from '../../services/api'
import { documentList, documentRecord, documentStatus, done, session, SOURCE, turn } from '../../test/fixtures'

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal()),
  getDocumentsDetailed: vi.fn(),
  getDocument: vi.fn(),
  deleteDocument: vi.fn(),
  sendChatStream: vi.fn(),
  sendChat: vi.fn(),
  uploadDocument: vi.fn(),
  clearSession: vi.fn(),
  getSessions: vi.fn(),
  getSessionMessages: vi.fn(),
}))

function renderChat() {
  const addToast = vi.fn()
  render(
    <AuthProvider>
      <ChatLayout onNavigateHome={vi.fn()} addToast={addToast} />
    </AuthProvider>,
  )
  return { addToast }
}

async function ask(question: string) {
  const user = userEvent.setup()
  await user.type(screen.getByPlaceholderText(/ask anything/i), `${question}{Enter}`)
  return user
}

describe('ChatLayout', () => {
  beforeEach(() => {
    vi.mocked(api.getDocumentsDetailed).mockReset()
    vi.mocked(api.getDocumentsDetailed).mockResolvedValue(documentList([documentRecord({ id: 7, filename: 'zephyr_manual.txt' })]))
    vi.mocked(api.deleteDocument).mockReset()
    vi.mocked(api.sendChatStream).mockReset()
    vi.mocked(api.clearSession).mockReset()
    vi.mocked(api.getSessions).mockReset()
    vi.mocked(api.getSessions).mockResolvedValue({ sessions: [] })
    vi.mocked(api.getSessionMessages).mockReset()
  })

  it('sends a question and shows the streamed answer with its source card', async () => {
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onToken, onDone }) => {
      onToken?.('The blades are inspected ')
      onToken?.('**every 90 days**.')
      onDone?.(done({ sources: [SOURCE], confidence: 0.81 }))
    })
    renderChat()
    expect(await screen.findAllByText('zephyr_manual.txt')).not.toHaveLength(0)  // sidebar document list

    const user = await ask('How often are the blades inspected?')

    expect(api.sendChatStream).toHaveBeenCalledTimes(1)
    expect(vi.mocked(api.sendChatStream).mock.calls[0][0]).toMatchObject({
      question: 'How often are the blades inspected?', mode: 'default',
    })
    expect(screen.getByText('How often are the blades inspected?')).toBeTruthy()

    // The answer is rendered as Markdown
    const bold = await screen.findByText('every 90 days')
    expect(bold.tagName).toBe('STRONG')

    // One source card in the margin with file, page, score and the passage; a click pins it open
    const card = screen.getByText('Sources').parentElement as HTMLElement
    expect(within(card).getByText('zephyr_manual.txt')).toBeTruthy()
    expect(within(card).getByText('p. 1')).toBeTruthy()
    expect(within(card).getByText('0.83')).toBeTruthy()
    expect(within(card).getByText(SOURCE.snippet)).toBeTruthy()
    const source = within(card).getByRole('button')
    expect(source.getAttribute('aria-expanded')).toBe('false')
    await user.click(source)
    expect(source.getAttribute('aria-expanded')).toBe('true')

    // The composer is usable again
    expect((screen.getByPlaceholderText(/ask anything/i) as HTMLTextAreaElement).disabled).toBe(false)
  })

  it('shows a stream error as a toast and keeps no partial answer', async () => {
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onToken, onError }) => {
      onToken?.('Half an ')
      onError?.(new Error('The connection closed before the answer was complete. Please try again.'))
    })
    const { addToast } = renderChat()
    await ask('Will this fail?')

    expect(addToast).toHaveBeenCalledWith('The connection closed before the answer was complete. Please try again.', 'error')
    expect(screen.queryByText(/Half an/)).toBeNull()
    expect(screen.queryByText('Sources')).toBeNull()
    expect((screen.getByPlaceholderText(/ask anything/i) as HTMLTextAreaElement).disabled).toBe(false)
  })

  it('passes the Hybrid mode to the request', async () => {
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onDone }) => onDone?.(done()))
    renderChat()
    const user = userEvent.setup()
    // The answer mode is one radio group now, not four toggle buttons
    await user.click(screen.getByRole('radio', { name: /hybrid/i }))
    await ask('Hybrid please')
    expect(vi.mocked(api.sendChatStream).mock.calls[0][0].mode).toBe('hybrid')
  })

  it('removes one document after a second, confirming click', async () => {
    vi.mocked(api.deleteDocument).mockResolvedValue({ message: "Deleted 'zephyr_manual.txt' (1 chunks).", filename: 'zephyr_manual.txt', deleted: 1 })
    const { addToast } = renderChat()
    const user = userEvent.setup()
    const remove = await screen.findByRole('button', { name: 'Remove zephyr_manual.txt' })

    // The first click only arms the button: nothing is deleted yet
    await user.click(remove)
    expect(api.deleteDocument).not.toHaveBeenCalled()
    const confirm = screen.getByRole('button', { name: 'Confirm removing zephyr_manual.txt' })
    expect(confirm.textContent).toBe('Remove?')

    // The second click deletes it by id, says so, and reloads the library
    vi.mocked(api.getDocumentsDetailed).mockResolvedValue(documentList([]))
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

  it('does not send a file over the 50 MB limit, and says why', async () => {
    const { addToast } = renderChat()
    const user = userEvent.setup()
    const big = new File(['x'], 'huge.pdf', { type: 'application/pdf' })
    Object.defineProperty(big, 'size', { value: 50 * 1024 * 1024 + 1 })
    await user.upload(document.querySelector('input[type="file"]') as HTMLInputElement, big)
    expect(api.uploadDocument).not.toHaveBeenCalled()
    expect(addToast).toHaveBeenCalledWith('huge.pdf is larger than 50 MB, the most one file may be.', 'error')
  })

  it('uploads a file, waits while it is read, and says how many passages it made', async () => {
    vi.mocked(api.uploadDocument).mockResolvedValue({ document_id: 9, filename: 'plan.pdf', status: 'processing', replaces: true, message: "Reading 'plan.pdf'." })
    vi.mocked(api.getDocument).mockReset()
    vi.mocked(api.getDocument).mockResolvedValue(documentStatus({ id: 9, filename: 'plan.pdf', status: 'ready', pages: 3, chunks: 12 }))
    const { addToast } = renderChat()
    const user = userEvent.setup()
    await user.upload(document.querySelector('input[type="file"]') as HTMLInputElement, new File(['%PDF'], 'plan.pdf', { type: 'application/pdf' }))
    await vi.waitFor(() => expect(addToast).toHaveBeenCalledWith(
      'Added plan.pdf: 12 passages from 3 pages. It replaced the earlier file of that name.', 'success'))
    expect(api.getDocument).toHaveBeenCalledWith(9)
    expect(api.deleteDocument).not.toHaveBeenCalled()
  })

  it('shows why an upload could not be read, and takes it out of the library', async () => {
    vi.mocked(api.uploadDocument).mockResolvedValue({ document_id: 10, filename: 'scan.pdf', status: 'processing', replaces: false, message: "Reading 'scan.pdf'." })
    vi.mocked(api.getDocument).mockReset()
    vi.mocked(api.getDocument).mockResolvedValue(documentStatus({
      id: 10, filename: 'scan.pdf', status: 'failed', error: "'scan.pdf' has no text to read.", pages: 0, chunks: 0,
    }))
    vi.mocked(api.deleteDocument).mockResolvedValue({ message: "Deleted 'scan.pdf' (0 chunks).", filename: 'scan.pdf', deleted: 0 })
    const { addToast } = renderChat()
    const user = userEvent.setup()
    await user.upload(document.querySelector('input[type="file"]') as HTMLInputElement, new File(['%PDF'], 'scan.pdf', { type: 'application/pdf' }))
    await vi.waitFor(() => expect(addToast).toHaveBeenCalledWith("'scan.pdf' has no text to read.", 'error'))
    expect(api.deleteDocument).toHaveBeenCalledWith(10)
  })

  it('marks a document that is still being read, or could not be read, in words', async () => {
    vi.mocked(api.getDocumentsDetailed).mockResolvedValue(documentList([
      documentRecord({ id: 1, filename: 'big.pdf', status: 'processing' }),
      documentRecord({ id: 2, filename: 'bad.pdf', status: 'failed', error: 'It is damaged.' }),
      documentRecord({ id: 3, filename: 'good.pdf', status: 'ready' }),
    ]))
    renderChat()
    expect(await screen.findByText('Reading')).toBeTruthy()
    expect(screen.getByText('Could not be read').getAttribute('title')).toBe('It is damaged.')
    expect(screen.getAllByText(/Reading|Could not be read/)).toHaveLength(2)
  })

  it('picks up the latest conversation, with its sources, after a reload', async () => {
    vi.mocked(api.getSessions).mockResolvedValue({ sessions: [session({ session_id: 'session_42', title: 'How often?', turns: 1 })] })
    vi.mocked(api.getSessionMessages).mockResolvedValue({ session_id: 'session_42', turns: [turn({
      turn_id: 5, question: 'How often are the blades inspected?', answer: 'Every **90 days**.',
      sources: [SOURCE], confidence: 0.81, mode: 'original', tool_used: null, feedback: 0, created_at: '2026-10-12T10:00:00',
    })] })
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onDone }) => onDone?.(done()))
    renderChat()
    expect(await screen.findByText('How often are the blades inspected?')).toBeTruthy()
    expect((await screen.findByText('90 days')).tagName).toBe('STRONG')
    expect(within(screen.getByText('Sources').parentElement as HTMLElement).getByText(SOURCE.snippet)).toBeTruthy()
    expect(screen.getByText('default mode')).toBeTruthy()
    expect(api.getSessionMessages).toHaveBeenCalledWith('session_42')

    // The next question goes on in the same conversation
    await ask('And who inspects them?')
    expect(vi.mocked(api.sendChatStream).mock.calls[0][0].sessionId).toBe('session_42')
  })

  it('starts a new thread without deleting the old one from the server', async () => {
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onToken, onDone }) => {
      onToken?.('An answer.')
      onDone?.(done())
    })
    const { addToast } = renderChat()
    await ask('A first question')
    const before = vi.mocked(api.sendChatStream).mock.calls[0][0].sessionId
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'New thread' }))
    expect(api.clearSession).not.toHaveBeenCalled()
    expect(addToast).toHaveBeenCalledWith('New thread started', 'info')
    expect(screen.queryByText('A first question')).toBeNull()
    await ask('A second question')
    expect(vi.mocked(api.sendChatStream).mock.calls[1][0].sessionId).not.toBe(before)
  })

  it('deletes the conversation from the server only when asked to in Settings', async () => {
    vi.mocked(api.clearSession).mockResolvedValue({ message: 'Session cleared', session_id: 'session_1' })
    const { addToast } = renderChat()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Settings' }))
    await user.click(screen.getByRole('button', { name: 'Clear conversation' }))
    expect(api.clearSession).toHaveBeenCalledTimes(1)
    expect(addToast).toHaveBeenCalledWith('Conversation deleted', 'info')
  })

  it('says "1 passage from 1 page", not "1 passages"', async () => {
    vi.mocked(api.uploadDocument).mockResolvedValue({ document_id: 11, filename: 'note.txt', status: 'processing', replaces: false, message: "Reading 'note.txt'." })
    vi.mocked(api.getDocument).mockReset()
    vi.mocked(api.getDocument).mockResolvedValue(documentStatus({ id: 11, filename: 'note.txt', status: 'ready', pages: 1, chunks: 1 }))
    const { addToast } = renderChat()
    const user = userEvent.setup()
    await user.upload(document.querySelector('input[type="file"]') as HTMLInputElement, new File(['hi'], 'note.txt', { type: 'text/plain' }))
    await vi.waitFor(() => expect(addToast).toHaveBeenCalledWith('Added note.txt: 1 passage from 1 page.', 'success'))
  })
})
