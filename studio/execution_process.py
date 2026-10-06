"""Narrow allowlisted local boundary for Unit B managed execution.

Increment 1 exposes only the offline timing operations, as pure in-process
functions over explicit local files. There is no subprocess, no shell, no
network, no provider, and no generic command runner. Inputs must be existing
local files; remote/network/pseudo references are refused before any work.

Failures raise :class:`ExecutionProcessError` and are never reported as success.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from typing import Dict, Optional

from timing import adapter as timing_adapter
from timing import phrases as timing_phrases
from timing import schema as timing_schema

OPERATIONS = ("normalize_timing", "phrase_captions")

_REMOTE_PREFIXES = (
    "http://", "https://", "ftp://", "ftps://", "tcp://", "udp://",
    "rtmp://", "rtmps://", "rtsp://", "rtsps://", "srt://", "rist://",
    "gopher://", "smb://", "telnet://", "tls://", "data:", "file:",
    "pipe:", "concat:", "crypto:", "subfile:", "cache:", "async:", "unix:",
)


class ExecutionProcessError(Exception):
    """A local execution input/operation is refused or failed."""


def validate_timeout(seconds: object) -> float:
    """A finite, positive timeout is required (None/0/negative/non-finite fail)."""
    if seconds is None or isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise ExecutionProcessError("a finite positive timeout is required")
    value = float(seconds)
    if not math.isfinite(value) or value <= 0:
        raise ExecutionProcessError("a finite positive timeout is required")
    return value


def ensure_local_file(path: object, label: str = "input") -> str:
    """Return the absolute path of an existing local file.

    Rejects URLs, network/pseudo protocols, and option-like paths before any
    read. This is not a discovery mechanism: the caller must name the file.
    """
    if not isinstance(path, str) or not path:
        raise ExecutionProcessError("%s must be a local file path" % label)
    lowered = path.lower()
    for prefix in _REMOTE_PREFIXES:
        if lowered.startswith(prefix):
            raise ExecutionProcessError("%s must be local, not a %s source" % (label, prefix))
    if path.startswith("//"):
        raise ExecutionProcessError("%s must be local, not a network path" % label)
    if path.startswith("-"):
        raise ExecutionProcessError("%s must be a file path, not an option" % label)
    abspath = os.path.abspath(path)
    if not os.path.isfile(abspath):
        raise ExecutionProcessError("%s is not an existing local file" % label)
    return abspath


def load_json_file(path: str, label: str = "input") -> Dict:
    abspath = ensure_local_file(path, label)
    try:
        with open(abspath, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ExecutionProcessError("%s is not readable JSON: %s" % (label, exc))
    if not isinstance(data, dict):
        raise ExecutionProcessError("%s must be a JSON object" % label)
    return data


def supported_providers() -> list:
    return timing_adapter.supported()


def normalize_timing(provider: str, provider_response_path: str,
                     audio_duration_ms: Optional[int] = None) -> Dict:
    """Normalize a local provider response file into canonical word timings."""
    if not isinstance(provider, str) or provider not in timing_adapter.supported():
        raise ExecutionProcessError("unsupported timing provider %r" % provider)
    if audio_duration_ms is not None and (
            isinstance(audio_duration_ms, bool) or not isinstance(audio_duration_ms, int)
            or audio_duration_ms <= 0):
        raise ExecutionProcessError("audio_duration_ms must be a positive integer or null")
    response = load_json_file(provider_response_path, "provider response")
    try:
        doc = timing_adapter.normalize(provider, response, audio_duration_ms=audio_duration_ms)
        return timing_schema.validate(doc)
    except timing_schema.TimingError as exc:
        raise ExecutionProcessError("timing normalization failed: %s" % exc)


def phrase_captions(timing_doc: Dict) -> Dict:
    """Group canonical word timings into validated caption phrases."""
    try:
        doc = timing_schema.validate(timing_doc)
        captions = timing_phrases.to_captions(doc["words"])
        return timing_phrases.validate_captions(captions)
    except timing_schema.TimingError as exc:
        raise ExecutionProcessError("caption grouping failed: %s" % exc)


def write_json_atomic(path: str, doc: Dict) -> str:
    """Atomically write JSON, refusing to overwrite an existing output."""
    abspath = os.path.abspath(path)
    if os.path.exists(abspath):
        raise ExecutionProcessError("refusing to overwrite existing output: %s" % abspath)
    directory = os.path.dirname(abspath)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, abspath)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return abspath


def remove_file(path: str) -> None:
    """Best-effort cleanup of a file this execution wrote."""
    try:
        os.unlink(path)
    except OSError:
        pass


def ensure_within_deadline(started_monotonic: float, timeout_seconds: float) -> None:
    """Fail if a pure operation exceeded its declared bound.

    The timing operations are non-blocking in-process functions, so this is a
    post-condition rather than preemption; it still guarantees the declared
    timeout is enforced and reported honestly.
    """
    if time.monotonic() - started_monotonic > timeout_seconds:
        raise ExecutionProcessError("execution exceeded the declared timeout")
