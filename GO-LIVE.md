# Going live — the copy list

The app ~40 classmates use lives in a different repo at a different URL.
Going live is a copy, not a deploy. **Three things move, and all three
have to.**

| Copy | Why |
|---|---|
| `index.html` | the app |
| `version.json` | the other half of the update check — `build` here must equal `APP_BUILD` in `index.html` |
| `launch/` (whole folder) | the iOS startup images `index.html` references by path |

`tools/` and `CLAUDE.md` can come too. Nothing at runtime reads them.
`launch/`, by contrast, **is** read at runtime — by iOS, at launch,
before the page loads. If it is missing, every iPhone gets a white flash
and nothing anywhere says why.

If `version.json` is missing or stale on the live side the check
`fetch`es it, fails, and swallows the error by design: nobody is ever
told about an update and nobody is ever prompted to re-add. That failure
is completely silent, which is the whole reason it is written down here.

## Current state

- `APP_BUILD` and `version.json` `build` are both `2026-09-22-91`.
- `frameId` is `go-live-1`. **Do not bump it** — before or after the
  copy. Bumping it is the only thing that re-prompts a device that has
  already acknowledged, and no device on the live origin has
  acknowledged this one yet, so it is still pending for all of them
  however many times the file changes first.
- `launch/` holds 42 images against 43 link tags (the extra is the
  media-less catch-all, which is the same 1320×2868 image).
  `python3 tools/gen-startup-images.py --check` reports up to date.

## After the copy

1. Open the live URL in Safari and check it boots.
2. `curl` the live `version.json` and confirm `build` reads
   `2026-09-22-91`.
3. Spot-check one launch image, e.g.
   `curl -sI <live-url>/launch/launch-1320x2868.png` → `200`,
   `image/png`.

## The one thing code cannot do

iOS reads the **icon, the app name, the status bar colour and the
launch images exactly once — when the app is added to the Home
Screen.** No reload, no cache clear and no JavaScript can change them
afterwards. An install that predates those changes keeps the old ones,
white launch screen included.

So every existing install needs the Nova icon removed from the Home
Screen and added back, once. That is what the re-add notice is for, and
it is armed: `frameId` is `go-live-1` and every live install will be
prompted exactly once.
