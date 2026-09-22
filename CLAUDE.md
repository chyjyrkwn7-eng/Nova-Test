# Nova — working notes

Study app for Class 26E, used by ~40 classmates. **26E is a police academy
class**, which is worth knowing before writing any copy for it: "While you
study" was rejected as a Settings header for not reading official enough, and
became "Studying & tests". The tone the app wants is plain and unfussy, not
chatty.

Most of this is distilled from a handoff written across the sessions that built
the app, plus what was learned working directly in the repo. Where the two
disagreed, the repo won and the difference is called out.

---

## Repo and deployment

- `index.html` — the app itself. Markup, one `<style>` block, all logic.
- `launch/` — iOS startup images, referenced by path from `index.html`.
  **Deploys with it.** See **iOS install-time metadata**.
- `version.json` — update-check sidecar. See **Shipping a change**.
- `tools/check-js.py` — syntax check for the inline scripts. See **Verifying**.
- `tools/gen-startup-images.py` — regenerates the iOS launch images. See the
  iOS section. `--check` fails if the block in `index.html` is stale.
- `tools/gen-app-icon.py` — draws the app icon and writes it into all three
  places it lives. `--check` fails if they drift. See **The app icon**.
- `tools/sim-safe-area.py` — bakes real safe-area insets into a copy for
  local testing. See **Verifying**.
- `tools/sweep-layout.py` — every main screen on every supported form
  factor. See **Every device, every way in**. Exits non-zero on a failure.
- `tools/check-positions.py` — the companion to it: not "is anything
  broken" but "did what I just positioned land where I meant it to", on
  every device. See **Every device, every way in**.
- `tools/shoot-flow.py` — screenshots every onboarding screen, Home and
  Settings by *clicking through* from a fresh install on seven devices,
  rather than mounting screens. Use it for anything Madison will look at.
- `tools/check-fixes.py` — the third question, after "is anything
  broken" (the sweep) and "did it land where I meant it to"
  (check-positions): **is this specific fix actually in effect here**,
  on every device, both orientations, installed and in a browser. Written
  after a batch of device-reported bugs were each verified on one iPad,
  which is not the bar. Exits non-zero and names the device. Extend it
  when a fix is worth holding to across the matrix; delete a check when
  the thing it guards is gone. Takes `--only <substring>` like the sweep,
  because 63 runs of a page that waits on a splash is a long time to wait
  to find out one device is wrong.
- `tools/check-sync.py` — the question none of the three layout tools can
  answer: **does this build still keep people's accounts?** The sync code
  surviving, recovery landing somewhere that isn't Welcome, a rankings row
  being retired when its code is abandoned, and Find me naming the right
  reason. Device-independent, so it runs once rather than 63 times. Every
  check in it was written against a build where it failed; `--against
  old-index.html` re-runs it there, which is the only thing that makes a
  green run mean anything. See **Accounts and the sync code**.
- `tools/check-behaviour.py` — **does the app still DO the right
  thing**, as opposed to still look right: the splash centred from its
  first visible frame, a thumb swipe changing the top tab, a back link
  landing somewhere that is not blank, a badge earned by every route to
  35 and only then, and a queue of badges playing back to back on the
  main menu. Every check in it was written against a build where it
  failed; `--against old-index.html` runs it there.
- `tools/firestore-admin.py` — `list`, `find <username>` and
  `purge --yes` against the live Firestore over the plain REST API, no SDK
  and no credentials (the rules are open). `find` is the "someone lost
  their code" lookup. **It is a tool and not a screen on purpose** — see
  **Accounts and the sync code**.
- GitHub Pages serves `main`. No build step, no bundler, no `npm install`.
- Develop on `claude/repo-update-jquqz4`; merge to `main` to deploy.

**Merging to `main` is part of finishing a change, not a separate request.**
Standing instruction from Madison, given after a whole session's work sat on
the branch while she opened the app and found nothing had changed: once a
change passes its checks, merge it to `main` and push, without asking. Pages
rebuilds in well under a minute, so the test URL is then current and what she
opens matches the screenshots she was just sent. The failure mode this exists
to prevent is silent — a branch that is 11 commits ahead looks exactly like a
branch that is up to date from the Home Screen. **If for any reason a change
is NOT on `main`, say so in the same message as the screenshots**; never let
her discover it by opening the app.

**Single file is the deployment model, not accretion.** Even Firebase loads via
plain `<script src=...compat.js>` rather than an ES module, precisely so no
bundler is needed. Introducing a build pipeline is a bigger decision than it
looks — it changes how ~40 people's browsers load the app.

There **is** a web app manifest, embedded as a base64 `data:` URI on a
`<link rel="manifest">`. Grepping for `manifest.json` finds nothing and it is
easy to conclude there is none. Decode it to edit; never hand-patch the base64.

---

## Hard rules

- **Every change is verified across the whole device matrix before it
  ships** — every device, both orientations, installed *and* in a browser.
  `python3 tools/sweep-layout.py`. See **Every device, every way in**.
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
- **`background_color` in the manifest does NOT colour the iOS launch
  screen.** This file used to say it was "the launch backdrop"; that is
  wrong, and believing it cost two failed attempts at the white flash. iOS
  ignores it entirely for a home-screen app and paints the launch screen
  **white** unless given an `apple-touch-startup-image` matching the device
  exactly. `background_color` still matters to Android/Chrome, which is why
  it stays `#12161B`.
- **The white flash on launch is that white launch screen**, not anything
  the page does. It cannot be fixed from CSS, because it happens before the
  page exists. The cure is a flat `#0A0A0A` startup image per device per
  orientation, generated by `tools/gen-startup-images.py` into `launch/` and
  a marked block in `<head>`, so the launch screen and `#splashscreen` are
  the same colour and the handover is invisible.
- **Verified end to end, and worth re-running rather than re-reasoning:**
  serve the repo over HTTP, pull every `apple-touch-startup-image` href,
  and check each one returns 200 as `image/png` and is a single flat
  `#0A0A0A`. Current state: 43 link tags, 42 unique files, all clean; the
  iPhone 17 Pro Max's exact 1320×2868 (440×956 at 3x) has both a matching
  file and a matching media query; and the media-less catch-all is the same
  1320×2868 image, so a device iOS fails to match by media query still gets
  black rather than white. That, plus `html{background:#0A0A0A}` inside the
  first ~300 bytes and `#splashscreen` at the same colour, is the whole
  chain — there is no remaining step between the icon being tapped and the
  app's own first paint that can be white.
- **They must be REAL FILES in `launch/`, not `data:` URIs.** The first
  version shipped 42 correct link tags carrying correct PNGs as data URIs
  and the flash did not move. It was not a coverage gap — an iPhone 17 Pro
  Max is 440×956 at 3x, which the existing 16 Pro Max entry matched exactly.
  The links were right and the images were right, so what was left was the
  delivery: iOS needs these images *before* the page it found them in has
  loaded, and every documented implementation references a fetchable path.
  **This is why `index.html` is no longer the whole app.** `launch/` has to
  be deployed with it; if it is missing, the links 404 and iOS falls back to
  white *silently*. `--check` verifies every referenced file is on disk.
- iOS matches on exact pixel dimensions and falls back to white on any
  mismatch, so **a new device needs a new entry in `DEVICES`** — but there
  is also a media-less catch-all entry, last in the block, which is the only
  thing that can cover a device whose size is not known in advance. Both
  orientations use the *portrait* `device-width`/`device-height`, differing
  only by `orientation:` — that is the convention iOS expects, not a bug.
- Startup images are almost certainly read at install time like the icon
  and the app name, so an existing install may need a re-add to pick them
  up. That is what `frameId` is for.
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

## The app icon

Drawn by `tools/gen-app-icon.py`, never edited by hand.

**The icon lives in three places and they must never drift apart:** the
`apple-touch-icon` link (the Home Screen app), `<link rel="icon">` (the
browser tab favicon), and the `icons` array inside the base64 manifest
(Android, desktop installs). The script writes all three in one go, and
**`--check` fails if any of them disagree** — that check exists because they
*did* drift: an earlier pass updated the apple-touch-icon and the manifest
and left the favicon still serving the old artwork, so every Safari and
Chrome tab went on showing the icon that had just been replaced, with nothing
anywhere to say so. Run `--check` after touching anything icon-shaped.

- **Full-bleed opaque square. No rounded corners, no transparency.** iOS
  applies its own mask; anything rounded here gets rounded twice. The icon
  this replaced had corners baked in and transparent gaps behind them —
  visible as white notches the moment it was composited on anything light.
- **One idea, legible at 60pt.** The V from NOVA and nothing else. The old
  icon was an illustration — sphere, starburst, orbiting moon, a small N —
  none of which survives the size it is actually used at.
- **The grey is calibrated against a real iOS icon, not chosen from a
  palette.** `GREY_TOP`/`GREY_BOTTOM` are `#323232` → `#141414`. They came
  from photographing Claude's icon next to Nova's on the same Home Screen and
  sampling both tiles down their edges, clear of the glyphs. Claude's reads
  `#2E2E2E` at the top falling to `#171718`, **dead neutral** (R=G=B at every
  point) on a gentle 23-level slope.

  Nova's was wrong in three separate, measurable ways at once: 16 levels too
  light at the top, a slope half again as steep (35 levels), and a consistent
  **+2 blue tint** that made the grey read cool next to Claude's neutral. Two
  levels of blue is invisible in isolation and obvious side by side, which is
  exactly why guessing at "systemGray5" does not work.

  The method is the reusable part: render the icon at the screenshot's tile
  size, sample the same fractions down the same columns, and compare. The
  local render reproduced the screenshot's values exactly, which is what
  makes the comparison trustworthy. Current match: **within 2 levels at every
  point, zero tint.**
- **No overhead highlight on the background.** There used to be a soft
  elliptical pool, and measured against Claude it was adding ~18 levels at
  the top and almost nothing at the bottom — precisely the "too light, too
  steep" above. iOS's dark icons do not have one: the plain top-to-bottom
  gradient *is* the lighting. The glyph's own banded shading carries the
  dimensionality.
- **A lit surface, not a flat fill** — but far less lighting than instinct
  suggests. A hairline along the top edge, and for the smooth variants a
  tight contact shadow and a soft specular on the glyph. The first pass used
  roughly four times the light and read as a gradient wallpaper; the second
  still measured 16 levels too bright against a real iOS icon.
- The V keeps Nova's own ramp (`#FFD37A` → `#F5804D` → `#C23B7A`, the
  wordmark's stops). **The ramp is mapped across the glyph's bounding box and
  weighted towards vertical.** Across the whole canvas, and on an even
  diagonal, a V only ever covers the middle of the ramp — it came out
  uniformly salmon with the gold and magenta both off the edges of the shape.
- **The shipped V is pixel art**, for the game-ish personality the app's
  points/stars/tiers earn. **The sprite is generated from one rule**
  (`build_v_sprite`), not typed out and not traced from the curve — three
  attempts, and only the third looked designed:
  - *Quantising the smooth polygon* gave steps of uneven length, two cells
    here and three there. That is what a low-resolution **render** looks
    like; sprite work has rhythm — the same step, the same run, all the way
    down.
  - *Typing the grid by hand* fixed the rhythm but put the taper off-centre
    by one cell, and the apex came out looking like a drip.
  - *Generating it* guarantees both: one cell across every two rows, and
    every row symmetric about the centre column by construction. There is an
    assertion's worth of truth in `all(line == line[::-1])`.
