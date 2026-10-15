/**
 * Find a passage on a PDF page: which of the page's text pieces, as pdf.js gives them, hold its
 * words. The passage was read by another PDF reader (pypdf on the server), which splits and spaces
 * words differently ("class ifying" for "classifying"), so the two are compared as runs of three
 * words in the passage's order, and only a run of at least MIN_RUN words counts: shorter ones are
 * common phrases that appear anywhere.
 */

const WORD = /[\p{L}\p{N}]+/gu
const SHINGLE = 3
const MIN_RUN = 6

export function wordsOf(text: string): string[] {
  return text.toLowerCase().match(WORD) ?? []
}

/** The indexes of the pieces that hold the passage, in order; empty when it is not on the page. */
export function piecesOfPassage(pieces: string[], passage: string): number[] {
  const own = wordsOf(passage)
  const wanted = new Set<string>()
  for (let i = 0; i + SHINGLE <= own.length; i++) wanted.add(own.slice(i, i + SHINGLE).join(' '))

  const words: { word: string; piece: number }[] = []
  pieces.forEach((piece, index) => {
    for (const word of wordsOf(piece)) words.push({ word, piece: index })
  })
  const marked = words.map(() => false)
  for (let i = 0; i + SHINGLE <= words.length; i++) {
    if (wanted.has(words.slice(i, i + SHINGLE).map((w) => w.word).join(' '))) {
      for (let j = i; j < i + SHINGLE; j++) marked[j] = true
    }
  }

  const kept = new Set<number>()
  let run: number[] = []
  const close = () => {
    if (run.length >= MIN_RUN) for (const j of run) kept.add(words[j].piece)
    run = []
  }
  marked.forEach((isMarked, j) => (isMarked ? run.push(j) : close()))
  close()
  return [...kept].sort((a, b) => a - b)
}
