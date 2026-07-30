# TOEFL Daily Practice Bot Design

**Status:** Approved in conversation on July 30, 2026
**Scope:** Replace the current generic English practice bot with a focused TOEFL iBT Reading, Speaking, and Writing trainer.

## 1. Purpose

The bot gives one compact TOEFL task type per scheduled section instead of a full test section. It sends a daily plan at 08:00 Europe/Moscow, tracks each answer, updates a durable learning profile, and exports that profile on demand.

The product serves one learner. It favors dependable daily practice over broad tutoring features. The daily path must work when external sources or the LLM are unavailable.

## 2. Current-State Findings

The current bot does not simulate the updated TOEFL format. `/speak` and `/write` open an untimed conversation on a generic topic. Both modes use the same conversational loop and the same generic end-of-session evaluator. The scheduler alternates Speaking and Writing three times a week. It does not send daily Reading or Speaking practice, use TOEFL task mechanics, enforce task timers, or score with task-specific rubrics.

The current error diary provides a useful starting point. It stores errors, groups literal error strings, exports Markdown and CSV, and reports simple weekly counts. It cannot group equivalent error patterns, measure mastery, record Reading weaknesses, or distinguish improvement from relapse.

The repository still contains stale documentation and configuration from the deleted article, podcast, and older TOEFL flows. The implementation must remove those remnants.

## 3. Updated TOEFL Task Model

The design follows the TOEFL iBT format introduced on January 21, 2026.

| Section | Task type | Official full-section quantity | Practice block |
| --- | --- | ---: | --- |
| Speaking | Listen and Repeat | 7 items | 7 sentences |
| Speaking | Take an Interview | 4 items | 4 related questions, 45 seconds each |
| Reading | Complete the Words | adaptive section | 70–100 words, 10 missing word endings |
| Reading | Read in Daily Life | adaptive section | 15–150 words, 2–3 questions |
| Reading | Read an Academic Passage | adaptive section | about 200 words, 5 questions |
| Writing | Build a Sentence | 10 items | 10 items |
| Writing | Write an Email | 1 item | 1 response, 7 minutes |
| Writing | Write for an Academic Discussion | 1 item | 1 response, 10 minutes |

The official full sections contain 11 Speaking items in about 8 minutes and 12 Writing items in about 23 minutes. The updated Reading section is adaptive and contains about 35–48 items in 18–27 minutes. This bot practices one task type at a time and does not claim that a block score is an official section score.

Primary references:

