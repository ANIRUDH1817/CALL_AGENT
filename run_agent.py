import time
import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write
import os
from loguru import logger
from local_brain import LocalBrain
from note_taker import NoteTaker

# Configuration
CHANNELS = 1
RATE = 16000 # Whisper likes 16kHz
CHUNK_DURATION = 0.5 # seconds
SILENCE_THRESHOLD = 0.05 # Adjust based on noise level
SILENCE_WAIT = 2.0 # seconds of silence before we process

class VoiceAgent:
    def __init__(self):
        self.brain = LocalBrain()
        self.note_taker = NoteTaker()
        self.is_running = True
        self.audio_buffer = []
        self.last_speech_time = time.time()
        self.in_speech = False

    def audio_callback(self, indata, frames, time_info, status):
        """This is called for every audio chunk."""
        if status:
            logger.warning(status)
        
        # Calculate volume
        volume_norm = np.linalg.norm(indata) * 10
        
        if volume_norm > SILENCE_THRESHOLD:
            if not self.in_speech:
                logger.debug("Speech detected...")
                self.in_speech = True
            
            self.audio_buffer.append(indata.copy())
            self.last_speech_time = time.time()
        else:
            if self.in_speech:
                # We were in speech, now it's quiet
                if time.time() - self.last_speech_time > SILENCE_WAIT:
                    logger.debug("Silence threshold reached. Processing...")
                    self.in_speech = False
                    self.process_buffer()

    def process_buffer(self):
        """Transcribe and respond to the accumulated audio."""
        if not self.audio_buffer:
            return

        # Save buffer to temp file
        full_audio = np.concatenate(self.audio_buffer, axis=0)
        temp_wav = "temp_input.wav"
        write(temp_wav, RATE, full_audio)
        
        # 1. Transcribe
        user_text = self.brain.transcribe(temp_wav)
        logger.info(f"User: {user_text}")
        
        if len(user_text) < 2:
            self.audio_buffer = []
            return

        # 2. Add to logs
        self.note_taker.add_to_transcript("Caller", user_text)
        
        # 3. Generate Response
        agent_response = self.brain.generate_response(user_text)
        logger.info(f"Agent: {agent_response}")
        
        # 4. Add to logs
        self.note_taker.add_to_transcript("Agent", agent_response)
        
        # 5. Speak
        self.brain.speak(agent_response)
        
        # Clean up
        self.audio_buffer = []
        if os.path.exists(temp_wav):
            os.remove(temp_wav)

    def start(self):
        logger.info("Agent started. Listening for calls...")
        try:
            with sd.InputStream(callback=self.audio_callback, channels=CHANNELS, samplerate=RATE):
                while self.is_running:
                    time.sleep(0.1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        logger.info("Stopping agent and saving call notes...")
        self.is_running = False
        # Final summary
        summary = self.brain.generate_response("Please summarize the call transcript we just had.")
        self.note_taker.save_call_summary(summary)

if __name__ == "__main__":
    agent = VoiceAgent()
    agent.start()
