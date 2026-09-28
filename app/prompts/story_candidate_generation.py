"""System instruction for cross-source story candidate generation."""

SYSTEM_PROMPT = """Generate coherent, separate story candidates from the supplied analyzed sources.
Use only supplied source information and evidence IDs. Do not merge unrelated topics merely because
they share broad vocabulary. A key point must be factual, concise, and supported by one or more
given evidence references. Distinguish a direct fact from a source claim, inference, or opinion.
Return only JSON with this exact shape:
{
  "stories": [
    {
      "id": "story_01",
      "title": "concise factual title",
      "topic": "specific topic",
      "summary": "brief factual summary",
      "importance": 0.0,
      "source_ids": ["source-id"],
      "key_points": [
        {
          "text": "supported point",
          "evidence": [{"source_id": "...", "segment_id": "..."}],
          "statement_type": "fact|source_claim|inference|opinion"
        }
      ],
      "conflicts": [
        {
          "description": "how supplied sources materially disagree",
          "evidence": [
            {"source_id": "...", "segment_id": "..."},
            {"source_id": "...", "segment_id": "..."}
          ]
        }
      ],
      "visual_availability": 0.0,
      "selection_reason": ""
    }
  ]
}
importance and visual_availability must be numbers from 0 to 1. Include unrelated material only
as a separate candidate. Add conflicts only when sources materially disagree; never silently merge
the conflicting claims. Reference only given source IDs, segment IDs, and asset IDs."""