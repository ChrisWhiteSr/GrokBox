#!/usr/bin/env python3
"""GrokBox Audio Test Harness.

Injects audio into the daemon via Unix socket and monitors journalctl
for stage-by-stage latency metrics.

Usage:
    # Run a full pipeline test (wake word + query):
    python3 tests/harness.py --wake tests/audio/hey_jarvis.wav --query tests/audio/test_query.wav

    # Run wake word detection test only:
    python3 tests/harness.py --wake tests/audio/hey_jarvis.wav

    # Just monitor daemon performance (no injection):
    python3 tests/harness.py --monitor
"""

import argparse
import os
import re
import socket
import struct
import subprocess
import sys
import threading
import time
import wave

INJECT_SOCK = "/tmp/grokbox_test_audio.sock"
JOURNAL_CMD = ["journalctl", "-u", "grokbox", "-f", "--no-pager", "-n", "0"]
CHUNK = 1280
SAMPLE_RATE = 16000
CHUNK_DURATION = CHUNK / SAMPLE_RATE  # ~0.08s


class StageTimings:
    """Collects timestamps for each pipeline stage."""

    STAGES = [
        "inject_start",
        "wake_detected",
        "beep_done",
        "stt_ready",
        "stt_partial",
        "stt_final",
        "llm_start",
        "llm_done",
        "tts_responding",
        "followup_or_wake",
    ]

    def __init__(self):
        self._marks = {}
        self._lock = threading.Lock()

    def mark(self, stage: str, t: float = None):
        with self._lock:
            if stage not in self._marks:  # keep first occurrence
                self._marks[stage] = t or time.time()

    def get(self, stage: str) -> float:
        with self._lock:
            return self._marks.get(stage, 0.0)

    def delta(self, start: str, end: str) -> float:
        s, e = self.get(start), self.get(end)
        if s and e:
            return round(e - s, 3)
        return -1.0

    def report(self) -> str:
        lines = ["\n=== Pipeline Latency Report ==="]

        pairs = [
            ("inject_start", "wake_detected", "Wake detection"),
            ("wake_detected", "stt_ready", "STT handshake"),
            ("stt_ready", "stt_final", "STT transcription"),
            ("stt_final", "llm_start", "Pre-LLM overhead"),
            ("llm_start", "llm_done", "LLM response"),
            ("wake_detected", "tts_responding", "TTFSW (wake → first audio)"),
            ("inject_start", "followup_or_wake", "Total cycle"),
        ]

        for start, end, label in pairs:
            d = self.delta(start, end)
            if d >= 0:
                color = "\033[92m" if d < 1.0 else "\033[93m" if d < 2.0 else "\033[91m"
                lines.append(f"  {label:.<40s} {color}{d:>6.3f}s\033[0m")
            else:
                lines.append(f"  {label:.<40s}   n/a")

        # Check for PERF_SUMMARY from daemon
        with self._lock:
            if "perf_summary" in self._marks:
                lines.append(f"\n  Daemon PERF_SUMMARY: {self._marks['perf_summary']}")

        lines.append("=" * 35)
        return "\n".join(lines)


