"""costgate — pre-generation cost approval gate.

Estimates the cost of planned PAID calls from an explicit pricing catalog,
presents it for human approval, and blocks generation until approved. It never
calls a provider, never invents pricing, and never modifies a video project.
"""

__all__ = ["schema", "gate"]
