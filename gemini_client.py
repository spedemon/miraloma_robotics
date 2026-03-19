"""
gemini_client.py — Gemini Multimodal Live API wrapper (stub)

This is a placeholder that keeps the UI fully functional without an API key.
Replace the stub logic with real Gemini calls in Phase 3.
"""

import asyncio
from typing import Optional, Callable


class GeminiClient:
    """Stub for the Gemini Multimodal Live API.

    Provides the same public interface that the real implementation will,
    so the UI can bind to it now and swap in the real client later.
    """

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key
        self._connected = False
        self._on_message: Optional[Callable[[str], None]] = None
        self._on_code: Optional[Callable[[str], None]] = None

    # ── Lifecycle ─────────────────────────────────────────────────

    async def connect(self) -> None:
        """Establish connection to Gemini (stub: always succeeds)."""
        if not self.api_key:
            raise ValueError("API key is required")
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── Callbacks ─────────────────────────────────────────────────

    def on_message(self, callback: Callable[[str], None]) -> None:
        """Register a callback for incoming text responses."""
        self._on_message = callback

    def on_code(self, callback: Callable[[str], None]) -> None:
        """Register a callback for generated Python code blocks."""
        self._on_code = callback

    # ── Messaging ─────────────────────────────────────────────────

    async def send_message(self, text: str) -> str:
        """Send a text message and return the AI response (stub).

        In the real implementation this will:
        1. Classify intent (simple vs. complex)
        2. Generate Python code if needed
        3. Stream the response back
        """
        await asyncio.sleep(0.3)  # simulate latency

        # Stub: echo back with a helpful message
        stub_response = (
            f"🤖 **[Gemini Stub]** Received: \"{text}\"\n\n"
            "Real AI integration coming in Phase 3. "
            "For now, use the Settings tab to configure your API key, "
            "and the Protocol Docs tab to see available robot commands."
        )

        if self._on_message:
            self._on_message(stub_response)

        # If the message looks like a movement command, generate stub code
        lower = text.lower()
        if any(kw in lower for kw in ("move", "drive", "scan", "forward", "back", "turn", "spin")):
            stub_code = self._generate_stub_code(text)
            if self._on_code:
                self._on_code(stub_code)

        return stub_response

    # ── Code Generation (stub) ───────────────────────────────────

    @staticmethod
    def _generate_stub_code(intent: str) -> str:
        """Generate a placeholder Python navigation script."""
        return f'''\
# Auto-generated navigation script
# Intent: "{intent}"
# ⚠️  Stub code — real generation in Phase 3

import time

def run(robot):
    """Execute the navigation plan."""
    robot.display_text("GO")
    robot.drive(100, 100, 100, 100)   # forward
    time.sleep(2)
    robot.stop()
    robot.display_text("DONE")
'''
