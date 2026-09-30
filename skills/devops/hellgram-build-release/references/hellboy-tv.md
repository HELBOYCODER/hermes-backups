# Hellboy TV: channel data, health probing, web player

## Data pipeline
- Bundled DB: `src/res/assets/helboy_data.bin` — gzip JSON `{tv, radio, webcams}`; each section has `by_country` (code → channel array), `by_category.all` (flat array; used by search and the Persian-superset merge in `HelboyStore.channelsByCountry`), `meta` (code → {country, channelCount, hasChannels}).
- Refresh asset (gzip JSON `{updated, source, channels:[{name, logo, country, url}]}`) is merged at runtime by `HelboyStore.mergeExternal`: match on `normalizeName` (lowercase, strip parenthesized quality suffixes and non-alphanumeric/Persian chars); existing channel gains extra mirror streams + logo backfill; new channels get an `rf-` prefixed id and are appended to `by_category.all`, their country bucket, and meta counts.
- Persian source of record: iptv-org on GitHub — `https://iptv-org.github.io/iptv/languages/fas.m3u` plus `countries/ir.m3u` (dedupe by name). Parse pairs of `#EXTINF` line (attrs tvg-logo/tvg-country, name after the comma) and the http URL on the next non-comment line.

## Health probing (`HelboyChannelHealth`)
- Status = data class {online, pingMs, checkedAt}, keyed by stream URL, cached 5 min, in-flight set prevents duplicate probes.
- Probe: GET with `Range: bytes=0-2047` and a UA; 6s connect/read timeouts; 12-thread pool; batch capped (~120); one UI callback via main-looper handler when the latch clears.
- Trust-all TrustManager + permissive HostnameVerifier for HTTPS probes only — many IPTV CDNs serve broken chains that players accept.
- List rows show `● Online <ping>ms` or `● قطع` as the UItem subtitle; the channel dialog repeats it and offers native-player fallback.

## Web player (`assets/helboy_player/index.html` + `HelboyWebPlayerActivity`)
- Plyr + hls.js bundled locally; a black screen means assets tried a CDN.
- Params through the fragment hash: `u=` stream, `y=` youtube id, `n=` name, `l=` logo url, `f=` favorite(0/1); legacy regex fallback for pre-URLSearchParams links.
- Bridge: `web.addJavascriptInterface(object { @JavascriptInterface fun openNative(url,name); fun toggleFavorite(v) }, "HelboyHost")`; resolve the channel via `HelboyStore.findById` on the UI thread; the activity passes `ch.id` as a constructor param.
- Recovery: exponential backoff retries (cap 12, reset on 'playing'), hls.js fatal-error handling (startLoad → recoverMediaError → scheduleRetry), a 20s stall watchdog (readyState<3 while playing), teardown-before-rebuild so orphaned hls.js workers don't fight the new pipeline.
- YouTube-style theming: CSS custom props (`--plyr-color-main`) and `!important` overrides on `.plyr__controls`; custom top bar (avatar/logo, name, live bitrate from video 'progress' events, quality flyout separate from Plyr's DOM); LIVE badge; hide/show the bar on Plyr controlshidden/shown events.
- WebView must re-assert `HelboyWebViewProxy.applyFromTunnel()` and reload on `proxySettingsChanged` so playback survives tunnel drops.
