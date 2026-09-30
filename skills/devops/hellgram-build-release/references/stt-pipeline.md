# STT (Voice Transcription) Pipeline — Sokhan/Google

Flow: TranscribeButton ("A" on a voice message) → `TranscribeHelper.transcribe()` (custom path taken whenever `AI_TRANSCRIBE_ENABLED` is on) → provider (default `SokhanSttEngine`: Google speech-api v2, keyless, FLAC 16 kHz mono) → result written into `messageObject.voiceTranscription` + `voiceTranscriptionUpdate` notification.

## Verifying the pipeline without the phone
End-to-end test from the host (validates the key, endpoint, and format in one shot):
1. Make real Persian speech: `uvx --from edge-tts edge-tts --voice fa-IR-DilaraNeural --text "سلام این یک تست است" --write-media /tmp/fa.mp3`
2. Convert exactly like the app sends it: `ffmpeg -i /tmp/fa.mp3 -ar 16000 -ac 1 /tmp/fa.flac`
3. POST to `https://www.google.com/speech-api/v2/recognize?output=json&lang=fa-IR&key=<SPEECH_KEY from SokhanSttEngine>` with `Content-Type: audio/x-flac; rate=16000`. A tone/silence returns `{"result":[]}` — real speech returns a transcript with confidence. Extract the key by regex from `src/kotlin/helpers/stt/SokhanSttEngine.kt`.

## Failure modes
- **"Could not download the voice message" is almost always a path-lookup bug, not a download bug.** Voice files land in the CACHE path first (`getPathToAttach(doc, false)`) and only reach the final attach path later; code that checks only `getPathToMessage()`/`getPathToAttach(doc, true)` never finds a freshly pressed voice note and times out. Resolve the audio by trying the message path, the cache attach path, and the final attach path in order (`resolveLocalAudio` in TranscribeHelper) — the file is usually already there.
- `HTTP 200` with empty `result` is the most common silent failure (unsupported audio/codec-rate/too short) — the engine must record it into the ErrorLog, not just return "".
- A failing feature must never surface as a thin bulletin only: record the full cause (provider, HTTP code, response body) in the shared ErrorLog journal and show a copyable report dialog. The user's standing expectation: every failure is copyable and reportable from inside the app (Settings → AI → Error log), and the combined Copy-logs dialog in InuSettings must include the ErrorLog journal alongside tunnel/crash logs.

## Language selection (Sokhan-parity)
`AI_TRANSCRIBE_LANGUAGE` (`SokhanSttEngine.resolveLanguage`) is authoritative when non-blank; blank = follow the app locale. Expose it in the Providers settings as a **radio picker** (fixed code+label list, first entry = Auto), never as a free-text ISO field: a typo'd code does not fail loudly, it silently degrades recognition — the "the translator guesses wrong" complaint. Keep the picker list and the recogniser's accepted codes in one shared list (`LANGUAGE_OPTIONS`) so they cannot drift.

## CI compile pitfalls in this area
- `LocaleController.getString(res)` takes no format args — use `LocaleController.formatString(res, args...)` (varargs, no Locale parameter). Mixing them fails only at CI compile.
- A click handler referencing a new `BUTTON_X = InuUtils.generateId()` fails CI if the companion declaration is missing — always confirm the declaration landed next to the handler.
