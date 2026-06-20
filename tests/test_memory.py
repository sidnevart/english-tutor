"""Native persona + per-user recall memory."""

from __future__ import annotations

from tutor.memory import Memory, load_soul
from tutor.memory.soul import DEFAULT_SOUL


def test_load_soul_default_and_file(tmp_path):
    assert load_soul(tmp_path) == DEFAULT_SOUL  # no SOUL.md -> default
    (tmp_path / "SOUL.md").write_text("Custom coach persona.", encoding="utf-8")
    assert load_soul(tmp_path) == "Custom coach persona."


def test_weak_words_accumulate_and_dedup(tmp_path):
    mem = Memory(tmp_path, user_id=764315256)
    assert mem.weak_words() == []
    assert mem.recall_hint() == ""

    mem.add_weak_words(["alpha", "beta"])
    mem.add_weak_words(["alpha", "gamma"])  # alpha now count 2

    words = mem.weak_words()
    assert words[0] == "alpha"  # highest count first
    assert set(words) == {"alpha", "beta", "gamma"}
    assert "alpha" in mem.recall_hint()


def test_persona_includes_user_profile(tmp_path):
    (tmp_path / "SOUL.md").write_text("Base persona.", encoding="utf-8")
    mem = Memory(tmp_path, user_id=1)
    assert mem.persona() == "Base persona."

    mem.user_dir.mkdir(parents=True, exist_ok=True)
    (mem.user_dir / "USER.md").write_text("Intermediate learner, business focus.", encoding="utf-8")
    persona = mem.persona()
    assert "Base persona." in persona
    assert "Intermediate learner" in persona


def test_recall_persists_across_instances(tmp_path):
    Memory(tmp_path, 1).add_weak_words(["serendipity"])
    assert "serendipity" in Memory(tmp_path, 1).weak_words()
