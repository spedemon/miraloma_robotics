"""
gemini_client.py — Google Gemini API wrapper

Uses the official `google-genai` SDK to interact with Google's Gemini models.
Supports multi-turn chat with system instructions, model selection, and
streaming responses.
"""

import asyncio
from typing import Optional, Callable

from google import genai
from google.genai import types


# ── Available models (user-facing label → API model name) ────────
AVAILABLE_MODELS: dict[str, str] = {
    "Gemini 2.5 Flash (Recommended)": "gemini-2.5-flash",
    "Gemini 2.5 Pro": "gemini-2.5-pro",
    "Gemini 2.5 Flash-Lite": "gemini-2.5-flash-lite",
}

DEFAULT_MODEL_LABEL = "Gemini 2.5 Flash (Recommended)"


class GeminiClient:
    """Google Gemini API client for robot command generation.

    Manages API key configuration, model selection, system prompt,
    and multi-turn chat history.
    """

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key
        self._model_label: str = DEFAULT_MODEL_LABEL
        self._client: Optional[genai.Client] = None
        self._chat = None
        self._connected = False
        self._on_message: Optional[Callable[[str], None]] = None
        self._on_code: Optional[Callable[[str], None]] = None
        self._system_prompt: str = ""

    # ── Configuration ────────────────────────────────────────────

    @property
    def model_label(self) -> str:
        return self._model_label

    @model_label.setter
    def model_label(self, label: str) -> None:
        if label in AVAILABLE_MODELS:
            self._model_label = label
            # Reset chat so next message uses the new model
            self._chat = None

    @property
    def model_name(self) -> str:
        """Return the API model identifier for the current selection."""
        return AVAILABLE_MODELS.get(self._model_label, "gemini-2.5-flash")

    @staticmethod
    def available_model_labels() -> list[str]:
        """Return the list of user-facing model labels."""
        return list(AVAILABLE_MODELS.keys())

    # ── Lifecycle ─────────────────────────────────────────────────

    def configure(self, api_key: str) -> None:
        """Set the API key and create the client.  Does NOT make a network call."""
        self.api_key = api_key
        self._client = genai.Client(api_key=api_key)
        self._chat = None
        self._connected = True

    async def test_connection(self) -> str:
        """Send a tiny request to verify the API key works.

        Returns a success message or raises on failure.
        """
        if not self._client:
            raise ValueError("Call configure() with an API key first")

        response = await asyncio.to_thread(
            self._client.models.generate_content,
            model=self.model_name,
            contents="Say 'hello' in one word.",
        )
        return response.text.strip() if response.text else "OK"

    async def disconnect(self) -> None:
        self._client = None
        self._chat = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    # ── System Prompt ─────────────────────────────────────────────

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system instruction for the model.

        Resets the chat so the new prompt takes on the next message.
        """
        self._system_prompt = prompt
        self._chat = None

    # ── Callbacks ─────────────────────────────────────────────────

    def on_message(self, callback: Callable[[str], None]) -> None:
        """Register a callback for incoming text responses."""
        self._on_message = callback

    def on_code(self, callback: Callable[[str], None]) -> None:
        """Register a callback for generated Python code blocks."""
        self._on_code = callback

    # ── Chat (multi-turn) ─────────────────────────────────────────

    def _ensure_chat(self) -> None:
        """Lazily create a chat session with the current model and system prompt."""
        if self._chat is None and self._client is not None:
            config = None
            if self._system_prompt:
                config = types.GenerateContentConfig(
                    system_instruction=self._system_prompt,
                )
            self._chat = self._client.chats.create(
                model=self.model_name,
                config=config,
            )

    async def send_message(self, text: str) -> str:
        """Send a text message and return the AI response.

        Uses the multi-turn chat API to maintain conversation history.
        Falls back to a friendly error if the API is not configured.
        """
        if not self.is_connected or not self._client:
            return (
                "🔑 **AI brain is not configured yet!**\n\n"
                "Go to the **⚙️ Setup** tab, paste your API key, "
                "and press **Save & Test** to activate the AI."
            )

        try:
            self._ensure_chat()

            # Run the blocking SDK call in a thread so NiceGUI stays responsive
            response = await asyncio.to_thread(
                self._chat.send_message, text
            )

            reply = response.text if response.text else "(no response)"

            if self._on_message:
                self._on_message(reply)

            # Check for code blocks in the response
            if "```" in reply and self._on_code:
                code = self._extract_code(reply)
                if code:
                    self._on_code(code)

            return reply

        except Exception as exc:
            error_msg = str(exc)
            # Provide friendly messages for common errors
            if "API_KEY_INVALID" in error_msg or "401" in error_msg:
                return "❌ **Invalid API key.** Check your key in the Setup tab."
            if "quota" in error_msg.lower() or "429" in error_msg:
                return "⏳ **Rate limit reached.** Wait a moment and try again."
            return f"⚠️ **AI Error:** {error_msg}"

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _extract_code(text: str) -> str:
        """Extract the first fenced code block from a response."""
        parts = text.split("```")
        if len(parts) >= 3:
            code_block = parts[1]
            # Strip optional language tag (e.g. "python\n")
            lines = code_block.split("\n", 1)
            if len(lines) > 1:
                return lines[1].strip()
            return code_block.strip()
        return ""
