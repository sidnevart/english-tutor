"""The deterministic 60-day base catalog.

The material is generated from checked-in editorial seeds, not from an LLM at
practice time. Stable IDs make rotations and persisted attempts reproducible.
"""
# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass

from tutor.catalog.validation import validate_task
from tutor.practice.models import CatalogTask, Section, TaskType

SCENARIOS = [
    "library orientation",
    "biology laboratory",
    "campus shuttle",
    "student health center",
    "art exhibition",
    "career workshop",
    "astronomy club",
    "recycling program",
    "language exchange",
    "music rehearsal",
    "research symposium",
    "sports center",
    "museum visit",
    "volunteer fair",
    "housing office",
    "computer laboratory",
    "field trip",
    "student newspaper",
    "theater production",
    "study group",
    "campus garden",
    "photography course",
    "history archive",
    "engineering showcase",
    "international festival",
    "tutoring center",
    "book discussion",
    "science lecture",
    "film screening",
    "community survey",
]

ACADEMIC_TOPICS = [
    (
        "urban birds",
        "ecology",
        "Some city birds adjust their calls when traffic noise masks low sounds.",
    ),
    (
        "water on Mars",
        "astronomy",
        "Mineral deposits show that liquid water once moved across parts of Mars.",
    ),
    (
        "animal sleep",
        "biology",
        "Different animals divide sleep into patterns that fit their need to feed and avoid danger.",
    ),
    (
        "ancient aqueducts",
        "history",
        "Gravity carried water through carefully graded channels in several ancient cities.",
    ),
    (
        "early photography",
        "art",
        "Shorter exposure times gradually made photography useful outside controlled studios.",
    ),
    (
        "coral recovery",
        "ecology",
        "Reef recovery depends on water quality, temperature, and the arrival of young corals.",
    ),
    (
        "volcanic islands",
        "earth science",
        "Repeated eruptions can build islands that are later reshaped by waves and erosion.",
    ),
    (
        "memory cues",
        "psychology",
        "People often recall information more easily when the learning context is recreated.",
    ),
    (
        "bee navigation",
        "biology",
        "Bees combine sunlight, landmarks, and learned routes when returning to food.",
    ),
    (
        "solar panels",
        "engineering",
        "Panel angle and local weather both influence how much electricity a system produces.",
    ),
    (
        "trade routes",
        "history",
        "Long-distance trade moved ideas and techniques as well as physical goods.",
    ),
    (
        "language change",
        "society",
        "Frequent contact between communities can spread words and grammatical patterns.",
    ),
    (
        "ocean currents",
        "earth science",
        "Winds and differences in water density help drive large ocean currents.",
    ),
    (
        "plant defenses",
        "biology",
        "Plants use physical barriers and chemical signals to reduce damage from insects.",
    ),
    (
        "public parks",
        "society",
        "The design of paths and seating affects how people share urban public space.",
    ),
    (
        "cave paintings",
        "archaeology",
        "Pigments and placement offer clues about how ancient groups used decorated caves.",
    ),
    (
        "robot sensors",
        "technology",
        "Robots combine several imperfect sensors to estimate their position.",
    ),
    (
        "child learning",
        "psychology",
        "Children test informal predictions while playing with unfamiliar objects.",
    ),
    (
        "wetland restoration",
        "ecology",
        "Restored wetlands can slow floodwater and create habitat for many species.",
    ),
    (
        "history of film",
        "art",
        "Editing allowed filmmakers to connect scenes recorded at different times and places.",
    ),
]

DAILY_CONTEXTS = [
    "library closing",
    "room change",
    "shuttle delay",
    "maintenance notice",
    "club registration",
    "event booking",
    "package pickup",
    "course waitlist",
    "lost property",
    "equipment return",
    "volunteer shift",
    "internet outage",
    "museum ticket",
    "study-room policy",
    "cafeteria hours",
    "workshop reminder",
    "housing inspection",
    "sports cancellation",
    "printing credit",
    "guest lecture",
]


