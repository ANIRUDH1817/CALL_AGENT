import os
import json
import base64
import asyncio
import importlib
import time
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from plivo import plivoxml
from dotenv import load_dotenv
import httpx
import websockets
from loguru import logger
from llm_client import LLMClient
from cloud_note_taker import CloudNoteTaker

load_dotenv()

# API Keys
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
DEEPGRAM_API_KEY = os.getenv('DEEPGRAM_API_KEY')
PORT = int(os.getenv('PORT', 5050))

if not GROQ_API_KEY and not os.getenv("GEMINI_API_KEY"):
    logger.error("[STARTUP] Neither GROQ_API_KEY nor GEMINI_API_KEY found — LLM will fail!")
if not DEEPGRAM_API_KEY:
    logger.error("[STARTUP] DEEPGRAM_API_KEY is missing — STT and TTS will fail!")

# In-memory store: callId → client dict (populated when outbound call is answered)
pending_call_clients: dict = {}


def load_clients() -> list:
    """Load clients from clients.json if it exists."""
    path = os.path.join(os.path.dirname(__file__), "clients.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)

# ---------------------------------------------------------------------------
# Skill Manager — loads prompt/voice/model config from the skills/ directory
# ---------------------------------------------------------------------------

class SkillManager:
    def __init__(self):
        self._module = None
        self.skill_name = None
        self._llm_client = None
        default = os.getenv("ACTIVE_SKILL", "personal_assistant")
        self.load(default)

    def load(self, skill_name: str):
        """Load a skill by name from the skills/ package."""
        try:
            self._module = importlib.import_module(f"skills.{skill_name}")
            self.skill_name = skill_name
            self._llm_client = None  # Reset so it's recreated with new skill settings
            logger.info(f"[SKILL] Loaded: {skill_name} (LLM: {self.llm_provider})")
        except ModuleNotFoundError:
            logger.error(f"[SKILL] '{skill_name}' not found — keeping current skill.")
            raise

    def list_skills(self):
        """Return all available skill names from the skills/ directory."""
        skills_dir = os.path.join(os.path.dirname(__file__), "skills")
        return sorted(
            os.path.splitext(f)[0]
            for f in os.listdir(skills_dir)
            if f.endswith(".py") and not f.startswith("_")
        )

    @property
    def system_prompt(self):
        return self._module.SYSTEM_PROMPT

    @property
    def voice(self):
        return getattr(self._module, "VOICE", "aura-asteria-en")

    @property
    def groq_model(self):
        return getattr(self._module, "GROQ_MODEL", "llama-3.3-70b-versatile")

    @property
    def llm_provider(self):
        return getattr(self._module, "LLM_PROVIDER", "groq")

    @property
    def llm_model(self):
        return getattr(self._module, "LLM_MODEL", None)

    @property
    def llm_client(self) -> LLMClient:
        """Lazy-init LLMClient — recreated when skill changes."""
        if self._llm_client is None:
            self._llm_client = LLMClient(
                provider=self.llm_provider,
                model=self.llm_model,
            )
        return self._llm_client

    @property
    def description(self):
        return getattr(self._module, "DESCRIPTION", "")


skill_manager = SkillManager()

app = FastAPI()

@app.on_event("startup")
async def startup():
    logger.info("[STARTUP] Initializing modules...")
    # Eagerly initialize LLM client to catch config errors early
    try:
        _ = skill_manager.llm_client
        logger.info(f"[STARTUP] ✓ LLM ready ({skill_manager.llm_provider} / {skill_manager.llm_client.model})")
    except Exception as e:
        logger.error(f"[STARTUP] ✗ LLM init failed: {e}")

    if DEEPGRAM_API_KEY:
        logger.info("[STARTUP] ✓ Deepgram API key found (STT + TTS ready)")
    else:
        logger.error("[STARTUP] ✗ Deepgram API key missing — calls will fail")

    logger.info(f"[STARTUP] Active skill: {skill_manager.skill_name}")
    logger.info("[STARTUP] Server ready.")

DEEPGRAM_WS_URL = (
    "wss://api.deepgram.com/v1/listen"
    "?model=nova-2-phonecall"
    "&encoding=mulaw"
    "&sample_rate=8000"
    "&channels=1"
    "&interim_results=false"
    "&endpointing=300"
)


@app.get("/")
async def root():
    return {"status": "Cloud Calling Agent is Online", "active_skill": skill_manager.skill_name}


@app.get("/skills")
async def list_skills():
    """List all available skills and the currently active one."""
    return {
        "active": skill_manager.skill_name,
        "description": skill_manager.description,
        "available": skill_manager.list_skills(),
    }


@app.post("/switch-skill")
async def switch_skill(request: Request):
    """Switch the active skill. Body: {"skill": "skill_name"}"""
    body = await request.json()
    skill_name = body.get("skill")
    if not skill_name:
        return {"error": "Missing 'skill' field in request body"}
    try:
        skill_manager.load(skill_name)
        return {"status": "switched", "active": skill_manager.skill_name, "description": skill_manager.description}
    except ModuleNotFoundError:
        return {"error": f"Skill '{skill_name}' not found", "available": skill_manager.list_skills()}


@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    """Handle incoming call from Plivo and return PlivoXML to start a bidirectional media stream."""
    host = request.url.hostname
    response = plivoxml.ResponseElement()
    response.add(
        plivoxml.StreamElement(
            f"wss://{host}/media-stream",
            bidirectional=True,
            keepCallAlive=True,
            contentType="audio/x-mulaw;rate=8000",
        )
    )
    logger.info(f"[CALL] Incoming call — streaming to wss://{host}/media-stream")
    return Response(content=response.to_string(), media_type="application/xml")


@app.api_route("/outbound-call", methods=["GET", "POST"])
async def handle_outbound_call(request: Request):
    """
    Answer URL for outbound calls. Called by Plivo when the client picks up.
    Reads client_id from query params, stores client context, returns Stream XML.
    """
    client_id = request.query_params.get("client_id")
    call_id   = (await request.form()).get("CallUUID") or request.query_params.get("CallUUID")

    client_info = None
    if client_id:
        clients = load_clients()
        client_info = next((c for c in clients if str(c.get("id")) == str(client_id)), None)

    if client_info and call_id:
        pending_call_clients[call_id] = client_info
        logger.info(f"[OUTBOUND] Call answered — client: {client_info.get('name')} (id={client_id}, callId={call_id}, skill={client_info.get('skill', 'default')})")
    else:
        logger.warning(f"[OUTBOUND] Answer URL hit but client_id={client_id} or call_id={call_id} missing")

    host = request.url.hostname
    response = plivoxml.ResponseElement()
    response.add(
        plivoxml.StreamElement(
            f"wss://{host}/media-stream",
            bidirectional=True,
            keepCallAlive=True,
            contentType="audio/x-mulaw;rate=8000",
        )
    )
    return Response(content=response.to_string(), media_type="application/xml")


@app.get("/clients")
async def list_clients():
    """List all clients from clients.json."""
    clients = load_clients()
    return {"total": len(clients), "clients": clients}


@app.websocket("/media-stream")
async def handle_media_stream(plivo_ws: WebSocket):
    """Handle WebSocket connection between Plivo and AI (Deepgram STT + LLM + Deepgram TTS)."""
    await plivo_ws.accept()
    logger.info("[CALL] New call connected")

    stream_id = None
    call_metadata = {}  # Populated on stream start with client info + skill
    note_taker = CloudNoteTaker()  # Per-call instance
    conversation_history = []  # Will be initialized once we know call context (inbound vs outbound)

    # Connect to Deepgram for real-time STT
    logger.info("[STT] Connecting to Deepgram...")
    deepgram_ws = await websockets.connect(
        DEEPGRAM_WS_URL,
        extra_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"}
    )
    logger.info("[STT] Deepgram connected")

    async def receive_from_plivo():
        """Forward audio from Plivo → Deepgram for transcription."""
        nonlocal stream_id, call_metadata
        try:
            async for message in plivo_ws.iter_text():
                data = json.loads(message)
                if data['event'] == 'start':
                    stream_id = data['start']['streamId']
                    call_id = data['start']['callId']
                    logger.info(f"[CALL] Stream started — streamId: {stream_id}, callId: {call_id}")

                    # Check if this is an outbound call with client context
                    client_info = pending_call_clients.pop(call_id, None)
                    if client_info:
                        # Load the skill specified for this client (fallback to active skill)
                        client_skill = client_info.get("skill")
                        if client_skill and client_skill != skill_manager.skill_name:
                            try:
                                skill_manager.load(client_skill)
                                logger.info(f"[SKILL] Switched to client skill: {client_skill}")
                            except ModuleNotFoundError:
                                logger.warning(f"[SKILL] Client skill '{client_skill}' not found — using active skill: {skill_manager.skill_name}")
                        system_prompt = build_outbound_prompt(client_info)
                        call_metadata = {
                            "type": "outbound",
                            "client_id": client_info.get("id"),
                            "client_name": client_info.get("name"),
                            "company": client_info.get("company"),
                            "interest": client_info.get("interest"),
                            "skill": skill_manager.skill_name,
                        }
                        logger.info(f"[CALL] Outbound call — client: {client_info.get('name')} | skill: {skill_manager.skill_name}")
                    else:
                        system_prompt = skill_manager.system_prompt
                        call_metadata = {"type": "inbound", "skill": skill_manager.skill_name}
                        logger.info("[CALL] Inbound call — using default skill prompt")

                    conversation_history.append({"role": "system", "content": system_prompt})
                elif data['event'] == 'media':
                    audio_bytes = base64.b64decode(data['media']['payload'])
                    await deepgram_ws.send(audio_bytes)
                elif data['event'] == 'stop':
                    logger.info("[CALL] Stream stopped by Plivo")
                    await deepgram_ws.send(json.dumps({"type": "CloseStream"}))
        except WebSocketDisconnect:
            logger.info("[CALL] Plivo WebSocket disconnected")
        except Exception as e:
            logger.error(f"[CALL] Error receiving from Plivo: {e}")

    async def receive_from_deepgram():
        """Receive transcriptions from Deepgram, generate AI response, and send audio back to Plivo."""
        nonlocal stream_id
        try:
            async for message in deepgram_ws:
                data = json.loads(message)

                # Only process final transcription results
                if data.get("type") == "Results":
                    transcript = (
                        data.get("channel", {})
                        .get("alternatives", [{}])[0]
                        .get("transcript", "")
                    )

                    if not transcript or len(transcript.strip()) < 2:
                        continue

                    is_final = data.get("is_final", False)
                    if not is_final:
                        continue

                    logger.info(f"[STT] Caller: {transcript}")
                    note_taker.add_line("Caller", transcript)

                    conversation_history.append({"role": "user", "content": transcript})

                    # Generate AI response via LLM
                    t0 = time.time()
                    ai_response = await get_llm_response(conversation_history)
                    logger.info(f"[LLM] Response ({time.time()-t0:.2f}s): {ai_response}")

                    conversation_history.append({"role": "assistant", "content": ai_response})
                    note_taker.add_line("Agent", ai_response)

                    # Convert AI response to mulaw audio via Deepgram TTS
                    t1 = time.time()
                    audio_data = await get_deepgram_tts(ai_response)
                    logger.info(f"[TTS] Audio generated ({time.time()-t1:.2f}s, {len(audio_data)} bytes)")

                    if audio_data and stream_id:
                        # Clear any queued audio first (handles interruptions)
                        await plivo_ws.send_text(json.dumps({
                            "event": "clearAudio",
                            "streamId": stream_id
                        }))
                        # Send audio back to Plivo
                        audio_b64 = base64.b64encode(audio_data).decode('utf-8')
                        await plivo_ws.send_text(json.dumps({
                            "event": "playAudio",
                            "media": {
                                "contentType": "audio/x-mulaw",
                                "sampleRate": 8000,
                                "payload": audio_b64
                            }
                        }))
                        # Checkpoint to track when playback finishes
                        await plivo_ws.send_text(json.dumps({
                            "event": "checkpoint",
                            "streamId": stream_id,
                            "name": f"response_{len(conversation_history)}"
                        }))

        except websockets.exceptions.ConnectionClosed:
            logger.info("[STT] Deepgram connection closed")
        except Exception as e:
            logger.error(f"[STT] Error receiving from Deepgram: {e}")

    try:
        await asyncio.gather(receive_from_plivo(), receive_from_deepgram())
    finally:
        if not deepgram_ws.closed:
            await deepgram_ws.close()
        logger.info("[CALL] Call ended — generating summary")
        await finalize_call(note_taker, conversation_history, call_metadata)


def build_outbound_prompt(client: dict) -> str:
    """Build a personalized system prompt for an outbound call using client data."""
    base = getattr(
        skill_manager._module,
        "OUTBOUND_SYSTEM_PROMPT",
        skill_manager.system_prompt
    )
    last_contact = client.get("last_contact") or "no previous contact"
    return base.format(
        name=client.get("name", "the client"),
        company=client.get("company", "their company"),
        interest=client.get("interest", "our services"),
        last_contact=last_contact,
        notes=client.get("notes", ""),
    )


async def get_llm_response(conversation_history):
    """Get AI response using the active skill's LLM provider."""
    try:
        return await skill_manager.llm_client.chat(conversation_history)
    except Exception as e:
        logger.error(f"[LLM] Error: {e}")
        return "I'm sorry, I'm having trouble right now. Could you repeat that?"


async def get_deepgram_tts(text):
    """Convert text to Mulaw audio via Deepgram's TTS REST API."""
    logger.info(f"[TTS] Converting: {text[:60]}...")
    url = "https://api.deepgram.com/v1/speak"
    params = {
        "model": skill_manager.voice,
        "encoding": "mulaw",
        "sample_rate": "8000",
    }
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {"text": text}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, headers=headers, json=payload, params=params)
            if response.status_code == 200:
                return response.content
            else:
                logger.error(f"[TTS] Deepgram error ({response.status_code}): {response.text}")
                return b""
    except httpx.TimeoutException:
        logger.error("[TTS] Deepgram TTS timed out")
        return b""
    except Exception as e:
        logger.error(f"[TTS] Exception: {e}")
        return b""


async def finalize_call(note_taker, conversation_history, metadata: dict = None):
    """Generate a summary, save JSON, and optionally POST to webhook after the call ends."""
    if len(note_taker.current_transcript) == 0:
        logger.info("[NOTES] No transcript to summarize (empty call).")
        return

    try:
        summary_messages = conversation_history + [
            {"role": "user", "content": "Please summarize this entire phone call in 2-3 sentences. Focus on who called, what they wanted, and any action items."}
        ]
        summary = await get_llm_response(summary_messages)
        logger.info(f"[NOTES] Call Summary: {summary}")
        await note_taker.send_summary(summary, metadata=metadata)
    except Exception as e:
        logger.error(f"[NOTES] Error during call finalization: {e}")
    finally:
        note_taker.clear()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
