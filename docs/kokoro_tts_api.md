# Kokoro TTS API — Remote Access

**Server:** `10.0.0.226:5050` (miniLobster)
**Model:** Kokoro v1.0 ONNX (CPU inference)

## Endpoints

### POST `/tts` — Synthesize speech

Returns WAV audio.

```bash
curl -X POST http://10.0.0.226:5050/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello from the lobster trap.", "voice": "af_heart", "speed": 1.0}' \
  -o output.wav
```

**Body (JSON):**

| Field   | Type   | Default     | Description                  |
|---------|--------|-------------|------------------------------|
| `text`  | string | (required)  | Text to speak                |
| `voice` | string | `af_heart`  | Voice ID (see `/voices`)     |
| `speed` | float  | `1.0`       | Playback speed (0.5 - 2.0)  |

**Response:** `audio/wav` binary

### GET `/voices` — List available voices

```bash
curl http://10.0.0.226:5050/voices
```

Returns JSON: `{"voices": ["af_heart", "af_bella", "am_michael", ...]}`

### GET `/health` — Health check

```bash
curl http://10.0.0.226:5050/health
```

Returns: `{"status": "ok", "model": "kokoro-v1.0-onnx"}`

## Quick examples

**Python:**
```python
import urllib.request, json

payload = json.dumps({"text": "Checking in from the windows box.", "voice": "af_heart"}).encode()
req = urllib.request.Request("http://10.0.0.226:5050/tts", data=payload, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=30) as resp:
    with open("output.wav", "wb") as f:
        f.write(resp.read())
```

**Play directly (Linux):**
```bash
curl -s -X POST http://10.0.0.226:5050/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "This is a test.", "voice": "af_heart"}' | aplay
```

**PowerShell (Windows):**
```powershell
$body = '{"text": "Hello from Windows.", "voice": "af_heart"}'
Invoke-WebRequest -Uri "http://10.0.0.226:5050/tts" -Method POST -ContentType "application/json" -Body $body -OutFile output.wav
```

## Popular voices

| Voice ID     | Description          |
|-------------|----------------------|
| `af_heart`  | Female, warm (default)|
| `af_bella`  | Female, clear         |
| `af_nova`   | Female, bright        |
| `am_michael`| Male, neutral         |
| `am_adam`   | Male, deep            |
| `bf_emma`   | British female        |
| `bm_daniel` | British male          |

Full list: `curl http://10.0.0.226:5050/voices`

## Notes

- Max recommended text length: ~500 chars per request (longer text = longer generation time)
- CPU inference: ~1-3 seconds for a typical sentence
- No auth required on LAN
- WAV format: 16-bit PCM mono, 24000 Hz sample rate
