---
name: hellgram-build-release
description: Use when building, fixing, or releasing the Hellgram fork.
---

# Hellgram Build & Release

Workflow for the Hellgram repo (github.com/HELBOYCODER/Hellgram, local clone in `~/.hermes/skills/Hellgram`). The user's trigger word 'Hellboy' (auto-hellboy skill) usually dispatches here.

## Repo ground rules (read AGENTS.md in the repo first)
- One feature = one commit, prefixes `[+] [-] [*] [=]`, no AI essays, no Co-Authored-By.
- Mandatory pre-commit checks: `npx -y bun run tsx scripts/entinychecker.ts`, `check-translations.ts`, `lint-patches.ts` (run via `npx -y bun`; stgit at /tmp/stgit-root if needed). Baseline has pre-existing warnings (dead strings, 59 partial overwrites) — verify with `git stash` that failures predate your change instead of 'fixing' them.
- Commit with `-c core.hooksPath=/dev/null` (stgit hooks break plain commits).

## Pushing (token hygiene)
- GitHub token comes from `~/.hermes/.env` (`# GITHUB_TOKEN` — note the leading `#` on the key line) or fresh from the user. NEVER put it in a remote URL or argv; never repeat it in chat.
- Push via a temp GIT_ASKPASS script (heredoc the token, chmod 700, delete after) from execute_code/terminal, then scrub. Validate the token first with `GET https://api.github.com/user` — a 401 means the user revoked it; ask for a new one.

## CI builds
- `apk-release.yml` (workflow_dispatch) → **artifact only** (name `entinygram-tunnel-helboy-release`, contains app.apk). ~35-50 min.
- `apk.yml` (Build APK, mode=release) → creates the real GitHub Release, but requires repo **secrets** (`GOOGLE_SERVICES_JSON`, signing, Telegram) that do not exist in this repo — it fails at 'Write google-services.json'. If a proper release is needed, create it manually (below) instead of debugging apk.yml.
- Concurrency group cancels duplicate runs: after dispatching, list `/actions/runs?per_page=3` and watch the newest `in_progress` run for the right head SHA, not the first one returned.
- Watch with a background poller script writing a log; do not sleep-loop in foreground.

## Downloading artifacts (auth quirk)
Artifact download 302-redirects and the Authorization header is dropped on the redirect → 401. Use a no-redirect opener, capture the Location header, then fetch it with a plain request.

## Publishing a release manually
`POST /repos/HELBOYCODER/Hellgram/releases` (tag, target_commitish=main, body with Full Changelog compare link), then upload the APK via `POST /uploads.github.com/repos/.../releases/<id>/assets?name=<file>` with `Content-Type: application/octet-stream`. Tag convention: `tunnel-helboy-test-N`. The download URL is public — give the user the `browser_download_url` directly.

## Tunnel settings parity (the user's yardstick: 'exactly like the real FCAE app')
When the user says a tunnel button/option is dead or 'useless', the cause is almost never the
engine — it is the Kotlin wrapper dropping the value. Two rules:

1. **Every option must reach `nativeStart` as a live parameter.** Grep the call site for literal
   arguments (`mode = 0`, `lanSharing = false`, `quickReconnect = true`, `sni = ""`,
   `sysProfile = 0`) — each hardcoded literal is a UI control that silently does nothing. Add an
   `InuConfig` item, a UI row, and wire it to the parameter, in that order.
2. **A settings change must apply even when the tunnel is not healthy.** Gating the restart on
   'is fully connected' makes every tap a no-op while dialing or after a failure — the exact
   'buttons do nothing' report. Restart whenever the user's enable flag is on, including
   mid-dial; bump a `startGeneration` counter so the superseded dial thread exits instead of
   polling an engine instance it no longer owns.

Do not invent new options — pull the list from the upstream app's own settings screen
(`MainActivity.kt`: every `spinner*`/`switch*`/`edit*` and the `nativeStart(...)` argument list
show the full surface) and mirror it. See references/tunnel-upstream-parity.md.

## i18n strings
Adding a UI string means adding it to **every** locale dir in `src/res/` (values, values-ru,
values-zh-rCN, values-ja, values-tr, values-uk) — not just `values/`. `check-translations.ts`
still exits 0 while listing every missing key, so the build stays green and the gap only shows
up as English text inside a translated UI. There is no `values-fa`; Persian falls back to English.
Escape any apostrophe in a translated string as `\'` — a raw `'` inside a translated value passes
check-translations but fails `mergeReleaseResources` ("Invalid unicode escape sequence") only at CI
build time, costing a full 35-50 min rebuild; scan all locale files with a `(?<!\\)'` regex before
committing new strings.

## Repo branding (user asked to fully rebrand from entinyGram to Hellgram)
- `PATCH /repos/...` for description/homepage; `PUT /repos/.../topics` with the `mercy-preview` Accept header for topics.
- README logo lives at `assets/logo.*`; repo assets live in the clone, commit and push like code.

