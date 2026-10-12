/**
 * citations.ts — turns the [n] markers of an answer into citation nodes, as a remark plugin.
 *
 * With AETHER_ANSWER_FROM=chunks the server writes answers that cite their passages as [1], [2],
 * and gives each cited source its number. remarkCitations(numbers) replaces each [n] whose n is
 * one of those numbers with a <cite data-n="n"> node, which the answer draws as a Cite chip. Any
 * other [n] stays text. Code is left alone: its text is not a text node.
 */

/** The parts of a Markdown (mdast) node this plugin reads and writes. */
interface MdNode {
  type: string
  value?: string
  children?: MdNode[]
  data?: { hName?: string; hProperties?: Record<string, string | number> }
}

const MARKER = /\[(\d+)\]/g

function split(text: string, numbers: ReadonlySet<number>): MdNode[] {
  const nodes: MdNode[] = []
  let last = 0
  for (const match of text.matchAll(MARKER)) {
    const n = Number(match[1])
    if (!numbers.has(n)) continue
    const at = match.index ?? 0
    if (at > last) nodes.push({ type: 'text', value: text.slice(last, at) })
    nodes.push({
      type: 'citation',
      data: { hName: 'cite', hProperties: { dataN: n } },
      children: [{ type: 'text', value: match[0] }],
    })
    last = at + match[0].length
  }
  if (last === 0) return [{ type: 'text', value: text }]
  if (last < text.length) nodes.push({ type: 'text', value: text.slice(last) })
  return nodes
}

function walk(node: MdNode, numbers: ReadonlySet<number>): void {
  if (!node.children) return
  node.children = node.children.flatMap((child) => {
    if (child.type === 'text' && child.value) return split(child.value, numbers)
    walk(child, numbers)
    return [child]
  })
}

/** A remark plugin that marks the citations of the given source numbers. */
export function remarkCitations(numbers: ReadonlySet<number>) {
  return () => (tree: MdNode) => {
    if (numbers.size) walk(tree, numbers)
  }
}
