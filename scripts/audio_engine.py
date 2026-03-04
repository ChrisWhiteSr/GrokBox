"""AudioEngine — centralized audio I/O for GrokBox.

Single PyAudio instance, dedicated capture thread, persistent output stream,
consumer-based distribution, and echo gating via playback state tracking.
"""

import collections
import io
import logging
import os
import queue
import socket
import threading
import time
import wave

import numpy as np
import pyaudio

log = logging.getLogger("grokbox.audio")

# Test injection socket path
TEST_SOCKET = "/tmp/grokbox_test_audio.sock"


class AudioEngine:
    """Manages all audio I/O for the GrokBox daemon.

    - One PyAudio instance with separate input/output streams
    - Dedicated capture thread that NEVER stops reading the mic
    - Persistent output stream at 24kHz (Kokoro TTS output format)
    - Consumer pattern: register callbacks to receive mic chunks
    - Playback-active flag for echo gating
    - Optional test audio injection via Unix socket
    """

    SAMPLE_RATE = 16000       # Mic capture rate (OpenWakeWord + AssemblyAI requirement)
    CHUNK = 1280              # Frames per mic read (~80ms at 16kHz)
    OUTPUT_RATE = 24000       # Kokoro TTS output rate
    OUTPUT_CHANNELS = 1
    OUTPUT_SAMPLE_WIDTH = 2   # bytes (int16)

    def __init__(self):
        self._pa: pyaudio.PyAudio | None = None
        self._mic_stream = None
        self._out_stream = None
        self._out_lock = threading.Lock()

        # Capture thread
        self._capture_thread = None
        self._capture_running = threading.Event()

        # Consumer callbacks: list of callable(raw_bytes, np_array)
        self._consumers: list = []
        self._consumers_lock = threading.Lock()

        # Playback state
        self._playback_active = threading.Event()
        self._playback_ended_at = 0.0

        # Pre-cached beep audio (resampled to output rate)
        self._beep_data: bytes | None = None

        # Test injection
        self._test_mode = os.environ.get("GROKBOX_TEST_MODE", "0") == "1"
        self._test_server = None
        self._test_conn = None
        self._test_thread = None

    def start(self):
        """Initialize PyAudio, open streams, start capture thread."""
        self._pa = pyaudio.PyAudio()

        # Mic input stream
        self._mic_stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.SAMPLE_RATE,
            input=True,
            frames_per_buffer=self.CHUNK,
        )

        # Persistent output stream at 24kHz (matches Kokoro)
        self._out_stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=self.OUTPUT_CHANNELS,
            rate=self.OUTPUT_RATE,
            output=True,
            frames_per_buffer=1024,
        )

        # Start capture thread
        self._capture_running.set()
        self._capture_thread = threading.Thread(
            target=self._capture_loop, daemon=True, name="audio-capture"
        )
        self._capture_thread.start()

        # Start test injection socket if enabled
        if self._test_mode:
            self._start_test_socket()

        log.info("AudioEngine started (capture=%dHz, output=%dHz, test_mode=%s)",
                 self.SAMPLE_RATE, self.OUTPUT_RATE, self._test_mode)

    def stop(self):
        """Shutdown everything."""
        self._capture_running.clear()
        if self._capture_thread:
            self._capture_thread.join(timeout=2.0)
        if self._mic_stream:
            try:
                self._mic_stream.stop_stream()
                self._mic_stream.close()
            except Exception:
                pass
        if self._out_stream:
            try:
                self._out_stream.stop_stream()
                self._out_stream.close()
            except Exception:
                pass
        if self._pa:
            self._pa.terminate()
        self._stop_test_socket()
        log.info("AudioEngine stopped")

    # ---- Capture ----

    def _capture_loop(self):
        """Continuously read mic audio and distribute to consumers."""
        chunk_bytes = self.CHUNK * 2  # int16 = 2 bytes/sample
        while self._capture_running.is_set():
            try:
                raw = self._mic_stream.read(self.CHUNK, exception_on_overflow=False)
            except Exception as e:
                log.error("Mic read error: %s", e)
                time.sleep(0.01)
                continue

            # Mix in test injection audio if available
            if self._test_mode and self._test_conn:
                raw = self._mix_test_audio(raw, chunk_bytes)

            # Convert to numpy for consumers that need it
            np_data = np.frombuffer(raw, dtype=np.int16)

            # Distribute to all registered consumers
            with self._consumers_lock:
                for consumer in self._consumers:
                    try:
                        consumer(raw, np_data)
                    except Exception as e:
                        log.error("Consumer error: %s", e)

    def add_consumer(self, callback):
        """Register a callback(raw_bytes, np_array) to receive every mic chunk."""
        with self._consumers_lock:
            self._consumers.append(callback)

    def remove_consumer(self, callback):
        """Unregister a consumer."""
        with self._consumers_lock:
            try:
                self._consumers.remove(callback)
            except ValueError:
                pass

    # ---- Playback ----

    @property
    def is_playing(self) -> bool:
        """True while audio is being written to the output stream."""
        return self._playback_active.is_set()

    @property
    def playback_ended_at(self) -> float:
        """Timestamp of the most recent playback completion."""
        return self._playback_ended_at

    def play_wav_bytes(self, wav_bytes: bytes):
        """Play WAV audio through the persistent output stream.

        Expects 24kHz mono int16 WAV (Kokoro's output format).
        Sets is_playing flag during playback for echo gating.
        """
        self._playback_active.set()
        try:
            with wave.open(io.BytesIO(wav_bytes)) as wf:
                data = wf.readframes(1024)
                with self._out_lock:
                    while data:
                        self._out_stream.write(data)
                        data = wf.readframes(1024)
        except Exception as e:
            log.error("Playback error: %s", e)
        finally:
            self._playback_active.clear()
            self._playback_ended_at = time.time()

    def load_beep(self, beep_path: str):
        """Pre-load and resample the beep WAV for instant playback.

        The beep is typically 16kHz; we resample to 24kHz to match
        the persistent output stream.
        """
        with wave.open(beep_path) as wf:
            src_rate = wf.getframerate()
            raw = wf.readframes(wf.getnframes())

        src = np.frombuffer(raw, dtype=np.int16)

        if src_rate != self.OUTPUT_RATE:
            # Linear resample
            ratio = self.OUTPUT_RATE / src_rate
            n_out = int(len(src) * ratio)
            indices = np.linspace(0, len(src) - 1, n_out).astype(int)
            resampled = src[indices]
            self._beep_data = resampled.tobytes()
        else:
            self._beep_data = raw

        log.info("Beep loaded and cached (%d -> %d samples)", len(src), len(self._beep_data) // 2)

    def play_beep(self):
        """Play the pre-cached beep with minimal latency."""
        if not self._beep_data:
            log.warning("No beep loaded — call load_beep() first")
            return
        self._playback_active.set()
        try:
            with self._out_lock:
                self._out_stream.write(self._beep_data)
        except Exception as e:
            log.error("Beep playback error: %s", e)
        finally:
            self._playback_active.clear()
            self._playback_ended_at = time.time()

    # ---- Test injection ----

    def _start_test_socket(self):
        """Start Unix socket server for test audio injection."""
        if os.path.exists(TEST_SOCKET):
            os.remove(TEST_SOCKET)
        self._test_server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._test_server.bind(TEST_SOCKET)
        self._test_server.listen(1)
        self._test_server.setblocking(False)
        self._test_thread = threading.Thread(
            target=self._test_accept_loop, daemon=True, name="test-inject"
        )
        self._test_thread.start()
        log.info("Test injection socket listening at %s", TEST_SOCKET)

    def _stop_test_socket(self):
        if self._test_server:
            try:
                self._test_server.close()
            except Exception:
                pass
        if os.path.exists(TEST_SOCKET):
            try:
                os.remove(TEST_SOCKET)
            except Exception:
                pass

    def _test_accept_loop(self):
        """Accept test audio connections."""
        while self._capture_running.is_set():
            try:
                conn, _ = self._test_server.accept()
                conn.setblocking(False)
                self._test_conn = conn
                log.info("Test audio client connected")
            except BlockingIOError:
                time.sleep(0.05)
            except Exception:
                if self._capture_running.is_set():
                    time.sleep(0.1)

    def _mix_test_audio(self, mic_raw: bytes, chunk_bytes: int) -> bytes:
        """Read from test socket and mix with mic audio."""
        try:
            test_data = self._test_conn.recv(chunk_bytes)
            if not test_data:
                self._test_conn = None
                return mic_raw
            # Pad if partial read
            if len(test_data) < chunk_bytes:
                test_data += b"\x00" * (chunk_bytes - len(test_data))
            # Mix: add signals, clip to int16 range
            mic_np = np.frombuffer(mic_raw, dtype=np.int16).astype(np.int32)
            test_np = np.frombuffer(test_data, dtype=np.int16).astype(np.int32)
            mixed = np.clip(mic_np + test_np, -32768, 32767).astype(np.int16)
            return mixed.tobytes()
        except BlockingIOError:
            return mic_raw
        except Exception:
            self._test_conn = None
            return mic_raw
