# Nova — working notes

Study app for Class 26E, used by ~40 classmates.

Most of this is distilled from a handoff written across the sessions that built
the app, plus what was learned working directly in the repo. Where the two
disagreed, the repo won and the difference is called out.

---

## Repo and deployment

- `index.html` — the entire app. Markup, one `<style>` block, all logic.
- `version.json` — update-check sidecar. See **Shipping a change**.
- `tools/check-js.py` — syntax check for the inline scripts. See **Verifying**.
- GitHub Pages serves `main`. No build step, no bundler, no `npm install`.
- Develop on `claude/repo-update-jquqz4`; merge to `main` to deploy.

**Single file is the deployment model, not accretion.** Even Firebase loads via
plain `<script src=...compat.js>` rather than an ES module, precisely so no
bundler is needed. Introducing a build pipeline is a bigger decision than it
looks — it changes how ~40 people's browsers load the app.

There **is** a web app manifest, embedded as a base64 `data:` URI on a
`<link rel="manifest">`. Grepping for `manifest.json` finds nothing and it is
easy to conclude there is none. Decode it to edit; never hand-patch the base64.

---

## Hard rules

- **Never rename `STORE_KEY` (`"class26e.drill.v1"`) or `"class26e.synccode"`.**
  Either orphans real saved progress on ~40 devices. This includes not
  "fixing" `class26e` to `nova` to match the rebrand — the rename was cosmetic
  and deliberate. Same for the Firebase project id and the IndexedDB name.
- **Never call Firestore `.onSnapshot()` directly** — always
  `onSnapshotResilient()`, which backs off and resubscribes. Direct calls
  reintroduce a shipped bug class where listeners went silently stale.
- **Applying data that arrived from the cloud uses `persistLocally()`, not
  `saveStore()`.** `saveStore()` pushes back up and two synced devices
  ping-pong forever.
- **Any new persisted field on `store` needs an explicit default in
  `applyLoadedData()`** — defaulted so *existing* users don't see it as new
  (e.g. a `seenXTour` flag defaults to already-seen for anyone past
  onboarding).
- **Don't reorder or rename questions' `topic`/`src`.** Question identity is a
  hash of those fields (`KEYS` via `hashOf()`), so changing them scrambles a
  real person's answer history for that question.

---

## iOS install-time metadata — the thing that cost a whole session

iOS reads three things **once**, when the app is added to the Home Screen, and
never again: **the icon, the app name, and the launch status bar colour.** No
reload, no cache clear, and no amount of JavaScript can change them afterwards.
Only removing the icon and re-adding it can.

This is why a flat grey strip at the top of the screen survived several
correct-looking fixes aimed at page layers (`background-attachment`, a
`position:fixed ::before`, a matching gradient on `html`). The status bar never
consults any of them. It was `theme-color`, read at launch.

Consequences worth keeping in mind:

- **Two places declare `theme-color` and they must stay in step:** the
  `<meta id="themecolor">` tag and `theme_color` inside the base64 manifest.
  iOS 16.4+ reads the manifest for an installed app and can prefer it, so a
  stale value there reinstates the bug on exactly the devices the meta fix
  appeared to solve it for. Both are `#271E23`.
- `background_color` in the manifest is a different thing — the launch
  backdrop — and correctly stays flat `--paper` (`#12161B`).
- The status bar colour is computed at runtime from the app's own tokens
  (`syncStatusBarColor()` → `--statusbar-mix2/3` alongside `--bg-glow-r1/r2`),
  cached to `class26e.statusbar.v1`, and replayed before first paint by a
  synchronous inline script in `<head>`. That script must stay synchronous and
  stay in `<head>` — anything deferred loses the race with first paint.
- `getComputedStyle` returns a `color-mix()` result as CSS Color 4
  (`color(srgb 0.15 0.12 0.14)`, 0–1 floats), **not** `rgb(18, 22, 27)`.
  Parsing it with 0–255 assumptions rounds every channel to 0 — a black status
  bar. Both serializations are handled; don't "simplify" that.

---

## Shipping a change

`APP_BUILD` in `index.html` and `build` in `version.json` **must be bumped
together, to the same value**, on every deploy. They are two halves of one
comparison: `version.json` is what the server serves, `APP_BUILD` is baked into
whatever copy is running.

- Bump only `version.json` → everyone gets a banner reloading can never clear.
- Bump only `APP_BUILD` → nobody is ever told there's an update.

`frameId` is the exception: it is deliberately **not** compared against
anything in `index.html`, only against what each device has acknowledged
(`class26e.frame.ok`). Bumping it alone is correct, and is how you re-prompt
everyone after an icon or app-name change. `frameNote` overrides the message.
Ship a **new** deployment (different URL) with `frameId: ""` — that disables
the notice, which is right when every install is fresh and already correct.

Two notices, both gated to the Welcome and Home screens only, never mid-test:

| | Update banner | Re-add notice |
|---|---|---|
| Who | everyone, incl. browser tabs | installed **and** not Android |
| Trigger | `build` ≠ `APP_BUILD` | `frameId` not acknowledged |
| Action | refetch with `cache:"reload"`, then reload | hand off to Safari |

Details that exist for a reason:

- `applyUpdate()` re-fetches the exact URL with `cache:"reload"` before
  reloading. A plain `location.reload()` may serve the same stale copy; a `?v=`
  cache-buster populates a *separate* cache entry and leaves the URL the Home
  Screen icon launches just as stale.
