"""Wave 07 — versioned detection loader, pin, re-score, calibration gates."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from telegram_lead_discovery.detection.engine import (
    clear_compile_cache,
    detect,
    seed_catalog_detect,
    stable_detection_payload,
)
from telegram_lead_discovery.detection.errors import RuleSetInvalidError
from telegram_lead_discovery.detection.loader import RuleCatalogLoader, get_default_loader
from telegram_lead_discovery.detection.seed import (
    SEED_RULES,
    SeedRule,
    catalog_checksum,
    seed_ruleset_ru_mvp_1,
)
from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.processing.normalization import normalize_message_text
from telegram_lead_discovery.processing.pipeline import (
    FAILED_PERMANENT,
    process_next_envelope,
    rescore_revision,
)
from telegram_lead_discovery.scoring.calibration import (
    HOT_PRECISION_MIN,
    HOT_WARM_PRECISION_MIN,
    PURCHASE_INTENT_RECALL_MIN,
    assert_corpus_invariants,
    load_corpus_jsonl,
    run_calibration,
    write_calibration_report,
)
from telegram_lead_discovery.settings.service import seed_defaults
from telegram_lead_discovery.storage.db import dispose_engine, init_engine
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import (
    MonitoringRule,
    ProcessingResult,
    RuleSetVersion,
    TelegramEventEnvelope,
    TelegramMessage,
    TelegramMessageRevision,
    TelegramSource,
)
from telegram_lead_discovery.storage.session import configure_session_factory, run_write

CORPUS_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "calibration" / "locked_corpus.jsonl"
)
ARTIFACT_DIR = (
    Path(__file__).resolve().parents[2]
    / ".omc"
    / "artifacts"
    / "lead-discovery-remediation"
    / "wave-07"
)

HOT_TEXT = (
    "Нужно сделать Telegram бот для заказов, задача для интеграции с оплатой, "
    "бюджет 120000 ₽, срочно, готов начать, @clientuser1000."
)


@pytest.fixture
async def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    paths = ensure_app_directories(resolve_app_paths())
    upgrade_head(paths.database_path)
    engine = await init_engine(paths.database_path)
    configure_session_factory(engine)
    get_default_loader().clear_cache()
    clear_compile_cache()

    async def _seed(session):
        await seed_defaults(session)
        ruleset = await seed_ruleset_ru_mvp_1(session)
        source = TelegramSource(
            telegram_id=42,
            username_normalized="leads_src",
            title="Leads",
            source_type="channel",
            public_url="https://t.me/leads_src",
            lifecycle_state="monitoring",
            quality_score=5,
        )
        session.add(source)
        await session.flush()
        return source.id, ruleset.id, ruleset.checksum

    source_id, ruleset_id, checksum = await run_write(_seed)
    yield paths, source_id, ruleset_id, checksum
    get_default_loader().clear_cache()
    clear_compile_cache()
    await dispose_engine()


async def _enqueue(session, source_id: int, text: str, *, msg_id: int = 1) -> int:
    now = datetime.now(UTC)
    env = TelegramEventEnvelope(
        event_id=f"{source_id}:message_new:{msg_id}:{now.isoformat()}",
        event_type="message_new",
        source_id=source_id,
        telegram_message_id=msg_id,
        edit_key="0",
        payload_json=json.dumps(
            {
                "text": text,
                "published_at": now.isoformat(),
                "permalink": f"https://t.me/leads_src/{msg_id}",
            },
            ensure_ascii=False,
        ),
        collection_mode="live",
        received_at=now,
        processing_state="queued",
    )
    session.add(env)
    await session.flush()
    return env.id


def test_detect_requires_explicit_checksum() -> None:
    analysis = normalize_message_text(HOT_TEXT).analysis_text
    with pytest.raises(RuleSetInvalidError):
        detect(analysis, rules=SEED_RULES, rule_set_checksum="deadbeef")


def test_byte_stable_reprocess() -> None:
    analysis = normalize_message_text(HOT_TEXT).analysis_text
    checksum = catalog_checksum(SEED_RULES)
    first = detect(analysis, rules=SEED_RULES, rule_set_checksum=checksum)
    second = detect(analysis, rules=SEED_RULES, rule_set_checksum=checksum)
    assert stable_detection_payload(first) == stable_detection_payload(second)
    assert json.dumps(stable_detection_payload(first), sort_keys=True) == json.dumps(
        stable_detection_payload(second), sort_keys=True
    )


def test_compile_cache_keyed_by_checksum() -> None:
    clear_compile_cache()
    checksum = catalog_checksum(SEED_RULES)
    analysis = normalize_message_text(HOT_TEXT).analysis_text
    detect(analysis, rules=SEED_RULES, rule_set_checksum=checksum)
    from telegram_lead_discovery.detection import engine as engine_mod

    assert checksum in engine_mod._COMPILE_CACHE
    # semantic result unchanged on cache hit
    again = detect(analysis, rules=SEED_RULES, rule_set_checksum=checksum)
    assert again.category == "direct_order"


@pytest.mark.asyncio
async def test_loader_cache_and_mismatch(db_env) -> None:
    _paths, _source_id, ruleset_id, checksum = db_env
    loader = RuleCatalogLoader()

    async def _ok(session):
        loaded = await loader.load(
            session, rule_set_version_id=ruleset_id, checksum=checksum
        )
        cached = loader.peek_cache(checksum)
        assert cached is not None
        assert cached.rule_set_version_id == loaded.rule_set_version_id
        with pytest.raises(RuleSetInvalidError) as exc:
            await loader.load(
                session, rule_set_version_id=ruleset_id, checksum="0" * 64
            )
        assert exc.value.error_code == "RULE_SET_INVALID"
        return loaded.checksum

    assert await run_write(_ok) == checksum


@pytest.mark.asyncio
async def test_bootstrap_seed_only_creates_immutable_version(db_env) -> None:
    _paths, _source_id, ruleset_id, checksum = db_env

    async def _check(session):
        first = await seed_ruleset_ru_mvp_1(session)
        second = await seed_ruleset_ru_mvp_1(session)
        assert first.id == second.id == ruleset_id
        assert first.checksum == second.checksum == checksum
        rules = list(
            (
                await session.execute(
                    select(MonitoringRule).where(
                        MonitoringRule.rule_set_version_id == ruleset_id
                    )
                )
            ).scalars()
        )
        assert len(rules) == len(SEED_RULES)
        return True

    assert await run_write(_check) is True


@pytest.mark.asyncio
async def test_pipeline_pins_version_no_seed_fallback(db_env) -> None:
    _paths, source_id, ruleset_id, checksum = db_env

    async def _run(session):
        await _enqueue(session, source_id, HOT_TEXT)
        result = await process_next_envelope(session, owner="test")
        assert result is not None
        assert result["outcome"] == "processed"
        assert result["rule_set_version_id"] == ruleset_id
        assert result["rule_set_checksum"] == checksum
        rows = list((await session.execute(select(ProcessingResult))).scalars())
        assert len(rows) == 1
        assert rows[0].rule_set_version_id == ruleset_id
        payload = json.loads(rows[0].explanation_json)
        assert payload["rule_set_checksum"] == checksum
        return True

    assert await run_write(_run) is True


@pytest.mark.asyncio
async def test_pipeline_mismatch_checksum_permanent(db_env) -> None:
    _paths, source_id, ruleset_id, _checksum = db_env
    get_default_loader().clear_cache()

    async def _corrupt_and_run(session):
        version = await session.get(RuleSetVersion, ruleset_id)
        assert version is not None
        # Keep DB checksum field but alter rule content → content mismatch on load
        # OR: pin wrong checksum by mutating version.checksum while rules unchanged.
        version.checksum = "f" * 64
        await session.flush()
        await _enqueue(session, source_id, HOT_TEXT, msg_id=99)
        result = await process_next_envelope(session, owner="test")
        assert result is not None
        assert result["outcome"] == FAILED_PERMANENT
        assert result["error_code"] == "RULE_SET_INVALID"
        env = (
            await session.execute(select(TelegramEventEnvelope).where(
                TelegramEventEnvelope.telegram_message_id == 99
            ))
        ).scalar_one()
        assert env.processing_state == FAILED_PERMANENT
        # No processing result written for failed permanent ruleset
        assert list((await session.execute(select(ProcessingResult))).scalars()) == []
        return True

    assert await run_write(_corrupt_and_run) is True


@pytest.mark.asyncio
async def test_rescore_new_trace_preserves_old(db_env) -> None:
    _paths, source_id, ruleset_id, checksum = db_env

    async def _run(session):
        await _enqueue(session, source_id, HOT_TEXT, msg_id=7)
        first = await process_next_envelope(session, owner="test")
        assert first is not None and first["outcome"] == "processed"
        old_rows = list((await session.execute(select(ProcessingResult))).scalars())
        assert len(old_rows) == 1
        old_id = old_rows[0].id
        old_explanation = old_rows[0].explanation_json

        # Create a second immutable ruleset clone with distinct checksum/version.
        now = datetime.now(UTC)
        alt_rules = tuple(
            SeedRule(
                stable_rule_id=r.stable_rule_id,
                priority=r.priority,
                target=r.target,
                dimension=r.dimension,
                weight=r.weight,
                pattern=r.pattern,
                explanation_code=r.explanation_code,
                kind=r.kind,
            )
            for r in SEED_RULES
        )
        # Force distinct checksum by tweaking one explanation_code copy in DB only
        # via a near-identical catalog with an unused signal weight bump on a clone pattern.
        # Safer: insert second version with same rules but different slug/version number
        # and checksum computed from same SEED — UNIQUE checksum prevents that.
        # So mutate one pattern slightly for v2 and seed rules manually.
        v2_rules = []
        for r in alt_rules:
            if r.stable_rule_id == "SIG-URG-001":
                v2_rules.append(
                    SeedRule(
                        stable_rule_id=r.stable_rule_id,
                        priority=r.priority,
                        target=r.target,
                        dimension=r.dimension,
                        weight=r.weight,
                        pattern=r.pattern + r"|немедленно",
                        explanation_code=r.explanation_code,
                        kind=r.kind,
                    )
                )
            else:
                v2_rules.append(r)
        v2_tuple = tuple(v2_rules)
        v2_checksum = catalog_checksum(v2_tuple)
        v2 = RuleSetVersion(
            version=2,
            slug="ru-mvp-2-test",
            locale="ru",
            state="draft",
            checksum=v2_checksum,
            hot_min=70,
            warm_min=50,
            cold_min=30,
            activated_at=None,
            created_at=now,
        )
        session.add(v2)
        await session.flush()
        for rule in v2_tuple:
            session.add(
                MonitoringRule(
                    rule_set_version_id=v2.id,
                    stable_rule_id=rule.stable_rule_id,
                    kind=rule.kind,
                    target=rule.target,
                    dimension=rule.dimension,
                    weight=rule.weight,
                    pattern=rule.pattern,
                    flags="IGNORECASE|FULLCASE|VERSION1",
                    priority=rule.priority,
                    explanation_code=rule.explanation_code,
                    enabled=True,
                    checksum=catalog_checksum((rule,)),
                )
            )
        await session.flush()

        msg = (
            await session.execute(select(TelegramMessage).where(
                TelegramMessage.telegram_message_id == 7
            ))
        ).scalar_one()
        rev = (
            await session.execute(
                select(TelegramMessageRevision).where(
                    TelegramMessageRevision.message_id == msg.id
                )
            )
        ).scalar_one()
        analysis = normalize_message_text(HOT_TEXT).analysis_text
        new_proc = await rescore_revision(
            session,
            message_id=msg.id,
            revision_id=rev.id,
            rule_set_version_id=v2.id,
            checksum=v2_checksum,
            analysis_text=analysis,
            published_at=msg.published_at,
            source_quality_score=5,
            now=now,
        )
        all_rows = list((await session.execute(select(ProcessingResult))).scalars())
        assert len(all_rows) == 2
        old = await session.get(ProcessingResult, old_id)
        assert old is not None
        assert old.explanation_json == old_explanation
        assert old.rule_set_version_id == ruleset_id
        assert new_proc.id != old_id
        assert new_proc.rule_set_version_id == v2.id
        return True

    assert await run_write(_run) is True


def test_locked_corpus_calibration_gates() -> None:
    assert CORPUS_PATH.is_file()
    samples = load_corpus_jsonl(CORPUS_PATH)
    assert_corpus_invariants(samples)
    report = run_calibration(samples, split="val")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    write_calibration_report(report, ARTIFACT_DIR / "calibration-report.json")
    assert report.hot_precision >= HOT_PRECISION_MIN
    assert report.hot_warm_precision >= HOT_WARM_PRECISION_MIN
    assert report.purchase_intent_recall >= PURCHASE_INTENT_RECALL_MIN
    assert report.gates_passed is True
    assert report.train_size > 0
    assert report.val_size > 0
    assert "direct_order" in report.category_metrics
    assert report.category_metrics["direct_order"]["tp"] >= 0


def test_seed_catalog_detect_helper() -> None:
    analysis = normalize_message_text("Сегодня отличная погода.").analysis_text
    result = seed_catalog_detect(analysis)
    assert result.category == "irrelevant"
    assert result.rule_set_checksum == catalog_checksum(SEED_RULES)
