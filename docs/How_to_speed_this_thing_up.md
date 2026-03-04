# GrokBox Latency Optimization

## Current Status (Feb 26 2026)

All four phases of the original streaming pipeline plan have been implemented.
Non-tool responses now land at **1.5s – 2.5s** time-to-first-spoken-word (TTFSW),
down from the original **3.0s – 9.5s** blocking pipeline.

Tool-call responses (web search, image search) add the tool execution round-trip
on top, typically landing at **2.5s – 4.0s**.

---

## What Was Done

### Phase 1: Silence Threshold Tuning (Change 1)
**Status: DONE**

Tightened AssemblyAI's end-of-turn detection in `stt_session_thread()`:
- `min_end_of_turn_silence_when_confident`: 550ms → **350ms**
- `max_turn_silence`: 1700ms → **800ms**

This shaves ~0.5–0.9s off the wait between the user finishing their sentence and
STT committing the final transcript. Trade-off: more aggressive cutoff means it
might clip users who pause mid-sentence. So far this hasn't been a problem in
practice.

Also promoted partial transcript logging from `log.debug` to `log.info` so the
GUI layer can display live transcription as words arrive.

### Phase 2: Streaming Grok Response (Change 2)
**Status: DONE**

Added `get_grok_response_streaming()` — a generator that:
1. Sends the request with `"stream": True` to the xAI API
2. Accumulates tokens into a buffer
3. Uses a sentence-boundary regex (`_SENTENCE_END`) to detect complete sentences
4. `yield`s each sentence as soon as it's complete, while tokens continue arriving

Tool calls are detected from stream deltas. When a tool call is found, the
generator collects it, executes it via `skill_mgr.execute_tool()`, then does a
non-streaming follow-up request to get the final spoken response. This is
intentional — tool results need to be fully assembled before Grok can summarize
them.

Helper functions added:
- `_split_sentences(text)` — regex-based sentence boundary splitter
- `_clean_response(text)` — strips markdown, citation brackets, extra whitespace

The old `get_grok_response()` is still in the file for easy rollback.

### Phase 3: Chunked Sentence-by-Sentence TTS (Change 3)
**Status: DONE**

Added `speak_streaming(sentence_iter)` — a 3-thread pipeline:
- **Main thread**: iterates the sentence generator, feeds sentences into `tts_q`
- **TTS worker thread**: pulls sentences from `tts_q`, POSTs each one to Kokoro,
  pushes the resulting WAV bytes into `play_q`
- **Play worker thread**: pulls WAV bytes from `play_q`, plays them via PyAudio

This means Sentence 1 is playing out of the speaker while Sentence 2 is being
TTS'd by Kokoro, and Sentence 3 might still be streaming from Grok. The user
hears the first sentence as soon as physically possible.

### Phase 4: In-Memory Audio Playback (Change 4)
**Status: DONE**

Added `play_wav_bytes(wav_bytes)` — plays WAV data directly from memory through
a persistent `PyAudio` output instance (`_audio_out`). No more writing temp files
to `/tmp/grok_response.wav` and launching `pw-play` as a subprocess.

The old `text_to_speech_kokoro()` function (file-based) is still in the file for
the sleep command TTS and rollback purposes.

Wired it together in `loop()`:
```python
# Old (blocking):
ans = get_grok_response(text)
text_to_speech_kokoro(ans)

# New (streaming):
speak_streaming(get_grok_response_streaming(text))
```

### Post-Launch Fix: Echo Suppression (Change 5)
**Status: DONE**

After deploying the streaming pipeline, the wake word model was false-triggering
immediately after every TTS response — it was hearing its own speaker output and
re-triggering "Hey Jarvis". The original 2-second `drain_mic()` wasn't sufficient
because the mic buffer accumulates the entire multi-second TTS playback while the
main loop is blocked inside `speak_streaming()`.

Fixes applied:
- **Increased mic drain** from 2.0s to **4.0s** to clear the larger buffer
- **Added 1.5-second wake word cooldown** (`WAKE_COOLDOWN`) — after TTS playback
  ends, all wake word detections are suppressed for 1.5s to reject reverb/echo
- **Delta-only partial logging** — partials now log only the new words
  (`[Partial]: ...nasdaq`) instead of repeating the full growing transcript
  (`[Partial]: tell me what the nasdaq`), cutting log noise significantly

### Follow-Up Listening Window (Change 6)
**Status: DONE**