- **Band the ramp, don't gradient it.** A continuous gradient across the
  cells is the other thing that stops pixel art reading as pixel art; the
  palette is reduced to six steps and the bands are meant to be obvious.
- **Shade by each row's runs, not by each cell's neighbours.** Testing "is
  anything above/below me" lights or darkens nearly every cell on a
  staircase — every step has both — and the glyph came out speckled, busier
  than the version it was replacing. A run has exactly one left edge and one
  right edge, so lighting one and shading the other gives a single light
  direction and leaves the middle of each arm flat.
- **No drop shadow on the pixel glyph.** A one-cell offset drops a dark
  block into every notch of the staircase — correct for a shadow, ruinous to
  look at, because it breaks each arm into a string of beads.
- **A pixel glyph is drawn at the final size, never supersampled and
  reduced.** Reducing is exactly what softens edges, and soft edges are the
  one thing pixel art cannot have. A useful consequence, measured rather than
  assumed: it is *crisper than the smooth V at small sizes* — at 16px the
  smooth one is mush and the pixel one still reads.
- **The cell size is a whole number of pixels and the sprite is centred on
  whole pixels.** Deriving each cell's bounds by rounding instead let them
  come out 6px and 7px wide in the same icon, so the grid was visibly uneven
  — the clearest tell that it was not real sprite work. A little empty margin
  is a fair price for every cell being square.
- Below about 1px per cell the rounding can collapse a cell to negative
  width and `ImageDraw` raises. Boxes are clamped to a single pixel; the
  pixel look is long gone at that size, but it has to render, not crash.

`--preview DIR` renders every variant plus a `_masked` version approximating
what iOS will actually show, so the corners can be looked at rather than
guessed at. The alternatives all still build: `brand` (the smooth V),
`white`, `noir`, `pixel-noir` and `pixel-white`. Switching is one command and
a rebuild. The sprite's own proportions are `V_COLS`, `V_THICK` and
`V_ROWS_PER_STEP` — 3-thick arms read too thin to hold together across the
steps, which is why it is 4.

**The icon is install-time metadata.** Changing it does nothing on a device
that already has the app until that icon is removed and re-added — which is
what `frameId` and the re-add notice exist for. See **Going live**.

---

## Launching: the first frame

Three separate things had to be right before the launch stopped flashing and
sitting crooked. They fail independently, so a fix for one looks like it did
nothing.

- **The white flash was not in the page at all** — see the iOS section above.
  It was the launch screen iOS paints before the page exists, white for want
  of an `apple-touch-startup-image`. Two plausible in-page explanations were
  found, fixed, verified in Chromium, shipped, and changed nothing on the
  device, because a symptom that appears before first paint cannot be caused
  by anything after it. **If a launch symptom survives a fix that measurably
  works, the cause is outside the document; stop editing CSS.**
- The two in-page fixes are still there and still correct, just not the
  cure: `color-scheme: dark` and `html{background:#0A0A0A}` in the first
  `<style>`, both inside the first ~300 bytes, closing the window before any
  rule colours the canvas (nothing else does for ~280 more lines). Keep them
  early — a comment block or a parser-blocking script ahead of them loses
  the race. Testable: truncate the document, force a paint, sample the pixel.
- **Pick the viewport unit deliberately; all three were wrong once.** `dvh` is
  dynamic and grows as the viewport settles, so centred content drifts down.
  `svh` is static but is the screen *minus* overlaid insets, so it comes up
  short by exactly the home-indicator height and leaves a strip of app
  background below the splash. `lvh` is static *and* full-height — that is the
  one. `100vh` is declared first purely as a fallback.
- **Chromium cannot reproduce any of this.** `svh`, `lvh`, `dvh` and `vh` all
  return the same number here and `env(safe-area-inset-*)` is always `0`. To
  test a layout that only misbehaves once the insets are real, serve a copy
  with the `env()` calls text-substituted for real values — see
  `tools/sim-safe-area.py`. It caught a genuine bottom-edge seam that measured
  zero without it.

---

## Every device, every way in

**This is the bar for every change, and it is not negotiable.** Nothing ships
— no fix, no tweak, no audit — until it has been checked across the whole
matrix: every common device, **both orientations**, and **both ways of
running the app**.

```
python3 tools/sweep-layout.py        # the whole matrix, before calling anything done
python3 tools/sweep-layout.py --quick   # one per family, while iterating
```

**Added to the Home Screen and opened in a browser are two different apps.**
An installed app gets the whole display and real safe-area insets — notch,
status bar, home indicator. A browser tab gets a shorter viewport, with
Safari's or Chrome's own bars taking the top and bottom, and essentially no
insets. The same CSS lands differently in each. Checking one is not checking
the other.

The matrix covers iPhones (SE through Pro Max), iPads (mini, 10.2", Air,
Pro 11", Pro 12.9", Pro 13"), Android phones and tablets, and laptops from
a Dell Latitude up through a MacBook Pro 16" and a 1440p display — each
portrait and landscape, each installed and in a browser. Desktops are
browser-only. 21 devices, 70 combinations.

**The seed is a USED account, and that is deliberate.** With empty stats
Profile, Rewards, the Leaderboard, the calendar, the review list and test
history all render their *empty* states, so half the app was being checked
as "nothing here yet". The seed carries real points, a streak, nine test
results and three weeks of study log so those screens lay out the content
people actually see. It also carries `onboardingComplete`, without which
the tab bar never appears anywhere (see below).

It reports horizontal page scroll, anything painting outside the viewport,
the primary button colliding with or hidden behind the tab bar, the tab bar
off-screen, controls colliding with the notch or home indicator, and uncaught
JS errors.

**The below-the-fold check used to sit inside the tab-bar branch**, so it
only ran on screens whose tab bar was visible — which is every screen except
onboarding, the exact place a primary button is most likely to fall off the
bottom. It is its own branch now. It also asks the right question: not "is
the button below the fold" (a long screen that scrolls to its button is
working as intended) but "is it below the fold **and** the page cannot
scroll to it", which is the only version of this that is actually a defect.

**It must cover every screen it can mount, not a handful.** It began with 6
of the app's 44 and reported `62/62 clean` while a regression had left
*every onboarding screen* — Welcome, the intro, username entry, character
select — bunched at the top with dead space below. None of them was in the
list. It now runs 25: everything that can be mounted cold.

**`showX()` names overlays as well as screens, so the count is not the
gap it looks like.** There are 45 `showX()` functions and 25 of them are
in `SCREENS`. The other 20 are excluded on purpose and fall into three
groups, checked rather than assumed: **overlays and banners**, which have
no screen of their own (`showToast`, `showNoticeBar`, `showUpdateBanner`,
`showFrameNotice`, `showDailyAlert`, `showTierUpBanner`,
`showPointsFlyEffect`, `showSafariFallback`, `showContextualInfo`,
`showDailyQuestionLockedPopup`, `showPracticeTestConfirm`,
`showCountdown`, `showVroomReadyFlourish`,
`showVirtualRoomFinaleReveal`); **screens needing run state**
(`showBankProblems`, `showAnswerReview`, `showTestHistoryDetail`,
`showVirtualRoomLobby`, `showVirtualRoomResults`); and one that renders
nothing on its own (`showGeneratingProfile`). **Anything else new belongs
in `SCREENS`** — a green sweep is only worth what it looked at, and the
way to check is to diff the app's `^function show` list against `SCREENS`
rather than to trust this paragraph.

**The sweep is an AUDIT, not a look.** It answers "is anything broken on
this device" — overflow, collisions, insets, JS errors. It does not answer
"did the thing I just positioned land where I meant it to", and a green
sweep says nothing about that. Both questions need asking on the whole
matrix. Asked properly the second time round, after a session whose
screenshots had only ever been taken at 440×956 and 834×1194, it found
three real defects a 66/66 sweep had sailed past: Start Studying 70–75px
off-centre on an iPad Pro 12.9"/13" (the fix for it was inside a phone
media query), the Welcome hint 20px below the fold on an SE 2nd/3rd gen,
and "What This Actually Is" overflowing its viewport on *every* short
device in the matrix — which in turn put its Continue button 184px away
from where every other onboarding screen puts it, while measuring 0px
apart on a Pro Max. `tools/check-positions.py` is that check: measure the specific decisions, on every device, and flag the
outliers rather than eyeballing two.

### Why this matrix and not a smaller one

Every bug below was invisible at 390×844 in a desktop browser, which is where
"looks fine" usually comes from:

- **A `padding` shorthand on `.wrap` under 32rem wiped out all four
  `env(safe-area-inset-*)` longhands** — so *every phone* lost its insets. On
  a notched iPhone the screen title sat at y=20 under a 59px status bar,
  behind the clock. **Never set `padding` shorthand on `.wrap`; use
  longhands**, or the insets go silently.
- **Do NOT add `env(safe-area-inset-bottom)` to the space reserved for the
  tab bar.** An earlier pass did, reasoning that the bar grows by the inset
  so the reservation must too. Measured, that is double-counting: the bar's
  whole footprint on an iPhone 15 is its offset (`0.6rem`) plus its 101px
  height — under 7rem *with* the home indicator already inside it — so the
  flat `7.5rem` covers it, and the addition opened a second gap of the same
  size under the button.
- **`min-height:calc(100dvh - Nrem)` must subtract only the EXTRA the insets
  add, not the insets themselves** — `var(--pad-inset-top)` /
  `var(--pad-inset-bottom)`, which are `max(0px, inset - baseline)`.
  Subtracting the raw insets double-counts the baseline the rem figure
  already contains: it took **~93px off every panel** on a notched iPhone
  and left every screen in the app bunched at the top with dead space under
  it. Each formula must collapse back to its original value at zero insets —
  that property is what makes a change here safe to reason about.
- The laptop collision: Home did not fit a 768px laptop screen (~640px of
  page in Chrome) and hid the primary action behind the tab bar.
- The tab bar was a fixed 344px wide, off both edges of a 320px phone; the
  Rewards tab switcher overflowed sideways below 384px.

**Short-viewport tiers must be short AND wide** — `(max-height:Nrem) and
(min-width:34rem)`. Height-only was the first instinct, on the reasoning that
the problem is purely vertical, and it was wrong: it also fires on a phone
held *upright*. An iPhone SE is 667px tall and was fitting comfortably, and
the tier shrank its hero from 295px to 227px and its title with it, for no
reason. The `34rem` floor keeps the tiers to what they were written for —
laptop windows and phones on their side. Home has three: 50rem, 36rem, 26rem.

**A full-bleed bar pinned to the bottom edge is supposed to reach the edge.**
It clears the home indicator with *padding*, not by stopping short — so
inset checks measure the CONTENT box, never the border box. `.floatbtn` does
need `padding-left`/`padding-right` insets though: full-bleed puts its label
under the notch on a phone held sideways.

