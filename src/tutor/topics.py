"""Static topic pools for speaking & writing practice.

Topics are curated (not LLM-generated) so a scheduled push can always start a
session reliably and for free, even when the LLM backend is down. The LLM is
used for the conversational turns and for end-of-session error extraction — not
for picking what to talk about.

`pick_topic(kind, index)` is pure and deterministic: it cycles the pool by
`index`. Callers persist `index` in `subscriber.prefs_json` (see
`Repository.get_pref`/`set_pref`) so practice rotates through the whole pool
instead of repeating.
"""

from __future__ import annotations

SPEAKING_TOPICS: list[str] = [
    "Describe a skill you'd like to learn and why it interests you.",
    "Should cities ban private cars from the centre? Give your view.",
    "Talk about a book, film, or show that changed how you think about something.",
    "Describe a person who has influenced you and explain how.",
    "What does a typical morning look like for you? Walk me through it.",
    "Is it better to work from home or from an office? Why?",
    "Tell me about a place you'd love to travel to and what you'd do there.",
    "Describe a difficult decision you had to make and how it turned out.",
    "What's a habit that has improved your life? Explain it.",
    "Do you think social media does more harm than good? Argue your side.",
    "Talk about something you're proud of — big or small.",
    "If you could have dinner with any person, alive or historical, who and why?",
    "Describe your job or studies to someone who knows nothing about them.",
    "What's the best piece of advice you've ever received?",
    "How do you usually spend your weekends? Describe a recent one.",
    "Should education focus more on practical skills or theory? Why?",
    "Talk about a time you failed at something and what you learned.",
    "What technology has changed your daily life the most?",
    "Describe a tradition or holiday that matters to you.",
    "Is it more important to be happy or to be successful? Defend your view.",
    "Tell me about a goal you're working towards right now.",
    "What do you value most in a friendship, and why?",
    "Describe the area where you grew up — what was it like?",
    "Do you prefer mountains, cities, or beaches? Explain your preference.",
    "Talk about a news story that caught your attention recently.",
    "What's something you used to believe but have changed your mind about?",
    "Describe a meal you love and how it's prepared.",
    "How do you handle stress? Share what works for you.",
    "If you had a free year and unlimited money, what would you do?",
    "What's a small thing that makes your day better?",
]

WRITING_TOPICS: list[str] = [
    "Write a short paragraph arguing for or against remote work.",
    "Describe a problem in your city and propose one realistic solution.",
    "Write a review of a product, app, or service you use often.",
    "Imagine you're writing to a friend who's moving to your city — give them advice.",
    "Write about a lesson you learned the hard way.",
    "Argue whether schools should teach coding to every student.",
    "Describe your ideal job and what makes it ideal.",
    "Write a short opinion piece: is AI a threat or an opportunity?",
    "Narrate a memorable day from your life in a few paragraphs.",
    "Write a comparison of two places you've lived in or visited.",
    "Propose one change that would improve your workplace or school.",
    "Write about a person you admire and the qualities that stand out.",
    "Argue for or against a four-day working week.",
    "Describe how a hobby or interest of yours began and grew.",
    "Write a short reflective essay on what success means to you.",
    "Explain a concept from your field as if to a beginner.",
    "Write about a decision you're glad you made.",
    "Discuss the pros and cons of living in a big city.",
    "Write a letter to your younger self giving one piece of advice.",
    "Describe a recent change in your routine and its effect on you.",
    "Argue whether money can buy happiness, with examples.",
    "Write about a book or article that shaped your thinking.",
    "Describe a goal for the next year and how you plan to reach it.",
    "Write a short piece on why learning a second language matters.",
    "Discuss one technology you think is overrated, and why.",
    "Write about a risk you took that paid off — or didn't.",
    "Describe your favourite way to spend an evening and why it works.",
    "Argue for or against homework being abolished.",
    "Write about a cultural difference you've noticed and found interesting.",
    "Describe a moment when you felt truly proud of yourself.",
]


def pick_topic(kind: str, index: int) -> str:
    """Return topic #index (cycling) from the pool for `kind` ('speak'|'write').

    Falls back to the speaking pool for any unknown kind.
    """
    pool = WRITING_TOPICS if kind == "write" else SPEAKING_TOPICS
    return pool[index % len(pool)]