- [TOEFL iBT 2026 Test Blueprint and Specifications](https://www.ets.org/content/dam/ets-india/pdfs/toefl/toefl-ibt-test-specifications-2026.pdf)
- [Updated TOEFL iBT Test Overview](https://www.ets.org/pdfs/toefl/toefl-ibt-test-overview.pdf)
- [TOEFL iBT Teacher Resources Practice Test 1](https://www.ets.org/content/dam/ets-org/pdfs/toefl/toefl-ibt-teachers-resources-practice-test-1.pdf)
- [TOEFL iBT Teacher Resources Practice Test 2](https://www.jp.ets.org/content/dam/ets-org/pdfs/toefl/toefl-ibt-teachers-resources-practice-test-2.pdf)
- [TOEFL Reading Lesson Plans](https://www.ets.org/content/dam/ets-org/pdfs/toefl/toefl-ibt-lesson-plan-reading.pdf)

## 4. Cadence and Daily Plan

The scheduler creates one plan for each local calendar day and sends it at 08:00 Europe/Moscow.

- Reading appears every day.
- Speaking appears every day.
- Writing appears every second calendar day.
- The first plan created after migration includes Writing. A persisted anchor date fixes the two-day rhythm; skipped or incomplete work never shifts it.
- Task types rotate independently within each section.
- The learner may complete the due sections in any order.
- Only one practice block may be active at a time.

The daily Telegram message shows each section with one state: `not started`, `in progress`, or `complete`. Buttons open the due blocks. `/today` returns the same durable plan and never creates duplicates.

## 5. Catalog-First Content

### 5.1 Base catalog

The repository ships with 60 calendar days of original, validated material:

- 30 Listen and Repeat blocks, totaling 210 sentences;
- 30 Interview blocks, totaling 120 questions;
- 20 Complete the Words blocks, totaling 200 gaps;
- 20 Daily Life blocks, totaling 40–60 questions;
- 20 Academic Passage blocks, totaling 100 questions;
- 10 Build a Sentence blocks, totaling 100 items;
- 10 Email prompts;
- 10 Academic Discussion prompts.

This distribution covers 60 days because Speaking alternates two task types, Reading rotates three task types, and Writing rotates three task types on its every-second-day schedule.

Each catalog record has a stable ID, version, section, task type, topic domain, target CEFR range, skill tags, prompt payload, answer key or rubric, explanation, provenance, source date, and validation state. The application validates every bundled record before it starts.

### 5.2 Topic balance

Reading material follows this target distribution:

- 50% science and technology;
- 25% history and social sciences;
- 25% daily-life notices, messages, schedules, forms, and instructions.

Academic topics may cover biology, ecology, animal behavior, astronomy, Earth science, psychology, history, archaeology, anthropology, engineering, art, film, economics, and society. Questions test main ideas, details, inference, vocabulary in context, purpose, relationships between ideas, and text structure. All required information must appear in the passage.

### 5.3 Source policy

The background catalog builder uses a configurable allowlist. Suitable default sources include NASA, NOAA, USGS, Smithsonian, university sites, and official public notices. Britannica is excluded by default because automated reuse may conflict with access and licensing restrictions.

The builder never republishes a source article. It extracts a bounded factual brief, generates an original TOEFL-style passage within the official length, and stores the source URL and retrieval date. Source pages are untrusted input: the fetcher strips active content, enforces size and timeout limits, and ignores instructions embedded in page text.

Speaking and Writing usually need no article. Their catalogs use original scenario templates modeled on ETS task progression:

- Listen and Repeat sentences grow in length and syntactic complexity within one campus scenario.
- Interview questions progress from factual experience to explanation, opinion, and a broader issue.
- Build a Sentence items come from a controlled grammar matrix with plausible distractors.
- Email prompts define audience, purpose, required points, and register.
- Academic Discussion prompts contain a professor's question and two distinct student positions.

### 5.4 Background replenishment

A weekly job maintains at least 14 unseen days beyond the bundled catalog.

1. Fetch a bounded brief from an allowed source when the task needs factual material.
2. Ask the LLM for a structured candidate.
3. Validate the schema, length, counts, answer uniqueness, evidence, and task rules in code.
4. Run a separate critic pass for source faithfulness, ambiguity, difficulty, and TOEFL fit.
5. Reject near-duplicates and failed candidates.
6. Store accepted tasks before they become eligible for practice.
7. Pre-generate audio for accepted Listen and Repeat and Interview prompts.

The practice path never waits for this job. When generation fails, the bot uses the bundled catalog. After all unseen items are exhausted, it starts a new cycle and prioritizes tasks linked to weak skills.

## 6. Architecture

The implementation keeps the existing Telegram, SQLite, LLM, STT, TTS, and notifier ports. It replaces the generic conversation layer with bounded modules:

- `practice`: task, plan, attempt, response, score, and learning-issue domain models;
- `catalog`: bundled catalog loader, selector, source metadata, validators, duplicate detection, and replenishment workflow;
- `reading`: the three Reading task runners and deterministic graders;
- `speaking`: audio delivery, response timing, transcription alignment, speech metrics, and rubric evaluation;
- `writing`: sentence builder and the two timed writing runners;
- `progress`: issue normalization, mastery transitions, skill statistics, reports, and exports;
- `bot`: commands, callbacks, daily-plan rendering, and resumable task orchestration;
- `scheduler`: idempotent daily-plan delivery, catalog replenishment, and pending evaluation retries.

SQLite owns plan and attempt state. Telegram FSM state may cache the active step, but a process restart must reconstruct it from SQLite.

## 7. Telegram Experience

### 7.1 Commands

- `/start`: register the learner and show today's plan;
- `/today`: show today's plan;
- `/reading`: open today's Reading block;
- `/speaking`: open today's Speaking block;
- `/writing`: open today's Writing block when due;
- `/progress`: show the current profile and trends;
- `/export [md|csv|json]`: export progress; Markdown is the default;
- `/cancel`: stop the active block without deleting saved answers;
- `/help`: explain the focused daily loop;
- `/reset`: erase progress after explicit confirmation.

The old `/speak`, `/write`, and `/coach` behaviors are removed.

### 7.2 Reading

Complete the Words sends one numbered passage. The learner replies with ten numbered completions in one message. The bot reports all results after submission.

Daily Life and Academic Passage send the text, then show one multiple-choice question at a time. The bot withholds correctness until the block ends so earlier feedback cannot reveal later answers. The final review gives the correct choice, evidence, and explanation for each missed item.

### 7.3 Speaking

Listen and Repeat sends seven audio prompts in sequence without visible transcripts. The learner may respond once to each prompt. The review later shows the source sentence, transcript, differences, and a 0–5 training score.

Interview sends one scenario and four prerecorded questions. Each question starts a 45-second response window and provides no preparation time. The bot records lateness, accepts the voice message, and advances. The review combines a 0–5 rubric estimate with focused feedback.

Telegram cannot prevent a learner from replaying an audio message. The bot preserves the exam order and hides transcripts but labels the experience as practice rather than a secure mock test.

### 7.4 Writing

Build a Sentence presents tappable fragments. The learner can undo the latest fragment, clear the answer, and submit. The bot scores all ten items at the end.

Email shows the scenario, audience, purpose, and required information, then starts a seven-minute timer. Academic Discussion shows the professor's question and two student posts, then starts a ten-minute timer. The first submitted response closes the task. If no text arrives before the deadline, the bot marks the response incomplete. Telegram cannot access an unsent draft.

### 7.5 Completion

Every block ends with a score, explanations, new or recurring learning issues, and these actions:

- `Fix mistakes`;
- `Next due section`;
- `Export`;
- `Back to today's plan`.

## 8. Evaluation

Reading and Build a Sentence use deterministic answer keys. Each scored item records the selected answer, correct answer, explanation, evidence, skill tag, and 0/1 result.

Listen and Repeat uses transcript alignment for omissions, substitutions, word order, and grammatical changes. Word timestamps, duration, pauses, and recognition confidence provide supporting intelligibility signals. The score follows the ETS 0–5 task description, but the bot reports it as an estimate because text transcription cannot fully measure pronunciation, rhythm, or intonation.

Interview evaluation combines the transcript with measurable speech signals. A structured LLM response assigns a 0–5 estimate and assesses relevance, elaboration, pace, intelligibility evidence, grammar, vocabulary, coherence, and task completion.

Email and Academic Discussion use separate 0–5 structured rubrics. Email includes communicative purpose, required details, register, organization, grammar, and vocabulary. Academic Discussion includes relevance, development, response to other views, academic tone, organization, grammar, and vocabulary.

The evaluator must return schema-validated data with criterion scores, strengths, issues, corrections, confidence, and a short explanation. It may not invent an official 1–6 section score from one practice block.

## 9. Dynamic Learning Profile

### 9.1 Learning issues

Speaking and Writing issues record the original excerpt, correction, explanation, category, canonical skill code, severity, evaluator confidence, attempt, task type, and date. Categories include grammar, vocabulary, phrasing, pronunciation, fluency, organization, and task fulfillment.

Reading issues record the selected answer, correct answer, explanation, evidence, question type, target skill, content domain, and date.

A fixed taxonomy and canonical pattern key group equivalent errors. Literal strings remain as examples, not identities.

### 9.2 Issue lifecycle

Issues move through these states:

`new -> recurring -> improving -> resolved`

A resolved issue becomes `relapsed` when it appears again. Three successful checks on separate local dates resolve a Speaking or Writing issue. A Reading skill becomes resolved after at least five opportunities with sustained accuracy of 80% or higher. New failures reopen the relevant skill.

The selector uses unresolved skills as a preference, not an absolute rule. Rotation and the no-repeat guarantee remain intact.

### 9.3 Progress view

`/progress` reports:

- daily-plan completion over 7, 30, and 60 days;
- raw scores and accuracy by TOEFL task type;
- active, improving, resolved, and relapsed issues;
- trends in accuracy and rubric scores;
- the skills that will receive more practice.

## 10. Export

`/export` sends a generated `toefl-progress.md` with the learner profile, recent trend, task-type results, active issues, resolved issues, relapses, and concrete examples.

`/export csv` sends a row-level attempt and issue history suitable for a spreadsheet. `/export json` sends a complete portable archive with schema version metadata. Exports reflect the latest committed attempts and issue transitions.

Anki export is removed. The new export module has no Anki dependency.

## 11. Persistence

The target schema contains these concepts:

- `catalog_task`: versioned task payload, provenance, eligibility, and validation state;
- `daily_plan`: local date, due sections, assigned task IDs, and completion states;
- `practice_attempt`: learner, task, timing, lifecycle, aggregate result, and evaluation state;
- `attempt_item`: prompt item, response, answer key data, score, feedback, and metrics;
- `learning_issue`: canonical issue identity, category, state, severity, and first/last occurrence;
- `issue_event`: occurrence, successful check, resolution, or relapse linked to an attempt;
- `skill_stat`: rolling opportunities, successes, accuracy, and trend;
- `catalog_generation_run`: source, generation result, validation failures, and cost diagnostics;
- `schedule_log`: scheduler diagnostics.

Migrations preserve existing `session_error` rows and convert them into learning issues and occurrence events. The migration is idempotent. It never deletes the existing database as part of deployment.

Temporary voice files are deleted after transcription. The database stores transcripts, timing metrics, scores, and feedback; it does not retain raw voice recordings by default.

## 12. Failure Handling

- Scheduler restarts cannot create duplicate daily plans or notifications.
- An unavailable source or LLM cannot block the bundled catalog.
- A failed open-response evaluation remains `pending` and enters a retry queue.
- A failed STT request preserves the attempt and offers `Retry transcription`.
- Missing generated audio makes a catalog item ineligible; selection chooses another item.
- Invalid or ambiguous generated tasks remain quarantined.
- Callback retries are idempotent and cannot submit one answer twice.
- A process restart resumes the exact active item and remaining task state.
- User-facing errors state what was saved and what action is available.

## 13. Removal and Migration Scope

Remove generic conversation topics, adaptive coach sessions, Anki integration, obsolete article/feed/podcast code, old worksheet flows, unused domain models, stale commands, and their dependencies. Keep only infrastructure required by the focused Reading, Speaking, Writing, progress, catalog, and deployment paths.

Update `README.md`, `.env.example`, deployment documentation, command registration, and help text to match the implemented product. Remove claims about deleted features.

## 14. Verification

Automated verification covers:

- every bundled catalog record;
- 60-day rotation, no-repeat behavior, and weak-skill preference;
- the 08:00 Europe/Moscow plan and calendar-based Writing cadence;
- idempotent scheduling and duplicate callbacks;
- all eight task runners and their timers;
- deterministic grading and structured rubric parsing;
- issue grouping, resolution, and relapse;
- legacy error migration;
- restart and resume behavior;
- Markdown, CSV, and JSON export;
- source, LLM, STT, TTS, and network failures;
- deletion of obsolete commands and dependencies.

The final gate runs catalog validation, focused tests throughout development, type checking, linting, and the full test suite. A local Telegram smoke test verifies the daily plan and one representative task from each section when credentials permit.

## 15. Acceptance Criteria

The work is complete when:

1. The bot sends one daily plan at 08:00 Europe/Moscow.
2. Reading and Speaking are due daily; Writing is due every second calendar day.
3. Each due section assigns one rotating TOEFL 2026 task type.
4. A fresh deployment has 60 days of original validated material and works without network access.
5. The weekly builder can add source-backed, validated tasks without blocking practice.
6. All eight task types run through their agreed Telegram mechanics.
7. Every completed attempt updates the dynamic learning profile.
8. `/progress` shows 7-, 30-, and 60-day trends and issue states.
9. `/export`, `/export csv`, and `/export json` return current files.
10. Existing Speaking and Writing errors survive migration.
11. Deleted features, commands, dependencies, and stale documentation are gone.
12. Catalog validation, linting, type checking, and the full test suite pass.
13. The final commit is pushed to `main`, triggering the existing GitHub deployment workflow.
