import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config.js'

// Tests run once and exit (`npm test`); `npx vitest` watches instead.
export default mergeConfig(viteConfig, defineConfig({
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
}))
