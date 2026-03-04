"""GrokBox Voice Assistant Daemon.

Event-driven architecture with continuous mic capture, echo-gated wake word
detection, streaming LLM + TTS pipeline, and performance instrumentation.
"""

import json
import logging
import os
import queue
import re
import signal
import sys
import threading
import time
import warnings
import ctypes

import requests

# Suppress ALSA/JACK/ONNX stderr spam before any audio imports
os.environ["ORT_LOG_LEVEL"] = "3"
warnings.filterwarnings("ignore", message=".*CUDAExecutionProvider.*")
warnings.filterwarnings("ignore", message=".*duckduckgo_search.*")

_alsa_error_handler_type = ctypes.CFUNCTYPE(
    None, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p
)
def _alsa_noop(*_): pass
_alsa_error_handler = _alsa_error_handler_type(_alsa_noop)
try:
    ctypes.cdll.LoadLibrary("libasound.so.2").snd_lib_error_set_handler(_alsa_error_handler)
except Exception:
    pass

_devnull = os.open(os.devnull, os.O_WRONLY)
_old_stderr = os.dup(2)
os.dup2(_devnull, 2)

from skills.skill_manager import SkillManager
skill_mgr = SkillManager()

from openwakeword.model import Model

os.dup2(_old_stderr, 2)
os.close(_old_stderr)
os.close(_devnull)

# Now import our new modules (after noisy imports are done)
from scripts.audio_engine import AudioEngine
from scripts.pipeline import WakeWordDetector, STTFeeder, speak_streaming
from scripts.pipeline_timer import PipelineTimer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("grokbox")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
from dotenv import load_dotenv
load_dotenv("/Code/grokbox/.env")

ASSEMBLYAI_KEY = os.environ["ASSEMBLYAI_KEY"]
XAI_KEY = os.environ["XAI_KEY"]
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
CONFIG_PATH = "/Code/grokbox/config.json"
KOKORO_SERVER = os.getenv("KOKORO_SERVER", "http://10.0.0.226:5050/tts")
DEFAULT_MODEL = "grok-4-1-fast-non-reasoning"

# Provider routing by model prefix
_PROVIDERS = {
    "grok": {"url": "https://api.x.ai/v1/chat/completions", "key": XAI_KEY},
    "gpt":  {"url": "https://api.openai.com/v1/chat/completions", "key": OPENAI_KEY},
    "o1":   {"url": "https://api.openai.com/v1/chat/completions", "key": OPENAI_KEY},
    "o3":   {"url": "https://api.openai.com/v1/chat/completions", "key": OPENAI_KEY},
    "o4":   {"url": "https://api.openai.com/v1/chat/completions", "key": OPENAI_KEY},
}


def _get_model():
    """Read the current model from the shared config file (hot-swappable)."""
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f).get("model", DEFAULT_MODEL)
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULT_MODEL


def _get_provider(model: str) -> dict:
    """Return {url, key} for a model based on its name prefix."""
    for prefix, provider in _PROVIDERS.items():
        if model.startswith(prefix):
            return provider
    return _PROVIDERS["grok"]  # fallback
VOICE = "af_heart"

STT_TIMEOUT = 12       # Seconds before force-killing a stuck STT session
FOLLOWUP_TIMEOUT = 12  # Seconds to wait for follow-up speech (from STT ready, not request time)

# Phrases that mean "stop listening"
SLEEP_PHRASES = [
    "stop listening", "pause listening", "go to sleep",
    "shut up", "be quiet", "mute yourself", "sleep mode",
    "stop it", "quiet down", "silence",
]

# Conversation memory
MAX_MEMORY_TURNS = 10
conversation_history = []

# ---------------------------------------------------------------------------
# Pause/resume via SIGUSR1
# ---------------------------------------------------------------------------
paused = False

def handle_sigusr1(signum, frame):
    global paused
    paused = not paused
    log.info("Listening %s via SIGUSR1", "paused" if paused else "resumed")

