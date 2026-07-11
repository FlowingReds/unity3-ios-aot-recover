#!/usr/bin/env python3
"""Make ILSpy output from stripped Unity iOS AOT assemblies compilable.

ILSpy emits an invalid expression statement for value-returning methods whose
only CIL instruction is ``ret``.  Some earlier recovery passes used the C# 7.1
``default`` literal, which Unity 2017's C# 4 compiler cannot parse.  This tool
replaces both forms with an explicit throw.  The throw is deliberately noisy:
it keeps unavailable AOT behavior distinct from donor-recovered behavior while
allowing a reconstructed project to compile and expose the next porting issue.
"""

from __future__ import annotations

import argparse
from pathlib import Path


ILSPY_STUB = (
    "/*Error: Method body consists only of 'ret', but nothing is being returned. "
    "Decompiled assembly might be a reference assembly.*/;"
)
THROW_STUB = (
    'throw new System.NotImplementedException('
    '"Native AOT method body was not available during recovery");'
)


def sanitize(path: Path) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8-sig")
    replacements = text.count(ILSPY_STUB)
    text = text.replace(ILSPY_STUB, THROW_STUB)

    default_stub = "return default; // stub"
    replacements += text.count(default_stub)
    text = text.replace(default_stub, THROW_STUB)

    if replacements:
        path.write_text(text, encoding="utf-8")
        return 1, replacements
    return 0, 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    files_changed = 0
    methods_changed = 0
    for root in args.paths:
        files = [root] if root.is_file() else sorted(root.rglob("*.cs"))
        for source in files:
            changed, replacements = sanitize(source)
            files_changed += changed
            methods_changed += replacements

    print(
        f"sanitized {methods_changed} stripped methods "
        f"across {files_changed} C# files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