## Splash / startup screens (three distinct surfaces)
- **System splash** (`src/res/drawable/inu_splash_320.xml`, the windowSplashScreenAnimatedIcon) is the one shown on cold launch — rebranding `inu_intro_logo` does not touch it. Check which surface the user's screenshot actually shows before editing drawables.
- Layer-list/shape drawables: inset attributes (`android:top` etc.) take **dp only** — percent strings ('25%') pass local review but fail AAPT only in CI (`incompatible with attribute top (attr) dimension`), costing a full rebuild. `android:drawable` on an `<item>` plus dp insets is the safe pattern for showing a PNG logo on a solid color.
- **Hang-proof app init:** wrap every startup helper call (tunnel, proxy, TV, url-cleaner) in its own independent try/catch so one throwing subsystem cannot abort the rest of Application/Activity init and leave the app stuck on the splash. When the user reports a splash hang, diff the last-known-good vs bad build's init-path changes first.
- Before integrating a third-party player/UI library, grep `src/res/assets/` for an already-bundled copy — it may exist and merely need promotion from fallback to primary.

## Launcher / intro logo specs
- Launcher foreground (`src/res/drawable/hellgram_fg.png`, 432x432): text-free circular emblem inside the adaptive-icon safe zone (~62% of canvas). Text is illegible at 48-96dp — always strip wordmarks for the launcher.
- Intro splash (`src/res/drawable-<dpi>/inu_intro_logo.png`, 5 densities 96/144/192/288/384): full logo WITH wordmark.
- Verify small-size legibility by rendering the composed icon at 48/72/96 px before committing.
- Fallback web players live in `src/res/assets/` (e.g. a Plyr HTML shell used by the fork's web player activity) — the web player can be made the primary path with the native player kept as manual fallback.

## Hellboy TV (channel DB, health, player)
- Channel DB is a bundled gzip-JSON asset (`src/res/assets/helboy_data.bin`): `{tv|radio|webcams}` each with `by_country`, `by_category.all`, `meta`. Refresh playlists ship the same way (e.g. `helboy_fas_refresh.bin`) and get merged into the in-memory JSON by normalized name — never fork a second copy of the store; add a `mergeExternal`-style method.
- Per-channel online/ping status: probe with a Range `bytes=0-2047` GET (time-to-first-byte), 12-way pool, 5-min cache, and tolerate broken TLS chains (trust-all + hostname-bypass in the probe only) — playback engines tolerate what the probe would otherwise reject, making live channels show as offline. Update the list UI once after the batch settles, not per result.
- Web player (Plyr + hls.js, `src/res/assets/helboy_player/index.html`): keep JS/CSS bundled locally — CDN-loaded player assets black-screen on exactly the filtered networks the player exists for. Pass params via the URL hash (`u=`, `n=`, `l=ogo`, `f=av`); expose a `HelboyHost` JS bridge (addJavascriptInterface, methods annotated `@JavascriptInterface`, hop to the UI thread inside) for native-player handoff and favorite toggles. Style via Plyr CSS-variable overrides (`--plyr-color-main`) plus `!important` strips — do not patch plyr.min.js.
- `iptv-org` GitHub playlists (`languages/fas.m3u`, `countries/ir.m3u`) are the reliable source for Persian satellite channels; parse EXTINF attrs (tvg-logo, tvg-country) then the following http line.

See references/tunnel-debugging.md for the FCAE tunnel engine pitfalls,
references/tunnel-upstream-parity.md for the upstream option surface mapping, and
references/stt-pipeline.md for the voice-transcription pipeline and its live-verification recipe.

## Source tree layout (grep the right copy)
The Android framework tree used by CI is `worktree/TMessagesProj/src/main/java` — the repo-root
`TMessagesProj/` may be absent/stale. Fork Kotlin code lives in the repo-root `src/kotlin/`. When
tracing a UI → helper chain, grep `worktree/` for the Java side and repo-root `src/` for the fork
side; do not conclude code 'doesn't exist' from searching only one copy.

## CI compile failures only (Kotlin)
Compile errors that never reproduce locally fail the CI run after the full 35–50 min build. Before
pushing Kotlin changes, re-check: every string-resource call matches `getString(res)` (no args) or
`formatString(res, args...)`; every new UI id has its companion declaration; every new locale
string passes the bare-apostrophe scan (rule above). When a CI run fails, pull the job log via the
no-redirect pattern and grep lines with `e: file:` — Kotlin errors carry exact file:line:col.

## Debug loop with the user (how a fix actually gets root-caused)
The user tests on a real phone and reports failures in Persian, often vague ("this button does
nothing", "the new version doesn't work"). Do NOT guess from the repro description:
1. Ship the diagnostics first — the copyable ErrorLog report turns one vague complaint into the
   exact failing step with provider/HTTP/state detail. Building the feature without the reporter
   means debugging blind over several build cycles.
2. If the report is still ambiguous, ask ONE structured question (e.g. which of these four
   behaviors do you see) rather than guessing — a wrong guess costs a 35–50 min build round-trip.
3. When the user pastes an error report, the cause named in it is the debugging target — verify
   it in the code path it names (e.g. 'could not download' → check the download resolution code,
   not the upload/provider side) before touching anything else.