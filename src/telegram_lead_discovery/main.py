from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="tld", description="Telegram Lead Discovery")
    parser.add_argument(
        "command",
        nargs="?",
        default="start",
        choices=["start", "migrate", "integrity-check", "backup", "restore", "purge"],
    )
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--backup",
        type=Path,
        default=None,
        help="Path to backup file inside the backups directory (required for restore)",
    )
    args = parser.parse_args()

    if args.bind != "127.0.0.1":
        print("startup_failed: bind address must be 127.0.0.1", file=sys.stderr)
        raise SystemExit("startup_failed")

    from telegram_lead_discovery.infrastructure.runtime import run_command

    raise SystemExit(
        asyncio.run(
            run_command(
                args.command,
                bind=args.bind,
                port=args.port,
                backup_path=args.backup,
            )
        )
    )


if __name__ == "__main__":
    main()
