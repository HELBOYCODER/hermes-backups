---
name: github-actions-release
description: "Use when shipping CI builds as downloadable GitHub Releases."
version: 1.0.0
author: MEOW
---

# GitHub Actions Release Shipping

Class-level workflow for turning a CI build into a **user-verifiable download**: dispatching workflows, pulling artifacts, creating GitHub Releases, and uploading assets. Applies to fork APKs, binaries, and any repo where CI produces deliverables.

## Rule 0 — Artifacts are not Releases
An `actions/upload-artifact` step produces a zip that requires a **GitHub login** to download (it lives on the run page under *Artifacts*). A GitHub Release has a tag, a page at `/releases/tag/<tag>`, and public `browser_download_url` links that work with no login. When the user asks for "the release" or "a link I can install from", a CI artifact is the wrong deliverable — check which workflow actually calls `gh release create` / the Releases API before dispatching. Two workflows can look interchangeable by name (`apk.yml` vs `apk-release.yml`) and differ exactly in this.

## Procedure
1. **Identify the release workflow.** Read `.github/workflows/*.yml` and grep for `gh release create`, `softprops/action-gh-release`, or the GitHub Releases API. Note its `on:` triggers and required inputs. Confirm the repo is at the commit you intend to ship.
2. **Check prerequisites before dispatching.** Release workflows usually need repo secrets (signing keys, `GOOGLE_SERVICES_JSON`, bot tokens). List them with `GET /repos/{owner}/{repo}/actions/secrets` (names only) — a run that dies on a missing secret wastes a full build cycle. If secrets are absent, do not dispatch that workflow; either ask the user to add them, or fall back to the artifact workflow plus a manual Release (step 4).
3. **Dispatch and poll.** `POST /repos/{owner}/{repo}/actions/workflows/{id}/dispatches` with `{"ref": "main", "inputs": {...}}`. Poll `GET /actions/runs/{id}` until `status == completed`; long builds (30–60 min) are best watched by a small background script that polls and writes a log, with the exit reason recorded in the log.
4. **Manual release from an artifact (proven path when the release workflow is unusable).** Download the artifact zip, create the release with `POST /repos/{owner}/{repo}/releases` (`tag_name`, `target_commitish`, `name`, `body` with a short changelog and a `compare/<prev>...<new>` link), then `POST <upload_url>?name=<file>` with `Content-Type: application/octet-stream`. Return the `browser_download_url`.
5. **Verify the deliverable.** Re-fetch the release and confirm the asset size/URL; report the concrete link, not "it should be available".

## Pitfalls
- **Artifact downloads 302-redirect and the Authorization header is dropped on the redirect → HTTP 401.** Use a no-redirect opener, catch the `HTTPError`, read `Location`, and fetch that signed URL without auth. Naive `urlopen` of `/actions/artifacts/<id>/zip` fails even with a valid token.
- **Pushing over HTTPS with a token:** never put the token in argv, the remote URL, or a command line the user can see. Write it into a 0700 `GIT_ASKPASS` script, export `GIT_ASKPASS` + `GIT_TERMINAL_PROMPT=0` for that one command, delete the file after. After the fact, `git remote -v` must show a token-free URL. When the user pastes a token into chat, use it exactly this way and do not persist it anywhere (no `.env`, no credential helper) — the owner revokes it themselves.
- **Validate a token before blaming anything else.** `GET /user` (Bearer) is the cheapest check; a revoked token fails git push as `Invalid username or token` and the API as 401. Tokens stored in a config file may be stale/commented out — never assume the stored one works.
- **Secrets do not survive a repo rename/fork** — re-check `actions/secrets` after any rename before assuming a workflow still works.
- **Pick the run id by status, not position.** A dispatch plus a push trigger on the same commit can create two runs, and `concurrency: cancel-in-progress` cancels the older one; the top entry in `/actions/runs` may be the cancelled one. Before pointing a poller/watcher at a run, filter for `status == in_progress` on the expected `head_sha` — a watcher parked on a cancelled run reports failure of a build that is actually still going.
- **Publishing a link the user can't use is a failed deliverable.** Give the release-page URL and the direct asset URL; state plainly when a link needs login.

## Tunnel/connectivity debug triage (user reports "stuck on connecting")
- Read the user's diagnostic log for the engine's OWN error line (e.g. `E [ffi] fcae_start: invalid configuration: ...`) before blaming the network. A config value outside the engine's accepted set makes every start fail and the retry loop spin forever, which looks exactly like a reconnect bug.
- Copy UI option values verbatim from the engine's validation message — don't paraphrase (`off` vs `none`). If stored prefs predate the fix, map legacy values to valid ones on the native start path, not just in the settings UI.

## References
- `references/hellgram-release-runbook.md` — concrete Hellgram (HELBOYCODER/Hellgram) build, release, token, and icon-replacement recipe built on this workflow.
