import type { AgentStep, FeedbackValue, Scope, Source, Usage } from '../../services/api'

/** A question as the conversation shows it. */
export interface QuestionMessage {
  id: string
  role: 'user'
  content: string
  timestamp?: string
}

/** An answer as the conversation shows it, with what came with it. */
export interface AnswerMessage {
  id: string
  role: 'assistant'
  content: string
  sources: Source[]
  confidence: number | null
  /** The confidence at which it reads as grounded: the server's line for the embedding model that searched */
  groundedAt?: number | null
  toolUsed: string | null
  mode: string
  turnId: number | null
  feedback: FeedbackValue
  /** What it cost: seconds and tokens, in all and by stage. Sent with a new answer, not kept with a saved one */
  usage?: Usage | null
  /** An agent answer's tool calls, in order. Sent with a new answer, not kept with a saved one */
  steps?: AgentStep[] | null
  /** The documents it searched, and why those. Sent with a new answer, not kept with a saved one */
  scope?: Scope | null
  timestamp?: string
}

export type ChatMessage = QuestionMessage | AnswerMessage

/** A reply that failed or was stopped, and the question to ask again. */
export interface Failure {
  threadId: string
  question: string
  stopped: boolean
  message: string
}

export type ToastType = 'info' | 'success' | 'error'
export type AddToast = (message: string, type?: ToastType, duration?: number) => void

/** An upload in progress: being sent, then read into passages by the server. */
export interface UploadProgress {
  filename: string
  status: 'uploading' | 'reading'
}
