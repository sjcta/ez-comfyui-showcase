---
name: image_reverse
description: Use for image reverse prompting, expert image interrogation, prompt reconstruction scoring, visible-fact extraction, pose/material/safety boundary validation, and replication-rate regression tests.
---

# Image Reverse Skill

Goal: produce a prompt that can replicate the visible image, not a pleasant caption.

## Closed Loop

1. Extract visible evidence first.
2. Validate evidence against image geometry and known conflict rules.
3. Merge evidence into `visual_spec` / `structured_prompt`, then translate the full structure into a complete positive `keyword_prompt`; negative constraints are optional and only for explicit error control.
4. Score the result against a 95 replication target.
5. Every result below 95 becomes a regression case or a new ontology rule.

## Evidence Before Prompt

Before every image analysis, load the categorized rulebook from `prompt_skills/image_reverse/rules/`.
The runtime prompt may inject only the short rule index, but the source of truth for rule details is the rulebook directory.

Always identify these before writing the final prompt:

- image aspect ratio and orientation
- visible body range and crop line
- body support points and weight-bearing surfaces
- hand endpoints and actual contact points
- foot/shoe visibility and weight-bearing
- clothing type, material, transparency, edge/cuff boundaries
- visible text confidence
- scene regions from outer frame to center
- lighting direction, color temperature, and material response
- NSFW labels only from visible adult nudity, genitals, sexual contact, or sexual fluids

Before writing the final prompt, use the four-step workflow:

1. Checklist pass: mark 30+ visual items as seen / not seen without conclusions.
2. Structured pass: expand only seen items into `visual_spec` or `structured_prompt`.
3. Prompt pass: translate the structured fields into a complete positive `keyword_prompt`.
4. Review pass: check whether any seen item was omitted, contradicted, duplicated, or polluted by JSON keys.

## Hard Rules

- Positive fields only contain visible facts.
- No uncertain alternatives such as A or B, possible, maybe, unclear.
- Do not mention unseen body parts in positive prompts.
- Negative prompts, when present, are pure tags/phrases and must be sibling to image description.
- Vertical source images must not be described as 1:1.
- If shoes/feet are visible, crop cannot be upper-body-to-thigh.
- Crouching with shoes on the ground is shoe/sole weight-bearing, not knee support.
- Text on clothing is only exact when reliably readable.

## Runtime

The executable validator lives in `modules/image_reverse_skill.py`.
Use `validate_reverse_prompt_quality()` after model output and before returning expert results.