signal.signal(signal.SIGUSR1, handle_sigusr1)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_sleep_command(text):
    """Check if the transcript is a sleep/pause command (not a question about sleeping)."""
    cleaned = re.sub(r'[^a-z\s]', '', text.lower()).strip()
    words = cleaned.split()

    # Reject questions — if the utterance starts with an interrogative word,
    # the user is asking ABOUT sleeping, not commanding it.
    question_starters = {
        "why", "what", "when", "where", "how", "who", "which",
        "did", "do", "does", "can", "could", "would", "should",
        "is", "are", "was", "were", "will", "have", "has",
    }
    if words and words[0] in question_starters:
        return False

    # Only match if a sleep phrase appears at the START of the utterance
    # (within the first 4 words) to avoid matching mid-sentence references.
    first_part = " ".join(words[:5])
    for phrase in SLEEP_PHRASES:
        if phrase in first_part:
            return True

    # Also check "stop/pause listening" pattern at start
    if words and words[0] in ("stop", "pause", "quit", "end", "halt"):
        if "listening" in words[:4]:
            return True

    return False


_SENTENCE_END = re.compile(r'(?<=[.!?])\s+(?=[A-Z"\u2018\u2019])|(?<=[.!?])\s*$')

def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_END.split(text.strip())
    return [p.strip() for p in parts if p.strip()]

def _clean_response(text: str) -> str:
    text = re.sub(r'\[\[?\d+\]?\]\([^)]*\)', '', text)
    text = re.sub(r'\*\*|\*|#{1,6} |`', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ---------------------------------------------------------------------------
# LLM — streaming response generator (KEPT from original)
# ---------------------------------------------------------------------------

def get_grok_response_streaming(transcribed_text, timer: PipelineTimer = None):
    """Generator. Yields complete sentences as Grok streams tokens."""
    global conversation_history
    log.info("Thought received to send to Grok: %s", transcribed_text)

    model = _get_model()
    provider = _get_provider(model)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {provider['key']}",
    }
    system_prompt = (
        "You are Jarvis, a voice-activated AI assistant built into a smart speaker. "
        f"You are powered by the {model} model. "
        "You have access to tools that can control Spotify playback and search the web. You MUST use these tools when asked. "
        "Your responses will be read aloud by a text-to-speech engine, so always respond in natural spoken language. "
        "Never use markdown, bullet points, lists, headers, citation brackets, or any special formatting. "
        "Keep every response to 2-3 sentences maximum. Be direct and conversational. "
        "You have memory of recent conversations with the user. Use it to give contextual replies."
    )

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": transcribed_text})

    tools = skill_mgr.get_tool_schemas()
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 150,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    start_t = time.time()
    full_response = ""

    resp = requests.post(provider["url"], headers=headers, json=payload, stream=True, timeout=30)
    if resp.status_code != 200:
        log.error("Grok API error %d: %s", resp.status_code, resp.text[:200])
        yield "Sorry, I had trouble reaching my brain."
        return

    tool_calls_raw = []
    token_buffer = ""
    first_token_logged = False

    for line in resp.iter_lines():
        if not line:
            continue
        line = line.decode("utf-8")
        if not line.startswith("data: "):
            continue
        data_str = line[6:]
        if data_str == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
        except Exception:
            continue

        choice = chunk.get("choices", [{}])[0]
        delta = choice.get("delta", {})

        # Tool call — collect deltas
        if delta.get("tool_calls"):
            for tc_delta in delta["tool_calls"]:
                idx = tc_delta.get("index", 0)
                while len(tool_calls_raw) <= idx:
                    tool_calls_raw.append({"id": "", "type": "function",
                                           "function": {"name": "", "arguments": ""}})
                if tc_delta.get("id"):
                    tool_calls_raw[idx]["id"] = tc_delta["id"]
                fn = tc_delta.get("function", {})
                if fn.get("name"):
                    tool_calls_raw[idx]["function"]["name"] += fn["name"]
                if fn.get("arguments"):
                    tool_calls_raw[idx]["function"]["arguments"] += fn["arguments"]
            continue

        content = delta.get("content", "")
        if not content:
            continue

        if not first_token_logged and timer:
            timer.mark("llm_first_token")
            first_token_logged = True

        token_buffer += content

        sentences = _split_sentences(token_buffer)
        if len(sentences) > 1:
            for s in sentences[:-1]:
                clean = _clean_response(s)
                if clean:
                    yield clean
                    full_response += clean + " "
            token_buffer = sentences[-1]

    if token_buffer.strip() and not tool_calls_raw:
        clean = _clean_response(token_buffer)
        if clean:
            yield clean
            full_response += clean

    # Handle tool calls
    if tool_calls_raw:
        log.info("Tool calls detected: %s", [tc["function"]["name"] for tc in tool_calls_raw])
        tool_message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["function"]["name"],
                                 "arguments": tc["function"]["arguments"]},
                }
                for tc in tool_calls_raw
            ],
        }
        messages.append(tool_message)
        for tc in tool_calls_raw:
            result = skill_mgr.execute_tool(tc)
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})

        followup_payload = {
            "model": model, "messages": messages,
            "temperature": 0.5, "max_tokens": 150,
        }
        followup = requests.post(provider["url"], headers=headers, json=followup_payload, timeout=30)
        if followup.status_code == 200:
            followup_text = followup.json()["choices"][0]["message"].get("content", "").strip()
            full_response = _clean_response(followup_text)
            for sentence in _split_sentences(full_response):
                yield sentence
        else:
            yield "I ran the tool but had trouble summarizing the result."

    # Save to conversation memory
    if full_response.strip():
        conversation_history.append({"role": "user", "content": transcribed_text})
        conversation_history.append({"role": "assistant", "content": full_response.strip()})
        if len(conversation_history) > MAX_MEMORY_TURNS * 2:
            conversation_history[:] = conversation_history[-(MAX_MEMORY_TURNS * 2):]

    log.info("Grok responded in %.1fs: %s", time.time() - start_t, full_response.strip())