class JournalMonitor:
    """Tails journalctl for the grokbox unit and extracts stage timestamps."""

    PATTERNS = [
        (re.compile(r"Wake word detected"), "wake_detected"),
        (re.compile(r"AssemblyAI streaming channel opened"), "stt_ready"),
        (re.compile(r"\[Partial\]:"), "stt_partial"),
        (re.compile(r"\[FINAL\]"), "stt_final"),
        (re.compile(r"Querying \["), "llm_start"),
        (re.compile(r"Grok responded in"), "llm_done"),
        (re.compile(r"SYSTEM RESPONDING"), "tts_responding"),
        (re.compile(r"Listening for follow-up|Listening for wake word"), "followup_or_wake"),
        (re.compile(r"\[PERF\] (\w+)"), "perf_mark"),
        (re.compile(r"\[PERF_SUMMARY\] (.+)"), "perf_summary"),
    ]

    def __init__(self, timings: StageTimings):
        self.timings = timings
        self._proc = None
        self._thread = None
        self._running = False
        self._verbose = False

    def start(self, verbose=False):
        self._verbose = verbose
        self._running = True
        self._proc = subprocess.Popen(
            JOURNAL_CMD, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )
        self._thread = threading.Thread(target=self._tail, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._proc:
            self._proc.terminate()

    def _tail(self):
        for line in iter(self._proc.stdout.readline, ""):
            if not self._running:
                break
            now = time.time()
            line = line.strip()

            if self._verbose and line:
                # Color-code log output
                if "[FINAL]" in line or "Wake word" in line:
                    print(f"\033[96m  >> {line}\033[0m")
                elif "[PERF" in line:
                    print(f"\033[95m  >> {line}\033[0m")
                elif "error" in line.lower():
                    print(f"\033[91m  >> {line}\033[0m")

            for pattern, stage in self.PATTERNS:
                m = pattern.search(line)
                if m:
                    if stage == "perf_mark":
                        self.timings.mark(m.group(1), now)
                    elif stage == "perf_summary":
                        self.timings._marks["perf_summary"] = m.group(1)
                    else:
                        self.timings.mark(stage, now)


class AudioInjector:
    """Sends WAV audio to the daemon's test injection Unix socket."""

    def __init__(self, sock_path=INJECT_SOCK):
        self.sock_path = sock_path

    def inject_wav(self, wav_path: str, timings: StageTimings = None):
        """Send a WAV file as raw PCM chunks at real-time rate."""
        with wave.open(wav_path) as wf:
            if wf.getframerate() != SAMPLE_RATE:
                print(f"WARNING: {wav_path} is {wf.getframerate()}Hz, expected {SAMPLE_RATE}Hz")
            raw = wf.readframes(wf.getnframes())

        chunk_bytes = CHUNK * 2  # int16 = 2 bytes per sample
        total_chunks = (len(raw) + chunk_bytes - 1) // chunk_bytes
        duration = len(raw) / (SAMPLE_RATE * 2)

        print(f"  Injecting {wav_path} ({duration:.1f}s, {total_chunks} chunks)")

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(self.sock_path)
        except (ConnectionRefusedError, FileNotFoundError):
            print(f"  ERROR: Cannot connect to {self.sock_path}")
            print(f"  Is the daemon running with GROKBOX_TEST_MODE=1?")
            return False

        if timings:
            timings.mark("inject_start")

        for i in range(0, len(raw), chunk_bytes):
            chunk = raw[i:i + chunk_bytes]
            # Pad last chunk if needed
            if len(chunk) < chunk_bytes:
                chunk += b"\x00" * (chunk_bytes - len(chunk))
            try:
                sock.sendall(chunk)
            except BrokenPipeError:
                print("  Connection lost during injection")
                break
            time.sleep(CHUNK_DURATION)

        sock.close()
        return True

    def inject_silence(self, duration_s: float, timings: StageTimings = None):
        """Inject silence (useful for padding between wake word and query)."""
        n_samples = int(SAMPLE_RATE * duration_s)
        raw = b"\x00" * n_samples * 2

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(self.sock_path)
        except (ConnectionRefusedError, FileNotFoundError):
            print(f"  ERROR: Cannot connect to {self.sock_path}")
            return False

        chunk_bytes = CHUNK * 2
        for i in range(0, len(raw), chunk_bytes):
            chunk = raw[i:i + chunk_bytes]
            if len(chunk) < chunk_bytes:
                chunk += b"\x00" * (chunk_bytes - len(chunk))
            try:
                sock.sendall(chunk)
            except BrokenPipeError:
                break
            time.sleep(CHUNK_DURATION)

        sock.close()
        return True


def run_pipeline_test(wake_wav: str, query_wav: str = None, timeout: float = 30.0):
    """Run a full pipeline test: inject wake word + optional query, report latency."""
    timings = StageTimings()
    monitor = JournalMonitor(timings)
    injector = AudioInjector()

    print("\nStarting pipeline test...")
    monitor.start(verbose=True)
    time.sleep(0.5)  # let monitor start tailing

    # Inject wake word
    print(f"\n[1/3] Injecting wake word audio...")
    if not injector.inject_wav(wake_wav, timings):
        monitor.stop()
        return

    # Wait for wake detection
    deadline = time.time() + 5.0
    while timings.get("wake_detected") == 0 and time.time() < deadline:
        time.sleep(0.05)

    if timings.get("wake_detected") == 0:
        print("\n  Wake word NOT detected within 5s")
        print("  Possible causes: audio too quiet, wrong format, or model didn't match")
        monitor.stop()
        return

    wake_dt = timings.delta("inject_start", "wake_detected")
    print(f"\n  Wake word detected! ({wake_dt:.3f}s after injection)")

    # Inject query
    if query_wav:
        # Small gap after beep
        time.sleep(0.5)
        print(f"\n[2/3] Injecting query audio...")
        injector.inject_wav(query_wav)

    # Wait for full pipeline
    print(f"\n[3/3] Waiting for pipeline completion (timeout {timeout}s)...")
    deadline = time.time() + timeout
    while timings.get("followup_or_wake") == 0 and time.time() < deadline:
        time.sleep(0.2)

    monitor.stop()
    time.sleep(0.5)

    # Report
    print(timings.report())


def run_monitor():
    """Just monitor daemon logs and report timing for manual interactions."""
    timings = StageTimings()
    monitor = JournalMonitor(timings)
    monitor.start(verbose=True)

    print("\nMonitoring GrokBox daemon (Ctrl+C to stop)...")
    print("Speak to the device and watch timing metrics.\n")

    try:
        last_cycle_end = 0.0
        while True:
            time.sleep(0.5)
            end = timings.get("followup_or_wake")
            if end and end != last_cycle_end:
                last_cycle_end = end
                print(timings.report())
                # Reset for next cycle
                timings = StageTimings()
                monitor.timings = timings
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        monitor.stop()


def main():
    parser = argparse.ArgumentParser(description="GrokBox Audio Test Harness")
    parser.add_argument("--wake", help="WAV file with wake word audio")
    parser.add_argument("--query", help="WAV file with query audio")
    parser.add_argument("--monitor", action="store_true", help="Monitor mode (no injection)")
    parser.add_argument("--timeout", type=float, default=30.0, help="Pipeline timeout in seconds")
    args = parser.parse_args()

    if args.monitor:
        run_monitor()
    elif args.wake:
        run_pipeline_test(args.wake, args.query, args.timeout)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
