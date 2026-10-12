/**
 * Replies as the backend sends them, for tests. Each is typed by the schema, so a test fixture
 * that drifts from the API fails the type check just as the app would.
 */
import type { DocumentRecord, DocumentStatus, DoneEvent, Schemas, Source, Turn } from '../services/api'

export const SOURCE: Source = {
  source: 'zephyr_manual.txt',
  page: 1,
  score: 0.834,
  snippet: 'The Zephyr turbine maintenance schedule requires a blade inspection every 90 days.',
}

export function documentRecord(fields: Partial<DocumentRecord> & Pick<DocumentRecord, 'id' | 'filename'>): DocumentRecord {
  return {
    status: 'ready', error: null, pages: 1, chunks: 1, size_bytes: 120, uploaded_at: '2026-10-12T09:00:00', file_hash: null,
    ...fields,
  }
}

export function documentStatus(fields: Partial<DocumentStatus> & Pick<DocumentStatus, 'id' | 'filename' | 'status'>): DocumentStatus {
  return { error: null, pages: 0, chunks: 0, size_bytes: 120, uploaded_at: '2026-10-12T09:00:00', ...fields }
}

export function documentList(documents: DocumentRecord[]): Schemas['DocumentList'] {
  return { documents, count: documents.length }
}

export function turn(fields: Partial<Turn> & Pick<Turn, 'turn_id' | 'question' | 'answer'>): Turn {
  return {
    sources: [], confidence: 0.7, mode: 'original', tool_used: null, feedback: 0, created_at: '2026-10-12T10:00:00',
    ...fields,
  }
}

export function session(fields: Partial<Schemas['SessionSummary']> & Pick<Schemas['SessionSummary'], 'session_id'>): Schemas['SessionSummary'] {
  return { title: 'A question', turns: 1, started_at: '2026-10-12T10:00:00', updated_at: '2026-10-12T10:00:00', ...fields }
}

export function done(fields: Partial<DoneEvent> = {}): DoneEvent {
  return { type: 'done', sources: [], confidence: 0, turn_id: null, ...fields }
}

export function chatReply(fields: Partial<Schemas['ChatResponse']> & Pick<Schemas['ChatResponse'], 'answer'>): Schemas['ChatResponse'] {
  return { sources: [], confidence: 0, session_id: 'default', tool_used: null, turn_id: null, ...fields }
}

/** A test double for fetch's Response: only the parts the client reads. */
export function asResponse(fake: object): Response {
  return fake as Response
}
