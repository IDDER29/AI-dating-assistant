import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

# Add src/ to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Stub heavy external dependencies so pure-function tests don't need them installed.
def _stub_module(name: str):
    parts = name.split(".")
    parent = None
    for i, part in enumerate(parts):
        full = ".".join(parts[: i + 1])
        if full not in sys.modules:
            mod = types.ModuleType(full)
            sys.modules[full] = mod
            if parent is not None:
                setattr(parent, part, mod)
        parent = sys.modules[full]

# google-genai (new SDK)
_stub_module("google")
_stub_module("google.genai")
_stub_module("google.genai.types")
_stub_module("google.genai.errors")

# Provide constructable stubs for the types used at runtime in ai_client.py
_types = sys.modules["google.genai.types"]
_types.Part = MagicMock                   # types.Part(text=...)
_types.Content = MagicMock               # types.Content(role=..., parts=[...])
_types.GenerateContentConfig = MagicMock  # types.GenerateContentConfig(system_instruction=...)

# errors stub — ClientError and ServerError need a .code attribute for with_api_retry
import types as _pytypes
_errors_mod = sys.modules["google.genai.errors"]


class _FakeClientError(Exception):
    def __init__(self, code=400, message=""):
        self.code = code
        self.message = message


class _FakeServerError(Exception):
    def __init__(self, code=500, message=""):
        self.code = code
        self.message = message


_errors_mod.ClientError = _FakeClientError
_errors_mod.ServerError = _FakeServerError
_errors_mod.APIError = Exception

# google-generativeai was the old SDK — stub it too so any residual
# imports during testing don't crash (e.g. if a module is cached).
_stub_module("google.api_core")
_stub_module("google.api_core.exceptions")
_stub_module("google.generativeai")

# Stub pyrogram / pyrofork
_stub_module("pyrogram")
_stub_module("pyrogram.errors")
_stub_module("pyrogram.handlers")
_stub_module("pyrogram.enums")
sys.modules["pyrogram"].Client = MagicMock
sys.modules["pyrogram"].filters = MagicMock()
sys.modules["pyrogram.enums"].ChatAction = MagicMock()

# Stub python-dotenv
_stub_module("dotenv")
sys.modules["dotenv"].load_dotenv = lambda: None
