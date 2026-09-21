"""Build the owner-facing list of every discovered public chat handle."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPORTS = (
    ROOT / "all_discovered_chats.txt",
    ROOT / "linked_discussion_candidates.txt",
    ROOT / "linked_discussion_ledger.txt",
    ROOT / "catalog_handle_candidates.txt",
    ROOT / "catalog_handle_ledger.txt",
)
EXTRA_HANDLES = {
    "@rabota_rf_chat", "@frilans_chati", "@freelance_rabotach",
    "@freelance_in_telegram", "@freelance_chatc", "@freelancebirza",
    "@work_online_today", "@freelance_chat_ru", "@freelance_prochat",
    "@chatfreelans", "@russianfreelance", "@birjafreelance",
    "@freelance_rabota_chat", "@freelance_help", "@free_chat_for_freelance",
    "@chat_frilansz", "@jir_chat", "@freelance_chatik0", "@profiwork",
    "@gamedev_chat_rus", "@freelance_vakansiii", "@freelansvipchat",
    "@frilans_chat3", "@freeassistant", "@frilanserSM",
    "@frilanc_topchat", "@freelance_onjob", "@vakansi_chat", "@kryloff_vakansii",
    "@freelanceGeeks", "@jobGeeks", "@holder_job_devs",
}
OUTPUT = ROOT / "all_found_chats.txt"
SOURCE_LINE = re.compile(r"^@([A-Za-z0-9_]+)\s+\|")


def main() -> None:
    handles: set[str] = set(EXTRA_HANDLES)
    for report in REPORTS:
        if not report.exists():
            continue
        for line in report.read_text(encoding="utf-8").splitlines():
            match = SOURCE_LINE.match(line)
            if match:
                handles.add("@" + match.group(1))
    OUTPUT.write_text("\n".join(sorted(handles, key=str.lower)) + "\n", encoding="utf-8")
    print(f"REGISTERED={len(handles)}")


if __name__ == "__main__":
    main()