- **`target="_blank"` does not reach Safari** from a standalone app on current
  iOS — a same-origin link navigates inside the app, which presents as the app
  reloading. Use the `x-safari-https:` scheme. `openInSafari()` watches for the
  app going hidden as proof it worked, and grows a copyable link if nothing
  happened after 1.5s.
- Acknowledgement is tied to the app actually going hidden, **not** to the tap.
  Acknowledging on tap turns a failed hand-off into a permanently silenced
  notice.
- The Android exclusion is written as `!/Android/i` rather than a positive iOS
  test **on purpose**: iPadOS Safari reports a Mac-like user agent, so
  `/iPad|iPhone/` misses the exact device this was written for.
- The check retries while the splash is up (20 × 1.2s). The first-run splash is
  **8 seconds**; a 6-retry budget silently ran out and the check was never
  made. Screen changes also trigger a check, so a lost attempt heals itself.

---

## Conventions

- **Screen functions are `showX()`** — except **Settings, which is
  `showAppearance()`**. A holdover from when it was only about theme. Search
  `showAppearance`, not `showSettings`.
- Screens mount via `stage.replaceChildren(...)`. Welcome and Home tag their
  root with `dataset.screen`, which is how the update notices know where they
  are — self-clearing, since the next screen's mount removes the node.
- **Tabbed screens (Rewards, Profile)** share one pattern: a
  `.navsegment`/`.iconbtn` pill switcher, `hidden`-attribute panels, and a
  `selectXTab(which)` toggler. Match it rather than inventing a new shape.
- **Shared classes are genuinely shared** (`.sect`, `.slab`, `.iconbtn`,
  `.panel`). A one-screen fix needs a screen-level ancestor scope; editing the
  bare class changes every screen, usually by accident.
- **Theming** is CSS custom properties keyed off `data-theme` and `data-accent`
  on `<html>`. Write the rule once, then override with a
  `[data-theme=...]`/`[data-accent=...]` prefixed version. Never a one-off
  hardcoded colour.
- **Tablet styling is `@media (min-width:40rem)`**, added *after* the phone
  rule as an override — never a rewrite of the base rule.
- New `localStorage` keys follow `class26e.<thing>` and are wrapped in
  `try/catch`. Keys added for the update machinery: `class26e.statusbar.v1`,
  `class26e.frame.ok`, `class26e.update.dismissed`, and session-scoped
  `class26e.updating`. None of these live on `store`, so the
  `applyLoadedData()` default rule doesn't apply to them.

---

## Known quirks

- **Two kinds of em dash exist in this file and they are not
  interchangeable.** Most comments use a real `—`. Some contain the literal
  six-character text `—` instead. Inside JS *string literals* a `—`
  escape is correct and renders as a dash at runtime; inside `/* comments */`
  it is inert text. This breaks exact-match edits. **Check raw bytes before
  editing text near a dash** (`sed -n 'N,Np' file | cat -A`). The same trap
  applies to `×` and friends — some are literal escapes in source, some
  are real characters.
- **A lot of the CSS is dead, not hidden features.** `loadTheme()` ignores any
  stored `"light"` mode or `"classic"` layout — both are fully retired — but
  their CSS was never deleted. `[data-theme="party"]` likewise has a whole
  theme's CSS that `applyTheme()` can never reach (it maps party → dark).
  Retired accent names `grinder`, `scholar`, `luminary` still have colour
  definitions. **If you change a colour and nothing happens, check the selector
  is reachable before assuming your edit was wrong.**
  (The light/classic values in `--statusbar-mix2/3` are inert for the same
  reason — kept as harmless defensive defaults.)
- **"Flares" ≠ "Secret Flares".** Flares are the orbiting badges on the Mastery
  Ladder. Secret Flares are titan tier's separate mystery-colour hunt
  (`mysteryStars`, `store.mysteryColorsFound`, keys `red`/`orange`/`yellow`).
- **Fixed-position elements render oddly in Playwright `fullPage` screenshots.**
  Verify their layout with `getBoundingClientRect()`, not by eyeballing.
- **Adjacent vertical margins collapse to the larger, they don't add.** A gap
  "smaller than the two margins suggest" is collapse, not specificity.
- **Don't copy the corner-positioning formula from `.daily-question-fab` /
  `.homeversion-btn`** (`right:max(calc(50% - Nrem), Yrem)`). It's relative to
  the centred bottom tab bar those sit beside and grows *further* from the
  screen edge as the viewport widens. Use
  `right:max(1.5rem, calc(env(safe-area-inset-right,0px) + 1.2rem))`.

---

## Verifying

Empirically, every time. Reading the code and concluding it's correct has
missed real bugs that a thirty-second check caught.

1. `python3 tools/check-js.py index.html` — extracts every inline script and
   runs `node --check`. It strips HTML comments first, because the Firebase
   comment contains the literal text `<script>` and a naive regex reports a
   phantom syntax error on prose.
2. A targeted Playwright check of the actual change — measure or screenshot it.
   Chromium is at `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`.
3. A broader pass across the main screens and sizes before calling it done.

Serve over HTTP for anything touching `version.json` — `fetch` fails on a
`file://` path, and the update check swallows that silently by design.

The Firebase CDN is blocked in the sandbox, so the splash never self-clears;
remove `#splashscreen` manually, *except* when testing the update check, where
the splash race is the thing under test. Those two console errors are expected
and unrelated to any change.

No committed regression suite exists yet. Worth building.
