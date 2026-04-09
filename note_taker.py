from datetime import datetime
import os
from loguru import logger

class NoteTaker:
    def __init__(self, notes_dir="notes"):
        self.notes_dir = notes_dir
        if not os.path.exists(self.notes_dir):
            os.makedirs(self.notes_dir)
        
        self.current_call_log = []

    def add_to_transcript(self, speaker, text):
        """Add a line to the current call transcript."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.current_call_log.append(f"[{timestamp}] {speaker}: {text}")

    def save_call_summary(self, summary_text):
        """Save a summary of the call to a markdown file."""
        date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"call_summary_{date_str}.md"
        filepath = os.path.join(self.notes_dir, filename)
        
        full_transcript = "\n".join(self.current_call_log)
        
        content = f"""# Call Summary - {date_str}

## Summary
{summary_text}

## Full Transcript
{full_transcript}
"""
        with open(filepath, "w") as f:
            f.write(content)
        
        logger.info(f"Call summary saved to {filepath}")
        return filepath

    def clear(self):
        """Clear the log for a new call."""
        self.current_call_log = []

if __name__ == "__main__":
    nt = NoteTaker()
    nt.add_to_transcript("Caller", "Hello, is Anirudh there?")
    nt.add_to_transcript("Agent", "He is busy right now, can I take a message?")
    nt.save_call_summary("Someone called asking for Anirudh.")
