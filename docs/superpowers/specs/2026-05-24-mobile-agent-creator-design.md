# Mobile Agent Creator Design

Date: 2026-05-24
Project: Ez ComfyUI Showcase
Status: Draft for review

## Goal

Build a mobile-first creation entry that feels close to ChatGPT or Gemini on a phone, while staying reliable on local hardware and local models. The user should express an image idea in one sentence by typing or speaking, confirm only a few simple options, and generate an image without understanding workflows, nodes, seeds, or model routing.

The first version focuses on the smallest useful loop:

```text
Open mobile home
  -> type or speak one image idea
  -> local agent understands the request
  -> app chooses a default text-to-image workflow
  -> user confirms style and ratio
  -> generate
  -> view, save, retry, or modify
```

## Product Principles

- The phone UI is an intent surface, not a workflow dashboard.
- The user should never need to pick a ComfyUI workflow in V1.
- The app should ask at most one clarification question before generation.
- The agent is task-bound and predictable; it does not run open-ended chat.
- Local rules own routing and safety. Local LLMs help with language, not control.
- The interface should avoid vertical scrolling during the main path.
- Existing `/api/generate`, workflow metadata, prompt optimization, job polling, and history behavior should remain the source of truth.

## V1 Scope

V1 supports one primary workflow: text-to-image from a typed or spoken prompt.

Included:

- Mobile creator home screen.
- Text input.
- Voice input through local Whisper-style speech-to-text.
- Intent parsing for `text_to_image`.
- Prompt cleanup and optimization using an already available local lightweight LLM such as Qwen, Gemma, or Llama.
- Default workflow routing to one approved text-to-image workflow.
- Minimal confirmation controls for style and aspect ratio.
- Generation progress and result actions.
- Clear failure fallbacks when speech, LLM, or generation is unavailable.

Deferred:

- Full multi-turn chat memory.
- General-purpose autonomous agent behavior.
- Manual workflow selection in the mobile-first path.
- Node-level editing.
- Batch generation.
- Image-to-image, image-to-video, text-to-video, and upscale as first-class flows.
- Cloud LLM dependency.

## Core User Flow

```text
[Mobile Home]
  User says or types: "Help me make a rainy cyberpunk city photo"
        |
        v
[Understand]
  Speech text is confirmed if voice was used
  Intent router classifies the task as text_to_image
        |
        v
[Compile]
  Prompt compiler removes request wording, extracts useful hints,
  and produces workflow-ready prompt fields
        |
        v
[Confirm]
  User sees a short summary plus 2-3 option groups
        |
        v
[Generate]
  Existing generate API creates a normal job
        |
        v
[Result]
  User can retry, modify, save, or go home
```

## Stage Wireframes

### 1. Mobile Home

Purpose: one calm entry point that invites creation.

```text
┌────────────────────────┐
│ EZ                     │
│                        │
│        Agent Avatar     │
│                        │
│ What do you want to    │
│ create today?          │
│                        │
│ ┌────────────────────┐ │
│ │ Describe an image  │ │
│ │ idea...            │ │
│ └────────────────────┘ │
│  image   mic   send     │
└────────────────────────┘
```

Notes:

- `image` is visible as a future path but can be disabled or marked secondary in V1.
- The text box should stay near the thumb zone.
- The mic button starts local recording and shows a recording state immediately.

### 2. Voice Capture

Purpose: make voice feel immediate while local transcription runs.

```text
┌────────────────────────┐
│ Listening...            │
│                        │
│      waveform / timer   │
│                        │
│ "A futuristic city..."  │
│                        │
│ [Stop]          [Use]   │
└────────────────────────┘
```

Notes:

- The app should show partial or final recognized text before running the LLM path.
- If Whisper fails, the recognized text area remains editable.

### 3. Agent Understanding

Purpose: show that the app understood the request without exposing technical routing.

```text
┌────────────────────────┐
│ I will create:          │
│ Rainy futuristic city   │
│ at night, cinematic...  │
│                        │
│ Style                  │
│ [Real] [Cinematic]     │
│ [Anime]                │
│                        │
│ Ratio                  │
│ [1:1] [3:4] [9:16]     │
│                        │
│        Generate         │
└────────────────────────┘
```

Notes:

- The summary is generated from the compiled prompt, not the raw user sentence.
- The default selected options should be inferred from the prompt when possible.
- If confidence is low, replace the option block with one question, such as "Photo or anime style?"

### 4. Generating

Purpose: reuse existing job truth while avoiding dashboard complexity.

```text
┌────────────────────────┐
│ Creating...             │
│                        │
│  28%  composing image   │
│ ━━━━━━━───────          │
│                        │
│ Rainy futuristic city   │
│                        │
│ [Cancel] [Wait in bg]   │
└────────────────────────┘
```

Notes:

- Progress should come from the existing job and WebSocket/polling path.
- Startup/model-loading states should be separate from actual generation time.
- Cancel must map to the existing authoritative cancel behavior.

### 5. Result

Purpose: one-screen completion with obvious next actions.

