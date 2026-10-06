"""Provider-neutral adapter registry.

The renderer consumes only the canonical format; it never needs to know which
provider produced the timings. Adding a provider means adding a module with a
``normalize(response, audio_duration_ms=None) -> canonical`` function and
registering it here.
"""

from __future__ import annotations

from typing import Dict, List

from .adapters import elevenlabs
from .schema import TimingError

_ADAPTERS = {
    "elevenlabs": elevenlabs.normalize,
}


def supported() -> List[str]:
    return sorted(_ADAPTERS)


def entries() -> Dict[str, object]:
    return dict(_ADAPTERS)


def normalize(provider: str, response: Dict, audio_duration_ms=None) -> Dict:
    fn = _ADAPTERS.get(provider)
    if fn is None:
        raise TimingError("no timing adapter for provider '%s' (have: %s)"
                          % (provider, ", ".join(supported())))
    return fn(response, audio_duration_ms=audio_duration_ms)


def get(provider: str):
    fn = _ADAPTERS.get(provider)
    if fn is None:
        raise TimingError("no timing adapter for provider '%s'" % provider)
    return fn
