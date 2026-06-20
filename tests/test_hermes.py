"""HermesLLMClient: complete_json stays on Ollama; complete is sealed."""

from __future__ import annotations

from tutor.adapters.llm.hermes import HermesLLMClient
from tutor.app import open_services
from tutor.bot.handlers import _coach_reply
from tutor.config import Settings


class FakeOllama:
    def __init__(self) -> None:
        self.complete_calls = 0
        self.json_calls = 0

    async def complete(self, system: str, user: str) -> str:
        self.complete_calls += 1
        return "ollama-reply"

    async def complete_json(self, system, user, schema):  # noqa: ANN001
        self.json_calls += 1
        return "ollama-json"


async def test_complete_json_always_uses_ollama():
    ollama = FakeOllama()

    async def hermes(system, user):  # pragma: no cover - must not be called
        return "hermes-json"

    client = HermesLLMClient(ollama, hermes)
    assert await client.complete_json("s", "u", object) == "ollama-json"
    assert ollama.json_calls == 1


async def test_complete_uses_hermes_when_healthy():
    ollama = FakeOllama()
    calls = {"n": 0}

    async def hermes(system, user):
        calls["n"] += 1
        return "hermes-reply"

    client = HermesLLMClient(ollama, hermes)
    assert await client.complete("s", "u") == "hermes-reply"
    assert ollama.complete_calls == 0 and calls["n"] == 1


async def test_complete_falls_back_to_ollama_on_error():
    ollama = FakeOllama()

    async def hermes(system, user):
        raise RuntimeError("hermes down")

    client = HermesLLMClient(ollama, hermes)
    assert await client.complete("s", "u") == "ollama-reply"
    assert ollama.complete_calls == 1


async def test_breaker_opens_after_threshold():
    ollama = FakeOllama()
    calls = {"n": 0}

    async def hermes(system, user):
        calls["n"] += 1
        raise RuntimeError("down")

    client = HermesLLMClient(ollama, hermes, failure_threshold=2)
    await client.complete("s", "u")  # failure 1
    await client.complete("s", "u")  # failure 2 -> breaker opens
    hermes_calls_at_open = calls["n"]
    await client.complete("s", "u")  # breaker open: Hermes skipped

    assert calls["n"] == hermes_calls_at_open  # Hermes not called again
    assert ollama.complete_calls == 3  # all three degraded to Ollama


async def test_no_hermes_is_pure_ollama():
    ollama = FakeOllama()
    client = HermesLLMClient(ollama, None)
    assert await client.complete("s", "u") == "ollama-reply"
    assert ollama.complete_calls == 1


async def test_coach_reply_uses_complete(tmp_path):
    settings = Settings(
        _env_file=None,
        db_path=str(tmp_path / "t.db"),
        data_dir=str(tmp_path / "data"),
        soul_dir=str(tmp_path / "soul"),
        llm_backend="stub",
        notifier_backend="stub",
    )
    with open_services(settings) as svc:
        reply = await _coach_reply(svc, settings.admin_user_id, "hello")
        assert "stub-llm" in reply
