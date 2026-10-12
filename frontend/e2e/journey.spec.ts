/**
 * The whole journey in a real browser, against the real backend with fake models (Sprint 6,
 * decisions 13 and 14): sign up, upload, wait until it is read, ask, see the sources, reload and
 * find the conversation back, start a second thread, return to the first from the thread list,
 * rate an answer, remove the document, sign out. Along the way axe checks the start page, the
 * chat and the settings sheet at 1280 px and at 375 px, and fails on any serious or critical
 * violation; at 375 px and 360 px each of them must fit the screen without scrolling sideways.
 */
import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const QUESTION = 'How often is the Zephyr turbine blade inspection?'
const SECOND = 'Who carries out the inspection?'
const AGENT_QUESTION = 'Where is the Zephyr blade inspection logged?'
const WIDE = { width: 1280, height: 800 }
const PHONE = { width: 375, height: 812 }
const NARROW = { width: 360, height: 740 }  // item 8: usable from 360 px

/** Run axe on the page as it is now and fail on a serious or critical violation. */
async function checkAccessibility(page: Page, where: string) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  const blocking = results.violations
    .filter((v) => v.impact === 'serious' || v.impact === 'critical')
    .map((v) => `${v.id} (${v.impact}): ${v.help} — ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)
  expect(blocking, `axe on ${where}`).toEqual([])
}

/** The page is no wider than the screen: nothing makes it scroll sideways. */
async function checkFits(page: Page, where: string) {
  const { scroll, client } = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth,
  }))
  expect(scroll, `${where} scrolls sideways`).toBeLessThanOrEqual(client)
}

/**
 * Check a page at desktop and at phone width with axe, and that at phone widths it fits the
 * screen. Each width is loaded fresh, as a phone would open it.
 */
async function checkAtBothWidths(page: Page, where: string, ready: () => Promise<void>) {
  for (const size of [WIDE, PHONE, NARROW]) {
    await page.setViewportSize(size)
    await page.reload()
    await ready()
    if (size !== NARROW) await checkAccessibility(page, `${where} at ${size.width} px`)
    if (size !== WIDE) await checkFits(page, `${where} at ${size.width} px`)
  }
  await page.setViewportSize(WIDE)
  await page.reload()
  await ready()
}

test('the whole journey, with the accessibility gate', async ({ page }) => {
  const username = `journey_${Date.now().toString(36)}`

  // ── The start page ────────────────────────────────────────────────────────
  await page.goto('/')
  const startReady = () => expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await startReady()
  await checkAtBothWidths(page, 'the start page', startReady)

  // ── Sign up ───────────────────────────────────────────────────────────────
  await page.getByRole('button', { name: 'Start asking' }).click()
  await expect(page).toHaveURL(/\/login$/)
  const signUp = page.getByRole('dialog', { name: 'Create your account' })
  await signUp.getByLabel('Username').fill(username)
  await signUp.getByLabel('Password').fill('a long journey password')
  await signUp.getByRole('button', { name: 'Create account' }).click()
  await expect(page).toHaveURL(/\/chat\/session_\d+$/)
  await expect(page.getByText(username, { exact: true })).toBeVisible()

  // ── Upload, and wait until it is read ─────────────────────────────────────
  await page.locator('.x-rail input[type="file"]').setInputFiles('e2e/fixtures/zephyr_manual.txt')
  await expect(page.getByText('Added zephyr_manual.txt: 1 passage from 1 page.')).toBeVisible()
  const library = page.locator('.x-library')
  await expect(library.getByText('zephyr_manual.txt')).toBeVisible()
  await expect(library.getByText('Reading')).toHaveCount(0)

  // ── Ask, and see the sources ──────────────────────────────────────────────
  const composer = page.getByLabel('Your question')
  await composer.fill(QUESTION)
  await composer.press('Enter')
  await expect(page.getByRole('heading', { name: QUESTION })).toBeVisible()
  const margin = page.locator('.x-margin')
  await expect(margin.getByText('Sources')).toBeVisible()
  await expect(margin.getByText('zephyr_manual.txt')).toBeVisible()
  await expect(page.locator('.p-answer').first()).toContainText('blade inspection every 90 days')
  const firstThread = new URL(page.url()).pathname

  // What it cost (Sprint 8, item 1): one quiet line, and its stages on demand
  const cost = page.locator('.x-usage summary')
  await expect(cost).toHaveText(/^\d+\.\d s, [\d,]+ tokens$/)
  await cost.click()
  const stages = page.getByRole('list', { name: 'Stages' })
  await expect(stages.getByRole('listitem')).toHaveCount(3)
  await expect(stages).toContainText('Search')
  await expect(stages).toContainText(/Answer[\d.]+ s[\d,]+ in, [\d,]+ out/)
  await cost.click()

  const chatReady = () => expect(page.getByRole('heading', { name: QUESTION })).toBeVisible()
  await checkAtBothWidths(page, 'the chat', chatReady)

  // ── Reload: the conversation is still there ──────────────────────────────
  await page.reload()
  await expect(page).toHaveURL(firstThread)
  await chatReady()
  await expect(margin.getByText('zephyr_manual.txt')).toBeVisible()

  // ── Rate the answer; the rating survives a reload ─────────────────────────
  const helpful = page.getByRole('button', { name: 'Helpful', exact: true })
  await helpful.click()
  await expect(helpful).toHaveAttribute('aria-pressed', 'true')
  await page.reload()
  await expect(page.getByRole('button', { name: 'Helpful', exact: true })).toHaveAttribute('aria-pressed', 'true')

  // ── A second thread, then back to the first from the thread list ──────────
  await page.locator('.x-rail').getByRole('button', { name: 'New thread' }).click()
  await expect(page).not.toHaveURL(firstThread)
  await expect(page.getByRole('heading', { name: QUESTION })).toHaveCount(0)
  await composer.fill(SECOND)
  await composer.press('Enter')
  await expect(page.getByRole('heading', { name: SECOND })).toBeVisible()
  await expect(page.locator('.x-margin').getByText('Sources')).toBeVisible()
  const secondThread = new URL(page.url()).pathname

  // An agent answer lists its steps above it (Sprint 8, item 2)
  await page.getByRole('radio', { name: 'Agent' }).click()
  await composer.fill(AGENT_QUESTION)
  await composer.press('Enter')
  const agentSteps = page.getByRole('list', { name: 'Steps the agent took' })
  await expect(agentSteps.getByRole('listitem')).toHaveCount(1)
  await expect(agentSteps).toContainText('Document search')
  await expect(agentSteps).toContainText(AGENT_QUESTION)
  await page.getByRole('radio', { name: 'Default' }).click()

  const threads = page.getByRole('navigation', { name: 'Conversations' })
  await expect(threads.getByRole('link')).toHaveCount(2)
  await expect(threads.getByRole('link', { name: new RegExp(SECOND) })).toHaveAttribute('aria-current', 'page')
  await threads.getByRole('link', { name: new RegExp(QUESTION) }).click()
  await expect(page).toHaveURL(firstThread)
  await chatReady()
  await expect(page.getByRole('heading', { name: SECOND })).toHaveCount(0)
  await expect(threads.getByRole('link', { name: new RegExp(QUESTION) })).toHaveAttribute('aria-current', 'page')
  expect(secondThread).not.toBe(firstThread)

  // Rename the first thread; delete the second with two clicks (Sprint 8, item 3)
  await threads.getByRole('button', { name: `Rename ${QUESTION}` }).click()
  const newName = threads.getByRole('textbox', { name: `New name for ${QUESTION}` })
  await newName.fill('Blade inspections')
  await newName.press('Enter')
  await expect(threads.getByRole('link', { name: /Blade inspections/ })).toBeVisible()
  await threads.getByRole('button', { name: `Delete ${SECOND}` }).click()
  await threads.getByRole('button', { name: `Confirm deleting ${SECOND}` }).click()
  await expect(page.getByText('Conversation deleted')).toBeVisible()
  await expect(threads.getByRole('link')).toHaveCount(1)
  await page.reload()
  await expect(page).toHaveURL(firstThread)
  await expect(threads.getByRole('link', { name: /Blade inspections/ })).toHaveAttribute('aria-current', 'page')
  await page.goto(secondThread)
  await expect(page.getByRole('heading', { name: SECOND })).toHaveCount(0)  // nothing of it is left
  await page.goto(firstThread)
  await chatReady()

  // ── Settings ──────────────────────────────────────────────────────────────
  await page.getByRole('button', { name: 'Settings' }).click()
  await expect(page).toHaveURL(/\/settings$/)
  const settingsReady = () => expect(page.getByRole('dialog', { name: 'Settings' })).toBeVisible()
  await settingsReady()
  await checkAtBothWidths(page, 'the settings sheet', settingsReady)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Settings' })).toHaveCount(0)

  // By keyboard: the sheet opens from its button, takes focus, and Escape gives it back
  await page.getByRole('button', { name: 'Settings' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog', { name: 'Settings' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Settings' })).toHaveCount(0)
  await expect(page).toHaveURL(/\/chat\/session_\d+$/)
  await expect(page.getByRole('button', { name: 'Settings' })).toBeFocused()

  // ── Remove the document: one click arms the button, a second confirms ────
  await library.getByText('zephyr_manual.txt').hover()
  await library.getByRole('button', { name: 'Remove zephyr_manual.txt' }).click()
  await library.getByRole('button', { name: 'Confirm removing zephyr_manual.txt' }).click()
  await expect(page.getByText('Removed zephyr_manual.txt')).toBeVisible()
  await expect(library.getByText('No documents yet')).toBeVisible()

  // ── Sign out; a reload stays signed out ───────────────────────────────────
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page).toHaveURL(/\/$/)
  await page.reload()
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
  await page.goto(firstThread)
  await expect(page).toHaveURL(/\/login$/)
})
