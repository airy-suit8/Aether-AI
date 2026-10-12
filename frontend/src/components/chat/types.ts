import type { FeedbackValue, Source } from '../../services/api'

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
  toolUsed: string | null
  mode: string
  turnId: number | null
  feedback: FeedbackValue
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
