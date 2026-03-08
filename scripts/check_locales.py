#!/usr/bin/env python3
"""Verify all locale files contain the same keys as the reference en.json."""

import json
import sys
from pathlib import Path

LOCALES_DIR = Path(__file__).parent.parent / "locales"
REFERENCE = LOCALES_DIR / "en.json"


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    ref = load(REFERENCE)
    ref_keys = set(ref)
    errors = []

    for path in sorted(LOCALES_DIR.glob("*.json")):
        if path == REFERENCE:
            continue
        try:
            data = load(path)
        except json.JSONDecodeError as e:
            errors.append(f"{path.name}: invalid JSON – {e}")
            continue

        missing = ref_keys - set(data)
        extra = set(data) - ref_keys
        if missing:
            for k in sorted(missing):
                errors.append(f"{path.name}: missing key '{k}'")
        if extra:
            for k in sorted(extra):
                errors.append(f"{path.name}: unexpected key '{k}' (not in en.json)")

    if errors:
        print("Locale consistency errors:")
        for e in errors:
            print(f"  {e}")
        return 1

    print(f"OK – all locale files match en.json ({len(ref_keys)} keys).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
