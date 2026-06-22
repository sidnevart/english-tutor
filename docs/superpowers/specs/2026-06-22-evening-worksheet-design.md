# Evening Worksheet Pipeline — Design Spec

## Problem

The current 20:00 `evening_reminder` is passive — it lists pending items and Anki card counts but provides no actual language practice. The user wants an active evening practice session in TOEFL iBT format, with exercises generated from today's materials and real speaking errors.

## Solution

A new `worksheet` pipeline that generates a printable exercise sheet at 20:00, sends it as MD + PDF, and grades the user's answers when they send the completed file back.

## User Flow

```
20:00 → Bot sends worksheet (MD + PDF)
     → User downloads, fills in answers offline
     → User sends completed file back to bot
     → Bot parses answers, grades, sends feedback
```

## Exercise Types

| Type | Count | Data Source | TOEFL Section |
|------|-------|------------|---------------|
| Fill in the blanks | 5-7 | Today's `vocab_item` | Vocabulary in Context |
| Error correction | 3-5 | Today's `session_error` | Writing/Speaking review |
| Sentence transformation | 2-3 | Today's `content_item.body_text` | Writing (paraphrase) |
| Mini reading comprehension | 1 passage, 3 questions | Today's article | Reading |
| Collocation match | 5 | Vocabulary + LLM | Vocabulary |

**Total: 18-23 exercises per evening.**

## Data Collection

All data is sourced from today's activities:

| What | Where | How |
|------|-------|-----|
| 10-15 vocabulary words | `vocab_item` table, filtered by today's `content_item` | SQL query |
| 3-5 real errors | `session_error` table, filtered by today | SQL query |
| 1-2 article excerpts | `content_item.body_text`, today's articles | SQL query |
| Collocations | LLM generates from vocabulary | LLM call |

## Data Model

### New table: `worksheet`

```sql
CREATE TABLE worksheet (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    items_json  TEXT NOT NULL,   -- JSON with all exercise items
    answers     TEXT DEFAULT '', -- user's answers (when submitted)
    score       REAL,            -- total score 0.0-1.0
    feedback    TEXT DEFAULT '', -- LLM-generated feedback
    status      TEXT NOT NULL DEFAULT 'pending'  -- pending | submitted | graded
);
CREATE INDEX ix_worksheet_user ON worksheet (user_id, created_at);
```

### `items_json` structure

```json
{
  "fill_blanks": [
    {
      "sentence": "Scientists have raised ________ about the effects of global warming.",
      "options": ["concerns", "questions", "issues", "problems"],
      "correct_index": 0,
      "source_word": "concerns",
      "source_vocab_id": 42
    }
  ],
  "error_correction": [
    {
      "sentence": "The circulation is driven by differences in water density, that are determined by temperature.",
      "error_span": "that",
      "correction": "which",
      "rule": "Non-restrictive relative clause requires 'which', not 'that'",
      "source_error_id": 15
    }
  ],
  "sentence_transform": [
    {
      "original": "The Neolithic Revolution was neither sudden nor uniformly beneficial.",
      "model_answer": "The transition to agriculture happened gradually and had both positive and negative effects.",
      "key_point": "Paraphrase 'neither...nor' + 'uniformly beneficial'"
    }
  ],
  "mini_reading": [
    {
      "passage_excerpt": "Ocean currents play a crucial role...",
      "source_content_id": 7,
      "questions": [
        {
          "prompt": "What is the main idea of the passage?",
          "options": ["A", "B", "C", "D"],
          "correct_index": 0,
          "explanation": "..."
        }
      ]
    }
  ],
  "collocation_match": [
    {
      "word": "conduct",
      "correct_partner": "research",
      "distractors": ["study", "experiment", "analysis"]
    }
  ]
}
```

## Pipeline

### Generation (scheduled, 20:00)

