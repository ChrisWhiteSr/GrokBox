"""Pipeline components for GrokBox voice assistant.

WakeWordDetector  — consumer that runs wake word model with echo gating
STTFeeder         — consumer that streams audio to AssemblyAI with echo gating
speak_streaming   — 3-thread TTS pipeline using AudioEngine for playback
"""

import logging
import queue
import threading
import time

import numpy as np
import requests

from scripts.audio_engine import AudioEngine
from scripts.pipeline_timer import PipelineTimer

log = logging.getLogger("grokbox")

# Persistent HTTP session for Kokoro TTS (connection keep-alive)
_kokoro_session = requests.Session()
_kokoro_session.headers.update({"Content-Type": "application/json"})


class WakeWordDetector:
    """Runs OpenWakeWord model on each mic chunk via AudioEngine consumer.

    Echo gating: suppresses detection while audio is playing and for
    COOLDOWN seconds after playback ends.
    """

    COOLDOWN = 1.5  # seconds after playback to suppress

    def __init__(self, engine: AudioEngine, model, on_wake, timer: PipelineTimer = None):
        self.engine = engine
        self.model = model
        self.on_wake = on_wake
        self.timer = timer
        self.enabled = True
        self._last_wake = 0.0
        engine.add_consumer(self._on_chunk)

    def _on_chunk(self, raw: bytes, np_data: np.ndarray):
        # ALWAYS feed the model to keep its internal sliding window current.
        # If disabled, feed but don't act on predictions.
        prediction = self.model.predict(np_data)

        if not self.enabled:
            return

        # Echo gating: suppress during playback and cooldown
        if self.engine.is_playing:
            return
        if time.time() - self.engine.playback_ended_at < self.COOLDOWN:
            return

        # Debounce: don't fire twice within 2 seconds
        if time.time() - self._last_wake < 2.0:
            return

        if prediction.get("hey_jarvis_v0.1", 0) > 0.5:
            self._last_wake = time.time()
            self.on_wake()


