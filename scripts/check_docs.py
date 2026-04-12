#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
TOP_LEVEL = sorted([p for p in DOCS.glob("*.md") if p.is_file()])
ALL_MD = sorted([p for p in DOCS.rglob("*.md") if p.is_file()])

METADATA_KEYS = ["Last Verified:", "Owner:", "Code References:", "Test References:"]
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def check_metadata(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    errs = []
    for key in METADATA_KEYS:
        if key not in text:
            errs.append(f"missing metadata '{key}' in {path}")
    return errs


def check_links(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    errs: list[str] = []
    for m in LINK_RE.finditer(text):
        target = m.group(1).strip()
        if not target or target.startswith("http://") or target.startswith("https://") or target.startswith("#"):
            continue
        clean = target.split("#", 1)[0]
        candidate = (path.parent / clean).resolve()
        if not candidate.exists():
            errs.append(f"broken link in {path}: {target}")
    return errs


def main() -> int:
    errors: list[str] = []
    for p in TOP_LEVEL:
        errors.extend(check_metadata(p))
    for p in ALL_MD:
        errors.extend(check_links(p))

    if errors:
        print("Docs check failed:")
        for e in errors:
            print(f"- {e}")
        return 1

    print("Docs check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
