# wyoming-piper-preproc

A tiny [Wyoming protocol](https://github.com/rhasspy/wyoming) proxy that sits in front of [Piper](https://github.com/rhasspy/wyoming-piper) and rewrites the text of each `Synthesize` event using a CSV of pronunciation overrides before forwarding to Piper.

Use it when Piper mispronounces specific words (your kid's name, a brand, a place) or reads unicode glyphs as raw characters (`μg/m³` → "mug em three"). Without this, you'd be patching pronunciations into the LLM's system prompt and hoping it doesn't slip; with this, you get a deterministic substitution layer that lives outside the model.

## Architecture

```
HA  ──Synthesize(text)─▶  wyoming-piper-preproc  ──Synthesize(text')─▶  Piper
HA  ◀────audio chunks─────         │             ◀────audio chunks─────  Piper
                                  (CSV)
```

Every event passes through unchanged **except** `Synthesize`, whose `text` field is rewritten before forwarding. Audio streams back transparently. One inbound TCP connection ↔ one upstream connection — sessions are short.

## Quick start

```bash
git clone https://github.com/<you>/wyoming-piper-preproc.git
cd wyoming-piper-preproc

# Edit data/pronunciations-piper.csv to taste
# Set UPSTREAM_HOST/PORT for your real Piper instance
docker compose up -d --build

# In Home Assistant, edit the Piper Wyoming integration
# and change Port from 10200 to 10210.
```

## Configuration

| env var | default | meaning |
|---|---|---|
| `LISTEN_HOST` | `0.0.0.0` | Bind host |
| `LISTEN_PORT` | `10210` | Bind port |
| `UPSTREAM_HOST` | `127.0.0.1` | Real Piper host |
| `UPSTREAM_PORT` | `10200` | Real Piper port |
| `PRONUNCIATIONS` | `/data/pronunciations.csv:/data/pronunciations-piper.csv` | Colon-separated list of CSVs; later wins on conflicts |
| `LOG_LEVEL` | `INFO` | Set to `DEBUG` for per-connection trace |

## Pronunciation CSV format

```csv
# Two columns, no header. Lines starting with # are comments.
# Longest entries are applied first so multi-word phrases match before substrings.
μg/m³,micrograms per cubic meter
°C,degrees Celsius
Kailey,Kaylee
ADP,A-Dee-Pee
```

The file is re-read on every Synthesize request, so you can edit it live without restarting the container. The cost is a few KB of disk read per TTS call — negligible compared to synthesis time.

You can layer files: a base `pronunciations.csv` shared with other TTS engines, plus a `pronunciations-piper.csv` overlay with Piper-specific spellings.

## Building / testing locally

```bash
# Direct (no docker)
pip install wyoming
python -m wyoming_piper_preproc --upstream-host 192.168.x.x --upstream-port 10200

# Smoke test against an upstream Piper
python - <<'PY'
import asyncio
from wyoming.client import AsyncTcpClient
from wyoming.tts import Synthesize, SynthesizeVoice
from wyoming.audio import AudioChunk, AudioStop

async def main():
    async with AsyncTcpClient("127.0.0.1", 10210) as c:
        await c.write_event(Synthesize(text="The PM2.5 reading is 1 μg/m³.").event())
        chunks = []
        while True:
            e = await c.read_event()
            if e is None or AudioStop.is_type(e.type): break
            if AudioChunk.is_type(e.type): chunks.append(AudioChunk.from_event(e).audio)
        print(f"got {sum(map(len,chunks))} bytes of audio")
asyncio.run(main())
PY
```

## Lessons learned (don't repeat them)

- **"cubic" sounded like Kubrick** via Piper's default voice (`en_US-hfc_female-medium`). Tempting fix: phonetic respelling like `cubic,kyoo-bik`. **Don't.** It came out as "kuel bic" (the hyphen breaks Piper's phrasing) and was worse than the original. Leave Piper's pronunciation of common technical words alone unless you can verify the result with the round-trip diagnostic first.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

The text-preprocessing pipeline pattern (normalize → pronunciations → engine-punctuation, all engine-aware) is borrowed from the TTS preprocessor in the [VE-Analysis-API](https://github.com/) project. Same idea — substitute then synthesize — applied to a different host.
