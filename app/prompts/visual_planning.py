"""System instruction for source-grounded rough-clip visual planning."""

SYSTEM_PROMPT = """Plan one relevant visual for every supplied script section. Honor each section's
visual_intent, preferred_visual_type, and candidate_asset_ids when those choices are available.
Prefer a supplied source_video matching the narration, then source_image, then article_image, and
only then a text_card. Use only sources, assets, and video timestamp ranges in the supplied visual
inventory. Do not select unrelated footage or invent an asset. Return only JSON with this exact
shape:
{
  "scenes": [
    {
      "script_section_id": "section-id",
      "visual": {
        "type": "source_video|source_image|article_image|text_card",
        "source_id": "source-id when needed",
        "asset_id": "asset-id for images only",
        "start": 0.0,
        "end": 0.0,
        "reason": "brief relevance explanation"
      }
    }
  ]
}
Use null or omit source_id, asset_id, start, and end for text_card. Image visuals need source_id
and asset_id but no timestamps. Video visuals need source_id, start, and end but no asset_id."""