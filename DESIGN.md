# Prism — the Aether AI design language

Status: 11 October 2026. Prism is applied to every screen of the app: the start page, the sign-in sheet, the workspace (library rail, conversation, composer) and settings. The old stylesheets are gone. All of it lives on the branch `design/prism` until Sprint 2 is merged.

**See it:** run `start.bat`, then open `http://localhost:5173/` for the app or `http://localhost:5173/design-lab.html` for every component on one page. The theme control offers System and Dark.

![The workspace in the dark theme, with an answer and its source](docs/design/prism-workspace-dark.png)

![The bench in the dark theme, with the second source active](docs/design/prism-bench-dark.png)

## The idea

Aether was the name for the medium light was once thought to travel through, so the interface is built on light.

A question is white light. Retrieval is the prism. The answer comes out as a spectrum: every source has its own hue, and every claim carries the hue of the source it came from. The one thing a person should remember after using it is that they could see where each sentence came from.

## Principles

1. **Content is the light; chrome is glass.** Surfaces stay quiet. Only the answer and its evidence glow.
2. **Colour means something.** About 90% neutral, 8% primary blue, 2% spectrum. Status colours never appear without a label or an icon.
3. **Everything responds.** Glass catches the pointer, controls move on springs, type changes weight and width with state.
4. **Calm at rest.** Nothing animates while idle. The background moves only when the app's state changes.
5. **Preferences are honoured.** Reduced motion and reduced transparency both have a designed fallback, and text contrast is at least 4.5:1.

## Colour

The method is Google's: neutral surfaces stacked by tone instead of shadow, one primary, and a small set of roles that each have a guaranteed readable "on" colour. Light and dark come from the same roles through `light-dark()`.

| Role | Light | Dark | Used for |
|---|---|---|---|
| `--p-bg` | `#f8fafd` | `#131314` | The page |
| `--p-surface` to `--p-surface-4` | `#ffffff` to `#dde3ea` | `#1e1f20` to `#3c4043` | Elevation by tone |
| `--p-ink`, `--p-ink-2`, `--p-ink-3` | `#1f1f1f`, `#444746`, `#5f6368` | `#e3e3e3`, `#c4c7c5`, `#9aa0a6` | Three levels of emphasis |
| `--p-primary` | `#1a73e8` | `#8ab4f8` | The one colour that means "act" |
| `--p-ok`, `--p-warn`, `--p-bad` | green, amber, red | lighter tints | Grounded, uncertain, failed |
| `--p-s1` to `--p-s5` | five hues at one lightness | the same hues, lighter | One per source |

The five source hues share one lightness and nearly one chroma (defined in OKLCH), so no source looks more important than another. They appear only as light: a citation chip, the edge of a source card, a thread. The full spectrum appears together in exactly one place, the rim of the composer while the model is working.

## Type

- **Mona Sans** (variable weight 200–900 and width 75–125) carries the interface and the answers. Display text runs wide and light; dense labels run narrow and heavier. Selected controls gain weight instead of changing colour.
- **Martian Mono** carries numbers: pages, scores, timings.
- Both are open-licensed (SIL OFL 1.1) and bundled in `frontend/src/design/fonts/`, so the app makes no font request to a third party.

## Material

One material, optical glass: a translucent pane with a hairline edge. A highlight on that edge and a soft glint inside follow the pointer, the way real glass catches light. While the model works, the composer's edge becomes a slowly turning spectrum.

## Components

| Component | File | Behaviour |
|---|---|---|
| `PrismRoot` | `prism.jsx` | Sets the theme and wires pointer light |
| `AmbientField` | `prism.jsx` | Corner light that tightens while retrieving and relaxes when answered |
| `Aperture` | `prism.jsx` | The composer: widens on focus, glows while busy, Send morphs into Stop |
| `Lens` | `prism.jsx` | One sliding control for a single choice; arrow keys move it |
| `ClarityRing` | `prism.jsx` | Confidence as optical clarity: sharp when grounded, diffuse when uncertain, hollow when refused |
| `Cite` | `prism.jsx` | A citation marker in the hue of its source |
| `SourceCard` | `prism.jsx` | Evidence in the margin: file, page, score and passage |
| `Threads` | `prism.jsx` | Lines of light from each citation to its source, routed through the gutter |
| `Switch` | `prism.jsx` | A toggle whose knob is a point of light |
| `Field` | `prism.jsx` | A text field: the label lifts on focus and the line under it splits into the spectrum |
| `HoldButton` | `prism.jsx` | For actions that cannot be undone: nothing happens unless the press is held |
| Library row remove | `Sidebar.jsx`, `app.css` (`.x-doc__remove`) | For removing one document, in a row too small for a hold: a quiet cross that shows with the row; one click arms it ("Remove?", in the status red), a second confirms; it disarms after four seconds or when focus leaves |
| `Dialog` | `prism.jsx` | A modal sheet: Escape and a click outside close it, Tab stays inside, focus returns afterwards |
| `DemoBench` | `DemoBench.jsx` | The self-playing demonstration used on the start page and in the lab |

Some interaction ideas (the light-point toggle, the floating-label field, hold to confirm) were prompted by browsing the open-source gallery at uiverse.io. They were written from scratch in this language; no code was copied.

Two moments are choreographed. **Development:** streamed words arrive blurred and settle into focus. **Dispersion:** when an answer completes, its source cards leave it one by one and the threads draw after they land.

## Layout

The answer sits on the left and its evidence in the right margin, like notes in a scholarly book. Below 860 px the margin moves under the answer and the threads are not drawn.

![The bench at phone width](docs/design/prism-bench-phone.png)

## Rules for building with it

- Every Prism screen is wrapped in `PrismRoot`; all tokens are scoped to `.prism` and prefixed `--p-`.
- Do not animate anything behind glass while idle, and do not put a blend mode on a full-screen layer. Both were measured as expensive during the first build.
- Status is never colour alone: pair it with a word.
- Use the spectrum for sources only.

## What comes next

1. Merge with the Sprint 2 test suite: two assertions in its chat test describe the old markup (the mode control is now a radio group, and a source card shows a preview of its passage).
2. A full keyboard and screen-reader pass. Focus handling, labels and Escape are built in, but so far it has been exercised with a pointer and by script.
3. Per-sentence source colour and threads in the real chat. This needs the backend to report which source supports which claim (Sprint 4); until then an answer links to its sources as a whole.
4. Stop only ends the reply on the screen; the server may still finish it. Cancelling on the server belongs with the API work in Sprint 5.
