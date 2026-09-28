"""System instruction for explicit, fact-grounded story evaluation."""

SYSTEM_PROMPT = """Evaluate every supplied story candidate for a truthful short-form reel.
Use only the supplied candidate facts, source context, and evidence IDs. Do not invent context,
claims, audience reactions, or visual availability. Score each dimension from 0 to 1, where 1 is
strongest: importance, novelty, audience_interest, clarity, storytelling_potential,
factual_support, visual_potential, and source_coverage. Explain the assessment concisely.
Return only JSON with this exact shape:
{
  "evaluations": [
    {
      "story_id": "existing-story-id",
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
Return exactly one evaluation for every supplied story ID. Favor the strongest supported story,
not unsupported sensationalism or clickbait."""