```text
┌────────────────────────┐
│ Done                   │
│ ┌────────────────────┐ │
│ │                    │ │
│ │    result image     │ │
│ │                    │ │
│ └────────────────────┘ │
│                        │
│ [Again] [Modify] [Save] │
└────────────────────────┘
```

Notes:

- `Again` reuses the same compiled request with a new seed.
- `Modify` returns to the confirmation screen with the existing prompt filled in.
- `Save` uses the existing history/gallery storage path.

## Technical Architecture

```text
Mobile Creator UI
  |
  | text, audio blob, future image
  v
Agent Orchestrator API
  |
  +--> Speech Service
  |      Local Whisper tiny/base/small, preferably warm
  |
  +--> Intent Router
  |      Deterministic rules first, LLM only when ambiguous
  |
  +--> Prompt Compiler
  |      Local Qwen/Gemma/Llama for semantic cleanup
  |
  +--> Workflow Router
  |      Chooses approved default workflow and minimal fields
  |
  v
Existing Generate API
  |
  v
Existing Job + History Systems
```

The agent layer should be a thin orchestration layer between the mobile UI and existing APIs. It should produce structured decisions, not directly mutate workflow JSON or bypass the current generation pipeline.

## Local Model Responsibilities

| Capability | Suggested Local Model | Responsibility | Required in V1 |
| --- | --- | --- | --- |
| Speech-to-text | Whisper tiny/base/small or faster-whisper equivalent | Convert short phone voice input into text | Yes |
| Intent classification | Rules with optional Qwen/Gemma/Llama | Decide `text_to_image` or ask for clarification | Yes |
| Prompt cleanup | Qwen/Gemma/Llama lightweight text model | Remove request wording and preserve visual intent | Yes |
| Prompt enrichment | Qwen/Gemma/Llama lightweight text model | Add useful visual detail without inventing a new concept | Yes |
| Parameter extraction | Rules plus LLM fallback | Detect ratio, style, image purpose, and language | Yes |
| Image understanding | Qwen VLM / existing prompt interrogator | Future image-to-image support | No |
| Video scripting | Existing video prompt optimizer path | Future video workflows | No |

## Agent Output Contract

The orchestrator returns a constrained JSON object. This keeps the UI simple and keeps model output testable.

```json
{
  "intent": "text_to_image",
  "confidence": 0.91,
  "raw_text": "帮我出一张未来城市雨夜的照片",
  "display_summary": "未来城市雨夜，真实照片感，霓虹灯与湿润街道",
  "compiled_prompt": "未来城市雨夜，真实照片风格，霓虹灯倒映在湿润街道上，高楼灯光，电影感构图，自然雨雾氛围",
  "style": "realistic",
  "aspect_ratio": "9:16",
  "workflow": "default_text_to_image",
  "needs_confirmation": false,
  "question": "",
  "options": {
    "style": ["realistic", "cinematic", "anime"],
    "aspect_ratio": ["1:1", "3:4", "9:16"]
  }
}
```

Rules:

- `intent` must be from a fixed enum.
- `workflow` must be an internal alias resolved by the backend, not a user-facing filename.
- `confidence < 0.65` should trigger one clarification question.
- If local LLM output is invalid JSON, fall back to deterministic prompt cleanup and default options.

## Routing Strategy

V1 routing is deliberately conservative:

```text
If text exists and no uploaded image/video:
  route to text_to_image

If text mentions "video", "move", "motion", "animate":
  in V1 show "video coming soon" or route to existing desktop flow

If image exists:
  in V1 show "image edit coming soon" or route to existing desktop flow

If text is too short:
  ask one question or suggest examples
```

The workflow router should map `default_text_to_image` to an admin-configured workflow. The first practical candidates are existing text-to-image workflows already visible in workflow metadata, such as Qwen Image, Z-Image, or Flux2 variants, but the design should not hard-code a filename in the UI.

## API Additions

The implementation can stay small by adding APIs around the existing pipeline:

```text
POST /api/mobile-agent/understand
  Input: text, optional speech transcript, optional locale
  Output: Agent output contract

POST /api/mobile-agent/transcribe
  Input: audio file
  Output: transcript, duration_ms, provider

POST /api/mobile-agent/generate
  Input: accepted agent output plus user edits
  Output: existing job payload
```

`/api/mobile-agent/generate` may internally call the same service function used by `/api/generate`, or the frontend can call `/api/generate` directly after `/understand`. The cleaner V1 option is to keep generation explicit in the UI and reuse `/api/generate` directly once the agent output is accepted.

## Performance Requirements

Target phone experience:

- Tap-to-record feedback: under 100 ms.
- Short speech transcription for 5-10 seconds audio: ideally under 2 seconds on warm local service.
- Intent and prompt compile: ideally under 1.5 seconds on warm local LLM.
- Confirmation screen visible: under 3 seconds after user stops speaking.
- No model cold-start spinner without a human-readable state.

Architecture choices:

- Keep Whisper and lightweight LLM services warm when possible.
- Use small local models for semantic tasks; do not load large image/video models for intent parsing.
- Send compact context: user text, workflow aliases, field summaries, and preferred options only.
- Cache recent transcriptions and prompt compile results.
- Use deterministic fallback when the LLM times out.
- Stream or stage status text so the phone never appears frozen.