```python
async def evening_worksheet(svc: Services, user_id: int) -> None:
    # 1. Collect today's data
    vocab = svc.repo.get_vocab_today(user_id)          # 10-15 words
    errors = svc.repo.recent_session_errors(user_id)    # 3-5 errors
    articles = svc.repo.fetch_today_articles(user_id)   # 1-2 articles

    # 2. Generate exercises via LLM
    items = await generate_worksheet(svc.llm, vocab, errors, articles)

    # 3. Render to MD + PDF
    md_content = render_worksheet_md(items, date=today)
    pdf_path = render_worksheet_pdf(md_content)

    # 4. Save to DB
    worksheet_id = svc.repo.save_worksheet(user_id, items)

    # 5. Send files
    await svc.notifier.send(user_id, "📝 Your evening worksheet is ready!")
    await svc.notifier.send_file(user_id, md_path, caption="Markdown version")
    await svc.notifier.send_file(user_id, pdf_path, caption="PDF version — print it or fill digitally")
```

### Grading (user sends file back)

```python
async def grade_worksheet_file(svc: Services, user_id: int, file_content: str) -> None:
    # 1. Get the latest pending worksheet from DB
    worksheet = svc.repo.get_latest_worksheet(user_id, status="pending")
    if not worksheet:
        await svc.notifier.send(user_id, "No pending worksheet found.")
        return

    # 2. Parse answers from file
    answers = parse_answers_from_md(file_content, worksheet.items_json)

    # 3. Grade
    score, feedback = await grade_worksheet(svc.llm, worksheet.items_json, answers)

    # 4. Save results
    svc.repo.update_worksheet_grade(worksheet.id, answers, score, feedback)

    # 5. Send feedback
    await svc.notifier.send(user_id, feedback)
```

## File Formats

### Markdown

```markdown
# 📝 Evening Worksheet — 2026-06-22

## Instructions
Fill in your answers below each question. Send this file back to the bot
when you're done. You can type your answers or write them by hand and
send a photo (we'll add OCR support later).

---

## Part 1: Fill in the Blanks (7 questions)
*Based on today's vocabulary from: "Ocean Currents and Climate"*

1. Scientists have raised ________ about the effects of global warming.
   - A) concerns  B) questions  C) issues  D) problems
   **Your answer:** ____

...

## Part 2: Error Correction (4 questions)
*Based on your speaking session errors today*

1. ❌ "The circulation is driven by differences in water density,
   that are determined by temperature."
   **Correct:** _________________________________
   **Rule:** _________________________________

...

## Part 3: Sentence Transformation (2 questions)
*Rewrite the sentence without changing its meaning.*

1. Original: "The Neolithic Revolution was neither sudden nor
   uniformly beneficial."
   Your version: _________________________________

...

## Part 4: Mini Reading Comprehension
*Read the passage and answer the questions.*

[PASSAGE - 150-200 words from today's article]

1. What is the main idea?
   A) ... B) ... C) ... D) ...
   **Your answer:** ____

...

## Part 5: Collocation Match (5 items)
*Match each word with its natural partner.*

| Word | Partner (write letter) |
|------|----------------------|
| conduct | A) research |
| pose | B) conclusions |
| draw | C) a threat |

---

## Summary
- Total time: ____ minutes
- Difficulty (1-5): ____
- Notes: _________________________________
```

### PDF

Same content, rendered via `weasyprint` (HTML → PDF) with:
- A4 page size
- Clean typography
- Adequate margins for handwriting
- Answer fields with underlines

## LLM Prompts

### Generation prompt

