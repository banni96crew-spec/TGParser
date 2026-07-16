# Telegram Lead Discovery

Персональное локальное MVP-приложение для одного оператора: поиск коммерческих запросов в публичных вручную одобренных Telegram-источниках.

## Требования

- Windows 10/11 x64
- Python 3.12.x
- `uv`

## Установка

```bash
uv sync --extra dev
```

## Запуск

```bash
uv run tld migrate
uv run tld start
```

UI: `http://127.0.0.1:8765`

## Документация

Нормативные требования: `docs/prd/README.md`.