def _question(stem: str, correct: str, distractors: list[str], skill: str, evidence: str) -> dict:
    return {
        "stem": stem,
        "options": [correct, *distractors],
        "correct": 0,
        "skill": skill,
        "evidence": evidence,
        "explanation": f"The text directly supports: {evidence}",
    }


def _listen_repeat(index: int, scenario: str) -> CatalogTask:
    place = scenario.title()
    sentences = [
        f"Welcome to the {scenario}.",
        "Please keep your student card with you.",
        "The first activity begins near the main entrance.",
        "You can ask a staff member if you need directions.",
        "Before the session starts, place your bag beside your chair.",
        f"Because the {scenario} is popular, arriving a few minutes early is recommended.",
        f"After everyone has completed the {scenario}, the coordinator will explain where the follow-up materials can be found.",
    ]
    return CatalogTask(
        id=f"sp-lr-{index:02d}",
        section=Section.SPEAKING,
        task_type=TaskType.LISTEN_REPEAT,
        topic_domain="campus",
        skill_tags=["intelligibility", "word_order", "grammar"],
        payload={"title": place, "sentences": sentences},
        explanation="Repeat each sentence once, preserving meaning and word order.",
    )


def _interview(index: int, scenario: str) -> CatalogTask:
    return CatalogTask(
        id=f"sp-in-{index:02d}",
        section=Section.SPEAKING,
        task_type=TaskType.INTERVIEW,
        topic_domain="campus_and_society",
        skill_tags=["relevance", "elaboration", "fluency"],
        payload={
            "scenario": f"A university researcher is interviewing students about {scenario}.",
            "questions": [
                f"What experience have you had with {scenario}?",
                f"What makes a {scenario} useful or enjoyable for students?",
                f"Should universities invest more time or money in {scenario}? Why?",
                f"How might {scenario} change the wider community in the future?",
            ],
            "seconds_per_question": 45,
            "rubric": "0-5: delivery, language use, topic development, and task completion",
        },
    )


