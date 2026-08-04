# Standalone Email Check and Speaking Cues Design

**Status:** Approved in conversation on August 4, 2026  
**Scope:** Add an on-demand email review command and TOEFL-like turn-taking cues to Listen and Repeat.

## 1. Purpose

The learner needs two small improvements to the Telegram practice loop:

- review an English email without opening or completing a scheduled Writing block;
- know when to listen and when to speak during Listen and Repeat.

These additions must preserve active practice, daily-plan scores, and durable attempt state.

## 2. Current Behavior

The bot accepts text only as an answer to the active practice item. Text sent without an active block receives an instruction to open `/today`. Email evaluation exists only for a scheduled Email task and depends on that task's scenario, audience, purpose, required points, and attempt record.

Listen and Repeat sends a text instruction and a Telegram voice message. The bot does not mark the listening interval, add the TOEFL start signal, or announce when the learner may record a response.

## 3. Decisions

### 3.1 Standalone email review

The learner sends the command and email in one Telegram message:

```text
/check <email text>
```

The command works with or without an active practice block. It never submits, pauses, advances, or replaces the active item. Command routing takes precedence over the generic text-answer handler.

The checker evaluates only qualities supported by the supplied text:

- email structure;
- clarity and organization;
- tone and register;
- grammar;
- vocabulary and phrasing.

The response contains:

1. a short overall assessment;
2. strengths;
3. specific issues with corrections and explanations;
4. a revised email that preserves the learner's intended meaning.

The checker does not assign an official TOEFL score. Without a scenario, audience, purpose, and required points, it cannot judge task fulfillment reliably.

Schema-validated checker results use a dedicated standalone email-review model. The checker records its issues through the existing `ProgressTracker`, under the Writing section and the existing canonical skill taxonomy. These issues appear in `/progress` and exports. The review does not create a daily plan entry, practice attempt, attempt item, or score.

If `/check` contains no non-whitespace text, the bot replies with a concise usage example and does not call the LLM. The implementation enforces Telegram's existing message-size constraints and escapes all learner- and model-provided text before rendering HTML.

If evaluation fails, the bot reports that the check could not be completed and asks the learner to retry. A failed check records no issues and changes no practice state.

### 3.2 Listen and Repeat cues

Each Listen and Repeat item follows this sequence:

1. Send `🔇 Слушайте. Пока не говорите.`
2. Send the hidden source sentence as a Telegram voice message.
3. End that audio with a short audible beep.
4. Wait for the encoded audio duration plus a 0.3-second handoff margin.
5. Send `🎙 Можно говорить. Повторите фразу один раз.`
6. Accept one voice response through the existing transcription and grading flow.

Telegram does not tell a bot when the learner starts or finishes playback. The duration-based delay therefore prevents the speaking cue from arriving immediately in the normal autoplay flow, while the terminal beep remains the authoritative signal if the learner starts playback later.

The experience follows the updated TOEFL iBT mechanic: the learner repeats immediately after the beep and receives no preparation pause. ETS gives 8–12 seconds to record each Listen and Repeat response, depending on the sentence. The block instructions present that range as guidance; the speaking cue stays short. The bot does not reject a Telegram recording solely because its duration exceeds the range. Existing speech metrics continue to store the actual duration.

The bot adds the beep only to Listen and Repeat prompts. Interview audio and deadlines retain their current behavior. Cached audio must include the beep or be transformed deterministically before delivery, so cached and newly synthesized prompts behave alike. Newly synthesized speech is checked for excessive micro-pauses and silence; a fragmented primary result is regenerated once with the Austin voice before delivery.

If audio preparation or delivery fails, the bot preserves the active item, sends the existing recovery message, and omits `Можно говорить`. Retrying the Speaking section delivers the same item again.

Primary timing reference:

- [ETS Updated TOEFL iBT Test Overview](https://www.ets.org/pdfs/toefl/toefl-ibt-test-overview.pdf)

## 4. Architecture

The design adds two focused seams.

### 4.1 Email checker

A standalone email checker owns its evaluation prompt, result schema, and conversion to learning issues. It depends on the existing LLM interface and `ProgressTracker`; it does not depend on `PracticeEngine` or a catalog task.

The Telegram `/check` handler extracts the email text, calls the checker, and renders the result. Keeping command orchestration in `bot` and evaluation rules in `eval` prevents the large router from owning rubric logic.

### 4.2 Speaking cue delivery

A small audio post-processor owns beep composition. The bot delivery function owns message order because it already coordinates prompt text and voice transport. It sends the listening cue before audio and the speaking cue only after successful voice delivery.

New synthesis is written under `audio_cache/tts-v2/<task-id>/<item>.ogg`, and the post-processor writes transformed prompts under `audio_cache/listen-repeat-cue-v2/<task-id>/<item>.ogg`. The version bump invalidates previously cached fragmented speech. The post-processor treats catalog audio and newly synthesized audio as immutable sources. A cache hit returns the transformed file without processing it again, which prevents duplicate beeps.

## 5. Data Flow

### 5.1 `/check`

```text
Telegram command
  -> validate and extract email
  -> standalone email checker
  -> schema-validated LLM result
  -> atomically record learning issues
  -> render assessment and revised email
```

Practice state remains unchanged throughout this flow.

### 5.2 Listen and Repeat

```text
active Listen and Repeat item
  -> listening cue
  -> synthesize or load versioned audio
  -> ensure one terminal beep
  -> send voice
  -> speaking cue
  -> receive learner voice response
  -> existing STT, metrics, grading, and progression
```

## 6. Error Handling

- Empty `/check`: show usage; do not evaluate.
- Invalid LLM output: show a retry message; record nothing.
- Progress-recording failure: roll back all issues from that check and report failure rather than returning a review that appears saved.
- Oversized rendered feedback: split it at section boundaries into Telegram-safe messages; never cut HTML tags.
- Beep composition failure: treat audio preparation as failed and preserve the active item.
- Telegram voice-delivery failure: omit the speaking cue and preserve the active item.

## 7. Testing

Automated tests must cover:

- `/check <email>` invokes the standalone checker and renders all response sections;
- `/check` without email returns usage and skips the LLM;
- `/check` leaves an active attempt, current item, and deadline unchanged;
- a successful check records canonical Writing issues but creates no plan, attempt, item, or score;
- a failed or invalid evaluation records nothing;
- learner and evaluator content is HTML-safe;
- Listen and Repeat sends the listening cue, voice, waits for the audio duration plus the handoff margin, and then sends the speaking cue;
- the speaking cue appears only after successful voice delivery;
- fragmented primary TTS is regenerated with Austin before transcoding and delivery;
- delivered Listen and Repeat audio contains exactly one terminal beep for both cache hits and new synthesis;
- Interview audio receives no beep and keeps its deadline behavior;
- audio failure preserves the current item and omits the speaking cue;
- the existing practice-engine, evaluator, bot-view, TTS, and notifier tests continue to pass.

The standard quality gates remain:

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest
```

## 8. Non-goals

This change does not:

- infer a missing TOEFL email prompt;
- assign an official TOEFL score to standalone text;
- add a multi-message `/check` conversation state;
- create standalone-review history beyond the existing learning issues;
- enforce a hard 8–12-second Telegram recording cutoff;
- detect when a learner presses Play or finishes listening;
- change Interview timing, grading, or prompts.

## 9. Acceptance Criteria

The change is complete when the learner can send `/check` and an email in one message, receive actionable feedback plus a corrected version, and retain the resulting issues in the learning profile without disturbing daily practice. During every Listen and Repeat item, the learner receives an explicit listening cue, hears one terminal beep, and then receives an explicit speaking cue. Failures preserve the active item and never announce that speaking may begin without delivered audio.