```
You are a TOEFL iBT preparation exercise writer. Generate a set of
practice exercises based on the learner's today materials and errors.

INPUT:
- Today's vocabulary: [list from vocab_item]
- Today's errors: [list from session_error]
- Today's article text: [body_text from content_item]

OUTPUT (JSON matching the items_json schema):
{
  "fill_blanks": [...],
  "error_correction": [...],
  "sentence_transform": [...],
  "mini_reading": [...],
  "collocation_match": [...]
}

RULES:
- All exercises MUST use content from the input data
- Fill in the blanks: test vocabulary IN CONTEXT, not just definitions.
  The sentence should make the meaning clear. 4 options per question.
- Error correction: use REAL errors from the learner's sessions.
  If no errors today, generate common B2-C1 grammar traps.
- Sentence transformation: test paraphrasing skills (TOEFL Writing).
  Provide a model answer and the key paraphrasing technique.
- Mini reading: use a 150-200 word excerpt from today's article.
  Generate 3 questions matching TOEFL Reading format.
- Collocation match: pair words with their natural academic partners.
  Include 3 distractors per word.
- Difficulty: B2-C1 (TOEFL level)
- All text in English
```

### Grading prompt

```
You are a TOEFL preparation grader. The learner completed a worksheet
and sent back their answers. Grade each answer and provide feedback.

INPUT:
- Worksheet questions (JSON from DB)
- Learner's answers (parsed from file)

OUTPUT:
- Score per section (fill_blanks, error_correction, etc.)
- Total score (0.0-1.0)
- Specific feedback on each mistake
- 2-3 things to review tomorrow

Be encouraging but honest. Focus on patterns, not individual errors.
```

## Answer Parsing

The parser extracts answers from the filled-in MD file using regex patterns:

| Question Type | Pattern in Template | Regex to Extract |
|--------------|-------------------|------------------|
| Fill in the blanks | `**Your answer:** ____` | `r'\*\*Your answer:\*\*\s*(.+)'` |
| Error correction | `**Correct:** ____` | `r'\*\*Correct:\*\*\s*(.+)'` |
| Sentence transformation | `Your version: ____` | `r'Your version:\s*(.+)'` |
| Collocation match | `| word | A) partner |` | Parse table rows, extract letter |

The parser is lenient:
- Strips whitespace from extracted answers
- Normalizes case (A → a)
- Accepts letter answers (A, B, C, D) or full text
- Missing answers → marked as incorrect
- Partial answers → scored proportionally

**Answer format the user fills in:**
- Multiple choice: type the letter (A, B, C, D) after `**Your answer:**`
- Error correction: type the corrected sentence after `**Correct:**`
- Sentence transformation: type the rewritten sentence after `Your version:`
- Collocation match: type the matching letter in the table cell

## Bot Integration

### New handler: document接收

```python
@router.message(F.document)
async def on_document(message: Message) -> None:
    """Handle worksheet file submission."""
    if not message.document.file_name.endswith(('.md', '.txt')):
        await message.answer("Please send a .md or .txt file.")
        return
    file = await bot.get_file(message.document.file_id)
    content = await bot.download_file(file.file_path)
    await grade_worksheet_file(svc, message.from_user.id, content.decode())
```

### Config additions

```python
worksheet_enabled: bool = True
worksheet_cron: str = "0 20 * * *"  # same as evening_cron
```

## Dependencies

- `weasyprint` — HTML → PDF rendering
- No new external APIs

## Testing Strategy

1. **Unit tests**: `parse_answers_from_md()` with known MD files
2. **Integration tests**: `generate_worksheet()` with StubLLM
3. **Eval tests**: `generate_worksheet()` with real LLM + judge
4. **E2E test**: Full flow from generation to grading

## File Structure

```
src/tutor/
├── worksheet/
│   ├── __init__.py
│   ├── generator.py      # generate_worksheet()
│   ├── renderer.py        # render_worksheet_md() + render_worksheet_pdf()
│   ├── parser.py          # parse_answers_from_md()
│   └── grader.py          # grade_worksheet()
├── db/
│   ├── schema.sql         # + worksheet table
│   └── repository.py      # + save_worksheet, get_worksheet, etc.
├── scheduler/
│   └── jobs.py            # + evening_worksheet()
└── bot/
    └── handlers.py        # + document handler
```
