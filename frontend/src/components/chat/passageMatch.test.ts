import { describe, expect, it } from 'vitest'
import { piecesOfPassage, wordsOf } from './passageMatch'

// A page as pdf.js gives it: one piece per run of text, lines split anywhere
const PAGE = [
  'Result For Splitting 80:20',
  'From Tabel 4, we conclude that XGBoost Classifier has the',
  'highest accuracy of 83.7% and Boosted Random Forest has the',
  'lowest accuracy of 81.8%. It means that XGBoost Classifier can',
  'predict the class better than the rest of the models.',
  'Gambar 5. (a) CM 80:20 Boosted Random Forest',
]

describe('piecesOfPassage', () => {
  it('marks the pieces that hold the passage', () => {
    const passage = 'From Tabel 4, we conclude that XGBoost Classifier has the highest accuracy of 83.7% and Boosted Random Forest has the lowest accuracy of 81.8%.'
    expect(piecesOfPassage(PAGE, passage)).toEqual([1, 2, 3])
  })

  it('finds a passage the other reader split and spaced differently', () => {
    // pypdf on the server read "Classifier" as "Classi fier" and joined the lines
    const passage = 'we conclude that XGBoost Classi fier has the highest accuracy of 83.7% and Boosted Random Forest has the lowest accuracy'
    expect(piecesOfPassage(PAGE, passage)).toEqual([1, 2, 3])
  })

  it('does not mark a short phrase the passage shares with the page', () => {
    expect(piecesOfPassage(PAGE, 'The Boosted Random Forest is a model of its own.')).toEqual([])
  })

  it('marks nothing when the passage is not on the page', () => {
    expect(piecesOfPassage(PAGE, 'The xBD dataset contains 11,034 pairs of satellite images.')).toEqual([])
    expect(piecesOfPassage([], 'anything at all here')).toEqual([])
  })
})

describe('wordsOf', () => {
  it('keeps letters and digits of any script, in lower case', () => {
    expect(wordsOf('Ω(h) = γT, 83.7% Müller')).toEqual(['ω', 'h', 'γt', '83', '7', 'müller'])
  })
})
