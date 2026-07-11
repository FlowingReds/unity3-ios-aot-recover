#!/usr/bin/env python3
"""Rewrite removed Unity 3 Component convenience properties for Unity 2017.

Unity 3 exposed ``component.audio``, ``component.animation`` and similar
shortcuts.  Unity 2017 marks those properties as hard errors.  Their documented
upgrade is a same-object ``GetComponent<T>()`` lookup.

Member names alone are not enough to identify those shortcuts: for example,
``RaycastHit.collider`` and a game's own ``AudioInfo.audio`` are unrelated APIs.
This module therefore rewrites only receivers that it can identify as a
``GameObject`` or ``Component`` from declarations in the input source corpus.
Ambiguous expressions are deliberately left for a compiler-assisted/manual
porting pass.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import re
from pathlib import Path
from typing import Iterable


COMPONENT_PROPERTIES = {
    "audio": "AudioSource",
    "animation": "Animation",
    "camera": "Camera",
    "renderer": "Renderer",
    "rigidbody": "Rigidbody",
    "collider": "Collider",
    "light": "Light",
    "guiTexture": "GUITexture",
}

# Built-in Unity types known to inherit Component, plus GameObject (which also
# exposes GetComponent).  User types derived from these are resolved below.
# Keep this list explicit: treating every capitalized UnityEngine-looking name
# as a Component would recreate the RaycastHit false positive this tool avoids.
UNITY_GET_COMPONENT_TYPES = {
    "Animation",
    "AudioSource",
    "Behaviour",
    "Camera",
    "CharacterController",
    "Collider",
    "Component",
    "GUIElement",
    "GUIText",
    "GUITexture",
    "GameObject",
    "Joint",
    "Light",
    "MonoBehaviour",
    "NavMeshAgent",
    "ParticleEmitter",
    "ParticleSystem",
    "Renderer",
    "Rigidbody",
    "Transform",
}

# ILSpy's receivers in these old projects are identifiers, ``base``/``this``,
# or member chains. Parenthesized, indexed and call expressions are excluded so
# a regular-expression rewrite cannot guess their result type.
RECEIVER = r"(?P<receiver>\b(?:base|this|[A-Za-z_]\w*)(?:\.[A-Za-z_]\w*)*)"

# System.Math members present in the .NET profile used by Unity 2017.  A game
# may also define a global Math helper, so unknown members must not be qualified.
SYSTEM_MATH_MEMBERS = {
    "Abs",
    "Acos",
    "Asin",
    "Atan",
    "Atan2",
    "BigMul",
    "Ceiling",
    "Cos",
    "Cosh",
    "DivRem",
    "E",
    "Exp",
    "Floor",
    "IEEERemainder",
    "Log",
    "Log10",
    "Max",
    "Min",
    "PI",
    "Pow",
    "Round",
    "Sign",
    "Sin",
    "Sinh",
    "Sqrt",
    "Tan",
    "Tanh",
    "Truncate",
}

CLASS_PATTERN = re.compile(
    r"\bclass\s+(?P<name>@?[A-Za-z_]\w*)"
    r"(?:\s*<[^>{};]+>)?\s*"
    r"(?:\:\s*(?P<bases>[^\{]+?))?\s*\{"
)
DECLARATION_PATTERN = re.compile(
    r"(?<![\w.])"
    r"(?P<type>(?:global::)?[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*"
    r"(?:\s*<[^>{};()\n]+>)?(?:\s*\[\s*\])?)"
    r"\s+(?P<name>@?[A-Za-z_]\w*)"
    r"(?=\s*(?:=|;|,|\)|\{|\}|\bin\b))"
)


def _mask_non_code(text: str) -> str:
    """Blank C# comments and literals while retaining offsets and newlines."""

    chars = list(text)
    index = 0
    length = len(text)
    while index < length:
        if text.startswith("//", index):
            end = text.find("\n", index + 2)
            end = length if end == -1 else end
            for position in range(index, end):
                chars[position] = " "
            index = end
            continue
        if text.startswith("/*", index):
            end_marker = text.find("*/", index + 2)
            end = length if end_marker == -1 else end_marker + 2
            for position in range(index, end):
                if chars[position] not in "\r\n":
                    chars[position] = " "
            index = end
            continue

        # Covers ordinary, interpolated and verbatim string literals.  Braces
        # inside interpolated strings are intentionally masked; declarations
        # and member accesses in interpolation expressions are too complex for
        # this conservative source rewriter.
        prefix_length = 0
        verbatim = False
        if text.startswith('$@"', index) or text.startswith('@$"', index):
            prefix_length = 3
            verbatim = True
        elif text.startswith('@"', index):
            prefix_length = 2
            verbatim = True
        elif text.startswith('$"', index):
            prefix_length = 2
        elif text[index] == '"':
            prefix_length = 1

        if prefix_length:
            end = index + prefix_length
            while end < length:
                if verbatim and text.startswith('""', end):
                    end += 2
                    continue
                if text[end] == '"':
                    end += 1
                    break
                if not verbatim and text[end] == "\\":
                    end += 2
                    continue
                end += 1
            for position in range(index, min(end, length)):
                if chars[position] not in "\r\n":
                    chars[position] = " "
            index = end
            continue

        if text[index] == "'":
            end = index + 1
            while end < length:
                if text[end] == "\\":
                    end += 2
                    continue
                if text[end] == "'":
                    end += 1
                    break
                end += 1
            for position in range(index, min(end, length)):
                if chars[position] not in "\r\n":
                    chars[position] = " "
            index = end
            continue

        index += 1
    return "".join(chars)


