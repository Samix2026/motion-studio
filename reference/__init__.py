"""reference — abstract style analysis of reference material (V1).

Extracts STYLE metadata only (pacing, density, layout behaviour) from local
video / image sets / manually provided observations. It never copies scripts,
wording, scene order, branding, logos, or assets, never calls the network, and
never modifies a video project or a brand profile.

Observed measurements and inferred traits are kept in separate sections.
"""

__all__ = ["schema", "analyzer", "video", "images"]
