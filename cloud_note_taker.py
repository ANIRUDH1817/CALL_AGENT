import httpx
import json
import os
from datetime import datetime
from loguru import logger

NOTES_DIR = os.path.join(os.path.dirname(__file__), "call_notes")


class CloudNoteTaker:
    def __init__(self):
        self.webhook_url = os.getenv("NOTES_WEBHOOK_URL")
        self.current_transcript = []
        os.makedirs(NOTES_DIR, exist_ok=True)

    def add_line(self, speaker, text):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.current_transcript.append({"time": timestamp, "speaker": speaker, "text": text})

    def save_local(self, summary_text: str, metadata: dict = None):
        """Save transcript + summary as a JSON file in call_notes/."""
        date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        client_name = (metadata or {}).get("client_name", "unknown")
        safe_name = client_name.replace(" ", "_").lower()
        filename = f"{date_str}_{safe_name}.json"
        filepath = os.path.join(NOTES_DIR, filename)

        data = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "summary": summary_text,
            "metadata": metadata or {},
            "transcript": self.current_transcript,
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        logger.info(f"[NOTES] Saved call notes → {filepath}")
        return filepath

    async def send_summary(self, summary_text: str, metadata: dict = None):
        """Save locally and optionally POST to a webhook."""
        self.save_local(summary_text, metadata)

        if not self.webhook_url:
            logger.info("[NOTES] No NOTES_WEBHOOK_URL set — skipping webhook.")
            return True

        data = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "summary": summary_text,
            "metadata": metadata or {},
            "transcript": self.current_transcript,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(self.webhook_url, json=data)
                if response.status_code in [200, 201]:
                    logger.info("[NOTES] Successfully sent call note to webhook.")
                    return True
                else:
                    logger.error(f"[NOTES] Webhook error ({response.status_code}): {response.text}")
                    return False
        except Exception as e:
            logger.error(f"[NOTES] Error sending to webhook: {e}")
            return False

    def clear(self):
        self.current_transcript = []