## Failure Handling

| Failure | User Experience | System Behavior |
| --- | --- | --- |
| Microphone permission denied | Show text input with a short permission hint | Do not block typing |
| Speech transcription fails | Keep audio result editable as text | Let user type or retry |
| LLM unavailable | Use rule-based prompt cleanup | Keep generate path available |
| Ambiguous intent | Ask one simple question | Do not show workflow list |
| Workflow unavailable | Show "creator is preparing" and offer retry | Do not submit invalid jobs |
| Generation fails | Show existing error and retry action | Preserve compiled prompt |

## Data Flow Details

```text
1. User enters text or records voice.
2. Voice path uploads audio to transcribe API.
3. UI sends final text to understand API.
4. Intent router applies rules.
5. Prompt compiler optionally calls local LLM.
6. Workflow router resolves an internal workflow alias.
7. UI renders summary and minimal options.
8. User taps Generate.
9. UI submits to existing generate path with workflow fields.
10. Existing job status and history systems drive progress and result.
```

## Frontend Structure

Add a dedicated mobile creator shell instead of reshaping the current desktop dashboard.

Suggested modules:

```text
static/js/modules/mobile-agent.js
  Home, voice state, understand call, confirmation state

static/js/modules/mobile-agent-ui.js
  Wireframe-derived rendering helpers and small controls

static/js/modules/generate.js
  Reuse final generate submission where possible
```

The UI should use the existing icon system and module conventions. It should avoid inline styles and avoid global full-list refreshes after local actions.

## Backend Structure

Suggested modules:

```text
modules/mobile_agent.py
  IntentRouter, PromptCompiler, WorkflowRouter, structured output validation

modules/speech_transcriber.py
  Whisper/faster-whisper adapter with timeout and warm-service settings

app.py
  Thin route bindings and auth checks
```

The backend should treat model calls as optional dependencies. A missing local LLM should degrade to rules and defaults.

## Workflow Configuration

Admin-controlled settings should define:

```json
{
  "mobile_creator": {
    "enabled": true,
    "default_text_to_image_workflow": "t2i_Qwen_Image_2512_4steps.json",
    "allowed_styles": ["realistic", "cinematic", "anime"],
    "allowed_ratios": ["1:1", "3:4", "9:16"],
    "llm_timeout_ms": 1500,
    "speech_timeout_ms": 5000
  }
}
```

The exact workflow filename is an example. The final implementation should read the configured workflow and validate that it is visible and supports the fields needed by the quick-generate path.

## Extension Path

After V1 proves stable:

```text
V2: image-to-image
  User uploads a photo and says what to change.

V3: image-to-video
  User uploads a photo and describes motion.

V4: text-to-video
  User describes a scene and motion without image upload.

V5: upscale/enhance
  User selects an existing result and chooses quality target.
```

Each new flow should still follow the same stage pattern:

```text
Intent input -> agent understanding -> minimal confirmation -> generation -> result actions
```

## Testing Strategy

Unit tests:

- Intent router classifies common Chinese and English text-to-image requests.
- Router does not accidentally send image/video requests into V1 text-to-image.
- Prompt compiler returns valid structured JSON or deterministic fallback.
- Workflow router rejects unavailable or unauthorized workflows.

Frontend contract tests:

- Mobile creator renders home, voice, confirmation, generating, and result states.
- Disabled future paths are visible but do not break the V1 path.
- Generate submission uses the existing workflow field structure.
- Mobile viewport has no horizontal overflow at 390px width.

Integration checks:

- `/api/mobile-agent/understand` works without local LLM by fallback.
- Whisper timeout returns an editable failure state.
- Existing `/api/generate` receives the compiled prompt and selected ratio.
- Job progress and cancel behave the same as normal generation.

Manual verification:

- Test typed Chinese prompt.
- Test typed English prompt.
- Test short voice prompt.
- Test ambiguous short prompt.
- Test local LLM unavailable.
- Test default workflow unavailable.

## Open Implementation Decisions

- Which local speech backend is installed in the target Docker/workflow environment: Whisper CLI, faster-whisper, or a ComfyUI speech node.
- Which lightweight LLM endpoint is most reliable and warm in the current deployment.
- Which text-to-image workflow should be the default admin-configured route.
- Whether mobile creator should replace the mobile home page or appear as a new top-level mode first.

## Acceptance Criteria

- A phone user can generate an image from a single typed sentence without choosing a workflow.
- A phone user can generate an image from a short voice request with one editable transcript step.
- The confirmation screen exposes only summary, style, ratio, and generate.
- The system still works when local LLM is unavailable.
- No cloud model is required for V1.
- Generation jobs use existing job tracking, cancel, and history behavior.
- The UI stays within one mobile viewport for the main path where possible.

## Spec Self-Review

- Placeholder scan: no unresolved placeholder markers.
- Consistency check: V1 remains text-to-image only across user flow, API, and tests.
- Scope check: the design is small enough for one implementation plan if speech is treated as an adapter with fallback.
- Ambiguity check: local LLM is explicitly auxiliary; routing remains rule-owned and constrained.
