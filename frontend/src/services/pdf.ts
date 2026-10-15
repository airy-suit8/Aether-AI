/**
 * Draw one page of a PDF on a canvas and say where its text lies, with pdf.js. pdf.js is large,
 * so it is loaded the first time a page is shown, not with the app.
 */
import type { TextItem } from 'pdfjs-dist/types/src/display/api'

/** A piece of the page's text, and the box it fills on the drawn page, in pixels of its width and height. */
export interface PlacedText {
  text: string
  left: number
  top: number
  width: number
  height: number
}

export interface DrawnPage {
  /** The page drawn (the one asked for, within the document) and how many there are */
  page: number
  pages: number
  width: number
  height: number
  texts: PlacedText[]
}

let library: Promise<typeof import('pdfjs-dist')> | null = null

function pdfjs() {
  library ??= Promise.all([import('pdfjs-dist'), import('pdfjs-dist/build/pdf.worker.min.mjs?url')])
    .then(([lib, worker]) => {
      lib.GlobalWorkerOptions.workerSrc = worker.default
      return lib
    })
  return library
}

/** Draw page `pageNumber` of the PDF in `data` on `canvas`, sharp at `width` CSS pixels wide.
 * The canvas is sized by its stylesheet, so the page follows the dialog when the window changes. */
export async function drawPage(data: ArrayBuffer, pageNumber: number, canvas: HTMLCanvasElement, width: number): Promise<DrawnPage> {
  const lib = await pdfjs()
  // pdf.js takes the bytes over (they are sent to its worker): give it a copy
  const task = lib.getDocument({ data: new Uint8Array(data.slice(0)) })
  try {
    const doc = await task.promise
    const number = Math.min(Math.max(1, pageNumber), doc.numPages)
    const page = await doc.getPage(number)
    const viewport = page.getViewport({ scale: width / page.getViewport({ scale: 1 }).width })
    const ratio = window.devicePixelRatio || 1
    canvas.width = Math.floor(viewport.width * ratio)
    canvas.height = Math.floor(viewport.height * ratio)
    await page.render({ canvas, viewport, transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0] }).promise
    const content = await page.getTextContent()
    const texts = content.items
      .filter((item): item is TextItem => 'str' in item && item.str.trim() !== '')
      .map((item) => {
        const [, , c, d, e, f] = lib.Util.transform(viewport.transform, item.transform)
        const height = Math.hypot(c, d)
        return { text: item.str, left: e, top: f - height, width: item.width * viewport.scale, height }
      })
    return { page: number, pages: doc.numPages, width: viewport.width, height: viewport.height, texts }
  } finally {
    await task.destroy()
  }
}
