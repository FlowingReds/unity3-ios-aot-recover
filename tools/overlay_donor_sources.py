#!/usr/bin/env python3
"""Overlay donor C# bodies onto an AssetRipper target without changing GUIDs.

Only files already present in the target tree are replaced.  This keeps the
target build's MonoScript inventory and ``.meta`` GUIDs intact and avoids
silently importing unrelated classes from a newer/full donor build.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=Path)
    parser.add_argument("donor", type=Path)
    args = parser.parse_args()

    replaced = 0
    missing = 0
    for target_file in sorted(args.target.rglob("*.cs")):
        relative = target_file.relative_to(args.target)
        donor_file = args.donor / relative
        if not donor_file.is_file():
            missing += 1
            continue
        shutil.copyfile(donor_file, target_file)
        replaced += 1

    print(
        f"overlaid {replaced} matching donor files; "
        f"kept {missing} target-only files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
