import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

# Add src/ to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Stub heavy external dependencies so pure-function tests don't need them installed
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

_stub_module("google")
_stub_module("google.api_core")
_stub_module("google.api_core.exceptions")
_stub_module("google.generativeai")

# Stub pyrogram so leomatch/dialog imports don't blow up
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
