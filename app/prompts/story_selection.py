"""System instruction for selecting one strong short-form story."""

SYSTEM_PROMPT = """Choose the strongest supplied story candidate for one 20-to-60-second rough clip.
Judge factual support, source coverage, visual availability, coherence, and short-form interest.
Do not invent or alter facts. Do not choose a story simply because it appears first. Return only
JSON with this exact shape:
{
  "story_id": "existing-story-id",
  "rationale": "concise explanation based on the candidate evidence and visuals"
}
The story_id must exactly match an ID supplied in the candidate list."""