**Clear the home indicator by MOVING a fixed element, not by padding it.**
`.bottomtabs` used `padding-bottom:max(.4rem, env(...))`, which grew the pill
downward by the whole inset — 34px of empty glass under the icons on an
iPhone, leaving them sitting high in a bar that looked wrong. An iPad's 20px
inset made the same mistake less obvious, which is why that one "looked
perfect" by comparison. `bottom:calc(.6rem + env(...))` keeps the pill the
shape it was designed to be on every device, and the total space it occupies
is unchanged. The offset itself is how low the bar sits — it was `1.1rem`
until it was reported as sitting too high; at `0.6rem` the pill clears the
home indicator's inset by 10px on both an iPhone and an iPad. Only ever
lower it toward the edge, never past it: the `7.5rem` reservation above
assumes the bar's whole footprint still fits inside it.

**A laptop is not a tall tablet either, and gating the enlargement on
height alone missed them all.** The `(min-width:40rem) and
(min-height:60rem)` block that scales Home's sphere and type up for a
tablet needs 960px of height — which an iPad in portrait clears and a
laptop browser window does not. A MacBook Pro 14" leaves 852px once
Chrome's chrome is gone, so it was falling all the way through to the
*phone* sizing: measured, a 368px sphere and a 15.2px tagline centred in a
1512px viewport. The fix is a second condition, `(min-width:64rem) and
(min-height:46rem)`: width is the safe way in, because the thing the
height gate protects is a short iPad in landscape, and those are 834px
tall at 40–52rem *wide*. Requiring 64rem of width excludes every one of
them and takes in every laptop.

**A tablet is not a big phone.** The hero sphere carries these screens and it
is the one element that can absorb a tablet's height — but **size it in `vh`,
not a flat `rem` cap.** `min(36rem, 56vh)` fits an 834×1194 iPad beautifully
and pushed Start Studying behind the tab bar on a 768×1024 one and on every
iPad in landscape. `min(36rem, 48vh)` serves both. The same applies to the
margins around it: fixed `rem` gaps that look right at 1194 are what tip a
1024-tall iPad over, so they are `min(2.4rem, 3vh)` and so on.

**`.panel.home` is `align-items:center`, so a flex child sizes to its own
content.** The fourth "What This Actually Is" card has the shortest text and
came out visibly narrower than the other three on an iPad; on a phone all
four wrap to full width, so it never showed there. Anything meant to be a
full-width row in that column needs `width:100%` explicitly.

**Welcome's layout is auto margins at every width now, not just on a
phone.** The tablets kept `justify-content:center`, which floated the
whole five-item column in the middle of a 1194px iPad with slack both
above the sphere and under the hint — "the stuff underneath the planet
system needs to be moved down or spaced out". `flex-start` plus
`margin-top:auto` on the hero and on the actions block puts the leftover
height where it reads as layout and lands the actions on the panel floor
on every device.

**Welcome also carries its own `--panel-reserve`, because it has no
bottom furniture.** It has no tab bar and no floating button, so the
shared `4rem` of `.wrap` bottom padding is reserved for things that are
not there — and that alone was holding the hint 82px off the bottom edge
everywhere. `body.on-welcome` (toggled in `syncVisibility()`, the same
self-clearing hook as `has-bottomtabs`) drops it to `2.25rem`, which
brings the hint to ~50px and 62px on a device with a home indicator.
**All three values move together**: `--panel-reserve` is `.wrap`'s top
padding plus its bottom padding, and `--pad-inset-bottom` is whatever the
inset adds *over that new bottom baseline*. Change one and the panels
mis-size — this is the same arithmetic that once cost every panel ~93px.

**Two `auto` margins centre an item in the leftover space.** That is the
right tool when a button should sit *between* the content and the bottom of
the panel rather than tucked under the content or jammed at the floor.

**A bottom margin on the last item is a self-cancelling gap, and it is the
only way to say "centre it when there is no room, floor it when there is".**
CSS has no `margin-top: max(2.5rem, auto)`. But a margin on the LAST CARD
is absorbed by the button's `margin-top:auto` wherever slack exists (a 13
mini has 113px of it — nothing moves) and, where there is none, grows the
panel past its `min-height` and carries the button down into the reserve
below it instead. On an SE 2nd/3rd gen that turned 3px above / 87px below
into 45/45 while every roomier device stayed byte-identical. It costs **34px**
of scroll on the SE (27px before the intro cards' gaps were raised; three
gaps at +2.4px each is the whole difference) — and measured rather than
assumed, **that scroll is slack below the button, not the button**: on an
SE 2nd/3rd gen Continue's bottom edge sits at 629 in a 667px viewport, 38px
above the fold and visible without scrolling anything. So the trade is
cheaper than it reads. Guard it with a `min-height` so it does not land on
a device that is already overflowing badly.

**A screen that overflows its viewport cannot honour a shared button
position, so making it fit IS the fix.** "What This Actually Is" is the
one onboarding screen with enough content to overflow, and wherever it
did, its Continue landed after the content instead of on the panel floor.
Two height tiers bring it back inside: `(max-height:52rem)` — height-only
on purpose, because here the upright phone *is* the case the rule exists
for — and a narrower `(max-width:32rem) and (max-height:44rem)` that also
trims the panel's side padding, since every pixel of column width is text
that does not have to wrap and a wrapped line costs ~17px four times over.
The body type stays at `.8rem` throughout: it was raised from that size
once already on an explicit report that it was too small to read, and
buying 20px back by undoing that is a bad trade.
An iPhone SE **1st gen** (320×568) still scrolls this screen and is not
expected to stop — four cards of real text do not fit a 4-inch display,
and hiding a card would be worse than a scroll.

**Every onboarding Continue button sits on its panel's content floor, and
that is the point.** Two separate attempts to give "What This Actually Is"
a position of its own (auto on both sides, then auto plus a fixed
`2.25rem`) both came back as *"slightly higher than the other continue
buttons"* — 29px on a phone, 120px on an iPad. There is nothing to tune
here: the answer is the shared floor, plus the same `padding-bottom:1.5rem`
every other `.panel.home` screen uses, or the floors themselves differ.

**The gap BETWEEN the intro cards has to beat the padding INSIDE them, or the
four of them read as one slab.** Reported as "awkward sized gaps" on an iPad,
and it was: measured, each card carried 35px of padding and only 27px of
margin below it, so the air inside each box outweighed the air separating
them. Phones never showed it — there they were 15/15 — which is why it
survived several passes. Each tier sets both numbers together
(tablet `margin-bottom:2.4rem` / `padding:1.8rem 2rem`, and so on down), and
the table in **Where things currently land** records the pair per device so
the relationship can be checked rather than eyeballed. The last card's margin
is cancelled by the shared-floor rule above, so raising it costs nothing at
the bottom of the panel.

**An auto margin only ever moves the things ABOVE it.** All the free space
in a column ends up above the last child no matter how many auto margins
divide it, so where the *other* children land is the only thing the split
decides. Welcome's phone layout wants the buttons low and the sphere where
it is, so the hero and the actions block take the two autos and the title
takes a fixed `1.6rem`. A third auto on the title instead divided the space
evenly and opened a 100px hole under the sphere — which measured correct and
looked like a gap in the screen. Fixed gaps are spacing; auto gaps are
leftovers.

**An `auto` margin in the main axis beats `justify-content` outright.** Free
space is handed to auto margins first and `justify-content` only ever sees
what is left, which is nothing. So `justify-content:center` plus
`margin-bottom:auto` on the last child is not "centred, a bit lower" — it is
the whole group jammed against the top. Home's phone rule
(`.panel.home.screen-home-actual .playbtn{margin-bottom:auto}`) has to be
explicitly reset to `0` inside the tablet block for exactly this reason.

**A `position:fixed` control holds no space, so the layout has to reserve
it by hand.** Home's daily-question circle and its version label are both
fixed off the bottom edge; Home's primary button was centred between the
tagline and the **tab bar**, which starts 54px *below* where the circle
starts. Measured, the two collided outright: Start Studying overlapped the
"?" by 8×44px on an SE 2nd/3rd gen and 8×9px on a 13 mini, and cleared it
by **one pixel** on a 14/15/16. Every phone was within a rounding error of
the same bug and the ones that looked fine were lucky, not right. The fix
reserves the row rather than nudging the circle —
`[data-layout="modern"] .panel.home.screen-home-actual{padding-bottom:5rem}`
on `(max-width:32rem)` — so the two auto margins go on centring the button
exactly as asked, just between the tagline and the furniture genuinely
below it. Padding is inside the border box, so the panel's `min-height` is
untouched and nothing that fit before starts scrolling. A tablet needs
none of this: its circle and label sit in the corners beside the centred
tab pill, 118px clear of the button.

**Where Home already overflows, padding below the button cannot move it** —
the button is at the end of the content, not on the panel floor, so the
height has to come from something real. The hero is the only element with
300px to spare, and `(max-width:32rem) and (min-height:36rem) and
(max-height:48rem)` trims it to `min(23rem, 34vh)`. Short AND **narrow**,
which is the opposite gate from the laptop tiers (short and *wide*) and
must not catch their devices. Both ends matter: without the `48rem`
ceiling a 13 mini at 812px loses a hero it has the room for, and without
the `36rem` floor this four-class selector reaches down and *undoes* the
`max-height:36rem` tier — an SE 1st gen's hero went from 148px back up to
210px on the first pass. The band that actually needed it, swept across
every phone height from 540 to 980px, is 736–800: a 14/15/16 in a
**browser tab** is 393×742 once Safari's chrome is gone, and that is where
the button landed level with the circle with 3px of horizontal gap between
them.

**`tools/check-fixes.py` now measures that row, and `check-positions.py`
measures the button against it** rather than against the tab bar — the
"centred" number that hid the collision was correct arithmetic about the
wrong floor. `check-fixes.py` takes `--only` like the sweep does.

**The same rule used deliberately is how four screens share one button
position.** `::before{content:"";margin-top:auto}` on the panel plus
`margin-top:auto` on the button gives two auto margins with the content
between them: the group floats mid-screen and the button lands on the panel
floor — the *same* floor on every screen using it, whatever its content
height. That is what puts Continue in one spot across username, character
select, Pick your class, the code screens and "You're all set", which
centring each screen separately cannot do (it left a 125px spread on an
iPad).

**"What This Actually Is" is on that rule too now, and the exception that
kept it off was a measurement with a shelf life.** It had the button half
(`margin-top:auto`) but not the `::before` spacer, on the reasoning that
four full-height cards plus a title left no spare height to float into —
correct when it was written. The cards then lost height in the gap fix
(padding down to `1.8rem` so the gap between them could beat the padding
inside them), and with only one auto margin the whole screen sat at the
top: **280px of dead space above Continue on an iPad Pro 11", 452px on a
12.9"**, reported as the one screen that stood out. With both autos it
floats like its neighbours (280 → 159, 452 → 245) and **Continue does not
move by a pixel** on any device, which is the property to check after
touching any of these screens. Where a screen genuinely has no slack —
every phone, the shortest laptops — an auto margin distributes nothing, so
adding one cannot strand anything. **The lesson is the shelf life, not the
rule**: an exception justified by a measurement needs re-measuring
whenever the thing it measured changes.

