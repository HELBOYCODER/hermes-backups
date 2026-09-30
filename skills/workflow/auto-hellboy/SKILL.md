---
name: auto-hellboy
description: "Use when user types 'Hellboy'; orchestrate related skills."
version: 1.0.0
author: MEOW
---

# Auto Hellboy — Master Dispatcher

When the user says **Hellboy** (e.g. «Hellboy این کارو بکن», «hellboy برو سراغ ریپو»), this skill activates. It is an ORCHESTRATOR, not a task skill: it figures out what the user wants, loads every related skill, and drives the work to completion.

## Activation

Any user message containing the word **Hellboy** (case-insensitive, also `hell boy`, `هلبوی`) is a trigger. Never ignore it — the user uses it to summon the full-capability mode.

## Step 1 — Detect the task domain

From the user's message, classify the work. Common domains for this user (HELBOYCODER):

| Domain | Load these skills (skill_view) |
|---|---|
| Debugging code | systematic-debugging, python-debugpy (py) or node-inspect-debugger (js) |
| Writing/impl. features | test-driven-development (or tdd), codebase-design |
| Code review | code-review, requesting-code-review |
| Frontend/React | vercel-react-best-practices, web-design-guidelines (if installed) |
| Android (Kotlin) | any android-related skill in skills_list; else general TDD + code-review |
| GitHub ops (repos, PRs, actions) | hermes-agent (for CLI patterns); use gh/api directly |
| Video/audio edits | video-editor or ffmpeg-video-editor |
| Documents/PRD | prd-writer-pro, documentation-writer |
| Web search / research | (no skill needed; use web_search/web_extract) |
| Hermes config itself | hermes-agent (always load this one first for Hermes questions) |

Rules:
- Load 2–4 skills max per task — only what's actually relevant.
- When unsure between two domains, load the lighter one and ask one clarifying question.
- Always check `skills_list` output at session start so you know what exists.

## Step 2 — Orchestrate

1. Restate the task in one line, then the loaded skills (so the user sees what got summoned).
2. Follow the loaded skills' workflows in order (plan → implement → test → review).
3. Use delegate_task for parallel independent subtasks; terminal for builds/tests.
4. GitHub work: the user's account is `HELBOYCODER`; prefer the GitHub API over guessing CLI flags.

## Step 3 — Close the loop

- Verify real execution (build/test/lint output) before claiming success.
- Offer to save any new reusable procedure into this skill via skill_manage (append to Domain table if a new domain emerged).

## Maintenance

When a new recurring domain appears (new repos, new languages), ADD a row to the table above with skill_manage patch — this skill should grow with the user's work.