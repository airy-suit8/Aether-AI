import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import SourceViewer from './SourceViewer'
import * as api from '../../services/api'
import * as pdf from '../../services/pdf'
import type { PassageView, Source } from '../../services/api'

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal()),
  getPassage: vi.fn(),
  getDocumentFile: vi.fn(),
}))
vi.mock('../../services/pdf', () => ({ drawPage: vi.fn() }))

const CITED = 'From Tabel 4, we conclude that XGBoost Classifier has the highest accuracy of 83.7% and Boosted Random Forest has the lowest accuracy of 81.8%.'
const SOURCE: Source = { source: '13003-64313-1-PB.pdf', page: 20, score: 0.72, snippet: CITED.slice(0, 60), document_id: 3, kind: 'pdf', passage: 62, passages: 74 }

function view(fields: Partial<PassageView> = {}): PassageView {
  return {
    document_id: 3, filename: '13003-64313-1-PB.pdf', kind: 'pdf', passages: 74, original: true,
    items: [
      { passage: 61, page: 19, text: 'Recall 0.806 0.802 0.816 F1 Score 0.802 0.799 0.812.' },
      { passage: 62, page: 20, text: CITED },
      { passage: 63, page: 20, text: 'Classifier has 169, and XGBoost Classifier has 170 True Positive.' },
    ],
    ...fields,
  }
}

const placed = (text: string, top: number) => ({ text, left: 72, top, width: 300, height: 12 })

describe('SourceViewer', () => {
  beforeEach(() => {
    vi.mocked(api.getPassage).mockReset()
    vi.mocked(api.getDocumentFile).mockReset()
    vi.mocked(pdf.drawPage).mockReset()
  })

  it('draws the cited page of a kept PDF and marks the passage on it', async () => {
    vi.mocked(api.getPassage).mockResolvedValue(view())
    vi.mocked(api.getDocumentFile).mockResolvedValue(new ArrayBuffer(8))
    vi.mocked(pdf.drawPage).mockResolvedValue({
      page: 20, pages: 23, width: 600, height: 800,
      texts: [
        placed('Result For Splitting 80:20', 40),
        placed('From Tabel 4, we conclude that XGBoost Classifier has the', 60),
        placed('highest accuracy of 83.7% and Boosted Random Forest has the', 74),
        placed('lowest accuracy of 81.8%.', 88),
        placed('Gambar 5. (a) CM 80:20', 300),
      ],
    })
    render(<SourceViewer source={SOURCE} n={2} onClose={() => {}} />)

    expect(await screen.findByText('The cited passage is marked.')).toBeTruthy()
    expect(screen.getByRole('dialog', { name: '13003-64313-1-PB.pdf' })).toBeTruthy()
    expect(screen.getByRole('img', { name: 'Page 20 of 13003-64313-1-PB.pdf' })).toBeTruthy()
    expect(screen.getByText('Page 20 of 23 · passage 62 of 74')).toBeTruthy()
    expect(api.getPassage).toHaveBeenCalledWith(3, 62)
    expect(vi.mocked(pdf.drawPage).mock.calls[0][1]).toBe(20)
    // The three lines of the passage, not the heading or the figure caption
    expect(document.querySelectorAll('.x-viewer__mark')).toHaveLength(3)
  })

  it('says so when the passage cannot be marked on the page', async () => {
    vi.mocked(api.getPassage).mockResolvedValue(view())
    vi.mocked(api.getDocumentFile).mockResolvedValue(new ArrayBuffer(8))
    vi.mocked(pdf.drawPage).mockResolvedValue({ page: 20, pages: 23, width: 600, height: 800, texts: [] })
    render(<SourceViewer source={SOURCE} n={2} onClose={() => {}} />)
    expect(await screen.findByText(/could not be marked on this page/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Open the whole PDF' })).toBeTruthy()
  })

  it('shows the text of a PDF whose file is not kept, and how to keep it', async () => {
    vi.mocked(api.getPassage).mockResolvedValue(view({ original: false }))
    render(<SourceViewer source={SOURCE} n={2} onClose={() => {}} />)
    expect(await screen.findByText(/Upload the same file again to see the page/)).toBeTruthy()
    expect(screen.getByText(CITED).tagName).toBe('MARK')
    expect(screen.getAllByRole('listitem')).toHaveLength(3)
    expect(api.getDocumentFile).not.toHaveBeenCalled()
  })

  it('shows a Word passage among its neighbours', async () => {
    vi.mocked(api.getPassage).mockResolvedValue(view({
      kind: 'docx', filename: 'Recos.docx', original: false,
      items: [{ passage: 1, page: 1, text: 'Recommendation Letter' }, { passage: 2, page: 1, text: 'Tirth developed an emergency application.' }],
    }))
    render(<SourceViewer source={{ ...SOURCE, source: 'Recos.docx', kind: 'docx', passage: 2, passages: 12 }} n={1} onClose={() => {}} />)
    expect((await screen.findByText('Tirth developed an emergency application.')).tagName).toBe('MARK')
    expect(screen.getByText('Passage 2 of 74')).toBeTruthy()
    expect(screen.queryByText(/Upload the same file again/)).toBeNull()
  })

  it('says why when the document cannot be opened', async () => {
    vi.mocked(api.getPassage).mockRejectedValue(new Error('That document has no such passage.'))
    render(<SourceViewer source={SOURCE} n={2} onClose={() => {}} />)
    expect((await screen.findByRole('alert')).textContent).toBe('That document has no such passage.')
    await waitFor(() => expect(screen.queryByText('Opening')).toBeNull())
  })
})