**`justify-content:space-between` spreads the leftover height into EVERY
gap, including ones that belong together.** Welcome's two buttons are styled
11px apart and measured 41px apart on an iPhone because each of the five gaps
in that column got an equal share. Grouping the pair (and the line explaining
them) into `.cosmic-welcome-actions`, one flex child, is the fix — the free space then lands *between*
blocks rather than inside one. Welcome is now plain `justify-content:center`
on a phone as well; space-between made the remaining three gaps ~50px each,
which read as three holes rather than a filled screen.

**Anything appended to `<body>` must clear itself on navigation.**
`.daily-alert` is `position:fixed`, so it cannot live inside `#stage` —
`#stage` animates, and a transform on an ancestor re-parents a fixed
element's containing block, which is the documented cause of the daily
button's own old positioning glitch. So it goes on `<body>` and takes a
one-shot `MutationObserver` on `#stage` that removes it on the next screen
change. It also has to be created *after* its own screen mounts: announcing
from inside `showHome()` before `stage.replaceChildren()` had the mount
immediately remove it, which a `setTimeout(…, 0)` fixes.

**A control hidden with `[hidden]` stops holding the layout up.** Three
onboarding screens gate Continue until something is chosen, and
`display:none` takes its `margin-top:auto` with it — so on a tablet the
panel's `::before` spacer was left as the only auto margin and swallowed
every spare pixel, sinking the whole screen to the bottom. Reported as
"all the stuff got pushed to the bottom" on Pick your class, Enter a
username and Choose a character, with "You're all set" (button never
hidden) looking right beside them. `visibility:hidden` is the tool: the
box and its auto margin stay, it is still out of the accessibility tree
so nothing announces a button that does nothing, and the layout does not
jump when the button arrives.

**Nothing may sit on top of a loading screen — and z-index alone does not
enforce it.** `#genprofile-overlay` was `z-index:200`, tied with
`.bottomtabs`, so the tab bar painted alongside a full-screen loading
state and stayed tappable *through* it; tapping Settings there started
the Settings tour on top of "GENERATING PROFILE". The overlay is 400 now
(above the tour overlay at 205 and its tooltip at 210), and
`startSimpleTour()` refuses to start while `#genprofile-overlay` or
`#splashscreen` exists. It **waits** rather than abandoning, because
every caller sets its own `seenXTour` flag to true *before* calling, so a
tour dropped there is one that person never sees; it gives up only if the
screen it was called for has been replaced, or after
`TOUR_OVERLAY_WAIT_MS`.

**A screen mount blurs a still-focused text field, and that
`MutationObserver` on `#stage` is load-bearing.** Focusing a field on iOS
scrolls the page to keep it above the keyboard; replacing that field's
screen while it still has focus dismisses the keyboard **without ever
undoing the scroll**, so the page is left pushed up — and because most of
this app's chrome is `position:fixed`, everything reads as shifted with
nothing to put it back. That was "the character screen comes up
off-centre and stays that way". The observer blurs the field and returns
to the top, and it is **deliberately conditional**: ordinary navigation
must not have its scroll position reset out from under it, so it only
fires in the one situation that causes the problem. Chromium has no soft
keyboard and no visual viewport offset to leave behind, so this cannot be
reproduced or regression-tested locally — don't "simplify" it because
nothing appears to depend on it.

**Dead code that appends to `<body>` is worse than dead.** `showTourSendoff()`
— the old "You're all set" popup — had not been called in a long time (the
send-off is the last step of `startMainMenuTour()` now), but it attached its
overlay to `<body>` rather than `#stage`, so nothing cleared it on a screen
change. Anything that called it, including a harness mounting every screen by
name, left it stuck over whatever came next. Deleted.

**A fixed element's offset from the bottom must carry the safe-area
inset if the thing it clears does.** `.homeversion`'s `6.2rem` offset did
not, while the tab bar's own height does — so the version label sat at
727..753 against a bar starting at 733, hidden behind it on precisely the
notched devices where anyone goes looking for a version number. It carries
the inset now. It also reads `v6.0` on a phone and `Version 6.0` from
tablet up, as **two spans picked by CSS** rather than a string chosen once
at render: the right answer changes when a device is rotated, and a
JS-chosen string does not.

**The sync code field is centred, mono and narrow, and all four parts
matter.** Reported as the x's not lining up with the box. A code is a
fixed-length string of characters, not prose, so it is
`text-align:center` + `var(--mono)` + `letter-spacing:.14em` inside an
`11rem` wrap — the narrow wrap is what makes centring read as deliberate
rather than as text stranded in a wide field, and the mono face is what
stops the characters drifting relative to each other. Widening the field
undoes the fix even with the centring left in.

**Tap targets: 44px minimum, and check them.** A sweep of every button
found the Settings controls running at 12.5–13.1px text in 40px boxes while
the primary button was 16.8px in 48px — `.cal-profile-btn`, `.more-toggle`,
`.restart` (22px tall) and `.daily-question-fab` (41.6px) were all under it.
Secondary does not mean small. Where a text link has to stay a text link,
give it padding and pull the padding back out with a negative margin, so the
target grows without disturbing the layout.

**A phone-only refinement needs a height floor as well as a width ceiling.**
Widening Home's column and opening up its text block is affordable at 852px
and pushes Start Studying behind the tab bar at 667px. `(max-width:32rem)`
alone is not "phones like mine", it is *every* phone, including an SE and
every phone in a browser tab. Pair it with `(min-height:46rem)`.

**`[data-layout="modern"] .panel{padding:1.5rem 1.25rem}` sits ~900 lines
below the phone rules and wins on source order.** Any phone override of
panel padding needs the `[data-layout="modern"]` prefix or it silently does
nothing — the same trap as `.opt .box`, `.next`'s box-shadow and
`.bottomtab-label`. The symptom is subtle: everything else in the block
applies and only the padding is ignored.

**A fix that stops overflow by squashing is not a fix.** The first attempt at
the Rewards switcher let the flex items shrink below their own `nowrap` text:
the page stopped scrolling sideways and the three labels overlapped instead.
**Look at a screenshot, not just the numbers.**

**Mounting an onboarding screen is not the same as reaching one, and the
difference moves the layout.** `showWelcome()` hides the nav buttons the
bottom tab bar derives its visibility from; every onboarding screen is
reached through it. Calling `showWelcomeIntro()` cold against a seeded
(finished) account skips that, so the bar stays up — which puts a tab bar
into screenshots of screens that never have one (reported twice as "a
massive bug", and it is not one: walked for real, both the create-account
and the sign-in-with-a-code paths report the bar `hidden` with height 0 on
every screen) **and** swaps `--panel-reserve` from 5.5rem to 9rem, which
moves every button on the screen by 3.5rem. Both `sweep-layout.py` and
`check-positions.py` now call `showWelcome()` first for anything in their
`ONBOARDING_SCREENS` set, and `tools/shoot-flow.py` is the
pattern for screenshots: click through from a fresh `localStorage` rather
than mounting anything.

**The bar is also now structurally impossible during onboarding**, not
merely absent: `syncVisibility()` requires `store.onboardingComplete`, the
same flag that decides at boot whether the app shows onboarding at all, so
the two cannot disagree. A harness that seeds a finished account has to
seed that flag too, or the bar will never appear anywhere.

**Diff a new tier against the one that is actually winning, not against
the base.** A laptop tier added at `(min-width:40rem) and
(max-height:44rem)` used values chosen as reductions from the *tablet*
block — but a short-viewport tier was already overriding that block, and
the new values were larger than its. Being later in source they won, and
the two shortest laptops came out bigger instead of tighter: a Dell
Latitude went from 49px above its button to 35 and picked up 23px of
overflow. The computed value is the only thing worth comparing against.

**Chromium cannot see any of this by itself.** It reports every
`env(safe-area-inset-*)` as `0` and has no display-mode emulation, so the
sweep simulates both — insets by substituting real values into the served
copy, standalone by patching `navigator.standalone` and the display-mode
media query. The inset figures and browser-chrome heights in `DEVICES` and
`CHROME_H` are *modelled, not measured from hardware*; correct them there if
a real device disagrees, rather than guessing again.

**Internet Explorer is not supported and cannot be.** The app is built on CSS
custom properties, `color-mix()`, `clamp()`, viewport units and modern DOM
APIs (`replaceChildren`, `IntersectionObserver`), none of which IE has.
Modern Edge is Chromium and is fine. Worth ruling out if someone reports "it
doesn't work", but there is no fix short of a rewrite.

---

## Accounts and the sync code

**The sync code IS the account.** Both Firestore collections are keyed by
it as the document id, there is no sign-in of any kind, and anybody holding
a code can link a device and read or overwrite that person's progress.
Everything below follows from that.

- **Never put a username → code lookup in the app.** The collection is
  world-readable, so a lookup shipped in `index.html` is a lookup all ~40
  classmates can run against each other. `tools/firestore-admin.py find`
  exists for the one person with the repo. Handing a code to somebody who
  asks for it is handing over their account — check their level/hundos
  against what they tell you first; usernames are not unique.
- **An onboarded account always has a code, and boot enforces it.** It is
  issued at sign-up, but it lives in `localStorage`, which iOS can evict on
  its own — and a device that has lost it is off the rankings, cannot be
  linked to, and cannot be recovered by anyone. So `store.onboardingComplete
  && !syncCode && !syncOff` issues one. `class26e.syncoff` is the only
  thing that holds that off, and only "Stop syncing this device" sets it —
  a reset deliberately does not, because a reset also clears
  `onboardingComplete` and the sign-up that follows issues its own.
- **The code is mirrored into IndexedDB beside the progress store**, and the
  mirror is written from `persistLocally()`, not only from `setSyncCode()`.
  `setSyncCode()` does not run on an ordinary launch, so mirroring only
  there would have recovered an existing install's progress under a
  brand-new code — the same person, quietly become a different account.
- **Recovery has to finish the job.** `if(!storageHadData)` used to restore
  the store from the mirror and then leave the person on the Welcome screen
  boot had already drawn, because the only screen it knew how to put right
  was Setup. That is the reported *"I hit update, came back, and it was at
  the welcome screen"* — and it is worse than it reads, because creating an
  account from that screen overwrites the progress sitting right behind it.
  Recovery now restores the code, reconnects, and lands on Home.
- **Abandoning a code must take its rankings row with it**, and that lives
  in `setSyncCode()` rather than at each call site, so every path that
  changes a code is covered including any added later. Linking this device
  to another account used to strand the old row on everyone else's board
  with nobody left holding the key to delete it. `retireLeaderboardEntry()`
  deletes **only** the rankings row, never the progress document, which may
  still belong to a device happily syncing under that code — which also
  makes it safe to fire speculatively: unowned, the row goes for good;
  owned, the next push puts it straight back.
- **Two synced devices are one row by construction**, because the row's
  document id is the shared code. Duplicates on the board are not two
  devices — they are separate sign-ups, each of which minted a code of its
  own, plus the orphans above.
