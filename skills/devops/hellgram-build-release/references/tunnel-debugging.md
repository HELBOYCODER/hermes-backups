# Hell Tunnel (FCAE/Aether) Debugging

The engine is a prebuilt Go/Rust pair (`libfcae_go_bridge.so`, `libfcaevpn_native.so`); all tuning goes through `NativeEngine.nativeStart(...)` in `src/kotlin/fcaevpn/NativeEngine.kt` and the state loop in `src/kotlin/helpers/network/BuiltInTunnelHelper.kt`. Reference implementation: upstream FCAE_VPN (`FCFlenkchy/FCAE_VPN`, GPLv3) — fetch its `NativeEngine.kt` / `FCAEVpnService.java` from GitHub when behavior questions arise.

## Rules

- **Validate every string param against the engine's accepted enums before sending it.** `noizeProfile` accepts only `off|light|balanced|aggressive|firewall|gfw` — an invalid value makes `fcae_start` return 'invalid configuration' and the retry loop spins on 'connecting' forever. Keep a UI-value → engine-value mapping at the nativeStart call site (e.g. legacy saved `"none"` → `"off"`).

- **Never time out a dial.** Upstream FCAE treats engine states 1..4 and 6 as in-progress and ends only on terminal 0 (idle) / 5 (error). The turbo gateway scan alone has a 45s budget and can legitimately run minutes; a Kotlin-side deadline that is shorter than the engine's own work kills it mid-scan and the retry loop rescans forever — exactly the 'stuck on connecting' symptom. Poll state until terminal; surface `nativeGetStatusMsg()` as live progress instead.

- **Trust state 4 only after a real SOCKS5 handshake.** The engine reports connected before the listener forwards. Drive a full SOCKS5 CONNECT (greeting + CONNECT to 1.1.1.1:443) through 127.0.0.1:1819 via `probeThroughProxy()` before pointing Telegram at the proxy. A plain TCP `isPortOpen` is not proof.

- **Bytes above 0x7F need `.toByte()`** in `byteArrayOf` literals — Kotlin refuses to coerce, and the whole module fails to compile (this breaks release CI).

- **State-machine rules on failure:** retry with backoff on both fresh starts and reconnects (bounded `MAX_AUTO_RETRIES`, reset when the watchdog probe succeeds); never clear the user's enabled preference on failure — the watchdog restarts the engine. Clear the `restarting` flag synchronously after spawning the restart thread, or the next retry sees it set and bails.

- **Debounce network callbacks** (3s window): `registerDefaultNetworkCallback` fires per network (wifi/cell/vpn) in bursts; without debouncing each event tears down and rebuilds the engine and they fight each other.

## Reading user-supplied logs
- Dead cached endpoints are NORMAL, not a regression: after an ISP/network change the engine logs 'cached endpoint no longer answers (verify timeout); trying the next one' then rescans fresh and usually lands a validated tunnel minutes later. Do not ship a fix for 'cached endpoints die' — only act when the scan itself finds nothing or the tunnel dies AFTER validation.
- `E [ffi] fcae_start: invalid configuration: <param>=<value>` → the wrapper sends a value the engine rejects; diff against upstream defaults (`noizeProfile` empty → 'balanced', `h2Enabled`/`echEnabled` default true).
- Repeated `[aether] engine starting:` blocks with no progress between them → something is killing the engine between attempts (external deadline or restart storm), not a network problem.
- `registration retry ... error sending request` for `api.cloudflareclient.com` → provisioning network path is blocked; it may recover on its own or need a different protocol/backend, but it is upstream of the scan phase.
- Tunnel validates (exit IP / 'tunnel validated' in the log) then dies and cycles → suspect OUR wrapper, not the network: a watchdog or deadline killing a healthy engine, or an obfuscation/ECH setting closing the handshake right after config injection (`local closed: code=0x179`). The engine's own reconnect (states 1..4/6) must never be interrupted — see the dial-timeout rule above.

## Watchdog vs engine self-healing
- **The watchdog may only intervene on terminal states (0/5).** The engine treats 1..4/6 as 'repairing itself'; a probe failure while its own reconnect is in progress must be tolerated — restarting (`nativeStop()` + `nativeStart()`) mid-repair discards the engine's recovery work and produces an endless reconnect loop even though the log shows a validated tunnel moments earlier.

## ECH and obfuscation defaults
- **Default ECH off and defer to the engine.** On filtered networks, injecting an ECH config into a MASQUE handshake closes the connection right after `ech config injected` with `local closed: code=0x179`; the engine has its own per-endpoint ECH logic ('ECH disabled … SNI sent in cleartext'). When a tunnel works with one obfuscation profile and dies with another, compare the two log sections before blaming the network.

## Superseding an in-flight dial
- When restarting because settings changed mid-dial, bump a generation counter captured by the dial thread and have its poll loop exit when the generation goes stale; otherwise the superseded thread keeps polling and reporting state for an engine instance it no longer owns.
