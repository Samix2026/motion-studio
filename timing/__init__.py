"""timing — provider-neutral canonical word-timing layer.

One canonical representation for word timing, adapters that normalize a
provider's real timestamp output into it, a cache that lives with the voice
asset, and deterministic phrase grouping. No network, no generation, no
fabricated timestamps.
"""

__all__ = ["schema", "adapter", "adapters", "cache", "phrases"]
