#!/usr/bin/env python3
"""Copy donor-only C# types needed by overlaid implementations.

Files whose relative paths already exist in any target assembly root are
excluded, preventing duplicate definitions across Assembly-CSharp and
Assembly-CSharp-firstpass.  Donor-only dependencies are placed in a separate
support tree so their provenance remains obvious.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("donor", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--exclude-root", action="append", type=Path, default=[])
    args = parser.parse_args()

    excluded: set[Path] = set()
    for root in args.exclude_root:
        excluded.update(path.relative_to(root) for path in root.rglob("*.cs"))

    copied = 0
    skipped = 0
    for donor_file in sorted(args.donor.rglob("*.cs")):
        relative = donor_file.relative_to(args.donor)
        if relative == Path("Properties/AssemblyInfo.cs") or relative in excluded:
            skipped += 1
            continue
        destination = args.output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(donor_file, destination)
        copied += 1

    print(f"copied {copied} donor-only support files; skipped {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
