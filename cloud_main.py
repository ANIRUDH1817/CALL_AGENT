import os
import json
import base64
import asyncio
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Connect
from dotenv import load_dotenv
import httpx
import websockets
from loguru import logger
from groq import AsyncGroq
from cloud_note_taker import CloudNoteTaker

load_dotenv()

# API Keys
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
DEEPGRAM_API_KEY = os.getenv('DEEPGRAM_API_KEY')
PORT = int(os.getenv('PORT', 5050))

if not GROQ_API_KEY:
    logger.error("Missing GROQ_API_KEY in environment variables!")
if not DEEPGRAM_API_KEY:
    logger.error("Missing DEEPGRAM_API_KEY in environment variables!")

app = FastAPI()
groq_client = None

@app.on_event("startup")
async def startup():
    global groq_client
    if GROQ_API_KEY:
        groq_client = AsyncGroq(api_key=GROQ_API_KEY)
        logger.info("Groq client initialized")
    else:
        logger.error("Cannot start: GROQ_API_KEY is missing!")

SYSTEM_PROMPT = """
You are a helpful AI calling assistant for Anirudh.
Your goal is to answer the phone and help the caller.
Keep your responses short and conversational — ideally 1-2 sentences.
If someone wants to leave a message, confirm you will pass it along.
If someone asks for Anirudh, say he is currently unavailable but you can help or take a message.
"""

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
    return {"status": "Cloud Calling Agent is Online"}


@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    """Handle incoming call from Twilio and return TwiML to start a media stream."""
    response = VoiceResponse()
    host = request.url.hostname
    connect = Connect()
    connect.stream(url=f'wss://{host}/media-stream')
    response.append(connect)
    return Response(content=str(response), media_type="text/xml")


@app.websocket("/media-stream")
async def handle_media_stream(twilio_ws: WebSocket):
    """Handle WebSocket connection between Twilio and AI (Deepgram STT + Groq LLM + Deepgram TTS)."""
    await twilio_ws.accept()
    logger.info("Twilio connected to /media-stream")

    stream_sid = None
    note_taker = CloudNoteTaker()  # Per-call instance
    conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Connect to Deepgram for real-time STT
    deepgram_ws = await websockets.connect(
        DEEPGRAM_WS_URL,
        extra_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"}
    )

    async def receive_from_twilio():
        """Forward audio from Twilio → Deepgram for transcription."""
        nonlocal stream_sid
        try:
            async for message in twilio_ws.iter_text():
                data = json.loads(message)
                if data['event'] == 'start':
                    stream_sid = data['start']['streamSid']
                    logger.info(f"Stream started: {stream_sid}")
                elif data['event'] == 'media':
                    # Decode Twilio's base64 audio and send raw bytes to Deepgram
                    audio_bytes = base64.b64decode(data['media']['payload'])
                    await deepgram_ws.send(audio_bytes)
                elif data['event'] == 'stop':
                    logger.info("Stream stopped by Twilio")
                    # Close Deepgram gracefully
                    await deepgram_ws.send(json.dumps({"type": "CloseStream"}))
        except WebSocketDisconnect:
            logger.info("Twilio WebSocket disconnected")
        except Exception as e:
            logger.error(f"Error receiving from Twilio: {e}")

    async def receive_from_deepgram():
        """Receive transcriptions from Deepgram, generate AI response, and send audio back to Twilio."""
        nonlocal stream_sid
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

                    logger.info(f"Caller: {transcript}")
                    note_taker.add_line("Caller", transcript)

                    # Add to conversation history
                    conversation_history.append({"role": "user", "content": transcript})

                    # Generate AI response via Groq
                    ai_response = await get_groq_response(conversation_history)
                    logger.info(f"Agent: {ai_response}")

                    conversation_history.append({"role": "assistant", "content": ai_response})
                    note_taker.add_line("Agent", ai_response)

                    # Convert AI response to mulaw audio via Deepgram TTS
                    audio_data = await get_deepgram_tts(ai_response)

                    if audio_data and stream_sid:
                        # Send audio back to Twilio
                        audio_b64 = base64.b64encode(audio_data).decode('utf-8')
                        await twilio_ws.send_text(json.dumps({
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": audio_b64}
                        }))
                        # Mark so we know when playback finishes
                        await twilio_ws.send_text(json.dumps({
                            "event": "mark",
                            "streamSid": stream_sid,
                            "mark": {"name": f"response_{len(conversation_history)}"}
                        }))

        except websockets.exceptions.ConnectionClosed:
            logger.info("Deepgram connection closed")
        except Exception as e:
            logger.error(f"Error receiving from Deepgram: {e}")

    try:
        await asyncio.gather(receive_from_twilio(), receive_from_deepgram())
    finally:
        # Cleanup
        if not deepgram_ws.closed:
            await deepgram_ws.close()
        # Generate and send call summary
        await finalize_call(note_taker, conversation_history)


async def get_groq_response(conversation_history):
    """Use Groq (async) to get a fast AI response."""
    try:
        chat_completion = await groq_client.chat.completions.create(
            messages=conversation_history,
            model="llama3-70b-8192",
            temperature=0.5,
            max_tokens=150,
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return "I'm sorry, I'm having trouble right now. Could you repeat that?"


async def get_deepgram_tts(text):
    """Convert text to Mulaw audio via Deepgram's TTS REST API."""
    url = "https://api.deepgram.com/v1/speak"
    params = {
        "model": "aura-asteria-en",
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
                logger.error(f"Deepgram TTS error ({response.status_code}): {response.text}")
                return b""
    except httpx.TimeoutException:
        logger.error("Deepgram TTS timed out")
        return b""
    except Exception as e:
        logger.error(f"Deepgram TTS exception: {e}")
        return b""


async def finalize_call(note_taker, conversation_history):
    """Generate a summary and send it after the call ends."""
    if len(note_taker.current_transcript) == 0:
        logger.info("No transcript to summarize (empty call).")
        return

    try:
        summary_messages = conversation_history + [
            {"role": "user", "content": "Please summarize this entire phone call in 2-3 sentences. Focus on who called, what they wanted, and any action items."}
        ]
        summary = await get_groq_response(summary_messages)
        logger.info(f"Call Summary: {summary}")
        await note_taker.send_summary(summary)
    except Exception as e:
        logger.error(f"Error during call finalization: {e}")
    finally:
        note_taker.clear()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
