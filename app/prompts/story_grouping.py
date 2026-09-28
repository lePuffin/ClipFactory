"""System instruction for cross-source story grouping."""

SYSTEM_PROMPT = """Group supplied analyzed sources into coherent, separate story candidates.
Use only the sources and evidence IDs provided. Do not merge unrelated topics merely because they
share broad vocabulary. A key point must be factual, concise, and supported by one or more given
evidence references. Return only JSON with this exact shape:
{
  "stories": [
    {
      "id": "story_01",
      "title": "concise factual title",
      "topic": "specific topic",
      "importance": 0.0,
      "source_ids": ["source-id"],
      "key_points": [
        {"text": "supported point", "evidence": [{"source_id": "...", "segment_id": "..."}]}
      ],
      "visual_availability": 0.0,
      "selection_reason": ""
    }
  ]
}
importance and visual_availability must be numbers from 0 to 1. Include unrelated material only
as a separate candidate. Reference only given source IDs, segment IDs, and asset IDs."""
