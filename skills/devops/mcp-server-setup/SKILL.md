---
name: mcp-server-setup
description: "Use when adding MCP servers to Hermes: find, install, debug."
version: 1.0.0
author: MEOW
---

# MCP Server Setup for Hermes

Standing user directive: when a task needs a capability the agent lacks, FIRST search for a ready MCP server or skill (official registry, GitHub, mcp.so/PulseMCP as directories), install it, and use it — before hand-rolling.

## Workflow

1. **Find a candidate**: query the official registry `https://prod.registry.modelcontextprotocol.io/v0/servers?search=<term>&limit=20` (fields: `server.name`, `description`, `remotes[].url` for HTTP, `packages[].identifier` for npx/uvx). Registry search times out often — retry once with a shorter query before giving up.
2. **Prefer remote HTTP** (`hermes mcp add <name> --url https://.../mcp`) over stdio: no runtime deps. Verify reachability first with a raw MCP `initialize` POST (headers `Content-Type: application/json`, `Accept: application/json, text/event-stream`) — a 200 with an SSE body means it works.
3. **Add non-interactively**: `yes | hermes mcp add <name> --command uvx --args <pkg>` — the enable-tools prompt must be piped `yes`, otherwise it cancels silently. Do NOT pass `--connect-timeout` (it leaks into the server's args and breaks startup); omit it entirely.
4. **Verify**: `hermes mcp list` shows enabled/disabled; `hermes mcp test <name>`. Fix or remove (`yes | hermes mcp remove <name>`) anything disabled. New tools only appear in a NEW session.
5. **Secrets**: pass per-server credentials only via `--env KEY=VALUE` (Hermes filters env for stdio servers anyway); never bake tokens into config comments or chat.

## Pitfalls

- PyPI MCP servers built against the old SDK fail with `'Server' object has no attribute 'list_tools'` or `No module named 'mcp.server.fastmcp'` — Hermes has mcp 2.x. Fix: `uvx --with 'mcp<2' <pkg>` as the command args. Check the server runs standalone (`timeout 60 uvx <pkg>`) before blaming Hermes config.
- A stdio server that fails on first connect is saved as `enabled: false`; after fixing, remove and re-add — editing the disabled entry by hand is refused.
- If a tool capability is missing at runtime, check `hermes mcp list` first — tools load only at session start; mid-session additions need a restart.

## Reference: proven free servers

- deepwiki — `https://mcp.deepwiki.com/mcp` — live docs/answers for any GitHub repo.
- context7 — `https://mcp.context7.com/mcp` — up-to-date library/framework docs.
- git — `uvx mcp-server-git` — repo operations.
- fetch — `uvx mcp-server-fetch` — URL fetch/extract.
- nettools — `uvx --with 'mcp<2' mcp-nettools` — ping/DNS/port/traceroute/TLS probes (235 tools).
- wireshark — `uvx --with 'mcp<2' mcp-wireshark` — pcap/live capture analysis (needs tshark installed).