def _simple_type_name(type_name: str) -> str:
    type_name = re.sub(r"\s+", "", type_name)
    type_name = type_name.removeprefix("global::")
    type_name = type_name.split("<", 1)[0]
    type_name = type_name.removesuffix("[]")
    return type_name.rsplit(".", 1)[-1].lstrip("@")


def _is_explicit_unity_type(type_name: str) -> bool:
    compact = re.sub(r"\s+", "", type_name).removeprefix("global::")
    if not compact.startswith("UnityEngine.") or "<" in compact or compact.endswith("[]"):
        return False
    return compact.rsplit(".", 1)[-1] in UNITY_GET_COMPONENT_TYPES


@dataclass(frozen=True)
class ClassRange:
    start: int
    end: int
    name: str


@dataclass
class SourceFacts:
    masked: str
    declarations: dict[str, set[str]]
    classes: list[ClassRange]


class SourceAnalysis:
    """Minimal, conservative type facts shared by all source files in a run."""

    def __init__(self, files: Iterable[Path]):
        self._facts: dict[Path, SourceFacts] = {}
        class_bases: dict[str, list[set[str]]] = {}

        for path in files:
            resolved = path.resolve()
            text = path.read_text(encoding="utf-8-sig")
            masked = _mask_non_code(text)
            declarations: dict[str, set[str]] = {}
            for match in DECLARATION_PATTERN.finditer(masked):
                name = match.group("name").lstrip("@")
                declarations.setdefault(name, set()).add(match.group("type"))

            classes: list[ClassRange] = []
            for match in CLASS_PATTERN.finditer(masked):
                name = match.group("name").lstrip("@")
                bases = {
                    re.sub(r"\s+", "", base).removeprefix("global::")
                    for base in (match.group("bases") or "").split(",")
                    if base.strip()
                }
                class_bases.setdefault(name, []).append(bases)
                opening_brace = match.end() - 1
                closing_brace = self._matching_brace(masked, opening_brace)
                classes.append(ClassRange(opening_brace, closing_brace, name))

            self._facts[resolved] = SourceFacts(masked, declarations, classes)

        # A duplicated simple class name is considered safe only if every class
        # with that name is a Component. This avoids namespace-collision guesses.
        safe_custom_types: set[str] = set()
        changed = True
        while changed:
            changed = False
            for name, definitions in class_bases.items():
                if name in safe_custom_types:
                    continue
                all_safe = bool(definitions) and all(
                    any(
                        self._base_is_safe(base, class_bases, safe_custom_types)
                        for base in bases
                    )
                    for bases in definitions
                )
                if all_safe:
                    safe_custom_types.add(name)
                    changed = True

        self._class_bases = class_bases
        self._safe_custom_types = safe_custom_types

    @staticmethod
    def _matching_brace(masked: str, opening_brace: int) -> int:
        depth = 0
        for position in range(opening_brace, len(masked)):
            if masked[position] == "{":
                depth += 1
            elif masked[position] == "}":
                depth -= 1
                if depth == 0:
                    return position
        return len(masked)

    @staticmethod
    def _base_is_safe(
        base: str,
        class_bases: dict[str, list[set[str]]],
        safe_custom_types: set[str],
    ) -> bool:
        if _is_explicit_unity_type(base):
            return True
        simple = _simple_type_name(base)
        if simple in class_bases:
            return simple in safe_custom_types
        if "." in base:
            return False
        return simple in UNITY_GET_COMPONENT_TYPES

    def _type_is_safe(self, type_name: str) -> bool:
        compact = re.sub(r"\s+", "", type_name)
        if "<" in compact or compact.endswith("[]"):
            return False
        if _is_explicit_unity_type(compact):
            return True
        simple = _simple_type_name(compact)
        if simple in self._class_bases:
            return simple in self._safe_custom_types
        if "." in compact.removeprefix("global::"):
            return False
        return simple in UNITY_GET_COMPONENT_TYPES

    def _containing_class_is_safe(self, path: Path, position: int) -> bool:
        facts = self._facts[path.resolve()]
        containing = [item for item in facts.classes if item.start < position < item.end]
        if not containing:
            return False
        innermost = min(containing, key=lambda item: item.end - item.start)
        return innermost.name in self._safe_custom_types

    def position_is_code(self, path: Path, position: int) -> bool:
        masked = self._facts[path.resolve()].masked
        return position < len(masked) and not masked[position].isspace()

    def receiver_is_safe(self, path: Path, position: int, receiver: str) -> bool:
        """Return true only when ``receiver.GetComponent`` is type-safe."""

        parts = receiver.split(".")
        first = parts[0]
        remaining = parts[1:]

        if first in {"this", "base"}:
            safe = self._containing_class_is_safe(path, position)
        elif first in {"gameObject", "transform"}:
            declared_types = self._facts[path.resolve()].declarations.get(first)
            safe = (
                all(self._type_is_safe(type_name) for type_name in declared_types)
                if declared_types
                else self._containing_class_is_safe(path, position)
            )
        else:
            declared_types = self._facts[path.resolve()].declarations.get(first)
            safe = bool(declared_types) and all(
                self._type_is_safe(type_name) for type_name in declared_types
            )

        # gameObject and transform preserve a known Component/GameObject
        # receiver type. Any other member access can change the type.
        return safe and all(part in {"gameObject", "transform"} for part in remaining)


