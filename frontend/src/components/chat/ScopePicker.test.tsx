import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ScopePicker, { describeChoice } from './ScopePicker'
import { documentRecord } from '../../test/fixtures'

const PDF = documentRecord({ id: 3, filename: '13003-64313-1-PB.pdf', title: 'Classification of Maternal Health Risks using Boosting Technique', kind: 'pdf' })
const PAPER = documentRecord({ id: 4, filename: 'Double-Column-Format-1-1 (1).docx', title: 'Automated Post-Disaster Infrastructure Assessment', kind: 'docx' })
const LETTER = documentRecord({ id: 5, filename: 'Tirth Ganatra Recos.docx', title: 'Recommendation Letter', kind: 'docx' })
const LIBRARY = [PDF, PAPER, LETTER]

function renderPicker(value: number[] | null = null) {
  const onChange = vi.fn()
  render(<ScopePicker documents={LIBRARY} value={value} onChange={onChange} />)
  return { onChange, user: userEvent.setup() }
}

describe('Search in', () => {
  it('lists every document by its title, with its file name, and the kinds there are', async () => {
    const { user } = renderPicker()
    const button = screen.getByRole('button', { name: /search in all documents/i })
    await user.click(button)
    expect(button.getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByRole('checkbox', { name: /Classification of Maternal Health Risks/ })).toBeTruthy()
    expect(screen.getByText('13003-64313-1-PB.pdf')).toBeTruthy()
    expect(screen.getByRole('radio', { name: /every PDF/i })).toBeTruthy()
    expect(screen.getByRole('radio', { name: /every Word file/i })).toBeTruthy()
    expect((screen.getByRole('radio', { name: /all documents/i }) as HTMLInputElement).checked).toBe(true)
  })

  it('searches the documents ticked, every file of a kind, or all of them again', async () => {
    const { user, onChange } = renderPicker()
    await user.click(screen.getByRole('button', { name: /search in/i }))
    await user.click(screen.getByRole('checkbox', { name: /Automated Post-Disaster/ }))
    expect(onChange).toHaveBeenLastCalledWith([4])
    await user.click(screen.getByRole('radio', { name: /every Word file/i }))
    expect(onChange).toHaveBeenLastCalledWith([4, 5])
  })

  it('unticking the last document searches all of them', async () => {
    const { user, onChange } = renderPicker([4])
    await user.click(screen.getByRole('button', { name: /search in/i }))
    await user.click(screen.getByRole('checkbox', { name: /Automated Post-Disaster/ }))
    expect(onChange).toHaveBeenLastCalledWith(null)
    await user.click(screen.getByRole('radio', { name: /all documents/i }))
    expect(onChange).toHaveBeenLastCalledWith(null)
  })

  it('closes on Escape and gives the focus back to its button', async () => {
    const { user } = renderPicker()
    const button = screen.getByRole('button', { name: /search in/i })
    await user.click(button)
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('group', { name: 'Search in' })).toBeNull()
    expect(document.activeElement).toBe(button)
  })

  it('says what is chosen in a few words', () => {
    expect(describeChoice(LIBRARY, null)).toBe('All documents')
    expect(describeChoice(LIBRARY, [5])).toBe('Recommendation Letter')
    expect(describeChoice(LIBRARY, [3])).toBe('Classification of Maternal He…')
    expect(describeChoice(LIBRARY, [4, 5])).toBe('Every Word file')
    expect(describeChoice(LIBRARY, [3, 5])).toBe('2 documents')
  })
})
