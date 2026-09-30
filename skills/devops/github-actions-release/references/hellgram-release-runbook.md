# Hellgram Release & Build Runbook

Concrete instantiation of `github-actions-release` for **github.com/HELBOYCODER/Hellgram** (Telegram Android fork, renamed from entinyGram). Repo rules live in its `AGENTS.md` — obey them (one feature = one commit, mandatory checks, no unrequested commits).

## Layout & toolchain
- Clone at `~/.hermes/skills/Hellgram`; stock worktree at `worktree/` created by `scripts/setup.ts`.
- Fork code lives in `src/kotlin` + `src/res` (symlinked into the worktree). Never hand-edit `patches/*.patch` or `series`.
- `bun` is not installed — run TS scripts as `npx -y bun run tsx scripts/<script>.ts`.
- `setup.ts` needs stgit: `export PATH="/tmp/stgit-root/usr/bin:$PATH"` (deb extracted to `/tmp/stgit-root`; re-extract from archive.ubuntu.com if `/tmp` was wiped). Set `git config user.name/user.email` inside the worktree before setup, or version checks fail.
- Mandatory checks before declaring done: `entinychecker.ts`, `check-translations.ts`, `lint-patches.ts`. Known baseline noise (dead strings, ~59 partial overwrites) predates any change — confirm with `git stash` → run → `git stash pop` before treating a failure as new.
- Commit with `git -c core.hooksPath=/dev/null commit` (stgit hooks fire on commit); format `[+]` add / `[-]` remove / `[*]` fix / `[=]` chore.

## Tunnel (FCAE/aether) debugging
- The engine logs its own rejection reason: grep the diag log for `fcae_start: invalid configuration` first — a bad config value (e.g. a noize profile outside `off|light|balanced|aggressive|firewall|gfw`) loops start→fail→retry and presents as "stuck on connecting".
- Tunnel state codes from `nativeGetState()`: 1 provisioning, 2 scanning, 3 connecting, 4 up-but-unverified (require a real SOCKS5 CONNECT probe before trusting it), 5 failed, 6 reconnecting.
- The noize-profile UI setting lives in `TunnelSettingsActivity.kt` (`NOIZE_VALUES`); `BuiltInTunnelHelper.start()` maps legacy stored values before `nativeStart`.

## Which workflow
| Workflow | Trigger | Output |
|---|---|---|
| `apk-release.yml` | workflow_dispatch + push to main | CI artifact `entinygram-tunnel-helboy-release` (zip with app.apk). ~35–50 min. No Release. |
| `apk.yml` ("Build APK") | workflow_dispatch (mode=release / release+tg, prerelease, build_arm7) | Real GitHub Release with tag + public APK links. Needs secrets (`GOOGLE_SERVICES_JSON`, TELEGRAM_*). |

The fork repo currently has **no repo secrets**, so `apk.yml` fails at its 'Write google-services.json' step. Ship via `apk-release.yml` + manual Release (see the umbrella skill's step 4). Tag series: `tunnel-helboy-test-<N>`, asset `hellgram-test-<N>.apk`.

## Icon / branding replacement
- Keep the launcher icon **text-free** — wordmarks are unreadable at launcher sizes. The full logo *with* text belongs to the intro splash.
- Launcher foreground: 432×432 canvas, artwork inside ~62% (adaptive-icon safe zone). Crop the source art to the emblem region, apply a circular mask, paste centred on a transparent canvas, write to `src/res/drawable/hellgram_fg.png` (referenced by `src/res/launcher/generated/drawable/icon_foreground_inu.xml` via `<bitmap>`).
- Intro splash: `src/res/drawable-{mdpi,hdpi,xhdpi,xxhdpi,xxxhdpi}/inu_intro_logo.png` at 96/144/192/288/384 px (consumed by `IntroActivity.java`).
- **Always validate the candidate with `vision_analyze` before committing**: ask specifically "is any text visible?", "do horns/emblem survive at 48px?", "is the bottom edge intentional or cropped-looking?". When source art has a text banner fused to the artwork, the reliable crop is above the banner — flat-colour patching over the text leaves a visible seam and is not worth it.
- Simulate real launcher sizes (downscale to 48/72/96 px) and inspect the pixelated result before shipping.