def rewrite(path: Path, analysis: SourceAnalysis | None = None) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8-sig")
    analysis = analysis or SourceAnalysis([path])
    replacements = 0
    properties = "|".join(COMPONENT_PROPERTIES)
    pattern = re.compile(RECEIVER + rf"\.(?P<legacy>{properties})\b")

    def replace(match: re.Match[str]) -> str:
        nonlocal replacements
        receiver = match.group("receiver")
        if (
            not analysis.position_is_code(path, match.start())
            or not analysis.receiver_is_safe(path, match.start(), receiver)
        ):
            return match.group(0)
        replacements += 1
        component_type = COMPONENT_PROPERTIES[match.group("legacy")]
        return f"{receiver}.GetComponent<{component_type}>()"

    # One pass keeps match offsets aligned with SourceAnalysis's original class
    # ranges even when an earlier replacement makes the source text longer.
    text = pattern.sub(replace, text)

    # Several recovered games define their own global ``Math`` helper. That
    # shadows System.Math inside donor code even when the donor imported
    # ``System``. Qualify only actual BCL members; leave game-specific helpers.
    if path.name != "Math.cs":
        members = "|".join(sorted(SYSTEM_MATH_MEMBERS, key=len, reverse=True))
        math_pattern = re.compile(
            rf"(?<![A-Za-z0-9_.])Math\.(?=(?:{members})\b)"
        )
        math_masked = _mask_non_code(text)

        def qualify_math(match: re.Match[str]) -> str:
            nonlocal replacements
            if math_masked[match.start()].isspace():
                return match.group(0)
            replacements += 1
            return "System.Math."

        text = math_pattern.sub(qualify_math, text)

    # Only unqualified NavMesh symbols need the Unity 5.6+ namespace import.
    masked = _mask_non_code(text)
    if (
        re.search(r"(?<![A-Za-z0-9_.])NavMesh(?:Path\b|\.)", masked)
        and "using UnityEngine.AI;" not in masked
        and not re.search(
            r"\b(?:class|struct|interface)\s+NavMeshPath\b", masked
        )
    ):
        text = "using UnityEngine.AI;\n" + text
        replacements += 1

    if replacements:
        path.write_text(text, encoding="utf-8")
        return 1, replacements
    return 0, 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    files: list[Path] = []
    for root in args.paths:
        files.extend([root] if root.is_file() else sorted(root.rglob("*.cs")))
    # A file may be covered by overlapping roots; rewrite it only once.
    files = list(dict.fromkeys(path.resolve() for path in files))
    analysis = SourceAnalysis(files)

    files_changed = 0
    expressions_changed = 0
    for source in files:
        changed, replacements = rewrite(source, analysis)
        files_changed += changed
        expressions_changed += replacements
    print(
        f"modernized {expressions_changed} Component API expressions "
        f"across {files_changed} files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