- **Find me has three reasons to fail and naming the wrong one is how this
  was reported**: a device with no code was told to turn on a setting that
  was already on. Not loaded / hidden (`leaderboardOptIn`) / not syncing
  (`!syncCode`) are separate messages. A brand-new account with no data is
  **not** one of them — `liveEntries()` synthesises your row at zero — so
  nothing there may ever say "not in the rankings yet" to somebody who
  simply has not answered a question.
- **Safari and the installed app are separate storage jars on iOS.** The
  re-add notice's `x-safari-https:` hand-off lands in a jar with no
  progress in it, showing Welcome. Signing in with the code is the way
  back; creating an account there is a second profile on the board.

---

## Levels, badges and ranks

The three things the app measures are **XP → level**, **badges**, and
**hundos**, and every screen that shows progress is built on those three.

- **A badge is a mastered unit, and mastery is `BADGE_THRESHOLD` (35)
  hundos in it.** Sixteen units, sixteen badges. `DRILL_STAR_THRESHOLD` is
  *written as that same constant* rather than as another literal, because
  it was a separate 40 for the same idea and a unit could read "Advanced"
  on its own card while still not being starred.
- **`levelProgress()` is the one place the level curve lives** — the
  level, how far into it, how far across, and what is left. The bar, the
  number under it and the leaderboard each used to do their own
  arithmetic on the same total. 300 XP at +5% a level, capped at 80. The
  cap came with the curve: 500 at +15% compounded 80 times asks for about
  200 million XP when an aced three-unit test pays under a thousand, so
  the ceiling Madison asked for was unreachable until the curve moved.
  **Check that a curve change cannot lower anybody's level** before
  making one — that property is what made this one safe.

### Ranks

**A rank and a flare are two different things, and they used to be one.**
The tiers were named after the flares — Spark, Ember, Comet — so the
Mastery Ladder and the Home screen's orbit were two names for one thing,
and climbing gave you nothing to be *given*. The ranks have their own
names now (`RANK_DISPLAY_NAME`) and the flare is one of the things a rank
**hands over**. Reaching Bronze lights the Ember flare and unlocks the
Ember colour; the rank is not called Ember. Keep that distinction in any
copy you write: `ACCENT_DISPLAY_NAME` is the flare/colour,
`RANK_DISPLAY_NAME` is the rank, and they have separate swatches
(`ACCENT_SWATCH` vs `RANK_COLOR`) for the same reason — a rank the same
colour as its own reward has nothing left to be.

**THE RANK NAME IS ITS COLOUR: Iron, Bronze, Silver, Gold, Sapphire,
Amethyst, Crimson.** That is the thing the reference does that makes it
read at a glance, and it took two passes to see it. Role names — Rookie,
Ranger, Veteran, Vanguard, Sentinel, Elite, Titan — carry no colour, so
seven coloured cards were seven arbitrary colours you had to learn. The
**keys are still those role words** and must stay: `TIER_UNLOCKS`,
`ACCENTS`, `ACCENT_SWATCH` and a theme somebody already has selected are
all keyed by them, so renaming a key is a migration for a cosmetic gain.

- **The thresholds did not move.** `TIER_UNLOCKS` is the same table with
  the same level-and-badges pairs; the keys are the same too, which is
  what kept this a rename rather than a migration — `ACCENTS`,
  `ACCENT_SWATCH` and a theme somebody already has selected are all keyed
  by them. **`adept` displays as "Sentinel"** and that is the one place a
  display name does not match its key: `adept` reads as a beginner's word
  sitting between Vanguard and Elite, and renaming the key would have
  touched a stored preference for a cosmetic gain.
- **`rankOfStats(level, badges, mystery)` is the single definition of who
  holds what**, and it takes the numbers rather than a store, because the
  rankings and the Virtual Room ask it about *other people* from a
  published document. `rankOf(store)` is the wrapper for yourself.
- **`mystery` is published to the leaderboard and to the room.** Titan
  needs all three Secret Flares, so without it every remote person is
  capped at Elite however far they have actually got. An older document
  lacking the field reads as 0 and self-heals on that person's next push.
- **SEVEN DIFFERENT MARKS, not one mark at seven sizes.** Three sets
  came before. The app's V inside a frame that gained wings and horns
  escalated but had nothing to do with the app. The one after that was a
  star inside a corona ring with rays coming off it, and it **read as a
  wheel** — which is what a ring plus evenly spaced radial lines always
  reads as. The third was generated from a single table (same star, more
  points, bigger radius) and came back as *"I dont like how they are all
  nearly identical just different in size, that's not the idea i had in
  mind."*
  **The escalation is a change of KIND, not of size.** Iron, Bronze and
  Silver are service insignia — one, two and three chevrons, flat,
  struck from metal, centred on the frame whatever the count. Gold is
  the turn: the chevrons collapse to a single base and a star takes the
  emblem. Sapphire drops the base entirely for a cut stone held between
  two crescents. Amethyst crowns it, doubles its points and throws
  sparks. **Supernova** is the app going off — a white-hot core rather
  than a coloured one, a blast shell drawn as broken arcs, flares longer
  than the frame and debris past the shell.
  `check-behaviour` asserts this structurally rather than by eye: the
  bottom three contain a straight-segment path with no curve in it, only
  the top one contains an arc command, and no two ranks produce the same
  shape signature.
- **The glow is a CIRCLE filled with the falloff gradient, not a burst
  shape filled with it.** A twelve-point burst at a wide waist is a
  bulging rounded square, and filled with a soft gradient that is exactly
  what it looked like — a coloured tile behind the emblem rather than
  light coming off it.
- **Reflecting an angle is `PI - th`, and the offset from straight up is
  not the angle.** Every "mirrored pair" of sparks in two successive
  versions landed both copies on the SAME side, because `[a, PI - a]`
  was being applied to the offset from `UP` rather than to the absolute
  angle. Visible as a star with all its sparks on the right.
  **Nothing in the current one is a circle or a spoke.** The arms are
  concave-sided: each side is a quadratic curve whose control point sits
  on the bisector at `waist`, so the tips are sharp and the sides are
  drawn in. That is the shape a light source makes and it cannot be
  mistaken for a rim. The small sparkles sit **in the gaps between the
  arms**, never on their axes, because a sparkle on an arm's axis is
  that arm made longer, which is a spoke again.
  **Lens streaks are always at different lengths** horizontally and
  vertically, because equal ones make a cross and a cross is a plus
  sign, not a flare. **Scattered sparks go in mirrored pairs at varying
  radii** — evenly spaced ones at one radius are a ring of dots, and a
  ring of dots round a star is a wheel again.
- **The top rank is called Supernova**, and that is the one place a rank
  is not named after its colour. Asked for by name: *"the very last one
  needs to be called supernova and it needs to be very cool."* Its key
  is still `titan` and its colour is still `#E23B3B`. It shares a name
  with its own flare, which the rule about ranks and rewards would
  normally forbid — here it is the point: the rank IS the app going off.
- **A locked rank still shows its colour.** The emblem is always drawn in
  the rank's own colour and the card only turns it down; it used to
  redraw in grey with the name in `--soft`, so four of the seven cards
  were the same colourless card and you could not see what you were
  heading towards. `check-behaviour` asserts all seven `--rank-color`
  values are distinct and set.
- **A rank card has a backdrop, in three layers and none of them an
  image**: the rank's own emblem enormous and almost invisible behind
  everything, a diagonal wash of its colour, and a vignette to stop the
  wash reaching the corners. The watermark reuses `buildRankEmblemSVG`
  rather than being a second drawing, so the two can never disagree, and
  it has to be **too big to read as an object** — at 78% it sat inside
  the card as a smaller second emblem below the real one, which is a
  duplicate, not a watermark.
- **The card is a GRID, and that is what lets one piece of markup be two
  layouts.** The name sits BESIDE the emblem on a phone and ABOVE it on
  a tablet, and no `flex-direction` can express that with one DOM order
  — `grid-template-areas` can. On the wide layout the header strip pulls
  back out through the card's own padding to run edge to edge with a
  rule under it, the way the reference's tier name does.
- **The glow comes off the emblem with a CSS `drop-shadow`, not an SVG
  filter.** SVG filters are the one feature that has bitten this app on
  real iOS hardware; `filter:drop-shadow()` on the element is safe and is
  what the hero already animates.
- **The meter belongs to the rank you are climbing to, and nothing
  else.** Every unreached rank carried one, which put a half-full bar on
  Crimson while you were working on Gold — progress towards something
  you are not working towards. A locked rank says what it costs and
  stops there.
- **The emblem is lit or it is not.** It was two stacked copies with the
  lit one clipped from the bottom, so a rank part-way earned was
  part-way lit — asked for, built, and then explicitly asked against
  ("the stuff slowly being filled up with colour is not the move"). A
  rank is something you hold or do not, and a waterline across it says
  neither. **Don't bring it back.**
- **Four states, and each card says which in a word.** Reached / You are
  here / Up next / Locked, as a chip. The colour and the dimming say it
  too, but only to somebody who has already worked out the code, and
  "what you are, what you have, what is to come" was the thing the
  rebuild was asked for. A meter appears only on a rank you have not
  reached; on a reached one it is a bar that is always full, which is
  noise.
