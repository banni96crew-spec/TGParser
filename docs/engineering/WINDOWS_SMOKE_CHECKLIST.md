# Windows smoke checklist (AT-GOV-011)

| Field | Value |
|---|---|
| Requirement | `GOV-011` / `AT-GOV-011` |
| Status | `not_run` |
| Reason | Desktop smoke hosts not confirmed available for matrix execution |

## Matrix

| Host | OS | Cursor | Node.js | PowerShell | Status |
|---|---|---|---|---|---|
| Desktop A | Windows 10 x64 | 3.11.25 | 22.x | 5.1 | `not_run` |
| Desktop B | Windows 11 x64 | 3.11.25 | 22.x | 5.1 | `not_run` |
| Capability spike (reference only) | Windows 10 | 3.11.25 | 22.22.2 | 5.1.19041.6456 | observed for capability baseline, **not** Desktop parity evidence |

## Commands to run when hosts are available

```powershell
node tools/quality/run-quality-suite.mjs
node tools/quality/ci-recompute.mjs
```

Both Desktop hosts must return the same governance verdict for identical trusted inputs. A hosted CI run (when eventually approved) must not be presented as Desktop compatibility evidence.

---

## Product MVP smoke (оператор)

Перед проверкой убедитесь, что установлены `uv` и Python 3.12, а в окружении заданы пути данных (`LOCALAPPDATA`). Секреты Telegram (`TG_API_ID`, `TG_API_HASH`, для live-уведомлений — `TG_BOT_TOKEN`, `TG_NOTIFY_CHAT_ID`) не коммитьте и не выводите в лог.

### Шаги

1. Миграции схемы:

```powershell
uv run tld migrate
# или: uv run python -m telegram_lead_discovery migrate
```

2. Проверка целостности SQLite:

```powershell
uv run tld integrity-check
```

3. Онлайн-backup (после успешного migrate):

```powershell
uv run tld backup
```

4. Автотесты продукта (без реальных Telegram credentials):

```powershell
uv run pytest tests -q
```

5. (Опционально) регистрация Task Scheduler:

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\Register-TldTasks.ps1
```

6. (Опционально) restore только при остановленном runtime:

```powershell
uv run tld restore --backup "$env:LOCALAPPDATA\TelegramLeadDiscovery\backups\daily-….sqlite3"
```

### Ожидаемый результат

| Шаг | Ожидание |
|---|---|
| migrate | exit `0`, schema head применена |
| integrity-check | exit `0` |
| backup | файл в каталоге `backups`, exit `0` |
| pytest | все тесты зелёные |
| restore при running | отказ `restore_requires_stopped_runtime` |
