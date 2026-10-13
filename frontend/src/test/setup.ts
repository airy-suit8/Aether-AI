import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// jsdom does not implement scrolling; the chat scrolls to the newest message
Element.prototype.scrollIntoView = function scrollIntoView() {}

// jsdom has no ResizeObserver; the threads between a claim and its evidence watch their container
class ResizeObserverStub implements ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = globalThis.ResizeObserver ?? ResizeObserverStub

afterEach(() => {
  cleanup()
})
