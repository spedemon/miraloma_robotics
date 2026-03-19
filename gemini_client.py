"""
gemini_client.py — Google Gemini API wrapper

Uses the official `google-genai` SDK to interact with Google's Gemini models.
Supports multi-turn chat with dynamic system instructions that include
robot identity, protocol commands, and code generation guidelines.
"""

import asyncio
import re
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


# ── Response classification ──────────────────────────────────────

class ResponseType:
    """Classification of LLM response."""
    ACTION = "action"           # Simple move command — auto-execute
    NAVIGATION = "navigation"   # Complex navigation — wait for Go!
    CONVERSATION = "conversation"  # No code — just chat


class ParsedResponse:
    """Parsed LLM response with classification and extracted code."""

    def __init__(self, response_type: str, message: str, code: str = ""):
        self.response_type = response_type
        self.message = message
        self.code = code

    @property
    def has_code(self) -> bool:
        return bool(self.code.strip())


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
        """Send a tiny request to verify the API key works."""
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

    @staticmethod
    def build_system_prompt(
        robot_name: str,
        architecture_md: str,
        protocol_yaml: dict,
        calibration: dict,
    ) -> str:
        """Build a comprehensive system prompt for the LLM.

        Args:
            robot_name: Name of the selected robot (e.g., 'Spider', 'Mecanum')
            architecture_md: Contents of the robot_architecture.md file
            protocol_yaml: Parsed protocol YAML dict
            calibration: Dict with calibration params:
                - speed_seconds_per_foot: float (default 3.0)
                - default_motor_speed: int (default 150)
        """
        speed_per_foot = calibration.get("speed_seconds_per_foot", 3.0)
        motor_speed = calibration.get("default_motor_speed", 150)

        # Build the command reference
        setter_lines = []
        for cmd in protocol_yaml.get("setters", []):
            params = ", ".join(
                f'{p["name"]}: {p["type"]}' + (f' ({p.get("range", "")})' if p.get("range") else "")
                for p in cmd.get("parameters", [])
            )
            setter_lines.append(
                f"  - send('{cmd['id']}', {params if params else '0'})  # {cmd['description']}"
            )

        getter_lines = []
        for cmd in protocol_yaml.get("getters", []):
            params = ", ".join(
                f'{p["name"]}: {p["type"]}'
                for p in cmd.get("parameters", [])
            )
            ret = cmd.get("returns", {})
            ret_info = f" → {ret.get('type', 'str')}" if ret else ""
            getter_lines.append(
                f"  - read('{cmd['id']}'{', ' + params if params else ''})  "
                f"# {cmd['description']}{ret_info}"
            )

        setters_text = "\n".join(setter_lines) if setter_lines else "  (none)"
        getters_text = "\n".join(getter_lines) if getter_lines else "  (none)"

        return f"""You are **{robot_name}**, a robot who lives at **Miraloma Elementary School**.
You are friendly, enthusiastic, and love helping kids learn about robotics.
When asked who you are, always identify as {robot_name} from Miraloma Elementary.

## Your Robot Body
{architecture_md}

## Commands Available
You control your body by generating Python code that calls these functions:

**Movement & Actuators (Setters):**
{setters_text}

**Sensors (Getters):**
{getters_text}

**Utility functions:**
  - stop()           # Emergency stop — halt all motors
  - wait(seconds)    # Wait for a duration (safely interruptible)
  - is_running()     # Check if script should keep running (for loops)

## Calibration
- Moving speed: approximately **{speed_per_foot} seconds per foot** at default speed
- Default motor speed: **{motor_speed}** (for movement commands that take a speed parameter)
- 1 foot = 30.48 cm, 1 meter = 3.281 feet

## Code Generation Rules

When the user asks you to **perform a physical action** (move, turn, dance, etc.),
you MUST generate Python code and tag your response appropriately.

### Classification Rules:
1. **[ACTION]** — Simple, finite commands (e.g., "move forward 3 feet", "turn left",
   "dance", "do a pushup"). These are executed IMMEDIATELY without confirmation.
   Generate a short script: stop → action → wait → stop.

2. **[NAVIGATION]** — Complex, continuous tasks (e.g., "explore the room",
   "avoid obstacles while moving forward", "follow the wall", "scan for objects").
   These require user confirmation before execution.
   Generate a loop that checks `is_running()`.

3. **No tag** — Conversational responses (questions, explanations, greetings).
   Do NOT generate code for these.

### Code Format:
Always wrap generated code in a Python code block (```python ... ```).
Place the classification tag on its own line BEFORE the code block.

### Action Command Template:
```
[ACTION]
```python
# Brief description of what this does
stop()
send('MFW', {motor_speed})  # Move forward
wait(9.0)      # 3 feet × {speed_per_foot} sec/foot
stop()
```
```

### Navigation Command Template:
```
[NAVIGATION]
```python
# Brief description of what this does
stop()
while is_running():
    # ... navigation/sensing logic ...
    wait(0.1)  # Small delay between iterations
stop()
```
```

### Important:
- ALWAYS call stop() at the beginning AND end of any script
- For ACTION scripts, calculate wait time: distance_in_feet × {speed_per_foot} seconds
- For navigation with sensors, use read() to get sensor data
- Support unit conversions: feet, meters, centimeters, inches
- Keep code simple and readable — this is for kids learning robotics!
- In conversational responses, be fun and encouraging. Use emojis.
- NEVER include import statements — the functions are already available.
"""

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

    # ── Response Parsing ──────────────────────────────────────────

    @staticmethod
    def parse_response(text: str) -> ParsedResponse:
        """Parse an LLM response into classification + code.

        Looks for [ACTION] or [NAVIGATION] tags and extracts code blocks.
        """
        code = GeminiClient._extract_code(text)

        # Check for classification tags
        text_upper = text.upper()
        if "[ACTION]" in text_upper:
            return ParsedResponse(ResponseType.ACTION, text, code)
        elif "[NAVIGATION]" in text_upper:
            return ParsedResponse(ResponseType.NAVIGATION, text, code)
        elif code:
            # Has code but no explicit tag — classify based on content
            if "while" in code and "is_running()" in code:
                return ParsedResponse(ResponseType.NAVIGATION, text, code)
            else:
                return ParsedResponse(ResponseType.ACTION, text, code)
        else:
            return ParsedResponse(ResponseType.CONVERSATION, text, code)

    @staticmethod
    def clean_message_for_display(text: str) -> str:
        """Remove classification tags and code blocks for chat display.

        The generated Python code is already shown in the collapsible
        Navigation Script panel, so we strip it from the chat bubble to
        keep responses concise and kid-friendly.
        """
        # Remove classification tags
        text = re.sub(r'\[ACTION\]', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\[NAVIGATION\]', '', text, flags=re.IGNORECASE)
        # Remove fenced code blocks (```...```)
        text = re.sub(r'```[\s\S]*?```', '', text)
        # Collapse excess whitespace left behind
        text = re.sub(r'\n{3,}', '\n\n', text).strip()
        return text

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
