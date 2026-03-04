#!/usr/bin/env python3
"""Multi-turn conversation test for GrokBox.

Injects a wake word + initial prompt, then feeds follow-up numbers during
the follow-up window to test sustained multi-turn performance.

Usage:
    python3 tests/multi_turn_test.py --turns 10
"""

import argparse
import os
import re
import socket
import sys
import subprocess
import threading
import time
import wave

INJECT_SOCK = "/tmp/grokbox_test_audio.sock"
CHUNK = 1280
SAMPLE_RATE = 16000
CHUNK_DURATION = CHUNK / SAMPLE_RATE

AUDIO_DIR = os.path.join(os.path.dirname(__file__), "audio")

# Follow-up number WAVs in order
FOLLOW_UP_WAVS = [
    "ten.wav", "twenty.wav", "fifty.wav", "hundred.wav",
    "two_hundred.wav", "five_hundred.wav", "thousand.wav",
    "three_thousand.wav", "ten_thousand.wav", "million.wav",
]


class LogWatcher:
    """Watches journalctl for specific events."""

    def __init__(self):
        self._proc = None
        self._thread = None
        self._running = False
        self._events = []
        self._lock = threading.Lock()
        self._waiters = {}  # pattern_name -> threading.Event

    def start(self):
        self._running = True
        self._proc = subprocess.Popen(
            ["journalctl", "-u", "grokbox", "-f", "--no-pager", "-n", "0"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )
        self._thread = threading.Thread(target=self._tail, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._proc:
            self._proc.terminate()

    def _tail(self):
        patterns = {
            "wake": re.compile(r"Wake word detected"),
            "stt_ready": re.compile(r"AssemblyAI streaming channel opened"),
            "stt_final": re.compile(r"\[FINAL\] (.+)"),
            "responding": re.compile(r"SYSTEM RESPONDING"),
            "grok_response": re.compile(r"Grok responded in ([\d.]+)s: (.+)"),
            "playback_done": re.compile(r"\[PERF\] playback_done"),
            "followup": re.compile(r"Listening for follow-up"),
            "followup_closed": re.compile(r"Follow-up window closed"),
            "perf_summary": re.compile(r"\[PERF_SUMMARY\] (.+)"),
            "stt_warning": re.compile(r"STT session didn't become ready"),
            "error": re.compile(r"\[ERROR\]"),
        }

        for line in iter(self._proc.stdout.readline, ""):
            if not self._running:
                break
            line = line.strip()
            now = time.time()

            for name, pat in patterns.items():
                m = pat.search(line)
                if m:
                    event = {"name": name, "time": now, "match": m, "line": line}
                    with self._lock:
                        self._events.append(event)
                        if name in self._waiters:
                            self._waiters[name].set()

                    # Print important events with color
                    if name == "wake":
                        print(f"\033[96m  [{now:.1f}] Wake word detected\033[0m")
                    elif name == "stt_final":
                        print(f"\033[92m  [{now:.1f}] STT: {m.group(1)}\033[0m")
                    elif name == "grok_response":
                        print(f"\033[93m  [{now:.1f}] Grok ({m.group(1)}s): {m.group(2)}\033[0m")
                    elif name == "followup":
                        print(f"\033[94m  [{now:.1f}] Follow-up window open\033[0m")
                    elif name == "followup_closed":
                        print(f"\033[91m  [{now:.1f}] Follow-up window CLOSED\033[0m")
                    elif name == "stt_warning":
                        print(f"\033[91m  [{now:.1f}] WARNING: STT not ready in 3s!\033[0m")
                    elif name == "error":
                        print(f"\033[91m  [{now:.1f}] ERROR: {line}\033[0m")

    def wait_for(self, event_name, timeout=30.0):
        """Wait for a specific event to occur. Returns True if seen, False on timeout."""
        evt = threading.Event()
        with self._lock:
            # Check if already seen recently (within last 0.5s)
            for e in reversed(self._events[-5:]):
                if e["name"] == event_name and time.time() - e["time"] < 0.5:
                    return True
            self._waiters[event_name] = evt

        result = evt.wait(timeout=timeout)
        with self._lock:
            self._waiters.pop(event_name, None)
        return result

    def clear_waiters(self):
        with self._lock:
            self._waiters.clear()

    def get_events(self, name=None):
        with self._lock:
            if name:
                return [e for e in self._events if e["name"] == name]
            return list(self._events)


def inject_wav(wav_path):
    """Send a WAV file to the daemon's test injection socket."""
    with wave.open(wav_path) as wf:
        raw = wf.readframes(wf.getnframes())
    duration = len(raw) / (SAMPLE_RATE * 2)

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(INJECT_SOCK)
    except (ConnectionRefusedError, FileNotFoundError):
        print(f"\033[91m  ERROR: Cannot connect to {INJECT_SOCK}\033[0m")
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


def run_multi_turn_test(num_turns):
    watcher = LogWatcher()
    watcher.start()
    time.sleep(0.5)

    wake_wav = os.path.join(AUDIO_DIR, "hey_jarvis.wav")
    prompt_wav = os.path.join(AUDIO_DIR, "game_prompt.wav")

    results = []

    print(f"\n{'='*60}")
    print(f"  GrokBox Multi-Turn Test: {num_turns} turns")
    print(f"{'='*60}")

    # === Turn 0: Wake word + game prompt ===
    print(f"\n--- Turn 0: Wake word + game prompt ---")
    t0 = time.time()
    print(f"  Injecting wake word...")
    inject_wav(wake_wav)

    if not watcher.wait_for("wake", timeout=5):
        print(f"\033[91m  FAIL: Wake word not detected\033[0m")
        watcher.stop()
        return

    time.sleep(0.3)
    print(f"  Injecting game prompt...")
    inject_wav(prompt_wav)

    if not watcher.wait_for("playback_done", timeout=30):
        print(f"\033[91m  FAIL: No response playback\033[0m")
        watcher.stop()
        return

    results.append({"turn": 0, "time": time.time() - t0, "status": "ok"})

    # === Follow-up turns ===
    for turn in range(1, num_turns + 1):
        wav_name = FOLLOW_UP_WAVS[(turn - 1) % len(FOLLOW_UP_WAVS)]
        wav_path = os.path.join(AUDIO_DIR, wav_name)

        print(f"\n--- Turn {turn}/{num_turns}: {wav_name} ---")
        t_turn = time.time()

        # Wait for follow-up window to open
        if not watcher.wait_for("followup", timeout=15):
            print(f"\033[91m  FAIL: Follow-up window never opened\033[0m")
            results.append({"turn": turn, "time": 0, "status": "no_followup"})
            break

        # Clear old events and inject the number
        watcher.clear_waiters()
        time.sleep(0.8)  # small gap so STT is ready
        print(f"  Injecting {wav_name}...")
        inject_wav(wav_path)

        # Wait for Grok's response to finish playing
        if not watcher.wait_for("playback_done", timeout=30):
            # Check if followup closed before we got a response
            closed = watcher.get_events("followup_closed")
            if closed and closed[-1]["time"] > t_turn:
                print(f"\033[91m  FAIL: Follow-up window closed before response\033[0m")
                results.append({"turn": turn, "time": time.time() - t_turn, "status": "window_closed"})
            else:
                print(f"\033[91m  FAIL: No response within 30s\033[0m")
                results.append({"turn": turn, "time": time.time() - t_turn, "status": "timeout"})
            break

        elapsed = time.time() - t_turn
        results.append({"turn": turn, "time": elapsed, "status": "ok"})
        print(f"\033[92m  Turn {turn} complete ({elapsed:.1f}s)\033[0m")

    watcher.stop()
    time.sleep(0.5)

    # === Summary ===
    print(f"\n{'='*60}")
    print(f"  Multi-Turn Test Results")
    print(f"{'='*60}")
    ok = sum(1 for r in results if r["status"] == "ok")
    total = len(results)
    print(f"  Turns completed: {ok}/{num_turns + 1} (including setup)")
    print()

    for r in results:
        status_color = "\033[92m" if r["status"] == "ok" else "\033[91m"
        print(f"  Turn {r['turn']:>2d}: {status_color}{r['status']:>15s}\033[0m  {r['time']:.1f}s")

    if ok < total:
        failed = [r for r in results if r["status"] != "ok"]
        print(f"\n  \033[91mFailed at turn {failed[0]['turn']}: {failed[0]['status']}\033[0m")

    times = [r["time"] for r in results if r["status"] == "ok" and r["turn"] > 0]
    if times:
        print(f"\n  Avg follow-up turn time: {sum(times)/len(times):.1f}s")
        print(f"  Min: {min(times):.1f}s  Max: {max(times):.1f}s")

    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="GrokBox Multi-Turn Test")
    parser.add_argument("--turns", type=int, default=10, help="Number of follow-up turns")
    args = parser.parse_args()
    run_multi_turn_test(args.turns)


if __name__ == "__main__":
    main()