- **One full-width row per rank, at every width.** Two short cards per
  row was the phone layout and it was reported as atrocious; the upright
  four-across card that replaced it on a tablet was reported next — seven
  of them wrap four-then-three, so the climb reads left to right and then
  left to right again. A ladder has one reading order. The phone
  arrangement was already the simple one and was already liked (*"I also
  like how you have it shown on the iPhone, you are making it a
  scrollable screen, that's a great idea"*), so a wide screen gets the
  same thing with more room rather than a second design: only sizes
  change at 46rem and 62rem, no grid areas move.
- **The tab is called "Ladder", not "Ranks".** The bottom bar already
  says Rankings and two things with the same name was reported as
  confusing. Renaming the bottom tab was the other option and is the
  worse one — "Rankings" there is a measured WIDTH decision (see
  `showRankings`) and "Leaderboard" does not fit a 320px phone's bar.
  The tab KEY is still `"ranks"`, and `"ladder"` was already an accepted
  alias, so nothing stored or linked had to move.
- **There is no Secret Flares box on this tab.** It was the one thing on
  the screen that was not a rank, with its own header, its own progress
  bar and its own vocabulary, and it came off per explicit request
  (*"this rank screen needs to be very simple to understand ... very
  clean"*). The hunt is untouched: the flares are still hidden in the
  app, finding all three still unlocks the Eclipse colour, and the top
  rank still needs them — which its own card says, because its
  requirement line lists them like any other requirement.

- **Only list rewards that exist.** Each card names three: the flare on
  Home, the theme colour, and the rank's emblem beside your name. The
  reference lists four per tier and it would have been easy to pad;
  a reward that does not exist is worse than a short list.
- **A person's rank hangs off their character, not beside it.**
  `decorateAvatar()` is the one builder — the three rankings boards, the
  Virtual Room lobby and the Virtual Room results all call it, so a
  classmate looks the same wherever they turn up. It goes top-left on a
  dark coin: Rookie's emblem is grey by design and vanished against a
  dark avatar, and the coin gives every rank the same footprint. In the
  flow it would not fit — a row already carries a place marker, a name
  and a stat line, and a 320px phone has no spare width.
  **There is no level number beside it, and there was.** A small blue
  one sat in the opposite corner, asked for on the Virtual Room lobby
  and then asked against everywhere ("forget the little level thing next
  to the characters, I do like the rank icon though"). A rank already
  says roughly where somebody is, the Level board ranks on the number
  itself so it is already printed on the row, and two marks on one 42px
  character is one too many. Somebody below Rookie gets nothing, which
  is correct: there is no rank to show and a placeholder would say
  otherwise. `check-behaviour` and `check-vroom` both assert its
  absence, so it cannot come back by accident.
  **Two row builders for one idea is how a fix misses the screen it
  matters most on.** The three rankings boards had their *own* row
  markup and never called `decorateAvatar()` — so when the level chip
  was taken off everywhere, it stayed on the boards, which is the place
  anyone actually looks at other people, and the rank emblem never
  arrived there at all. Checking the builder is not checking the screen:
  `check-behaviour` asserts against a real `.rank-row` now, built by the
  app, rather than against `decorateAvatar()` in isolation.

### Badges

- **Badge detection diffs the real list either side of the recording
  calls** in `summarize()`, rather than trusting any one of them to
  report it. `recordMultiUnitPerfectsIfEligible` does return a
  `newlyStarred` list, but only for multi-unit runs — a single-unit run
  and a Virtual Room race cross the threshold by different paths, and a
  badge that only celebrates on some of them is worse than one that never
  celebrates at all. `tools/check-behaviour.py` runs all four routes.
- **The cutscene queue is on `store`, not passed along.** There is no
  fixed route from a test to Home — Home, Profile and the tab bar are all
  reachable from the results screen — so `store.pendingBadgeUnlocks`
  survives the trip and a relaunch. It **defaults to empty** for an
  existing account, per the `applyLoadedData` rule: somebody who mastered
  four units last month must not be met by four cutscenes on the first
  launch after this ships.
- **`playQueuedBadgeCutscenes()` re-checks its preconditions per badge**,
  not once: it runs for several seconds, and a splash, a generating
  overlay or a tour can appear inside that window. It refuses on any
  screen but Home by testing `dataset.screen`, which is set in exactly two
  places in the file, so every other screen fails by construction.
- **`muteBanners` mutes the cutscene too**, and clears the queue while
  doing it — a muted badge that stayed queued would ambush somebody weeks
  later if they unmuted. `reduceMotion` gets the same words as a static
  note rather than the spin, because the global
  `[data-reduce-motion="true"] *{animation:none}` would otherwise strip
  the keyframes and leave a badge sitting motionless behind a dim.
- **These are STAINED GLASS IN A BLUE-SILVER SETTING.** They were
  enamel in a neutral silver setting for one round and came back as
  *"it almost looks like the colored stuff is colored stained glass,
  within the nice blue/silver looking metal and its all shiny."* Two
  things make that true rather than described: every pane carries its
  own light (bright where the light falls, deep where it does not,
  which is what a translucent material does and a painted one does
  not), and the divisions between panes are **leading** — one thin line
  of the same metal — rather than each pane being a separately rimmed
  object stacked on the one below.
- **No metal on metal.** The stacking above is exactly what came back as
  *"some badges have details or pieces where it looks like metal is
  sitting on metal"*: the old drawing gave every inner field a dark
  stroke AND a silver stroke, then laid a metal motif on a dark underlay
  on top of that — three rings of metal and an ornament, on a badge 60px
  wide. The motif is leading now: drawn once, in the metal, no underlay.
  Leading does not need separating from the thing it divides.
- **No pane may be near-black or near-white**, and `glassTint()` is the
  floor and the ceiling. Glass works because light gets through it, so a
  black pane in a silver setting is a hole; and the setting is blue-
  silver now, so a pale pane has nothing to be. Both ends are clamped
  where the colour is USED rather than where it is declared, so the
  families themselves stay as they are.
- **`badgeHexRgb` takes `rgb(r,g,b)` as well as `#RRGGBB`, and that is
  load-bearing.** The secondary pane colour IS a `badgeShade()` result
  for half the sixteen units, so anything that shades it a second time
  parsed `"rgb(..."` as hex, got NaN for all three channels and painted
  the pane BLACK. It worked for as long as that colour was only ever a
  flat fill; the moment it became the input to a gradient ramp, four
  badges lost their inner colour outright.
- **Corners are rounded, on the badge AND on its slot.** A hard-cornered
  polygon cut into a lining reads as a vector path, which is what *"the
  empty cut outs look bad and inconsistent and not very smooth"* was
  pointing at. The radius is clamped to under half the shorter edge at
  each vertex so a star's point stays a point. Round one and not the
  other and they stop fitting each other — it is one outline.
- **The recess is not black.** It is the lining seen in shadow, so a
  desaturated blue-grey in the same family as the metal, with wide
  low-opacity strokes for the lip. A hairline reads as a drawn outline;
  material giving way is soft.
- The older note, still true about the SETTING: it is not gems and not
  flat tokens. One pass cut every badge like a stone — a pavilion of shaded
  faces around a bright table — and it read as sixteen jewels. The next
  led with a heavy black keyline and put a thin pale line outside it,
  which is backwards: the black was the dominant edge, so what the
  sixteen had in common was a black line, and **black is not a
  material**. What the reference actually shares is a broad pale-silver
  rim following each badge's own outline, the colour filled inside it,
  and the devices inside outlined in that same silver.
- **The setting is two strokes on one path**: a dark one at 11.4, the
  silver a little narrower at 8.2 on top. What shows of the dark is a
  hairline on either side of the metal — outside it against the case,
  inside it against the colour — which is what stops the silver
  dissolving into either. **The inner fields get the same treatment at a
  smaller scale**, and that repetition at two scales is most of why
  sixteen different silhouettes read as one set.
- **The device is metal too, on a dark underlay**, and the underlay is
  the motif scaled up about its own centre rather than a widened stroke:
  these motifs mix fills and strokes, and a widened stroke would only
  outline half of them.
- **Flat is not the same as dull, and the shine is three separate
  things.** The silver is a GRADIENT, not a flat grey: a white
  highlight, through shadow, to a bright bottom edge, because a flat
  grey rim is a drawn line and a ramp is a piece of metal catching
  light. The gloss is a broad wash over the upper-left plus a **narrow
  bright streak** across it — the streak is what reads as shine; the
  wash on its own just made the top half paler. And a four-point glint
  sits proud of the rim at the badge's top-left vertex, drawn
  **outside** the token group so it can overlap the silhouette: a
  sparkle that stops at the outline is one painted on the badge rather
  than one coming off it. A dome highlight is what made the gem set read
  as glass — everything here is hard-edged and clipped to the token.
- **No enamel colour may be close to the setting.** Arrest, Search and
  Seizure was gunmetal, for steel, and inside a silver rim it came out
  as a blank piece of metal with no badge in it. It is a much darker
  steel-blue now: the relevance survives, the collision does not. Check
  any new family against the silver before adding it.
- **Every badge has a slot, and the slot is drawn whether the badge is
  earned or not.** That is the other half of the reference: each badge
  sits in a recess cut to its own outline, which is why an empty slot
  still tells you the shape of what goes in it and a filled one reads as
  something *placed*. A recess lit from the top-left has its shadow on
  the TOP-LEFT inner edge and its catch-light on the bottom-right, which
  is the opposite of a raised object and the whole reason it reads as a
  hole. Two copies of the outline, offset in opposite directions and
  clipped to it, do that without a filter — filters are the one SVG
  feature that has bitten this app on real iOS hardware.
  The token is scaled to `.945` inside its slot: exactly the size of the
  hole and it looks printed on.
- **Never one colour field.** `bands` is two or three, never one. One is
  a flat disc of a single colour with a mark on it, which is precisely
  the "the entire badge is not a solid colour" the reference never does.
  The inner field is a darker sibling on some and a lighter one on
  others, decided by the unit's own hash — all-darker was one reason
  these read as repeated, because sixteen tokens with the same tonal
  move in them look like sixteen printings of one design.
- **The colour NODS at the unit; the shape does not.** `UNIT_BADGE_THEME`
  hand-assigns one of the twenty-one `BADGE_FAMILY` colours per unit —
  gold for Ethics, police blue for Professional Policing, gunmetal for
  Arrest/Search/Seizure, amber for Missing and Exploited Children. That
  is the whole of the relevance, and it is deliberate: a badge that
  *draws* its subject was rejected twice, but a set where the colour
  means nothing at all is what made these read as sixteen arbitrary
  objects. The reference works the same way — the red gym badges are
  fire and none of them is a picture of a flame.
  **Sixteen DISTINCT families, and that is checkable rather than
  assumed.** A hash into a sixteen-entry table is sixteen independent
  draws from sixteen slots, which lands about six of them on a colour
  another badge already has — reported as "a lot of repeating colours",
  and it was. The families are named rather than evenly spaced round the
  hue wheel: even steps is the obvious answer and it produces four
  greens out of sixteen, because green occupies about a sixth of the
  wheel and reads as one colour whatever the spacing says.
- **Badges are GROWN from the unit name, and the shape is mirror-symmetric
  by construction.** Vertices sit at even angles starting straight up, and
  that angle set is already closed under a reflection in the vertical axis
  (reflecting `-90 + i*360/n` gives `-90 + (n-i)*360/n`, another vertex of
  the same set) — so the only thing that can break the mirror is unequal
  radii, and the half is generated and copied across, jitter included.
  **The free rotation the first version applied is gone**: it is exactly
  what stopped the shapes reading as designed rather than found. The
  inner field's four shapes keep the mirror too — a concentric copy and
  a circle obviously do, and a 180-degree turn does as well, because
  reflect-then-turn is a reflection in the other axis.
- **Every pattern carries at least one near radius.** The all-far pattern
  draws a regular polygon, which is the one shape a seed can land on that
  looks like nothing was designed — it produced three plain pentagons out
  of sixteen. **A wide near/far ratio is most of the shape variety there
  is**; at 0.54–0.82 every badge came out a pentagon-ish blob with a dent
  in it.
- **Twelve marks and four inner shapes, not eight marks.** Eight put the
  same device on two badges in a set of sixteen often enough to be
  reported as "repeated in a lot of ways". Twelve marks by four inner
  shapes by two band counts is ninety-six combinations before the
  silhouette is counted. They are all symmetric about the badge's own
  vertical axis so they cannot break the mirror, and all sized against
  the innermost field rather than at a fixed radius — a mark that reads
  as a device on the widest token is a speck on the narrowest.
  **None of them is a picture of anything**, no crowns, no eyes, no
  shields: the shapes were already asked not to represent the unit they
  belong to, and a motif that did it instead would only move the problem
  inside the badge. The first set was a bar and a double rule and they
  read as a capital I and an equals sign, which is a meaning where there
  is supposed to be none.
- **An unearned badge is its empty slot.** Not an outline, not a solid
  silhouette on the tray, not an empty setting — all three were tried
  and the second reference photo (a partly-filled case) settled it: you
  read the shape of the hole and nothing else, which is what makes an
  earned one beside it look placed.
- **Gradient ids inside a generated SVG must be unique per instance.**
  Sixteen badges on one screen referencing `url(#badge-grad)` is one
  shared definition and fifteen wrong fills; `badgeSvgSeq` exists for
  that, `rankEmblemSeq` does the same job for the rank emblems, and the
  same applies to every `clipPath` id.
- **Look at a generated shape before believing its name.** Four of the
  sixteen hand-written silhouettes did not draw what they were called —
  the wings rendered as an arrow, the crescent as a hairline, the bloom
  as a shield, and the scroll was indistinguishable from the speech
  bubble. Rendering all sixteen at once is a thirty-second check and it
  is the only reason any of this got fixed.
- **Two columns on a narrow phone, three from 27rem, four from 40rem.**
  Three across a 375px screen leaves each name 72px and
  "Professionalism" alone is 89px, so `overflow-wrap:anywhere` was
  breaking it mid-word ("Multiculturalis / m"). `break-word` is the
  right value — it breaks only a word that cannot fit at all — but the
  real fix is the column count, measured per device.
- **A grid of cards needs `minmax(0, 1fr)`, never a bare `1fr`** — the
  same trap `.pick` already documents. The badge grid's tracks sized
  themselves to the longest unbreakable word ("Multiculturalism") and ran
  391px wide inside a 375px phone. **The screenshots did not show it**,
  because the overflow scrolls sideways rather than clipping; the sweep
  did, and only because the Profile tabs were added to `SCREENS`.
- **`SCREENS` entries may carry arguments** (`"showProfile('badges')"`).
  Profile is four tabs and a bare `showProfile()` lays out only one of
  them, so three quarters of that screen had no gate at all.

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

**A notice sits at the TOP of the screen, and where exactly is measured.**
It used to sit at the bottom, above the primary button — which meant
`positionNotice()` had to measure its way around four pieces of furniture
(`#nextbtn`, `.homeversion`, `.daily-question-fab`, `.bottomtabs`) that all
live down there and all move at the tablet breakpoint. Per explicit request
it now pins to the top instead, where both screens it can appear on are
empty: `top:calc(env(safe-area-inset-top) + .75rem)` in CSS, and
`positionNotice()` measures the *bottom* edge of whatever the current screen
puts up there (`NOTICE_OBSTRUCTIONS`, now `.wrap > .top`, `.wrap > .count`,
`.back-link`) and parks the banner below the lowest of them. On Welcome and
Home none of those is showing, so the CSS value is what you get. Anything
new added along the TOP of Home or Welcome needs its selector in
`NOTICE_OBSTRUCTIONS` or the banner will sit on top of it.
**Both top banners share that measurement**, via `topNoticeOffset()`.
`.daily-alert` used to skip it entirely — it only ever knew how to park
below the update banner, and assumed nothing else was up there, which was
true while it only appeared on Home. The moment "Find me" started
answering with one on Rankings it landed squarely on the screen title, and
then on the Level/Badges/Hundos switcher. `.panel > .navsegment` is in the
list for that; the update banner never meets one, since it is gated to
Welcome and Home. The entrance
animation is `translateY(-8px)` for the same reason — it drops in from
above now rather than rising from an edge it no longer sits on.

**Neither notice may appear while a tour is running, and not for a few
seconds after one ends.** Reported from a screenshot: the re-add banner was
sitting behind the dim while the main-menu tooltips were being clicked
through. `noticeAllowedHere()` tests for `#tour-overlay` — the full-screen
dim every tour puts up — so one test covers every tour rather than each one
having to opt in. `startSimpleTour`'s own `cleanup()` then calls
`holdNoticesAfterTour()`, which sets a `TOUR_NOTICE_QUIET_MS` (3.5s) window
and schedules the re-check itself. That re-check is not optional: a tour
ending is not a screen change, so nothing else would ever call
`syncNoticeVisibility()` again and a held notice would stay held until the
next navigation.

**Gating to Welcome and Home is structural, not a list.** `dataset.screen`
is set in exactly two places in the whole file (`showWelcome` and
`showHome`), so every other screen fails the test by construction — there is
no list of excluded screens to keep up to date, and a new screen is excluded
by default. Verified by grep, not assumed.

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

## Going live

This repo is a **test** repo. The app ~40 classmates actually use lives in a
different repo, at a different URL, and has not had any of this work yet.
Going live means copying the built state across.

**Copy `index.html`, `version.json` AND the `launch/` folder. All three.**
`index.html` and `version.json` are one comparison split across two files;
`launch/` holds the iOS startup images the page references by path, and
without it every iPhone gets a white flash on launch with nothing to say
why. If `version.json` is missing or stale on the live side, the
check `fetch`es it, fails, and swallows the error by design — so nobody is
ever told about an update and nobody is ever prompted to re-add. That failure
is completely silent, which is exactly what makes it worth stating here.
`tools/` and this file are for whoever maintains it and can come too; nothing
at runtime reads them. `launch/`, by contrast, **is** read at runtime — by
iOS, at launch, before the page loads.

**The re-add prompt must fire exactly once, and it is armed.** `frameId` is
`go-live-1`. Everything iOS reads only at install has changed — icon, app
name, status bar colour, and now the launch image — so every existing install
genuinely does need re-adding, once.

- **Do not bump `frameId` again**, before or after going live. Bumping it is
  the *only* thing that re-prompts a device that has already acknowledged.
- Further install-time changes landing before go-live need **no** bump. No
  device on the live origin has acknowledged `go-live-1` yet, so it is still
  pending for all of them however many times the file changes first.
- `localStorage` is per-origin, so acknowledging on the test URL does not
  carry to the live URL, and vice versa. Testing here cannot spend the live
  prompt.

Verified end to end: a device is prompted once and never again after either
"I've done this" or a successful Safari hand-off; "Not now" (the ×) stores
nothing and returns next launch, as intended; a device holding an older
acknowledged `frameId` is prompted exactly once for the new one; Android and
plain browser tabs are never prompted; and an update and a re-add pending
together never stack — the update takes the screen and the re-add is
re-evaluated on the next check.

---

## Conventions

- **Screen functions are `showX()`** — except **Settings, which is
  `showAppearance()`**. A holdover from when it was only about theme. Search
  `showAppearance`, not `showSettings`.
- Screens mount via `stage.replaceChildren(...)`. Welcome and Home tag their
  root with `dataset.screen`, which is how the update notices know where they
  are — self-clearing, since the next screen's mount removes the node.
- **No Done/exit button on a screen the bottom tab bar can already leave.**
  Home, Settings, Profile, Rewards and Leaderboard have none — the tab bar is
  the way out. Two keep theirs for a reason: Answer Review's button says
  "Finished" and goes to the test Setup screen, which no tab reaches, and the
  end-of-test summary force-hides the tab bar (`window.forceHideBottomTabs`),
  so it has no other exit.
- **Tabbed screens (Rankings, Profile)** share one pattern: a
  `.navsegment`/`.iconbtn` pill switcher, `hidden`-attribute panels, and a
  `selectXTab(which)` toggler. Match it rather than inventing a new shape.
  Profile's four tabs are **Profile, Stats, Badges, Ladder**, driven off
  one `profileTabDefs` list rather than four hand-written copies of the
  same four lines. `PROFILE_TABS` is the swipe order and has to carry
  the same order as the buttons — a thumb swipe that skips a tab is
  worse than no swipe. `"achievements"`, `"ladder"` and `"unlocks"` are all
  still accepted as tab names, so every name this tab has ever had lands
  on it rather than falling back to Profile.
  It was five for a while, and five labels only ever fitted a 375px phone
  by being tightened for five specifically (`:has(.iconbtn:nth-child(5))`)
  and allowed to step just outside the panel's side padding below 26rem;
  measured, they wanted 299px where a 375px phone's content column offers
  295. Those rules are still there, guarded by that `:has()`, and they
  match nothing at four — which is the point: they are a safety net keyed
  on the tab count, not leftovers from a retired feature.
- **Anything that fills or animates on a Profile tab has to fire when the
  tab is SHOWN, not when it is built.** `showProfile("stats")` builds
  every panel while another one is visible, so an XP bar that animated on
  build is a bar nobody saw move.
- **Shared classes are genuinely shared** (`.sect`, `.slab`, `.iconbtn`,
  `.panel`). A one-screen fix needs a screen-level ancestor scope; editing the
  bare class changes every screen, usually by accident.
- **The Profile tab is one card, not two.** The identity block (name,
  character) and the level block (level, badges, XP bar) were two slabs
  and are one now, with a rule between them — *"maybe the top two boxes,
  the one with the level and the other with the name, could be joined"*.
  The consecutive-day streak came off it entirely. The class calendar
  and the recent test review sit BELOW the card as two destination rows:
  they are places to go, not facts about you, and inside the card they
  were the only tappable things in a block of read-only text.
- **Theming** is CSS custom properties keyed off `data-theme` and `data-accent`
  on `<html>`. Write the rule once, then override with a
  `[data-theme=...]`/`[data-accent=...]` prefixed version. Never a one-off
  hardcoded colour.
- **Tablet styling is `@media (min-width:40rem)`**, added *after* the phone
  rule as an override — never a rewrite of the base rule.
- **Settings' behaviour toggles are two sections, not one.** "Motion &
  interaction" (smooth scrolling, reduce motion, swipe to advance) and
  **"Studying & tests"** (keep screen awake, auto-advance, mute banners,
  auto-flag) — seven under one header had visibly piled up. The second
  header was "While you study" first and was reported as not reading
  official enough for what this app is; the name in the app is the one
  that counts, and this file said the old one for a while. Both headers
  are `.slab.motion-summary` so they read as a matched pair; the second
  also carries `.section-divider` for the gap above it. A new toggle goes
  into whichever group it belongs to, and into that group's own
  `motionDetails`/`studyDetails` container in `showAppearance()`.
- **Behaviour toggles live on `theme`**, not `store` — `smoothScroll`,
  `swipeAdvance`, `autoAdvance`, `hapticTouch`, `reduceMotion`, `keepAwake`,
  `muteBanners`, `autoFlagMissed` — and each needs three things: a default in
  the `theme` object, a `typeof ... === "boolean"` line in `loadTheme()`, and a
  field in `saveTheme()`. Miss any one and it silently stops persisting.
- **The daily question button has three states and a live timer.**
  `is-ready` is a quiet ring that runs whenever the question is unanswered;
  `is-fresh` is a brighter, deliberately finite light-up (five cycles, ~6s)
  plus a toast, shown when the period has rolled over since this device last
  saw Home; `is-done` greys it out. The button is `3.4rem` on a phone and
  `4.6rem` from tablet up — it was 41.6px once, under the 44px minimum,
  and the tablet size exists because a control sized for a phone reads as
  an afterthought beside an iPad's tab bar.
  Both animations are a `::after` ring and
  a `box-shadow` — never the button's own size, because a tap target that
  changes size under a finger is worse than no animation. The global
  `[data-reduce-motion="true"] *{animation:none}` rule switches both off
  without naming either.
  **The announcement is a top banner (`.daily-alert`), not a toast, and
  that was measured rather than chosen.** A toast lands in the bottom
  corner and Home's bottom corner is full: at the toast's own height the
  message painted *under* the "?" it tells you to tap, and lifted clear of
  the "?" it painted *over* Start Studying — the gap between those two is
  26px, so there is no third option down there. `positionDailyAlert()`
  parks it below the update notice when one is up, and is called from
  three places because the two arrive in either order: the notice is
  fetched asynchronously and routinely lands a second after the alert, so
  positioning once at creation left both at y=74.
  `class26e.daily.seen` holds the last period this DEVICE displayed, and is
  deliberately a `localStorage` key rather than a field on `store`: it is
  viewing history, not progress, so syncing it would announce a reset on a
  second device that already happened on the first. A null value means a
  fresh install and announces nothing — it just records.
  `dailyResetTimer` lives outside `showHome()` so a rebuild replaces it
  instead of stacking, fires at `nextDailyResetMs()`, and checks the button
  is still in the document before doing anything, so navigating away lets it
  expire harmlessly. It updates the button in place rather than re-rendering
  Home under someone.
- **The ring round the Profile tab has two causes now.** The first is the
  welcome bonus: at the end of the main-menu tour `awardWelcomeBonus()`
  adds 100 XP and `showPointsFlyEffect()` flies a banner into
  `#bottomtab-profile` and pulses it — an `avatar-pulse` ring expanding
  0 → 14px while the icon scales to 1.18× and back. The second is a badge
  cutscene finishing, which flies the badge to the same tab and pulses it
  the same way, deliberately: "something new is in there" should be one
  gesture the app makes, not two. Those are the only two things in the
  app that ring a tab, so an unexplained halo in a screenshot is one of
  them and nothing else. **Its removal timeout must match the animation's own
  duration** — it was `500` against a `.8s` animation, left behind when the
  animation was lengthened from `.5s` (to stop it being missed), so the
  class came off at 62% with the icon still at ~1.05 and it snapped back to
  size instead of settling. Measured, the ring had already faded by then,
  so the whole visible cost was that snap; both are 800 now.
- **`autoFlagMissed`** flags a question every *fifth* miss
  (`AUTO_FLAG_MISS_THRESHOLD`), hooked in `recordResult()` — the single place a
  miss is recorded, so every mode gets it without its own copy. Every-fifth,
  not five-or-more: with `>=`, un-flagging a question by hand was undone by the
  very next miss, which makes the manual control useless.
- New `localStorage` keys follow `class26e.<thing>` and are wrapped in
  `try/catch`. Keys added for the update machinery: `class26e.statusbar.v1`,
  `class26e.frame.ok`, `class26e.update.dismissed`, `class26e.daily.seen`,
  and session-scoped `class26e.updating`. None of these live on `store`, so the
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
- **Haptics are not achievable on iOS, and the obvious workaround has
  already been tried on a real device.** WebKit has never shipped the
  Vibration API, so `navigator.vibrate` is simply absent on iPhone and iPad.
  The known workaround — since iOS 17.4, actuating an
  `<input type="checkbox" switch>` fires the system haptic — was built,
  shipped and tested on an up-to-date iPad. **Detection succeeded** (the
  control genuinely renders as a switch there), but **actuation failed**: a
  script-generated `click()` is not a trusted gesture, and iOS produces the
  haptic only for a real finger landing on the control. Being inside a
  user-gesture call stack is not enough. The whole feature was removed
  afterwards rather than left as a dead toggle. The only route left is
  layering a real, tappable switch over every answer choice and forwarding
  the interaction — judged not worth the regression risk on the most-used
  screen for a nicety, and explicitly declined. Don't quietly retry it; a
  visual shake is the feedback that cannot fail.
- **"Flares" ≠ "Secret Flares" ≠ badges.** Flares are the orbiting marks
  on Home, one per Mastery Ladder tier. Badges are the sixteen unit
  awards on Profile. The three are separate and the words are not
  interchangeable in copy. Secret Flares are titan tier's separate mystery-colour hunt
  (`mysteryStars`, `store.mysteryColorsFound`, keys `red`/`orange`/`yellow`).
- **A solid-coloured child inside a `backdrop-filter` surface can tear on
  iOS** — reported as glitched lines running through the update banner's
  button. The parent needs `will-change:backdrop-filter` (`.toast` has always
  had it and has never glitched; `.update-banner` did not) and the child needs
  its own compositing layer (`translateZ(0)` + `backface-visibility:hidden` +
  `isolation:isolate`) so it is rasterised once instead of resampled through
  the filter every frame.
- **The `html` background is a *fallback* for the `body::before` glow, so it
  has to be pixel-identical, not just the same gradient.** A gradient's
  percentage stops resolve against the box it paints on, and html's box is the
  full scroll height — so the same declaration arrived stretched and read as a
  seam wherever the fixed layer failed to paint. `background-size:100vw 100lvh`
  plus `no-repeat` pins it to the same box `body::before` occupies. Measured
  difference went from up to 8 levels (5 of them in the bottom 40px on a
  tablet) to exactly 0.
- **Three things move together when the ambient glow changes.** The glow is
  declared twice (the `body::before` stack and the `html` fallback, which
  must stay pixel-identical) and its strength is modelled a third time in
  `--statusbar-mix2/3`, which are the share of glow 1 and glow 2 still in
  play at the very top edge — calibrated at 55% and 50% of their peaks. Dark
  currently runs `--theme-c2` at 13.5% and `--theme-c3` at 14.5% (up from
  10%/11%, which was reported as dull), so the tokens are 7.4%/7.25%. There
  is a third, gold `--theme-c1` glow now as well, deliberately anchored at
  `50% 104%` — along the BOTTOM edge, where it contributes nothing up in the
  status bar strip and therefore needs no token of its own. Add a glow near
  the top and that stops being true. The dimmed `has-active-question`
  variant is a fourth copy of the same numbers (4%/4.7%, tokens
  2.2%/2.35%) and has to be re-scaled with them, or the status bar stays
  tuned to the full glow on the single most-used screen in the app.
  **Scale the tokens with the peaks; do not re-sample in Chromium.** The
  55%/50% share was measured against real hardware. Chromium's own top
  strip runs ~6 levels darker than the model on a phone and ~8 lighter on
  a tablet — the glow radius doubles at `min-width:40rem` and one flat
  token has to serve both — so tuning to either reading walks the
  calibration away from the device it came from.
- **The halo round the hero sphere is `.homeglow.homeglow-hero`, not the
  background.** Its base is a single `var(--accent)` ellipse, and on the
  default accent `--accent` is `var(--ink)` — which is exactly why it read as
  "a faint white glow". The dark override paints it in `--theme-c1`/`--theme-c3`
  instead, so it re-themes with every accent rather than going grey.
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

## Showing the work

**Every change gets a screenshot at BOTH sizes, sent to Madison, every time
— phone and tablet.** Not one or the other, and not only when a change "looks
layout-related": this app is used on both, and a change that reads fine at
390px can be adrift at 1024px (the Pause button sat 88px from the edge on an
iPad while looking perfectly normal on a phone). Madison's own two are an
**iPhone 17 Pro Max (440×956)** and an **iPad Pro 11" (834×1194)** — those are
the reference devices, and a change that moves them needs saying out loud.

**Use `tools/shoot-flow.py`, do not mount screens.** It clicks through from a
fresh install on seven devices and fails loudly on a tab bar during
onboarding, a missing tab bar on Home, or a tooltip over a loading screen. It
also draws the status bar, because a screenshot with an unexplained black band
at the top has now been misread twice — once as a tab-bar bug, once as the
update banner "not aligned to the top".

Fixed-position elements render oddly in Playwright `fullPage` screenshots, so
screenshot the viewport and scroll, and measure with `getBoundingClientRect()`
rather than trusting a tall capture.

### Where things currently land

Regenerate with `python3 tools/check-positions.py`; these are the numbers to
check a change against, not to trust forever. Measured installed, portrait.

| | iPhone SE 2/3 | 13 mini | 14/15/16 | **17 Pro Max** | iPad mini | **iPad Pro 11"** | iPad Pro 12.9" | Dell Latitude | MBP 14" |
|---|---|---|---|---|---|---|---|---|---|
| viewport | 375×667 | 375×812 | 393×852 | **440×956** | 744×1133 | **834×1194** | 1024×1366 | 1366×638 | 1512×852 |
| onboarding Continue, y | 527 | 672 | 712 | **816** | 993 | **1055** | 1227 | 502 | 716 |
| …spread across the 6 screens | 54¹ | 0 | 0 | **0** | 0 | **1** | 1 | 1 | 0 |
| Home: tagline→button / button→furniture | 50/21 | 33/19 | 40/26 | **68/54** | 82/83 | **93/94** | 128/128 | 45/60 | 34/49 |
| Welcome: hint off the bottom edge | 42 | 62 | 62 | **62** | 50 | **49** | 50 | 46 | 46 |
| intro cards: padding in / gap between | 5/6 | 5/6 | 8/11 | **14/15** | 29/38 | **29/38** | 29/38 | 6/8 | 8/11 |
| daily question button | 54px | 54 | 54 | **54** | 74 | **74** | 74 | 74 | 74 |

¹ The one deliberate exception: on an SE the intro screen's four cards fill
the panel exactly, so its Continue is carried ~54px lower by the
self-cancelling last-card margin rather than sitting on the shared floor.
An **SE 1st gen (320×568)** is the one device that does not fit this screen at
all and is not expected to.

Rules those numbers encode, worth keeping: the gap **between** intro cards
always beats the padding **inside** them; Home's button sits within a few px
of the midpoint between the tagline and the furniture below it — the
daily-question circle on a phone, the tab bar on a tablet, where the circle
and the version label sit in the corners beside the bar instead; every
onboarding
Continue lands on one line per device; and the Welcome hint clears the bottom
edge by ~50px, or ~62px where there is a home indicator inside that.

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
3. `python3 tools/sweep-layout.py` — the full device matrix. Every device,
   both orientations, installed and in a browser. This is required on every
   change, not just layout ones; a JS error only thrown on one screen shows
   up here too. It exits non-zero on any failure.
4. `python3 tools/check-sync.py` — the account-integrity gate. Required on
   anything touching the sync code, the rankings, reset, or boot; see
   **Accounts and the sync code**.
5. `python3 tools/check-behaviour.py` — the behaviour gate: launch,
   swipe, navigation, badges, cutscene. Required on anything touching
   those; see **Levels, badges and the ladder**.
6. `python3 tools/check-positions.py` — did what you positioned land where
   you meant it to, on all 21 devices. A green sweep does not answer this;
   see **Every device, every way in**.
7. `python3 tools/shoot-flow.py` — screenshots by walking the app, for
   Madison, per **Showing the work**.

Serve over HTTP for anything touching `version.json` — `fetch` fails on a
`file://` path, and the update check swallows that silently by design.

The Firebase CDN is blocked in the sandbox, so the splash never self-clears;
remove `#splashscreen` manually, *except* when testing the update check, where
the splash race is the thing under test. Those two console errors are expected
and unrelated to any change.

No committed regression suite exists yet. Worth building.
