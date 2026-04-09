import os
import subprocess
import ollama
from faster_whisper import WhisperModel
from loguru import logger

class LocalBrain:
    def __init__(self, model_size="base"):
        logger.info(f"Initializing Whisper model: {model_size}")
        # Use CPU for whisper for maximum compatibility, can be changed to 'cuda' or 'auto'
        self.stt_model = WhisperModel(model_size, device="cpu", compute_type="int8")
        
        self.ollama_model = "llama3" # Make sure user has run `ollama pull llama3`
        
        self.system_prompt = """
        You are a helpful AI assistant for Anirudh. 
        You are answering a phone call. 
        Be concise, professional, and friendly. 
        If the user wants to leave a message, say you will take a note of it.
        """

    def transcribe(self, audio_path):
        """Transcribe an audio file to text."""
        segments, info = self.stt_model.transcribe(audio_path, beam_size=5)
        text = " ".join([segment.text for segment in segments])
        return text.strip()

    def generate_response(self, user_text):
        """Generate a response using Ollama."""
        try:
            response = ollama.chat(model=self.ollama_model, messages=[
                {'role': 'system', 'content': self.system_prompt},
                {'role': 'user', 'content': user_text},
            ])
            return response['message']['content']
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            return "I'm sorry, my brain is a bit slow right now. Can you repeat that?"

    def speak(self, text):
        """Use macOS 'say' command for zero-cost TTS."""
        logger.info(f"Speaking: {text}")
        try:
            # -v Samantha is a high-quality voice on macOS
            subprocess.run(["say", "-v", "Samantha", text])
        except Exception as e:
            logger.error(f"TTS error: {e}")
            print(f"AGENT: {text}")

if __name__ == "__main__":
    # Test
    brain = LocalBrain()
    print(brain.generate_response("Hello, who are you?"))
    brain.speak("Hello! I am your free calling agent.")