def _complete_words(index: int, topic: tuple[str, str, str]) -> CatalogTask:
    name, domain, fact = topic
    word_sets = (
        (
            "studying",
            "evidence",
            "compare",
            "record",
            "explanation",
            "pattern",
            "report",
            "check",
            "process",
            "change",
        ),
        (
            "examining",
            "information",
            "contrast",
            "document",
            "interpretation",
            "tendency",
            "publish",
            "verify",
            "procedure",
            "variation",
        ),
        (
            "observing",
            "measurements",
            "review",
            "describe",
            "account",
            "sequence",
            "present",
            "confirm",
            "method",
            "difference",
        ),
        (
            "investigating",
            "observations",
            "connect",
            "register",
            "proposal",
            "relationship",
            "share",
            "inspect",
            "approach",
            "shift",
        ),
        (
            "analyzing",
            "records",
            "evaluate",
            "note",
            "hypothesis",
            "structure",
            "summarize",
            "test",
            "technique",
            "fluctuation",
        ),
        (
            "exploring",
            "samples",
            "match",
            "archive",
            "model",
            "distribution",
            "release",
            "repeat",
            "strategy",
            "transition",
        ),
        (
            "tracking",
            "findings",
            "combine",
            "log",
            "conclusion",
            "trend",
            "communicate",
            "assess",
            "routine",
            "development",
        ),
        (
            "surveying",
            "material",
            "separate",
            "list",
            "reasoning",
            "arrangement",
            "outline",
            "validate",
            "system",
            "adjustment",
        ),
        (
            "documenting",
            "indicators",
            "relate",
            "collect",
            "framework",
            "cycle",
            "announce",
            "examine",
            "protocol",
            "movement",
        ),
        (
            "monitoring",
            "traces",
            "classify",
            "store",
            "theory",
            "formation",
            "state",
            "recheck",
            "practice",
            "alteration",
        ),
        (
            "reviewing",
            "reports",
            "measure",
            "capture",
            "description",
            "progression",
            "explain",
            "replicate",
            "workflow",
            "divergence",
        ),
        (
            "testing",
            "results",
            "compare",
            "write",
            "prediction",
            "configuration",
            "disclose",
            "audit",
            "sequence",
            "revision",
        ),
        (
            "mapping",
            "signals",
            "contrast",
            "trace",
            "claim",
            "network",
            "circulate",
            "corroborate",
            "operation",
            "departure",
        ),
        (
            "measuring",
            "details",
            "review",
            "report",
            "inference",
            "regularity",
            "describe",
            "authenticate",
            "analysis",
            "modification",
        ),
        (
            "comparing",
            "documents",
            "connect",
            "record",
            "argument",
            "organization",
            "publish",
            "substantiate",
            "investigation",
            "turn",
        ),
        (
            "researching",
            "statistics",
            "evaluate",
            "document",
            "assessment",
            "profile",
            "present",
            "crosscheck",
            "study",
            "conversion",
        ),
        (
            "evaluating",
            "readings",
            "match",
            "describe",
            "explanation",
            "series",
            "share",
            "verify",
            "inquiry",
            "change",
        ),
        (
            "inspecting",
            "images",
            "combine",
            "register",
            "interpretation",
            "pattern",
            "release",
            "confirm",
            "process",
            "variation",
        ),
        (
            "recording",
            "estimates",
            "separate",
            "note",
            "account",
            "tendency",
            "communicate",
            "test",
            "procedure",
            "difference",
        ),
        (
            "assessing",
            "accounts",
            "relate",
            "archive",
            "proposal",
            "sequence",
            "summarize",
            "repeat",
            "method",
            "shift",
        ),
    )

    def gap(word: str) -> tuple[str, str]:
        split = min(len(word) - 1, max(2, len(word) // 2))
        return word[:split] + "_" * (len(word) - split), word[split:]

    words = word_sets[index - 1]
    gaps, answers = zip(*(gap(word) for word in words), strict=True)
    passage = (
        f"Researchers {gaps[0]} {name} use several kinds of {gaps[1]}. {fact} They {gaps[2]} "
        f"observations from different places and {gaps[3]} how conditions change over time. A useful "
        f"{gaps[4]} must account for the whole {gaps[5]}, not only one unusual example. Scientists "
        f"also {gaps[6]} their methods so other teams can {gaps[7]} the results. This careful "
        f"{gaps[8]} helps separate a lasting trend from a temporary {gaps[9]} and makes the final "
        "conclusion more reliable for readers."
    )
    return CatalogTask(
        id=f"rd-cw-{index:02d}",
        section=Section.READING,
        task_type=TaskType.COMPLETE_WORDS,
        topic_domain=domain,
        skill_tags=["vocabulary_in_context", "grammar", "cohesion"],
        payload={"title": name.title(), "passage": passage, "answers": list(answers)},
    )


def _daily_life(index: int, context: str) -> CatalogTask:
    day = (index % 20) + 2
    passage = (
        f"Subject: {context.title()} update. The original arrangement for August {day} has changed. "
        "Please use Room 204 at 3:30 p.m. instead of the location printed in the first message. "
        "Bring your confirmation email and arrive ten minutes early. If you cannot attend, reply by noon tomorrow so the available place can be offered to another student."
    )
    return CatalogTask(
        id=f"rd-dl-{index:02d}",
        section=Section.READING,
        task_type=TaskType.DAILY_LIFE,
        topic_domain="daily_life",
        skill_tags=["purpose", "detail", "next_action"],
        payload={
            "title": context.title(),
            "passage": passage,
            "questions": [
                _question(
                    "Why was this message sent?",
                    "To announce a changed arrangement",
                    ["To advertise a new course", "To request payment"],
                    "purpose",
                    "The original arrangement has changed.",
                ),
                _question(
                    "What should an attendee bring?",
                    "A confirmation email",
                    ["A printed schedule", "A student essay"],
                    "detail",
                    "Bring your confirmation email.",
                ),
                _question(
                    "What should a student do if unable to attend?",
                    "Reply by noon tomorrow",
                    ["Visit Room 204", "Call after the event"],
                    "next_action",
                    "Reply by noon tomorrow.",
                ),
            ],
        },
    )


def _academic(index: int, topic: tuple[str, str, str]) -> CatalogTask:
    name, domain, fact = topic
    passage = (
        f"Researchers interested in {name} begin with a practical question: how can a broad pattern be distinguished from a local accident? {fact} "
        "A single observation, however, rarely explains why the pattern occurs. Investigators therefore compare sites, time periods, or groups that differ in a limited number of conditions. This comparison helps them identify which factors are consistently associated with the result.\n\n"
        "Measurement also matters. A method that works well in one setting may miss important changes in another, so teams often combine direct observations with records collected over longer periods. They describe their procedures carefully, allowing other researchers to repeat the work or challenge an interpretation. Unexpected results are not simply discarded; they may reveal that an earlier explanation was too narrow.\n\n"
        "Finally, researchers connect the evidence to a claim whose strength matches the data. They distinguish correlation from cause and note limits in place, sample, or duration. This cautious approach can make a conclusion sound less dramatic, but it makes the knowledge more useful. Later studies can then test a precise idea instead of starting again with an unsupported assumption."
    )
    questions = [
        _question(
            "What is the passage mainly about?",
            f"How researchers build reliable explanations of {name}",
            ["Why research should avoid comparison", "How one discovery ended a debate"],
            "main_idea",
            "The passage describes comparison, measurement, replication, and cautious claims.",
        ),
        _question(
            "Why do investigators compare sites or groups?",
            "To identify consistently related factors",
            ["To remove all unexpected evidence", "To shorten every study"],
            "purpose",
            "Comparison helps identify consistently associated factors.",
        ),
        _question(
            "What can unexpected results indicate?",
            "An earlier explanation was too narrow",
            ["The measurements must be hidden", "No further study is possible"],
            "inference",
            "Unexpected results may reveal a narrow explanation.",
        ),
        _question(
            "The word 'precise' is closest in meaning to",
            "specific",
            ["popular", "temporary"],
            "vocabulary_in_context",
            "A precise idea is a specific, clearly defined idea.",
        ),
        _question(
            "Which claim is supported by the passage?",
            "Useful conclusions acknowledge limits",
            ["Strong claims require only one observation", "Replication makes methods less clear"],
            "detail",
            "Researchers note limits in place, sample, or duration.",
        ),
    ]
    return CatalogTask(
        id=f"rd-ap-{index:02d}",
        section=Section.READING,
        task_type=TaskType.ACADEMIC_PASSAGE,
        topic_domain=domain,
        skill_tags=["main_idea", "detail", "inference", "purpose", "vocabulary_in_context"],
        payload={"title": name.title(), "passage": passage, "questions": questions},
    )


GRAMMAR_SUBJECTS = [
    "The advisor",
    "The research team",
    "The museum director",
    "The student committee",
    "The laboratory assistant",
    "The course instructor",
    "The city planner",
    "The archive manager",
    "The workshop leader",
    "The campus librarian",
]

GRAMMAR_PREDICATES = [
    ("recommended", "that participants submit", "the form early"),
    ("confirmed", "that the results were", "ready for review"),
    ("explained", "why the schedule had", "changed unexpectedly"),
    ("asked whether", "the proposal could be", "revised by Friday"),
    ("reported", "that attendance had increased", "during the summer"),
    ("decided", "to extend the program", "for another month"),
    ("noted", "that the new procedure was", "easier to follow"),
    ("promised", "to send the updated materials", "after the meeting"),
    ("discovered", "that one record had been", "filed incorrectly"),
    ("suggested", "using a quieter room", "for the interview"),
]


def _build_sentence(index: int) -> CatalogTask:
    items = []
    for offset in range(10):
        parts = (GRAMMAR_SUBJECTS[index - 1], *GRAMMAR_PREDICATES[offset])
        items.append(
            {"fragments": list(reversed(parts)), "answer": " ".join(parts) + ".", "skill": "syntax"}
        )
    return CatalogTask(
        id=f"wr-bs-{index:02d}",
        section=Section.WRITING,
        task_type=TaskType.BUILD_SENTENCE,
        topic_domain="academic_and_campus",
        skill_tags=["syntax", "word_order"],
        payload={"items": items},
    )


def _email(index: int, scenario: str) -> CatalogTask:
    return CatalogTask(
        id=f"wr-em-{index:02d}",
        section=Section.WRITING,
        task_type=TaskType.EMAIL,
        topic_domain="campus",
        skill_tags=["purpose", "register", "organization"],
        payload={
            "scenario": f"You need help from the coordinator of the {scenario}.",
            "audience": "University coordinator",
            "purpose": "Request a practical change",
            "required_points": [
                "explain the situation",
                "request a specific solution",
                "suggest an alternative",
            ],
            "minutes": 7,
            "rubric": "0-5: communicative purpose, required details, register, organization, grammar, vocabulary",
        },
    )


def _discussion(index: int, topic: tuple[str, str, str]) -> CatalogTask:
    name, domain, _ = topic
    return CatalogTask(
        id=f"wr-ad-{index:02d}",
        section=Section.WRITING,
        task_type=TaskType.ACADEMIC_DISCUSSION,
        topic_domain=domain,
        skill_tags=["development", "academic_tone", "response_to_views"],
        payload={
            "professor": f"What is the most important consideration when society makes decisions about {name}?",
            "student_a": "Leah: Decision makers should prioritize measurable long-term benefits, even when the initial cost is high.",
            "student_b": "Omar: Local experience and immediate community needs should receive more attention than broad forecasts.",
            "minutes": 10,
            "rubric": "0-5: relevance, development, response to views, academic tone, organization, grammar, vocabulary",
        },
    )


def _build_tasks() -> list[CatalogTask]:
    tasks: list[CatalogTask] = []
    for i, scenario in enumerate(SCENARIOS, 1):
        tasks.extend((_listen_repeat(i, scenario), _interview(i, scenario)))
    for i, topic in enumerate(ACADEMIC_TOPICS, 1):
        tasks.extend((_complete_words(i, topic), _academic(i, topic)))
    for i, context in enumerate(DAILY_CONTEXTS, 1):
        tasks.append(_daily_life(i, context))
    for i in range(1, 11):
        tasks.extend(
            (
                _build_sentence(i),
                _email(i, SCENARIOS[i - 1]),
                _discussion(i, ACADEMIC_TOPICS[i - 1]),
            )
        )
    return tasks


@dataclass(frozen=True)
class BundledCatalog:
    tasks: tuple[CatalogTask, ...]

    @classmethod
    def load(cls) -> BundledCatalog:
        return cls(tuple(_build_tasks()))

    def validate(self) -> list[str]:
        errors: list[str] = []
        ids: set[str] = set()
        for task in self.tasks:
            if task.id in ids:
                errors.append(f"duplicate id: {task.id}")
            ids.add(task.id)
            errors.extend(f"{task.id}: {error}" for error in validate_task(task))
        return errors

    def select(
        self,
        section: Section,
        task_type: TaskType,
        *,
        seen_ids: set[str] | None = None,
        weak_skills: set[str] | None = None,
    ) -> CatalogTask:
        seen_ids = seen_ids or set()
        weak_skills = weak_skills or set()
        candidates = [t for t in self.tasks if t.section is section and t.task_type is task_type]
        unseen = [t for t in candidates if t.id not in seen_ids]
        pool = unseen or candidates
        return max(
            pool,
            key=lambda task: (len(set(task.skill_tags) & weak_skills), -candidates.index(task)),
        )
