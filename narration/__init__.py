"""narration — narration mode (off | optional | required) and its gated pipeline.

Read-only. Resolves the per-project narration mode and reports the state of the
ten-step narration pipeline. It never calls a provider, never renders, and never
writes to a project. Voice generation (steps 1-2) stays behind the cost gate and
only runs on an explicit command.
"""

__all__ = ["mode", "plan"]
