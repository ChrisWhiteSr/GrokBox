#!/usr/bin/env python3
"""Generate test audio WAV files for the GrokBox test harness.

Modes:
  --record       Record from the mic interactively (press Enter to stop)
  --synthesize   Use Kokoro TTS to generate speech (may not trigger wake word)
  --silence      Generate silence WAV files for padding

Usage:
  python3 tests/generate_test_audio.py --record hey_jarvis
  python3 tests/generate_test_audio.py --record test_query
  python3 tests/generate_test_audio.py --synthesize "What time is it?" test_query
  python3 tests/generate_test_audio.py --silence 1.0 silence_1s
"""

import argparse
import os
import sys
import wave
import struct
import numpy as np

AUDIO_DIR = os.path.join(os.path.dirname(__file__), "audio")
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # int16


def generate_silence(duration_s: float, output_name: str):
    """Generate a silent WAV file."""
    n_samples = int(SAMPLE_RATE * duration_s)
    path = os.path.join(AUDIO_DIR, f"{output_name}.wav")
    with wave.open(path, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b"\x00" * n_samples * SAMPLE_WIDTH)
    print(f"Generated {duration_s}s silence: {path}")


def record_from_mic(output_name: str):
    """Record from the default mic until Enter is pressed."""
    import pyaudio
    import threading

    CHUNK = 1280
    path = os.path.join(AUDIO_DIR, f"{output_name}.wav")

    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=CHANNELS,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK,
    )

    frames = []
    stop = threading.Event()

    def _read():
        while not stop.is_set():
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)

    t = threading.Thread(target=_read, daemon=True)
    t.start()

    print(f"Recording '{output_name}' at 16kHz mono. Press Enter to stop...")
    input()
    stop.set()
    t.join(timeout=1.0)

    stream.stop_stream()
    stream.close()
    pa.terminate()

    with wave.open(path, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b"".join(frames))

    duration = len(frames) * CHUNK / SAMPLE_RATE
    print(f"Saved {duration:.1f}s recording: {path}")


def synthesize_speech(text: str, output_name: str):
    """Use Kokoro TTS to generate speech, then resample to 16kHz."""
    import requests
    import io

    kokoro = os.environ.get("KOKORO_SERVER", "http://10.0.0.226:5050/tts")
    voice = "af_heart"

    print(f"Requesting TTS from Kokoro: '{text}'")
    resp = requests.post(kokoro, json={"text": text, "voice": voice}, timeout=20)
    if resp.status_code != 200:
        print(f"Kokoro error {resp.status_code}: {resp.text}")
        sys.exit(1)

    # Kokoro outputs 24kHz — resample to 16kHz for mic simulation
    with wave.open(io.BytesIO(resp.content)) as wf:
        src_rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    src = np.frombuffer(raw, dtype=np.int16)
    if src_rate != SAMPLE_RATE:
        ratio = SAMPLE_RATE / src_rate
        n_out = int(len(src) * ratio)
        indices = np.linspace(0, len(src) - 1, n_out).astype(int)
        resampled = src[indices]
    else:
        resampled = src

    path = os.path.join(AUDIO_DIR, f"{output_name}.wav")
    with wave.open(path, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(resampled.tobytes())

    duration = len(resampled) / SAMPLE_RATE
    print(f"Saved {duration:.1f}s synthesized audio: {path}")


def main():
    os.makedirs(AUDIO_DIR, exist_ok=True)

    parser = argparse.ArgumentParser(description="Generate test audio for GrokBox harness")
    sub = parser.add_subparsers(dest="mode")

    rec = sub.add_parser("record", help="Record from mic")
    rec.add_argument("name", help="Output filename (without .wav)")

    syn = sub.add_parser("synthesize", help="Generate via Kokoro TTS")
    syn.add_argument("text", help="Text to synthesize")
    syn.add_argument("name", help="Output filename (without .wav)")

    sil = sub.add_parser("silence", help="Generate silence")
    sil.add_argument("duration", type=float, help="Duration in seconds")
    sil.add_argument("name", help="Output filename (without .wav)")

    args = parser.parse_args()

    if args.mode == "record":
        record_from_mic(args.name)
    elif args.mode == "synthesize":
        synthesize_speech(args.text, args.name)
    elif args.mode == "silence":
        generate_silence(args.duration, args.name)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
