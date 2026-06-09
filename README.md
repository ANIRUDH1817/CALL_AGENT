# AI Calling Agent

A real-time AI voice agent that answers **incoming calls** and makes **outbound calls** to potential clients — with full conversation memory, call summaries, and switchable personalities (skills).

Built with **FastAPI**, **Plivo (telephony)**, **Deepgram (STT + TTS)**, and **Groq / Gemini (LLM)**. Runs entirely in Docker.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [Skills System](#skills-system)
- [Outbound Calling](#outbound-calling)
- [API Reference](#api-reference)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)

---

## Features

- **Inbound Calls** — answers calls to your Plivo number, talks with callers in real time
- **Outbound Calls** — reads a `clients.json` file and calls leads with personalized context
- **Per-client Skills** — assign a specific skill to each client in `clients.json`; the agent auto-switches when the call connects
- **Call Notes** — every call is saved as a JSON file in `call_notes/` with full transcript + AI summary
- **Skills System** — switch the agent's personality/purpose at runtime (personal assistant, receptionist, sales agent, etc.)
- **LLM Choice** — use Groq (Llama 3.3) or Google Gemini per skill, configurable per skill file
- **Real-time STT** — Deepgram Nova-2 streams audio live with silence detection
- **High-quality TTS** — Deepgram Aura voices converted to phone-compatible mulaw audio
- **Call Summaries** — auto-generates and POSTs a summary + transcript to any webhook after each call
- **Structured Logging** — every module (STT, LLM, TTS, CALL) logs with timing info
- **Docker Ready** — single `docker compose up --build` to run everything

---

## Architecture

```
Inbound Call:
  Caller → Plivo → /incoming-call (webhook) → WebSocket /media-stream
                                                    │
                              ┌─────────────────────┼──────────────────────┐
                              ▼                     ▼                      ▼
                      Deepgram STT (live)     Groq/Gemini LLM        Deepgram TTS
                      (audio → text)          (text → text)          (text → audio)
                              └─────────────────────┼──────────────────────┘
                                                    ▼
                                          Plivo ← audio playback

Outbound Call:
  clients.json → outbound_caller.py → Plivo API dials client
                                            │
                                  Client picks up → /outbound-call (webhook)
                                            │
                                  Loads client context → personalized AI prompt
                                            │
                                  Same WebSocket pipeline as inbound
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.9, FastAPI, uvicorn |
| Telephony | Plivo (Media Streams / WebSocket) |
| Speech-to-Text | Deepgram Nova-2 (real-time WebSocket) |
| Text-to-Speech | Deepgram Aura (REST, mulaw output) |
| LLM | Groq (llama-3.3-70b-versatile) or Google Gemini Flash |
| Containerization | Docker, Docker Compose |
| Tunneling (dev) | Cloudflare Tunnel (no account needed) or ngrok |

---

## Project Structure

```
CALL_AGENT/
├── cloud_main.py          # FastAPI server — inbound/outbound endpoints + WebSocket pipeline
├── llm_client.py          # Unified LLM client (Groq + Gemini)
├── cloud_note_taker.py    # Stores transcripts and POSTs summaries to a webhook
├── outbound_caller.py     # CLI tool to initiate outbound calls from clients.json
├── clients.json           # Your leads/clients (gitignored — keep private)
├── skills/
│   ├── personal_assistant.py   # Default skill — Anirudh's personal AI assistant
│   └── receptionist.py         # Professional receptionist skill
├── Dockerfile
├── docker-compose.yml
├── render.yaml            # Render deployment config
├── requirements.txt
├── .env.example           # Template for your .env file
└── .gitignore
```

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- [Plivo account](https://console.plivo.com) — free trial includes credits
- [Deepgram account](https://console.deepgram.com) — free $200 credit
- [Groq account](https://console.groq.com) — free tier
- A public URL for your server (Cloudflare Tunnel or ngrok for local dev, or any cloud host)

---

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/call-agent.git
cd call-agent
```

### 2. Create your `.env` file

```bash
cp .env.example .env
```

Open `.env` and fill in your API keys (see [Environment Variables](#environment-variables)).

### 3. Start the server

```bash
docker compose up --build
```

Verify it's running:

```bash
curl http://localhost:5050
# → {"status":"Cloud Calling Agent is Online","active_skill":"personal_assistant"}
```

### 4. Expose your server publicly (local dev)

Choose **one** of the two options below:

#### Option A — Cloudflare Tunnel (recommended, no account needed)

```bash
# macOS (Intel)
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz | tar xz
./cloudflared tunnel --url http://localhost:5050
```

Copy the `https://xxxx.trycloudflare.com` URL it prints.

> **Note:** If your corporate network blocks port 7844, Cloudflare will fail with error 1033. Switch to a mobile hotspot or use Option B.

#### Option B — ngrok (requires free account)

1. Sign up at [ngrok.com](https://ngrok.com) and grab your auth token from the dashboard.
2. Install ngrok:

```bash
# macOS
brew install ngrok
# or download from https://ngrok.com/download
```

3. Authenticate once:

```bash
ngrok config add-authtoken YOUR_NGROK_AUTH_TOKEN
```

4. Start the tunnel:

```bash
ngrok http 5050
```

Copy the `https://xxxx.ngrok-free.app` URL it prints.

> **Note:** If you are on a corporate/restricted network and get a TLS/cert error, switch to a mobile hotspot — both tunnel tools require unrestricted outbound HTTPS.

### 5. Configure Plivo

1. Go to [console.plivo.com](https://console.plivo.com) → **Phone Numbers** → your number
2. Set **Answer URL** to your tunnel URL + `/incoming-call` (e.g. `https://xxxx.trycloudflare.com/incoming-call`)
3. Method: `POST` → **Save**

### 6. Test it

Call your Plivo number — the AI will answer. Watch the logs in real time:

```bash
docker compose logs -f
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in all required values.

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | Yes (if using Groq) | [console.groq.com](https://console.groq.com) — free |
| `DEEPGRAM_API_KEY` | Yes | [console.deepgram.com](https://console.deepgram.com) — free $200 credit |
| `GEMINI_API_KEY` | Only if skill uses Gemini | [aistudio.google.com](https://aistudio.google.com/apikey) — free |
| `PLIVO_AUTH_ID` | Yes for outbound calls | Plivo console → API credentials |
| `PLIVO_AUTH_TOKEN` | Yes for outbound calls | Plivo console → API credentials |
| `PLIVO_NUMBER` | Yes for outbound calls | Your Plivo phone number e.g. `+12183079774` |
| `SERVER_URL` | Yes for outbound calls | Your public URL e.g. `https://xxxx.trycloudflare.com` |
| `NOTES_WEBHOOK_URL` | No | POST call summaries here (Zapier, Make, custom endpoint) |
| `ACTIVE_SKILL` | No | Default skill to load on startup (default: `personal_assistant`) |
| `CLIENTS_FILE` | No | Path to clients JSON file (default: `clients.json`) |
| `PORT` | No | Server port (default: `5050`) |

---

## Skills System

Skills define the agent's personality, purpose, and which LLM to use. Each skill is a single Python file in the `skills/` directory.

### Switching skills at runtime

```bash
# See all available skills
curl http://localhost:5050/skills

# Switch to receptionist
curl -X POST http://localhost:5050/switch-skill \
  -H "Content-Type: application/json" \
  -d '{"skill": "receptionist"}'
```

No server restart needed — the next call uses the new skill.

### Creating a custom skill

Create `skills/my_skill.py`:

```python
SKILL_NAME = "my_skill"
DESCRIPTION = "Brief description of what this skill does"

SYSTEM_PROMPT = """
You are a helpful AI agent.
Keep responses to 1-2 sentences — this is a phone call.
"""

# For outbound calls — use {placeholders} from clients.json fields
OUTBOUND_SYSTEM_PROMPT = """
You are calling {name} from {company}.
They are interested in {interest}. Notes: {notes}. Last contact: {last_contact}.
Introduce yourself and ask if they'd like to discuss further.
"""

# LLM provider: "groq" or "gemini"
LLM_PROVIDER = "groq"

# Model name (None = use provider default)
LLM_MODEL = "llama-3.3-70b-versatile"

# Deepgram TTS voice — see https://developers.deepgram.com/docs/tts-models
VOICE = "aura-asteria-en"
```

The skill is automatically available — no other code changes needed.

### Available Deepgram voices

| Voice | Style |
|---|---|
| `aura-asteria-en` | Friendly, conversational (default) |
| `aura-luna-en` | Soft, professional |
| `aura-orion-en` | Deep, authoritative |
| `aura-stella-en` | Warm, energetic |

---

## Outbound Calling

### 1. Add clients to `clients.json`

```json
[
  {
    "id": "1",
    "name": "Rahul Sharma",
    "phone": "+919876543210",
    "company": "Sharma Enterprises",
    "interest": "cloud software solutions",
    "last_contact": "2026-05-15",
    "notes": "Met at a conference. Interested in automating billing.",
    "skill": "personal_assistant"
  },
  {
    "id": "2",
    "name": "Priya Nair",
    "phone": "+919876500000",
    "company": "Nair & Co",
    "interest": "HR automation",
    "last_contact": "2026-06-01",
    "notes": "Warm lead from LinkedIn.",
    "skill": "receptionist"
  }
]
```

The `"skill"` field is optional. When set, the agent automatically switches to that skill when the call connects. If omitted or the skill file doesn't exist, the server falls back to the default `ACTIVE_SKILL`.

> `clients.json` is gitignored — your lead data stays private.

### 2. Add Plivo and server config to `.env`

```
PLIVO_AUTH_ID=your_auth_id
PLIVO_AUTH_TOKEN=your_auth_token
PLIVO_NUMBER=+12183079774
SERVER_URL=https://your-tunnel.trycloudflare.com
```

### 3. Run the caller

```bash
# Preview without making calls
python3 outbound_caller.py --dry-run

# Call a specific client by ID
python3 outbound_caller.py --id 1

# Call all clients
python3 outbound_caller.py
```

The agent will call each number, and when the client picks up, it uses their personal context (name, company, interest, notes) to conduct a relevant conversation.

---

## Call Notes

After every call (inbound or outbound), a JSON file is automatically saved to `call_notes/`:

```
call_notes/
└── 2026-06-09_14-32-01_rahul_sharma.json
```

Each file contains:

```json
{
  "date": "2026-06-09 14:32:01",
  "summary": "Rahul called about cloud billing automation. He is interested in scheduling a follow-up call.",
  "metadata": {
    "type": "outbound",
    "client_id": "1",
    "client_name": "Rahul Sharma",
    "company": "Sharma Enterprises",
    "interest": "cloud software solutions",
    "skill": "personal_assistant"
  },
  "transcript": [
    {"time": "14:32:05", "speaker": "Agent", "text": "Hi, am I speaking with Rahul? Great! I'm calling on behalf of Anirudh..."},
    {"time": "14:32:10", "speaker": "Caller", "text": "Yes, I've been meaning to follow up actually."}
  ]
}
```

Optionally set `NOTES_WEBHOOK_URL` in `.env` to also POST each note to a webhook (Zapier, Make, your own endpoint).

> `call_notes/` is gitignored — your conversation data stays private.

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Health check + active skill |
| `GET` | `/skills` | List all skills and the active one |
| `POST` | `/switch-skill` | Switch active skill `{"skill": "name"}` |
| `GET` | `/clients` | List all clients from `clients.json` |
| `POST` | `/incoming-call` | Plivo webhook — answer inbound calls |
| `POST` | `/outbound-call` | Plivo webhook — answer outbound calls |
| `WS` | `/media-stream` | WebSocket — real-time audio pipeline |

---

## Deployment

### Docker Compose (local / VPS)

```bash
docker compose up --build -d    # run in background
docker compose logs -f          # tail logs
docker compose down             # stop
```

### Oracle Cloud Always Free (recommended for 24/7)

1. Create a free VM at [cloud.oracle.com](https://cloud.oracle.com) (4 ARM cores, 24GB RAM — forever free)
2. SSH into the VM, install Docker, clone this repo
3. Fill in `.env`, run `docker compose up -d`
4. Open port 5050 in Oracle's security group rules
5. Point your Plivo webhook to `http://YOUR_VM_IP:5050/incoming-call`

### Render / Fly.io

The `render.yaml` is included. Connect your GitHub repo on [render.com](https://render.com), set env vars in the dashboard, and deploy. Note: free tiers on most platforms now require a credit card.

---

## Troubleshooting

### Agent answers but says nothing
- Check `[TTS]` logs — Deepgram TTS may be failing. Verify `DEEPGRAM_API_KEY`.
- Check audio bytes: `[TTS] Audio generated (0.3s, 0 bytes)` means TTS returned empty — usually a bad API key or exhausted credits.

### Call connects but AI doesn't respond to speech
- Check `[STT]` logs — Deepgram WebSocket may not be connecting.
- Ensure audio is flowing: look for `[CALL] Stream started` in logs.
- Try speaking clearly after 1-2 seconds of silence.

### Cloudflare tunnel error 1033
- Your network is blocking port 7844. Switch to a mobile hotspot, or use ngrok instead (Option B in Quick Start).

### ngrok TLS / CRL error
- `failed to fetch CRL` means your network is blocking ngrok's auth servers. Switch to a mobile hotspot.

### Groq error: model not found
- The model `llama3-70b-8192` is deprecated. Use `llama-3.3-70b-versatile` (already set as default in skill files).

### Outbound call not connecting
- Verify `PLIVO_AUTH_ID`, `PLIVO_AUTH_TOKEN`, and `PLIVO_NUMBER` are set in `.env`.
- Verify `SERVER_URL` is publicly reachable: `curl $SERVER_URL` should return a JSON response.
- Check Plivo console → Call Logs for error details.

### Docker not starting
- Make sure Docker Desktop is running on your Mac.
- Run `docker compose up --build` (not just `up`) after code changes.
