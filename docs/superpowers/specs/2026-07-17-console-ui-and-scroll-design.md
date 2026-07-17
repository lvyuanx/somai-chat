# Console UI and scroll design

## Goal

Refresh the SOMAI browser console as a focused dark chat workspace and fix the
conversation timeline so it can always scroll independently of the shell.

## Scope

- Preserve the existing WebSocket protocol, session controls, trace rail,
  accessibility semantics, and mobile feature set.
- Replace the industrial paper styling with a dark blue visual system using
  layered surfaces, rounded cards, restrained borders, and clear blue, green,
  and red state colors.
- Keep the desktop three-column layout. On small screens, retain the compact
  session/status header and hide the trace rail as today.

## Layout and scrolling

The console shell remains viewport-bound. Grid and flex ancestors that contain
the conversation must explicitly permit shrinkage with `min-height: 0` and
`min-width: 0`. The conversation panel uses a three-row grid: header, flexible
timeline, and composer. Only the timeline scrolls vertically; the composer is
always visible.

The desktop trace list remains independently scrollable. Mobile keeps the
conversation panel as the flexible row beneath the compact header and applies
the same minimum-height rule, so the timeline—not the document body—scrolls.

## Smart follow behavior

Before appending or refreshing streaming content, the view determines whether
the timeline is at most 48 CSS pixels from its bottom. If so, it scrolls to the
new bottom after the DOM update. If the reader has scrolled higher than that,
the DOM updates without changing `scrollTop`.

User-directed display resets retain deliberate positioning: starting a new
session and clearing the display put the empty timeline at its top. This is
separate from the automatic streaming rule.

## Components and boundaries

- `app.css` owns the dark visual tokens and desktop layout constraints.
- `responsive.css` owns mobile constraints and does not alter protocol logic.
- `view.js` owns near-bottom measurement and conditional scroll behavior.
- `tests/js/console_view.mjs` verifies both follow and non-follow branches.
- `src/somai_chat/web/AGENTS.md` documents the revised visual system and
  follow behavior.

## Error handling and accessibility

Existing state colors, focus-visible treatment, reduced-motion rules, live
region, and button disabled states remain intact. Scroll logic is passive: it
does not catch or suppress application errors, and it never changes a user's
position while they are reading older content.

## Verification

Use TDD: add a view harness case that fails when a reader above the threshold
is pulled down, and one that fails when a reader near the bottom does not
follow. Then run the JavaScript view and state harnesses, the web-console
integration tests, and the repository quality checks appropriate to the files
changed.