# ---------------------------------------------------------------------------
# Main event loop
# ---------------------------------------------------------------------------

def loop():
    global paused

    # --- Initialize audio engine ---
    engine = AudioEngine()

    # Suppress stderr during PyAudio init (JACK noise)
    _dn = os.open(os.devnull, os.O_WRONLY)
    _oe = os.dup(2)
    os.dup2(_dn, 2)
    engine.start()
    os.dup2(_oe, 2)
    os.close(_oe)
    os.close(_dn)

    # Load beep
    engine.load_beep("/Code/grokbox/beep.wav")

    # --- Initialize wake word model ---
    model_path = "/Code/grokbox/venv/lib/python3.13/site-packages/openwakeword/resources/models/hey_jarvis_v0.1.onnx"
    ww_model = Model(wakeword_model_paths=[model_path])

    # --- Performance timer ---
    timer = PipelineTimer()

    # --- Event queue for cross-thread communication ---
    event_q = queue.Queue()

    # --- Wire up wake word detector ---
    def on_wake():
        event_q.put(("wake", None))

    wake_detector = WakeWordDetector(engine, ww_model, on_wake, timer=timer)

    # --- Wire up STT feeder ---
    stt_feeder = STTFeeder(engine, ASSEMBLYAI_KEY, timer=timer)

    def on_stt_final(text):
        event_q.put(("stt_final", text))

    def on_stt_partial(text):
        event_q.put(("stt_partial", text))

    # --- State machine ---
    # States: wake_word, stt_active, responding, followup
    state = "wake_word"
    stt_started_at = 0.0
    last_partial_at = 0.0   # Track when we last heard speech (extends timeout)
    in_followup = False

    log.info("GrokBox Daemon starts listening for 'Hey Jarvis'...")

    def _handle_response(text):
        """Run LLM + TTS pipeline in a separate thread."""
        try:
            log.info("Querying [%s] with: %s", _get_model(), text)
            if timer:
                timer.mark("llm_start")
            sentence_gen = get_grok_response_streaming(text, timer=timer)
            speak_streaming(sentence_gen, engine, KOKORO_SERVER, VOICE, timer=timer)
        except Exception as e:
            log.error("Response pipeline error: %s", e)
        finally:
            event_q.put(("response_done", None))

    def _handle_sleep_command():
        """Speak the sleep message via the streaming pipeline."""
        try:
            def _sleep_sentences():
                yield "OK, I'll stop listening. Say Hey Jarvis to wake me up."
            speak_streaming(_sleep_sentences(), engine, KOKORO_SERVER, VOICE)
        except Exception as e:
            log.error("Sleep TTS error: %s", e)
        finally:
            event_q.put(("sleep_done", None))

    def _handle_resume():
        """Speak the resume message."""
        try:
            def _resume_sentences():
                yield "I'm back. What do you need?"
            speak_streaming(_resume_sentences(), engine, KOKORO_SERVER, VOICE)
        except Exception as e:
            log.error("Resume TTS error: %s", e)
        finally:
            event_q.put(("resume_done", None))

    try:
        while True:
            try:
                event_type, data = event_q.get(timeout=0.2)
            except queue.Empty:
                # Periodic checks
                if state in ("stt_active", "followup"):
                    timeout = FOLLOWUP_TIMEOUT if in_followup else STT_TIMEOUT
                    # Use the later of stt_started_at or last_partial_at as baseline
                    # so active speech extends the window
                    baseline = max(stt_started_at, last_partial_at)
                    if time.time() - baseline > timeout:
                        stt_feeder.stop_session(quiet=in_followup)
                        if in_followup:
                            log.info("Follow-up window closed — listening for wake word")
                        else:
                            log.info("Listening for wake word again")
                        state = "wake_word"
                        in_followup = False
                        last_partial_at = 0.0
                        ww_model.reset()
                        wake_detector.enabled = True
                        timer.log_summary()
                        timer.reset()
                continue

            # === WAKE WORD DETECTED ===
            if event_type == "wake" and state == "wake_word":
                timer.reset()
                timer.mark("wake_detected")

                if paused:
                    # Unpause: beep + resume message
                    log.info("Wake word detected — resumed from sleep!")
                    paused = False
                    engine.play_beep()
                    timer.mark("beep_done")
                    wake_detector.enabled = False
                    state = "resuming"
                    threading.Thread(target=_handle_resume, daemon=True).start()
                else:
                    log.info("Wake word detected!")
                    engine.play_beep()
                    timer.mark("beep_done")

                    # Start STT session
                    wake_detector.enabled = False
                    state = "stt_active"
                    in_followup = False
                    last_partial_at = 0.0
                    stt_feeder.start_session(on_stt_final, on_partial_callback=on_stt_partial)
                    stt_started_at = time.time()

            # === STT PARTIAL (extends timeout while user is speaking) ===
            elif event_type == "stt_partial" and state in ("stt_active", "followup"):
                last_partial_at = time.time()

            # === STT FINAL TRANSCRIPT ===
            elif event_type == "stt_final" and state in ("stt_active", "followup"):
                text = data

                if is_sleep_command(text):
                    paused = True
                    log.info("Pause command received — sleeping until wake word")
                    state = "sleeping"
                    threading.Thread(target=_handle_sleep_command, daemon=True).start()
                else:
                    state = "responding"
                    threading.Thread(
                        target=_handle_response, args=(text,), daemon=True
                    ).start()

            # === RESPONSE DONE ===
            elif event_type == "response_done" and state == "responding":
                timer.log_summary()

                # Open follow-up listening window
                in_followup = True
                state = "followup"
                last_partial_at = 0.0
                timer.reset()
                stt_feeder.start_session(on_stt_final, on_partial_callback=on_stt_partial)
                # Set timeout baseline AFTER session is ready (not before)
                stt_started_at = time.time()
                log.info("Listening for follow-up...")

            # === SLEEP TTS DONE ===
            elif event_type == "sleep_done" and state == "sleeping":
                log.info("Paused — listening for wake word only")
                state = "wake_word"
                ww_model.reset()
                wake_detector.enabled = True
                timer.log_summary()
                timer.reset()

            # === RESUME TTS DONE ===
            elif event_type == "resume_done" and state == "resuming":
                log.info("Listening for wake word again")
                state = "wake_word"
                ww_model.reset()
                wake_detector.enabled = True
                timer.log_summary()
                timer.reset()

    except KeyboardInterrupt:
        log.info("Exiting...")
    finally:
        engine.stop()


if __name__ == "__main__":
    loop()
