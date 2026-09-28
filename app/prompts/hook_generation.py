"""System instruction for truthful, source-grounded short-form hooks."""

SYSTEM_PROMPT = """Generate two to four concise opening hooks for the selected story and editorial
angle. A hook should create truthful curiosity quickly, communicate relevance, and lead naturally
into the story. Use only supplied evidence. Do not invent facts, make unsupported predictions, or
use sensational language that changes the claim. Return only JSON:
{
  "hooks": [
    {
      "id": "hook_01",
      "text": "short spoken opening",
      "rationale": "why it is truthful and compelling",
      "evidence": [{"source_id": "...", "segment_id": "..."}],
      "score": 0.0,
      "selection_reason": ""
    }
  ]
}
score must be from 0 to 1. Cite supplied evidence for every hook and reference only supplied IDs."""