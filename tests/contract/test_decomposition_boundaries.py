from __future__ import annotations

import ast
import dataclasses
import subprocess
import sys
from pathlib import Path

import pytest

from telegram_lead_discovery.source_discovery import worker
from telegram_lead_discovery.source_discovery.worker_parts import claims
from telegram_lead_discovery.source_discovery.worker_parts.dependencies import (
    RUNTIME_CONFIG,
)

ROOT = Path(__file__).resolve().parents[2]
PART_ROOTS = (
    ROOT / "src/telegram_lead_discovery/collector/adapter/telethon_parts",
    ROOT / "src/telegram_lead_discovery/collector/port_parts",
    ROOT / "src/telegram_lead_discovery/dashboard/discovery/view_parts",
    ROOT / "src/telegram_lead_discovery/storage/model_parts",
    ROOT / "src/telegram_lead_discovery/source_discovery/worker_parts",
)
STANDALONE_PARTS = (
    "telegram_lead_discovery.detection.catalog_types",
    "telegram_lead_discovery.detection.catalog_v1",
    "telegram_lead_discovery.detection.catalog_v1_a",
    "telegram_lead_discovery.detection.catalog_v1_b",
    "telegram_lead_discovery.detection.catalog_v1_c",
    "telegram_lead_discovery.detection.catalog_versions",
    "telegram_lead_discovery.source_discovery.keyword_profile_normalization",
    "telegram_lead_discovery.source_discovery.keyword_profile_seed",
    "telegram_lead_discovery.source_discovery.keyword_profile_selection",
    "telegram_lead_discovery.source_discovery.profile_seed_service",
    "telegram_lead_discovery.storage.retention_batches",
    "telegram_lead_discovery.storage.retention_discovery",
)


def _module_name(path: Path) -> str:
    relative = path.relative_to(ROOT / "src").with_suffix("")
    return ".".join(relative.parts)


def _part_modules() -> tuple[str, ...]:
    modules = set(STANDALONE_PARTS)
    for directory in PART_ROOTS:
        modules.update(
            _module_name(path) for path in directory.glob("*.py") if path.name != "__init__.py"
        )
    return tuple(sorted(modules))


def test_every_decomposed_part_cold_imports() -> None:
    failures: list[str] = []
    for module in _part_modules():
        result = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if result.returncode:
            failures.append(f"{module}: {result.stderr.strip()}")
    assert not failures, "\n\n".join(failures)


def test_worker_runtime_limits_have_one_mutable_owner() -> None:
    names = set(worker._RUNTIME_CONSTANT_NAMES)
    config_fields = {field.name for field in dataclasses.fields(RUNTIME_CONFIG)}
    assert names == config_fields

    original_facade = {name: getattr(worker, name) for name in names}
    original_config = {name: getattr(RUNTIME_CONFIG, name) for name in names}
    try:
        for index, name in enumerate(sorted(names), start=1):
            current = getattr(worker, name)
            replacement = (
                (index, index + 1)
                if isinstance(current, tuple)
                else (f"value-{index}" if isinstance(current, str) else index)
            )
            setattr(worker, name, replacement)
        worker._sync_runtime_constants()
        assert {name: getattr(RUNTIME_CONFIG, name) for name in names} == {
            name: getattr(worker, name) for name in names
        }
    finally:
        for name, value in original_facade.items():
            setattr(worker, name, value)
        for name, value in original_config.items():
            setattr(RUNTIME_CONFIG, name, value)

    bare_consumers: dict[str, list[str]] = {}
    worker_parts = ROOT / "src/telegram_lead_discovery/source_discovery/worker_parts"
    for path in worker_parts.glob("*.py"):
        if path.name == "dependencies.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bare = sorted(
            {
                node.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and node.id in names
            }
        )
        if bare:
            bare_consumers[path.name] = bare
    assert bare_consumers == {}


@pytest.mark.asyncio
async def test_facade_entrypoints_sync_runtime_overrides(monkeypatch) -> None:
    original_facade = worker.HEARTBEAT_SECONDS
    original_config = RUNTIME_CONFIG.HEARTBEAT_SECONDS
    seen: list[int] = []

    async def record(*args, **kwargs):
        seen.append(RUNTIME_CONFIG.HEARTBEAT_SECONDS)
        return None

    monkeypatch.setattr(worker, "_process_keyword", record)
    monkeypatch.setattr(worker, "_claim_keyword", record)
    monkeypatch.setattr(worker, "_process_graph", record)
    monkeypatch.setattr(worker, "_claim_graph", record)
    monkeypatch.setattr(claims.KeywordDiscoveryClaimLoop, "_run", record)
    monkeypatch.setattr(claims.GraphDiscoveryClaimLoop, "_run", record)
    try:
        worker.HEARTBEAT_SECONDS = 999
        await worker.process_keyword_discovery_job()
        await worker.claim_and_process_keyword_job()
        await worker.process_graph_discovery_job()
        await worker.claim_and_process_graph_job()
        await worker.KeywordDiscoveryClaimLoop(object())._run()
        await worker.GraphDiscoveryClaimLoop(object())._run()
        assert seen == [999] * 6
    finally:
        worker.HEARTBEAT_SECONDS = original_facade
        RUNTIME_CONFIG.HEARTBEAT_SECONDS = original_config
