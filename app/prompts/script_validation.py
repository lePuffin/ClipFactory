"""System instruction for repairing an invalid structured editorial script."""

SYSTEM_PROMPT = """Repair the supplied candidate script using only the selected_story,
selected_angle, selected_hook, allowed_source_ids, available_assets, and listed validation
failures. Return a compact complete replacement script as one JSON object. Preserve required_ids
and required_hook_text exactly: hook must be that JSON string, and the first section must repeat
it. Use only evidence references supplied in selected_story, selected_angle, or selected_hook;
never cite another source. Do not invent missing support. Use no more than maximum_sections, and
make every duration_seconds value greater than 0.5 and no greater than
maximum_section_duration_seconds. Remove or rewrite unsupported, duplicate, empty, overlong, or
visually invalid sections. Attribute any source disagreement instead of combining it as fact.

Return only this compact shape; omit candidate_asset_ids, visual_hint, and statement_type unless
they are needed:
{
	"story_id": "required story ID",
	"angle_id": "required angle ID",
	"hook_id": "required hook ID",
	"title": "concise factual title",
	"hook": "required hook text",
	"sections": [
		{
			"id": "section_01",
			"role": "hook|context|development|key_revelation|implication|ending",
			"text": "short spoken narration",
			"duration_seconds": 4.0,
			"evidence": [{"source_id": "...", "segment_id": "..."}],
			"visual_intent": "specific visual direction",
			"preferred_visual_type": "source_video|source_image|article_image|text_card"
		}
	]
}"""