# Unique Listen and Repeat Catalog

## Problem

The planner rotates unique task IDs, but every bundled Listen and Repeat task shares four sentences. The learner therefore hears repeated content on different days even though the database records different tasks. Existing tests check task-ID uniqueness and sentence count; they do not check content uniqueness across tasks.

## Approaches

### 1. Author complete sentence sets

Store seven scenario-specific sentences for each of the 30 tasks. This produces natural prompts and permits deliberate progression from short to complex sentences. It adds catalog data, but the data stays deterministic and reviewable.

### 2. Combine sentence templates

Generate sentences from interchangeable openings, actions, locations, and instructions. This requires less data, but mechanical combinations can sound unnatural and remain semantically repetitive.

### 3. Generate prompts at runtime

Ask the LLM for new sentences before practice. This avoids a large bundled catalog, but adds latency, cost, nondeterminism, and a new failure mode to daily practice.

Use approach 1. The bundled catalog must remain available without network access, and prompt quality matters more than minimizing source data.

## Design

Replace the scenario-only Listen and Repeat factory with 30 explicit sentence sets. Each set contains seven sentences tied to one campus scenario. Sentences progress from short statements to longer instructions and preserve the current TOEFL-style task shape.

Keep existing task IDs so current plans and attempts remain valid. Startup catalog synchronization refreshes each task's payload. Change synthesized-audio paths from `audio_cache/tts-v2` to `audio_cache/tts-v3` and cue paths from `audio_cache/listen-repeat-cue-v2` to `audio_cache/listen-repeat-cue-v3`; the bot will regenerate audio for changed text instead of serving stale files.

Catalog validation must normalize Listen and Repeat sentences by trimming whitespace and applying case folding. It must reject:

- duplicate sentences within one task;
- duplicate sentences across the bundled Listen and Repeat catalog.

Per-task structural validation remains responsible for seven non-empty strings. A bundled-catalog test owns the cross-task invariant because a single-task validator cannot see neighboring tasks.

## Verification

Automated checks must prove that:

- all 210 bundled Listen and Repeat sentences are unique after normalization;
- every task still contains seven sentences;
- the 60-day planner rotation still uses unique task IDs;
- the catalog contains 150 valid tasks;
- audio delivery uses only the version-three cache paths;
- all existing bot, evaluator, catalog, and practice tests pass.

The fix is complete when consecutive Listen and Repeat tasks contain no identical sentence and production regenerates their audio from the new payloads.
