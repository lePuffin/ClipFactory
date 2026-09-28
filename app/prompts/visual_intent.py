"""Requirements appended to the script prompt for renderer-compatible visual intent."""

VISUAL_INTENT_REQUIREMENTS = """Visual intent must describe the visual that best supports the
spoken section, not a generic mood. Prefer a relevant source video, then a source image, then an
article image. Use text_card only when no useful source visual is available. Candidate asset IDs
must be drawn from the supplied visual inventory. The renderer may use a text-card fallback when a
planned asset cannot be acquired."""