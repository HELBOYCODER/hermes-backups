---
name: hellgram-release
description: Use when shipping Hellgram APK builds, fixes and releases.
---

# Hellgram Release Workflow

Repo: github.com/HELBOYCODER/Hellgram (Telegram Android fork, pkg `ua.entaytion.entinygram`).
Worktree: `~/.hermes/skills/Hellgram` (branch `merge-verify-to-main`, pushed to `main`).
Wait for release != build — build (artifact) is automatic on push to main (workflow 'Release APK (fork CI, repo keystore)'); a PUBLIC release must be created MANUALLY via API, because apk.yml needs secrets the repo lost in the rename.

## Steps
0. Know the two-layer repo layout before editing: `src/` (inugram Kotlin overlay + `src/res`) is packaged directly, but JAVA/UPSTREAM-XML changes (e.g. `worktree/TMessagesProj/src/main/res/values/styles.xml`, `LaunchActivity.java`) live in the stgit patch series — CI runs `bun run setup` and REBUILDS the worktree from patches, so a raw edit to `worktree/` never ships. For upstream-side changes: `export PATH=/tmp/stgit-root/usr/bin:$PATH; cd worktree && stg new <name> -m '<msg>'`, edit, `stg refresh`, commit in the worktree repo, then `npx -y bun run tsx scripts/export.ts` (regenerates patches/ + series from worktree commits) and commit patches+series in the main repo. `src/res/values-night/*` files are symlinks into `src/res` — editing src/res covers night mode; a light-mode counterpart needs the patch route.
1. Patch sources under `src/kotlin/...` (runtime code) and `src/res/values*/strings_inu.xml` (strings in ALL 6 locales — en, ru, zh-rCN, ja, tr, uk; there is no values-fa, Persian falls back to en).
2. Gate: run `npx -y bun run tsx scripts/check-translations.ts`, `scripts/lint-patches.ts`, `scripts/entinychecker.ts` from repo root. Failures only matter if NEW vs baseline — verify with `git stash` + rerun. Baseline = 59 partial-overwrite warns, dead-string errors, zh-rCN extras.
3. Commit one feature per commit: `git -c user.name=HELBOYCODER -c user.email=HELBOYCODER@users.noreply.github.com -c core.hooksPath=/dev/null commit`. Never trust `~/.hermes/.env` tokens; push with a temp GIT_ASKPASS file holding the current user-supplied token, then `git remote set-url origin https://github.com/HELBOYCODER/Hellgram.git` to scrub the URL. Never echo the token or put it in argv/remote.
4. Build auto-triggers on push; each push cancels the previous run (concurrency group). Confirm the run for the FINAL head sha via `GET /repos/HELBOYCODER/Hellgram/actions/runs?per_page=6`.
5. Download artifact (always manual): the artifacts endpoint 302-redirects and DROPS the auth header — send the request, catch the HTTPError redirect, follow Location WITHOUT auth. Extract the .apk from the zip.
6. Release manually — POST `/releases` (tag like `tunnel-helboy-test-N`, target main), then POST the asset to `uploads.github.com/.../releases/<id>/assets?name=<apk>` with `Content-Type: application/octet-stream`. Deliver the `browser_download_url` — it is public, no login needed.
7. Feature order for the TV/player surface: check `src/kotlin/ui/helboy/` + `src/kotlin/helpers/helboy/` first — the Plyr web player (`src/res/assets/helboy_player/index.html`, bundled hls.js+plyr locally, NEVER CDN-loaded) is the primary player; channel health probes live in `HelboyChannelHealth.kt`, the Persian/IPTV refresh playlist in `src/res/assets/helboy_fas_refresh.bin` (regenerate from iptv-org languages/fas + countries/ir m3u).

## Pitfalls
- Android strings.xml — escape every literal apostrophe as `\'` in ANY locale (proxy's -> proxy\'s); one unescaped apostrophe fails `mergeReleaseResources` a full build after the code is already fine.
- Use `npx -y bun` — plain `bun` does not exist; tsx script paths are `scripts/<name>.ts` (no `checks/` subdir).
- A 'failure' conclusion on a run may be a cancelled duplicate dispatch — check which run matches the final sha before debugging.
- Do not background-watch builds — poll the runs API in short execute_code checks; long foreground `sleep` times out at 420s, chain `sleep 400` commands instead.
- FCAE tunnel engine (external CluvexStudio/Aether binary) — NEVER impose app-level dial timeouts; upstream treats only states 0/5 as terminal, 1..4/6 are self-healing, and 45s equals the engine scan budget. Kill nothing mid-scan.
- Tunnel settings must restart the engine immediately on change (with a generation counter so stale dial threads exit), else taps feel dead while connecting or failed.
- noize values are off|light|balanced|aggressive|firewall|gfw (never 'none'); map legacy 'none' to 'off'.
- byteArrayOf literals above 0x7F need `.toByte()`.
- `git add worktree` silently aborts the whole `&&` chain (worktree is gitignored in the main repo) — add only the real paths (`src/`, `patches/`, `series`) and run the push step unconditionally in a separate call; always re-check `git log --oneline -1` after a chained add/commit/push.
- Verify packaged fixes INSIDE the shipped APK before releasing: unzip it and inspect the resource (e.g. open the PNG and check corner alpha) — a source fix that missed the packaging path (see step 0) looks committed but is absent from the artifact.
- Image assets baked with an opaque background (check corner pixel alpha != 0) must be regenerated from the transparent source (`src/res/drawable/hellgram_fg.png`) — resizing preserves the baked background, so resize the SOURCE and save to every density dir.
- UI-visible fixes (splash, logos, player) get a visual complaint from the user if only committed, never rendered — after release, verify the asset inside the artifact and say exactly what was visually verified; do not rely on green CI as proof of visuals. Real on-device verification is possible without KVM: see `references/visual-test-redroid.md`.
- The release workflow builds with env `ABI_FILTERS: arm64-v8a` — the APK is arm64-only. The Redroid 14 `_64only` image still runs it (no x86 libs needed); a stock SDK emulator on x86_64 will refuse to install it.
- On emulators with no battery service (`present: false, level: 0`) the app may show a Power-Saving toast with an INT32_MIN battery percentage — an emulator artifact, not an app regression; do not chase it, and never treat battery/cell-radio absence in a container as a login-flow bug.
