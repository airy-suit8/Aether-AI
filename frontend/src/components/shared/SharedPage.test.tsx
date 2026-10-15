import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import SharedPage from './SharedPage'
import * as api from '../../services/api'
import { SOURCE } from '../../test/fixtures'

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal()),
  getSharedConversation: vi.fn(),
}))

const TOKEN = 'kQ3vX9pLm2Zr7TtYb5NwEa8HcJd4UfGs'

function renderShared() {
  render(
    <MemoryRouter initialEntries={[`/shared/${TOKEN}`]}>
      <Routes>
        <Route path="shared/:token" element={<SharedPage />} />
        <Route path="/" element={<p>the start page</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('SharedPage', () => {
  beforeEach(() => {
    vi.mocked(api.getSharedConversation).mockReset()
  })

  it('shows the conversation with its sources, read only', async () => {
    vi.mocked(api.getSharedConversation).mockResolvedValue({
      title: 'Blade inspections',
      grounded_at: 0.6,
      turns: [{
        question: 'How often are the blades inspected?', answer: 'Every **90 days**.', confidence: 0.83, mode: 'original',
        sources: [SOURCE], tool_used: null, created_at: '2026-10-13T10:00:00',
      }],
    })
    renderShared()

    expect(await screen.findByRole('heading', { level: 1, name: 'Blade inspections' })).toBeTruthy()
    expect(api.getSharedConversation).toHaveBeenCalledWith(TOKEN)
    expect(screen.getByText('Shared conversation · read only')).toBeTruthy()
    expect(screen.getByRole('heading', { level: 2, name: 'How often are the blades inspected?' })).toBeTruthy()
    expect(screen.getByText('90 days').tagName).toBe('STRONG')
    expect(screen.getByText('zephyr_manual.txt')).toBeTruthy()

    // Nothing to do here but read: no rating, no composer
    expect(screen.queryByRole('button', { name: 'Helpful' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Not helpful' })).toBeNull()
    expect(screen.queryByPlaceholderText(/ask anything/i)).toBeNull()
    expect(screen.getByRole('link', { name: 'Ask your own documents' }).getAttribute('href')).toBe('/')
  })

  it('does not print the first question twice when the conversation has no name of its own', async () => {
    vi.mocked(api.getSharedConversation).mockResolvedValue({
      title: 'How often are the blades inspected?',
      grounded_at: 0.6,
      turns: [{
        question: 'How often are the blades inspected?', answer: 'Every 90 days.', confidence: 0.83, mode: 'original',
        sources: [], tool_used: null, created_at: '2026-10-13T10:00:00',
      }],
    })
    renderShared()
    expect(await screen.findByRole('heading', { level: 1, name: 'A conversation shared with you' })).toBeTruthy()
    expect(screen.getAllByText('How often are the blades inspected?')).toHaveLength(1)
  })

  it('says the link no longer works when it was withdrawn or never made', async () => {
    vi.mocked(api.getSharedConversation).mockRejectedValue(
      new api.ApiError('This conversation is not shared, or its link was withdrawn.', 404))
    renderShared()
    expect(await screen.findByRole('heading', { level: 1, name: 'This link no longer works.' })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Go to the start page' }).getAttribute('href')).toBe('/')
  })

  it('says so when the server could not be reached, without calling the link dead', async () => {
    vi.mocked(api.getSharedConversation).mockRejectedValue(new api.ApiError('The request failed (error 503). Please try again.', 503))
    renderShared()
    expect(await screen.findByRole('heading', { level: 1, name: 'This conversation could not be loaded.' })).toBeTruthy()
    expect(screen.getByText('The request failed (error 503). Please try again.')).toBeTruthy()
  })
})
