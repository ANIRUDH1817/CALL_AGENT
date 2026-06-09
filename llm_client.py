import os
import asyncio
from loguru import logger


class LLMClient:
    """
    Unified LLM client supporting Groq and Gemini.
    Configure per-skill by setting LLM_PROVIDER in the skill file.
    """

    def __init__(self, provider: str = "groq", model: str = None):
        self.provider = provider.lower()
        self.model = model
        self._groq_client = None
        self._genai = None

        if self.provider == "groq":
            self._init_groq()
        elif self.provider == "gemini":
            self._init_gemini()
        else:
            raise ValueError(f"[LLM] Unknown provider: '{provider}'. Use 'groq' or 'gemini'.")

    def _init_groq(self):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("[LLM] GROQ_API_KEY is missing from environment.")
        from groq import AsyncGroq
        self._groq_client = AsyncGroq(api_key=api_key)
        self.model = self.model or "llama-3.3-70b-versatile"
        logger.info(f"[LLM] Groq initialized — model: {self.model}")

    def _init_gemini(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("[LLM] GEMINI_API_KEY is missing from environment.")
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        self._genai = genai
        self.model = self.model or "gemini-2.0-flash"
        logger.info(f"[LLM] Gemini initialized — model: {self.model}")

    async def chat(self, messages: list, temperature: float = 0.5, max_tokens: int = 150) -> str:
        if self.provider == "groq":
            return await self._groq_chat(messages, temperature, max_tokens)
        elif self.provider == "gemini":
            return await self._gemini_chat(messages, temperature, max_tokens)

    async def _groq_chat(self, messages, temperature, max_tokens):
        response = await self._groq_client.chat.completions.create(
            messages=messages,
            model=self.model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    async def _gemini_chat(self, messages, temperature, max_tokens):
        # Extract system prompt and build history
        system_prompt = ""
        history = []
        last_user_msg = ""

        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            elif msg["role"] == "user":
                history.append({"role": "user", "parts": [msg["content"]]})
                last_user_msg = msg["content"]
            elif msg["role"] == "assistant":
                history.append({"role": "model", "parts": [msg["content"]]})

        model = self._genai.GenerativeModel(
            self.model,
            system_instruction=system_prompt or None,
            generation_config=self._genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )

        # All messages except the last user message go into history
        chat_history = history[:-1] if len(history) > 1 else []
        chat = model.start_chat(history=chat_history)

        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: chat.send_message(last_user_msg)
        )
        return response.text
