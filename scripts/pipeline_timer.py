"""Pipeline performance instrumentation for GrokBox.

Tracks timestamps for each stage of a wake-to-done cycle and emits
structured timing summaries to the log (parseable by the test harness).
"""

import logging
import threading
import time

log = logging.getLogger("grokbox.perf")

STAGE_ORDER = [
    "wake_detected",
    "beep_done",
    "stt_ready",
    "stt_final",
    "llm_start",
    "llm_first_token",
    "tts_first_sentence",
    "playback_start",
    "playback_done",
]


class PipelineTimer:
    """Tracks timestamps for each stage of a single pipeline cycle."""

    def __init__(self):
        self._stages: dict[str, float] = {}
        self._lock = threading.Lock()

    def mark(self, stage: str):
        """Record timestamp for a pipeline stage and log it."""
        t = time.time()
        with self._lock:
            self._stages[stage] = t
        log.info("[PERF] %s", stage)

    def get(self, stage: str) -> float:
        with self._lock:
            return self._stages.get(stage, 0.0)

    def summary(self) -> dict:
        """Compute deltas between consecutive stages."""
        with self._lock:
            s = dict(self._stages)

        result = {}
        for i in range(1, len(STAGE_ORDER)):
            prev, curr = STAGE_ORDER[i - 1], STAGE_ORDER[i]
            if prev in s and curr in s:
                result[f"{prev}_to_{curr}"] = round(s[curr] - s[prev], 3)

        if "wake_detected" in s and "playback_start" in s:
            result["ttfsw"] = round(s["playback_start"] - s["wake_detected"], 3)

        if "wake_detected" in s and "playback_done" in s:
            result["total"] = round(s["playback_done"] - s["wake_detected"], 3)

        return result

    def log_summary(self):
        """Emit structured timing summary to log."""
        s = self.summary()
        if s:
            log.info("[PERF_SUMMARY] %s", s)

    def reset(self):
        """Clear all recorded stages for the next cycle."""
        with self._lock:
            self._stages.clear()
