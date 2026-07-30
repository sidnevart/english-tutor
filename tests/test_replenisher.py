from __future__ import annotations

from pathlib import Path

from tutor.catalog import BundledCatalog
from tutor.catalog.replenisher import CatalogCritique, CatalogReplenisher
from tutor.catalog.validation import validate_task
from tutor.practice.models import CatalogTask, Section, TaskType


class FakeFetcher:
    async def fetch(self, url: str) -> str:
        return "<html><script>bad()</script><p>NASA reports a carefully measured change.</p></html>"


class FakeLLM:
    def __init__(self, candidate) -> None:
        self.candidate = candidate
        self.calls = []

    async def complete_json(self, system, user, schema):
        self.calls.append((system, user, schema))
        if schema is CatalogCritique:
            return CatalogCritique(accepted=True)
        return self.candidate


class FakeSynthesizer:
    async def synthesize(self, text: str, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"audio")
        return out_path


async def test_replenisher_accepts_valid_original_task_from_allowlisted_source(
    repo, tmp_path
) -> None:
    source = BundledCatalog.load().tasks[3]
    candidate = source.model_copy(update={"id": "generated-interview-1"})
    llm = FakeLLM(candidate)
    builder = CatalogReplenisher(repo, llm, FakeFetcher(), FakeSynthesizer(), tmp_path)

    accepted = await builder.build_one("https://www.nasa.gov/example", TaskType.INTERVIEW)

    assert accepted is not None
    assert accepted.provenance == "source-backed-original"
    assert "<script>" not in llm.calls[0][1]
    assert repo.catalog_task("generated-interview-1") is not None


async def test_replenisher_rejects_disallowed_domains_without_fetching(repo, tmp_path) -> None:
    builder = CatalogReplenisher(
        repo, FakeLLM(BundledCatalog.load().tasks[0]), FakeFetcher(), FakeSynthesizer(), tmp_path
    )

    accepted = await builder.build_one("https://britannica.com/topic/example", TaskType.INTERVIEW)

    assert accepted is None
    assert repo.latest_generation_run()["status"] == "rejected_source"


async def test_replenisher_quarantines_near_duplicate(repo, tmp_path) -> None:
    catalog = BundledCatalog.load()
    repo.seed_catalog(catalog.tasks)
    duplicate = catalog.tasks[0].model_copy(update={"id": "generated-duplicate"})
    builder = CatalogReplenisher(
        repo, FakeLLM(duplicate), FakeFetcher(), FakeSynthesizer(), tmp_path
    )

    accepted = await builder.build_one("https://www.si.edu/example", TaskType.LISTEN_REPEAT)

    assert accepted is None
    assert repo.latest_generation_run()["status"] == "rejected_duplicate"


def test_validator_rejects_wrong_container_types_without_crashing() -> None:
    task = CatalogTask(
        id="invalid-listen-task",
        section=Section.SPEAKING,
        task_type=TaskType.LISTEN_REPEAT,
        topic_domain="campus",
        skill_tags=["delivery"],
        payload={"sentences": 7},
    )

    assert validate_task(task)
