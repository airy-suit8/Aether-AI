/**
 * The whole journey in a real browser, against the real backend with fake models (Sprint 6,
 * decisions 13 and 14): sign up, upload, wait until it is read, ask, see the sources, reload and
 * find the conversation back, start a second thread, return to the first from the thread list,
 * rate an answer, remove the document, sign out. Sprint 8 added: what an answer cost, an agent's
 * steps, renaming and deleting a thread, and signing out everywhere from a second browser.
 * Along the way axe checks the start page, the chat and the settings sheet at 1280 px and at
 * 375 px, and fails on any serious or critical violation; at 375 px and 360 px each of them must
 * fit the screen without scrolling sideways.
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
const PASSWORD = 'a long journey password'

/**
 * Run axe on the page once it has come to rest and fail on a serious or critical violation.
 * Something still fading in is measured at the contrast it has at that instant, not its own.
 */
async function checkAccessibility(page: Page, where: string) {
  await page.evaluate(() => Promise.all(
    document.getAnimations()
      .filter((animation) => animation.effect?.getComputedTiming().iterations !== Infinity)
      .map((animation) => animation.finished.catch(() => undefined)),
  ))
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

/** Sign in on the start page's sign-in sheet (/login), and wait for the workspace. */
async function signIn(page: Page, username: string) {
  const sheet = page.getByRole('dialog', { name: 'Welcome back' })
  await sheet.getByLabel('Username').fill(username)
  await sheet.getByLabel('Password').fill(PASSWORD)
  await sheet.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/chat\/session_\d+$/)
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

test('the whole journey, with the accessibility gate', async ({ page, browser }) => {
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
  await signUp.getByLabel('Password').fill(PASSWORD)
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

  // ── Share the conversation: anyone with the link can read it, until it is withdrawn ──
  await page.getByRole('button', { name: 'Share', exact: true }).click()
  const shareSheet = page.getByRole('dialog', { name: 'Share this conversation' })
  await shareSheet.getByRole('button', { name: 'Create link' }).click()
  const link = await shareSheet.getByLabel('Link').inputValue()
  expect(link).toMatch(/\/shared\/[A-Za-z0-9_-]{32}$/)

  const visitor = await browser.newContext()  // someone who is not signed in
  const shared = await visitor.newPage()
  const sharedReady = () => expect(shared.getByRole('heading', { level: 2, name: QUESTION })).toBeVisible()
  for (const size of [WIDE, PHONE]) {
    await shared.setViewportSize(size)
    await shared.goto(new URL(link).pathname)
    await sharedReady()
    await checkAccessibility(shared, `the shared page at ${size.width} px`)
    if (size === PHONE) await checkFits(shared, 'the shared page at 375 px')
  }
  await expect(shared.locator('.p-answer').first()).toContainText('blade inspection every 90 days')
  await expect(shared.getByText('zephyr_manual.txt').first()).toBeVisible()
  await expect(shared.getByRole('button', { name: 'Helpful', exact: true })).toHaveCount(0)  // read only
  await expect(shared.getByLabel('Your question')).toHaveCount(0)

  await shareSheet.getByRole('button', { name: 'Stop sharing' }).click()
  await expect(shareSheet.getByRole('button', { name: 'Create link' })).toBeVisible()
  await shared.reload()
  await expect(shared.getByRole('heading', { name: 'This link no longer works.' })).toBeVisible()
  await visitor.close()
  await shareSheet.getByRole('button', { name: 'Close' }).click()

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

  // Changed to Not helpful: after the journey, e2e/check-feedback-export.js finds it in the
  // feedback export (Sprint 8, item 5)
  await page.getByRole('button', { name: 'Not helpful' }).click()
  await expect(page.getByRole('button', { name: 'Not helpful' })).toHaveAttribute('aria-pressed', 'true')
  await page.reload()
  await expect(page.getByRole('button', { name: 'Not helpful' })).toHaveAttribute('aria-pressed', 'true')

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

  // ── Sign out everywhere (Sprint 8, item 4): a second browser is signed out too ──
  await signIn(page, username)
  const elsewhere = await browser.newContext()
  const other = await elsewhere.newPage()
  await other.goto('/login')
  await signIn(other, username)
  await page.getByRole('button', { name: 'Settings' }).click()
  await page.getByRole('dialog', { name: 'Settings' }).getByRole('button', { name: 'Sign out everywhere' }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByText('Signed out on every device')).toBeVisible()
  await page.reload()
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
  await other.reload()
  await expect(other).toHaveURL(/\/login$/)
  await elsewhere.close()
})
