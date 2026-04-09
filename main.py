import os
import json
import base64
import asyncio
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from twilio.twiml.voice_response import VoiceResponse, Connect
from dotenv import load_dotenv
import websockets
from loguru import logger

from agent_config import SYSTEM_PROMPT, VOICE, MODEL, TOOLS

load_dotenv()

# Environment variables
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
PORT = int(os.getenv('PORT', 5050))

app = FastAPI()

if not OPENAI_API_KEY:
    logger.error("Missing OPENAI_API_KEY in environment variables")

@app.get("/", response_class=HTMLResponse)
async def index_page():
    return {"message": "Twilio Media Stream Server is running!"}

@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    """Handle incoming call from Twilio and connect to media stream."""
    response = VoiceResponse()
    # <Say> is optional, we can just connect the stream immediately
    # response.say("Please wait while I connect you to the AI assistant.")
    host = request.url.hostname
    connect = Connect()
    connect.stream(url=f'wss://{host}/media-stream')
    response.append(connect)
    return Response(content=str(response), media_type="text/xml")

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """Handle WebSocket connection between Twilio and OpenAI."""
    logger.info("New connection to media-stream")
    await websocket.accept()

    async with websockets.connect(
        f"wss://api.openai.com/v1/realtime?model={MODEL}",
        extra_headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=2024-10-01"
        }
    ) as openai_ws:
        
        # Initial Handshake: Send session update
        await initialize_session(openai_ws)

        stream_sid = None

        async def receive_from_twilio():
            """Receive audio data from Twilio and send it to OpenAI."""
            nonlocal stream_sid
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    if data['event'] == 'media' and openai_ws.open:
                        audio_payload = data['media']['payload']
                        audio_append = {
                            "type": "input_audio_buffer.append",
                            "audio": audio_payload
                        }
                        await openai_ws.send(json.dumps(audio_append))
                    elif data['event'] == 'start':
                        stream_sid = data['start']['streamSid']
                        logger.info(f"Incoming stream started: {stream_sid}")
            except WebSocketDisconnect:
                logger.info("Twilio WebSocket disconnected")
                if openai_ws.open:
                    await openai_ws.close()

        async def send_to_twilio():
            """Receive response from OpenAI and send audio back to Twilio."""
            nonlocal stream_sid
            try:
                async for message in openai_ws:
                    response = json.loads(message)
                    
                    if response["type"] == "response.audio.delta" and response.get("delta"):
                        try:
                            audio_payload = response["delta"]
                            await websocket.send_text(json.dumps({
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {"payload": audio_payload}
                            }))
                        except Exception as e:
                            logger.error(f"Error sending audio: {e}")

                    # Handle interruptions: when user starts speaking, clear the buffer
                    if response["type"] == "input_audio_buffer.speech_started":
                        logger.info("Speech started, clearing Twilio buffer")
                        await websocket.send_text(json.dumps({
                            "streamSid": stream_sid,
                            "event": "clear"
                        }))

            except Exception as e:
                logger.error(f"Error in OpenAI transmission: {e}")

        await asyncio.gather(receive_from_twilio(), send_to_twilio())

async def initialize_session(openai_ws):
    """Send initial configuration to OpenAI session."""
    session_update = {
        "type": "session.update",
        "session": {
            "instructions": SYSTEM_PROMPT,
            "voice": VOICE,
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "modalities": ["text", "audio"],
            "temperature": 0.8,
            # "tools": TOOLS  # Add this if you want to support tool calling
        }
    }
    logger.info("Sending session update to OpenAI")
    await openai_ws.send(json.dumps(session_update))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
