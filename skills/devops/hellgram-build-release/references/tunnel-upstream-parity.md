# Upstream FCAE Option Surface → Hellgram Mapping

How to keep the Hellgram tunnel settings screen at parity with the upstream app
(github.com/FCFlenkchy/FCAE_VPN, `android/app/src/main/java/com/fc/fcaevpn/MainActivity.kt`).

## Reading the upstream surface
- Every `spinner*`, `switch*`, `edit*` field in MainActivity is a user-facing option.
- The authoritative argument list is the `engine.nativeStart(...)` call — any argument the
  upstream passes from UI state and we pass as a literal is a missing feature.

## Option map (verified)

| Upstream control | nativeStart param | Value encoding | Hellgram item |
|---|---|---|---|
| spinnerProtocol | protocol | 0=masque, 1=wg, 2=gool(warp-in-warp), 3=auto, 5=masque-in-masque; upstream positions 4/5 are Tor/Psiphon (peers, need backend flag) | BUILT_IN_TUNNEL_PROTOCOL |
| spinnerProtocol h3/h2 variants | h2Enabled | positions 1 and 7 are the HTTP/2 variants of masque / masque-in-masque | BUILT_IN_TUNNEL_H2 (global toggle) |
| spinnerScan | scanMode | raw position (0..4) | BUILT_IN_TUNNEL_SCAN |
| spinnerIpVersion | ipVersion | 4=ipv4, 6=ipv6, 10=dual (NOT 0/1/2) | BUILT_IN_TUNNEL_IP |
| spinnerNoize | noizeProfile | off\|light\|balanced\|aggressive\|firewall\|gfw; legacy "none"→"off" | BUILT_IN_TUNNEL_NOIZE |
| switchEch | echEnabled | bool; ECH breaks MASQUE on some filtered networks — default OFF | BUILT_IN_TUNNEL_ECH |
| switchQuick | quickReconnect | bool | BUILT_IN_TUNNEL_QUICK |
| switchLan | lanSharing | bool | BUILT_IN_TUNNEL_LAN |
| editSni | sni | free text | BUILT_IN_TUNNEL_SNI |
| spinnerSysprofile | sysProfile | 0=auto,1=low,2=medium,3=high (raw position) | BUILT_IN_TUNNEL_SYS_PROFILE |
| editForcePeer | forcePeer | "ip:port" string | BUILT_IN_TUNNEL_PEER |
| spinnerMode | mode | 0=proxy, 1=TUN | (proxy mode only) |
| backend selector | backend | 0=aether, 1=psiphon | BUILT_IN_TUNNEL_BACKEND |

## Apply-on-change semantics
Upstream saves prefs and applies on next Start; Hellgram's UI must feel equivalent without a
manual reconnect: call `BuiltInTunnelHelper.restartIfNeeded()` after every change — it restarts
whenever the user's enable flag is on (running, dialing, or failed), guarded by a
`startGeneration` counter so a superseded dial thread exits.

## Strings
Every new label needs a key in all locale dirs (values, -ru, -zh-rCN, -ja, -tr, -uk); no -fa
dir exists (Persian falls back to English).