import httpx
import json
import os
from datetime import datetime
from loguru import logger

class CloudNoteTaker:
    def __init__(self):
        # Users can set a webhook URL (e.g., from Zapier, Make, or a custom endpoint)
        self.webhook_url = os.getenv("NOTES_WEBHOOK_URL")
        self.current_transcript = []

    def add_line(self, speaker, text):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.current_transcript.append({"time": timestamp, "speaker": speaker, "text": text})

    async def send_summary(self, summary_text):
        """Send the transcript and summary to a persistent external service."""
        if not self.webhook_url:
            logger.warning("No NOTES_WEBHOOK_URL configured. Note will be lost when server restarts.")
            return False

        data = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "summary": summary_text,
            "transcript": self.current_transcript
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(self.webhook_url, json=data)
                if response.status_code in [200, 201]:
                    logger.info("Successfully sent call note to webhook.")
                    return True
                else:
                    logger.error(f"Failed to send note: {response.text}")
                    return False
        except Exception as e:
            logger.error(f"Error sending cloud note: {e}")
            return False

    def clear(self):
        self.current_transcript = []
