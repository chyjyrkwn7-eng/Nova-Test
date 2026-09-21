# Nova — working notes

Study app for Class 26E, used by ~40 classmates.

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
  Settings by *clicking through* from a fresh install on six devices,
  rather than mounting screens. Use it for anything Madison will look at.
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
list. It now runs 26: everything that can be mounted cold. A screen needing
run state (`showBankProblems`, `showAnswerReview`) or rendering nothing on
its own (`showGeneratingProfile`) is excluded; **anything else new belongs
in `SCREENS`.** A green sweep is only worth what it looked at.

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
into 45/45 while every roomier device stayed byte-identical. It costs 27px
of scroll on the SE — nothing is hidden, the button still sits 45px off the
bottom edge — which is the right trade for the screen it fixes. Guard it
with a `min-height` so it does not land on a device that is already
overflowing badly.

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

**The same rule used deliberately is how four screens share one button
position.** `::before{content:"";margin-top:auto}` on the panel plus
`margin-top:auto` on the button gives two auto margins with the content
between them: the group floats mid-screen and the button lands on the panel
floor — the *same* floor on every screen using it, whatever its content
height. That is what puts Continue in one spot across username, character
select, Pick your class, the code screens and "You're all set", which
centring each screen separately cannot do (it left a 125px spread on an
iPad).

**`justify-content:space-between` spreads the leftover height into EVERY
gap, including ones that belong together.** Welcome's two buttons are styled
11px apart and measured 41px apart on an iPhone because each of the five gaps
in that column got an equal share. Grouping the pair (and the line explaining
them) into one flex child is the fix — the free space then lands *between*
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

**Dead code that appends to `<body>` is worse than dead.** `showTourSendoff()`
— the old "You're all set" popup — had not been called in a long time (the
send-off is the last step of `startMainMenuTour()` now), but it attached its
overlay to `<body>` rather than `#stage`, so nothing cleared it on a screen
change. Anything that called it, including a harness mounting every screen by
name, left it stuck over whatever came next. Deleted.

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
`NOTICE_OBSTRUCTIONS` or the banner will sit on top of it. The entrance
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
- **Settings' behaviour toggles are two sections, not one.** "Motion &
  interaction" (smooth scrolling, reduce motion, swipe to advance) and
  "While you study" (keep screen awake, auto-advance, mute banners,
  auto-flag) — seven under one header had visibly piled up. Both headers
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
  saw Home; `is-done` greys it out. Both animations are a `::after` ring and
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
- **"Flares" ≠ "Secret Flares".** Flares are the orbiting badges on the Mastery
  Ladder. Secret Flares are titan tier's separate mystery-colour hunt
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
| …spread across the 6 screens | 47¹ | 0 | 0 | **0** | 0 | **1** | 1 | 1 | 0 |
| Home: tagline→button / button→tab bar | 50/33 | 61/68 | 68/75 | **96/103** | 82/83 | **93/93** | 148/149 | 45/63 | 34/51 |
| Welcome: hint off the bottom edge | 42 | 62 | 62 | **62** | 50 | **49** | 50 | 46 | 46 |
| intro cards: padding in / gap between | 5/6 | 5/6 | 8/11 | **14/15** | 29/38 | **29/38** | 29/38 | 6/8 | 8/11 |
| daily question button | 54px | 54 | 54 | **54** | 74 | **74** | 74 | 74 | 74 |

¹ The one deliberate exception: on an SE the intro screen's four cards fill
the panel exactly, so its Continue is carried ~47px lower by the
self-cancelling last-card margin rather than sitting on the shared floor.
An **SE 1st gen (320×568)** is the one device that does not fit this screen at
all and is not expected to.

Rules those numbers encode, worth keeping: the gap **between** intro cards
always beats the padding **inside** them; Home's button sits within a few px
of the midpoint between the tagline and the tab bar; every onboarding
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
4. `python3 tools/check-positions.py` — did what you positioned land where
   you meant it to, on all 21 devices. A green sweep does not answer this;
   see **Every device, every way in**.
5. `python3 tools/shoot-flow.py` — screenshots by walking the app, for
   Madison, per **Showing the work**.

Serve over HTTP for anything touching `version.json` — `fetch` fails on a
`file://` path, and the update check swallows that silently by design.

The Firebase CDN is blocked in the sandbox, so the splash never self-clears;
remove `#splashscreen` manually, *except* when testing the update check, where
the splash race is the thing under test. Those two console errors are expected
and unrelated to any change.

No committed regression suite exists yet. Worth building.