After each Grok response, the system now auto-opens a new STT session with a
6-second timeout (`FOLLOWUP_TIMEOUT`) instead of immediately returning to wake
word mode. If the user speaks within that window, it processes the follow-up
without needing "Hey Jarvis" again. If silence for 6 seconds, quietly closes the
STT session and returns to wake word mode.

This enables natural multi-turn conversations:
- User: "Hey Jarvis, what's the weather?"
- Jarvis: "It's 45 degrees and cloudy..."
- User: "What about this weekend?" *(no wake word needed)*
- Jarvis: "Saturday looks sunny..."

The `_in_followup` flag tracks whether the current STT session is a follow-up,
and adjusts the timeout accordingly (`FOLLOWUP_TIMEOUT` vs `STT_TIMEOUT`).

---

## Measured Latency Breakdown (Post-Optimization)

| Stage | Before | After |
|-------|--------|-------|
| STT silence detection | 0.55–1.7s | 0.35–0.8s |
| LLM first token | 0.6–3.0s | 0.6–2.0s (same API, but we act on first sentence) |
| TTS first sentence | 1.0–3.0s | 0.3–0.8s (one sentence, not a paragraph) |
| Playback start | ~0.2s | ~0.0s (in-memory, no subprocess launch) |
| **TTFSW (total)** | **3.0–9.5s** | **1.5–2.5s** |

---

## What To Do Next

### Near-Term Improvements

**1. Persistent AssemblyAI Connection**
Currently we open a brand new WebSocket to AssemblyAI for every wake word trigger.
The `time.sleep(0.5)` handshake delay is still there. Keeping the STT connection
alive persistently and just feeding it audio on demand would eliminate this 0.5s
hit entirely. Requires managing connection keep-alive and reconnection logic.

**2. Warm Kokoro Connection Pool**
Each sentence TTS request opens a new HTTP connection to the Kokoro server. Using
a `requests.Session()` with keep-alive would reuse the TCP connection and skip
the TLS/TCP handshake on subsequent sentences. Easy win — probably saves 50–100ms
per sentence after the first.

**3. Reduce STT Handshake Sleep**
The `time.sleep(0.5)` after launching the STT thread is a fixed guess. Replace it
with an event-based approach: have `on_begin()` set a threading.Event, and have
the main loop wait on that event with a short timeout. If the connection is fast
(which it usually is), we save 200–400ms.

**4. Speculative First-Sentence TTS**
Start generating TTS for the first partial sentence before it's fully complete.
If the first 6+ words match a common response pattern ("Sure, here's what I
found"), fire off TTS early. If the final sentence differs, discard and regenerate.
Risky but could shave 0.5s off TTFSW for predictable responses.

### Medium-Term Improvements

**5. Local Wake Word + STT**
AssemblyAI adds network latency (round-trip to their servers). A local STT model
like Whisper.cpp or faster-whisper running on the Pi's CPU would eliminate the
network hop entirely. Trade-off: accuracy and the nice end-of-turn detection
AssemblyAI provides. Worth benchmarking.

**6. Software AEC (Acoustic Echo Cancellation)**
The current echo suppression (drain + cooldown) is crude. A proper software AEC
implementation (e.g., SpeexDSP or WebRTC's AEC module via `py-webrtcvad`) would
subtract the known speaker output from the mic input in real-time. This would:
- Eliminate false wake word triggers without needing a cooldown window
- Enable barge-in (user can interrupt Jarvis mid-sentence)
- Allow shorter drain times

The Pi 5 has enough CPU for this. Requires feeding a reference signal (the TTS
audio being played) into the AEC alongside the mic input.

**7. Kokoro Streaming TTS**
If Kokoro supports (or can be modified to support) chunked/streaming audio output,
we could start playing audio before the full sentence WAV is generated. This would
reduce per-sentence TTS latency from 300–800ms to potentially under 200ms.

### Long-Term / Aspirational

**8. Full-Duplex Conversation**
With proper AEC in place, the system could listen for wake words (or even natural
conversational cues) while speaking, enabling true back-and-forth dialogue without
the wake-word-per-turn cycle.

**9. On-Device LLM Fallback**
For simple queries ("what time is it", "set a timer"), a small local model could
respond instantly without the network round-trip to xAI. Use the cloud LLM only
for complex queries. Latency for simple queries would drop to sub-1-second.