class STTFeeder:
    """Streams mic audio to AssemblyAI when active.

    Echo gating: does not feed audio while playback is active, and suppresses
    for ECHO_COOLDOWN seconds after playback ends to avoid picking up the tail
    of TTS audio from the speaker (especially important with fast-responding
    models like GPT-4o).

    Session reuse: keeps the same WebSocket connection alive across follow-up
    turns to avoid connection churn. Only disconnects when explicitly stopped.
    """

    ECHO_COOLDOWN = 1.0  # seconds after playback to suppress feeding

    def __init__(self, engine: AudioEngine, assemblyai_key: str, timer: PipelineTimer = None):
        self.engine = engine
        self._api_key = assemblyai_key
        self.timer = timer
        self.active = False
        self._client = None
        self._ready = threading.Event()
        self._done_event = threading.Event()
        self._on_final = None
        self._on_partial = None
        self._last_partial = ""
        engine.add_consumer(self._on_chunk)

    def _on_chunk(self, raw: bytes, np_data: np.ndarray):
        if not self.active or not self._client:
            return

        # Echo gating: don't feed speaker audio to STT, and suppress for
        # ECHO_COOLDOWN after playback ends to avoid picking up echo tail
        if self.engine.is_playing:
            return
        if time.time() - self.engine.playback_ended_at < self.ECHO_COOLDOWN:
            return

        try:
            self._client.stream(raw)
        except Exception:
            pass

    def start_session(self, on_final_callback, on_partial_callback=None):
        """Start or resume an AssemblyAI streaming session.

        If a WebSocket connection already exists and is healthy, reuse it
        (zero-cost follow-up). Only creates a new connection if needed.

        Args:
            on_final_callback: called with (text: str) when final transcript arrives
            on_partial_callback: called with (text: str) for partial transcripts
        """
        self._on_final = on_final_callback
        self._on_partial = on_partial_callback
        self._last_partial = ""
        self._done_event.clear()

        # If we already have a live session, just resume feeding audio
        if self._client is not None and self._ready.is_set():
            self.active = True
            log.info("Reusing existing STT session — feeding audio...")
            return

        # Need a new connection — clean up any dead one first
        if self._client is not None:
            log.info("Cleaning up dead STT session before starting new one")
            self._force_disconnect()

        # Import here to avoid circular imports and allow lazy loading
        from assemblyai.streaming.v3 import (
            BeginEvent,
            StreamingClient,
            StreamingClientOptions,
            StreamingEvents,
            StreamingParameters,
            StreamingSessionParameters,
            TerminationEvent,
            TurnEvent,
        )

        self._ready.clear()

        client = StreamingClient(
            StreamingClientOptions(api_key=self._api_key, api_host="streaming.assemblyai.com")
        )

        def _on_begin(c, event: BeginEvent):
            log.info("AssemblyAI Streaming Session ID: %s", event.id)
            if self.timer:
                self.timer.mark("stt_ready")
            self._ready.set()

        def _on_turn(c, event: TurnEvent):
            transcript = event.transcript.strip()
            if not transcript:
                return

            if event.end_of_turn:
                if event.turn_is_formatted:
                    log.info("[FINAL] %s", transcript)
                    if self.timer:
                        self.timer.mark("stt_final")
                    self.active = False  # Stop feeding audio, but keep session alive
                    self._done_event.set()
                    if self._on_final:
                        self._on_final(transcript)
                else:
                    c.set_params(StreamingSessionParameters(format_turns=True))
            else:
                # Delta-only partial logging
                if transcript.startswith(self._last_partial.rstrip()):
                    delta = transcript[len(self._last_partial.rstrip()):].strip()
                else:
                    delta = transcript
                if delta:
                    log.info("[Partial]: ...%s", delta)
                    if self._on_partial:
                        self._on_partial(transcript)
                self._last_partial = transcript

        def _on_terminated(c, event: TerminationEvent):
            log.info("STT session terminated by server")
            self._ready.clear()  # Mark session as dead
            self._client = None
            self._done_event.set()

        client.on(StreamingEvents.Begin, _on_begin)
        client.on(StreamingEvents.Turn, _on_turn)
        client.on(StreamingEvents.Termination, _on_terminated)

        # Connect in a thread so we don't block
        def _connect():
            try:
                client.connect(
                    StreamingParameters(
                        sample_rate=self.engine.SAMPLE_RATE,
                        speech_model="universal-streaming-english",
                        format_turns=True,
                        end_of_turn_confidence_threshold=0.45,
                        min_end_of_turn_silence_when_confident=350,
                        max_turn_silence=800,
                        vad_threshold=0.4,
                    )
                )
            except Exception as e:
                log.error("STT connect error: %s", e)
                self._ready.clear()
                self._client = None
                self._done_event.set()

        self._client = client
        t = threading.Thread(target=_connect, daemon=True, name="stt-connect")
        t.start()

        # Event-based wait (replaces time.sleep(0.5))
        if not self._ready.wait(timeout=3.0):
            log.warning("STT session didn't become ready in 3s")

        self.active = True
        log.info("AssemblyAI streaming channel opened. Feeding audio...")

    def _force_disconnect(self):
        """Disconnect and discard the current client. Non-blocking."""
        client = self._client
        self._client = None
        self._ready.clear()
        if client:
            def _disconnect():
                try:
                    client.disconnect()
                except Exception:
                    pass
            threading.Thread(target=_disconnect, daemon=True, name="stt-disconnect").start()

    def stop_session(self, quiet=False):
        """Disconnect the STT session entirely (e.g., follow-up window closed)."""
        self.active = False
        self._force_disconnect()
        self._done_event.set()

    def wait_for_done(self, timeout: float) -> bool:
        """Wait for the STT session to produce a final transcript or terminate.

        Returns True if done within timeout, False if timed out.
        """
        return self._done_event.wait(timeout=timeout)


def speak_streaming(sentence_iter, engine: AudioEngine, kokoro_server: str,
                    voice: str, timer: PipelineTimer = None):
    """3-thread pipeline: sentence generator → TTS worker → play worker.

    Uses AudioEngine's persistent output stream and requests.Session
    for HTTP keep-alive to Kokoro.
    """
    tts_q = queue.Queue()
    play_q = queue.Queue()
    DONE = object()
    first_play = threading.Event()

    def tts_worker():
        first_sentence = True
        while True:
            sentence = tts_q.get()
            if sentence is DONE:
                play_q.put(DONE)
                return
            try:
                resp = _kokoro_session.post(
                    kokoro_server,
                    json={"text": sentence, "voice": voice},
                    timeout=15,
                )
                if resp.status_code == 200:
                    if first_sentence and timer:
                        timer.mark("tts_first_sentence")
                        first_sentence = False
                    play_q.put(resp.content)
                else:
                    log.error("Kokoro %d for: %s", resp.status_code, sentence[:40])
            except Exception as e:
                log.error("TTS error: %s", e)

    def play_worker():
        first = True
        while True:
            audio = play_q.get()
            if audio is DONE:
                return
            if first and timer:
                timer.mark("playback_start")
                first = False
            engine.play_wav_bytes(audio)

    t_tts = threading.Thread(target=tts_worker, daemon=True, name="tts-worker")
    t_play = threading.Thread(target=play_worker, daemon=True, name="play-worker")
    t_tts.start()
    t_play.start()

    first = True
    for sentence in sentence_iter:
        if not sentence.strip():
            continue
        if first:
            log.info("SYSTEM RESPONDING")
            first = False
        tts_q.put(sentence)

    tts_q.put(DONE)
    t_tts.join()
    t_play.join()

    if timer:
        timer.mark("playback_done")
