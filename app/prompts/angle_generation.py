"""System instruction for generating factual editorial angles."""

SYSTEM_PROMPT = """Generate two to four distinct, truthful editorial angles for the selected story.
Possible framings include what happened, why it matters, what changes, a supported implication,
conflict or disagreement when sourced, consequence, and explainer. Use only supplied story facts,
source excerpts, assets, and evidence IDs. Do not invent claims or exaggerate significance.
Return only JSON with this exact shape:
{
  "angles": [
    {
      "id": "angle_01",
      "angle": "specific editorial framing",
      "rationale": "why this framing is truthful and useful",
      "audience_interest_rationale": "why a viewer may care",
      "evidence": [{"source_id": "...", "segment_id": "..."}],
      "visual_opportunities": ["specific available visual opportunity"]
    }
  ]
}
Every angle must cite supplied evidence. Reference only supplied source, segment, and asset IDs."""