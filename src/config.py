"""
Compatibility shim — re-exports everything from settings and credentials.
Modules should import directly from settings or credentials going forward.
"""
from settings import *  # noqa: F401, F403
from credentials import *  # noqa: F401, F403
