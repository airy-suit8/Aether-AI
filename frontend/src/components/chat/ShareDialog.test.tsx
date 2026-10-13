import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ShareDialog, { sharedLink } from './ShareDialog'
import * as api from '../../services/api'

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal()),
  getSharing: vi.fn(),
  shareSession: vi.fn(),
  stopSharing: vi.fn(),
}))

const TOKEN = 'kQ3vX9pLm2Zr7TtYb5NwEa8HcJd4UfGs'

function renderDialog() {
  const addToast = vi.fn()
  const onClose = vi.fn()
  render(<ShareDialog sessionId="session_1" onClose={onClose} addToast={addToast} />)
  return { addToast, onClose }
}

describe('ShareDialog', () => {
  beforeEach(() => {
    vi.mocked(api.getSharing).mockReset()
    vi.mocked(api.shareSession).mockReset()
    vi.mocked(api.stopSharing).mockReset()
  })

  it('says who can read what, makes the link, and copies it', async () => {
    vi.mocked(api.getSharing).mockResolvedValue({ session_id: 'session_1', token: null })
    vi.mocked(api.shareSession).mockResolvedValue({ session_id: 'session_1', token: TOKEN })
    const { addToast } = renderDialog()
    const user = userEvent.setup()

    expect(screen.getByText(/Anyone with the link can read this conversation and the passages it cites/)).toBeTruthy()
    const create = await screen.findByRole('button', { name: 'Create link' })
    expect(api.getSharing).toHaveBeenCalledWith('session_1')
    expect(screen.queryByLabelText('Link')).toBeNull()

    await user.click(create)
    expect(api.shareSession).toHaveBeenCalledWith('session_1')
    const field = await screen.findByLabelText<HTMLInputElement>('Link')
    expect(field.value).toBe(`${window.location.origin}/shared/${TOKEN}`)
    expect(field.value).toBe(sharedLink(TOKEN))
    expect(field.readOnly).toBe(true)

    await user.click(screen.getByRole('button', { name: 'Copy link' }))
    expect(await navigator.clipboard.readText()).toBe(sharedLink(TOKEN))
    expect(addToast).toHaveBeenCalledWith('Link copied', 'success')
  })

  it('shows the link of a conversation that is already shared, and withdraws it', async () => {
    vi.mocked(api.getSharing).mockResolvedValue({ session_id: 'session_1', token: TOKEN })
    vi.mocked(api.stopSharing).mockResolvedValue({ session_id: 'session_1', token: null })
    renderDialog()
    const user = userEvent.setup()

    expect((await screen.findByLabelText<HTMLInputElement>('Link')).value).toBe(sharedLink(TOKEN))
    expect(api.shareSession).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Stop sharing' }))
    expect(api.stopSharing).toHaveBeenCalledWith('session_1')
    expect(await screen.findByRole('button', { name: 'Create link' })).toBeTruthy()
    expect(screen.queryByLabelText('Link')).toBeNull()
  })

  it('says so when the link cannot be made, and stays as it was', async () => {
    vi.mocked(api.getSharing).mockResolvedValue({ session_id: 'session_1', token: null })
    vi.mocked(api.shareSession).mockRejectedValue(new Error('No such conversation.'))
    const { addToast } = renderDialog()
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Create link' }))
    expect(addToast).toHaveBeenCalledWith('No such conversation.', 'error')
    expect(screen.getByRole('button', { name: 'Create link' })).toBeTruthy()
  })
})
