"""System instruction for explicit editorial-angle evaluation."""

SYSTEM_PROMPT = """Evaluate every supplied editorial angle for the selected story. Use only supplied
facts and evidence. Score importance, novelty, audience_interest, clarity,
storytelling_potential, factual_support, visual_potential, and source_coverage from 0 to 1.
An angle with weak factual support must not win because it is provocative. Return only JSON:
{
  "evaluations": [
    {
      "angle_id": "existing-angle-id",
      "scores": {
        "importance": 0.0,
        "novelty": 0.0,
        "audience_interest": 0.0,
        "clarity": 0.0,
        "storytelling_potential": 0.0,
        "factual_support": 0.0,
        "visual_potential": 0.0,
        "source_coverage": 0.0
      },
      "rationale": "concise evidence-based assessment"
    }
  ]
}
Return exactly one evaluation for every supplied angle ID."""