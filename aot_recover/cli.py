from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import textwrap
from typing import Any
import zipfile

from . import __version__
from .macho import MachOError, MachOSlice, parse_macho
from .mono_aot import AotModule, build_method_map, parse_aot_modules, sanitize_module_name


RESOURCE_ROOT = Path(__file__).resolve().parent / "resources"
METADATA_PROJECT = RESOURCE_ROOT / "MetadataDump" / "MetadataDump.csproj"
DONOR_INDEX_PROJECT = RESOURCE_ROOT / "DonorIndex" / "DonorIndex.csproj"
GAME_ASSEMBLY_PATTERN = re.compile(r"^Assembly-CSharp(?:-firstpass)?\.dll$", re.IGNORECASE)
UNITY_VERSION_PATTERN = re.compile(rb"\b\d+\.\d+\.\d+[abfp]\d+\b")


class RecoveryError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _find_ilspy(explicit: str | None) -> str | None:
    dotnet_tools = Path.home() / ".dotnet" / "tools"
    candidates = [
        explicit,
        shutil.which("ilspycmd"),
        str(dotnet_tools / ("ilspycmd.exe" if sys.platform == "win32" else "ilspycmd")),
    ]
    return next((candidate for candidate in candidates if candidate and Path(candidate).is_file()), None)


def _helper_dll(project: Path, assembly_name: str) -> Path:
    def target_version(path: Path) -> tuple[int, ...]:
        match = re.fullmatch(r"net(\d+(?:\.\d+)*)", path.parent.name)
        return tuple(int(part) for part in match.group(1).split(".")) if match else (0,)

    sources = [project, *sorted(project.parent.glob("*.cs"))]
    fingerprint = hashlib.sha256()
    for source in sources:
        fingerprint.update(source.name.encode("utf-8"))
        fingerprint.update(b"\0")
        fingerprint.update(source.read_bytes())
    cache_root = Path(
        os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
    ).expanduser().resolve()
    cache_base = (
        cache_root
        / "unity3-aot-recover"
        / __version__
        / assembly_name
        / fingerprint.hexdigest()[:16]
    )
    cached_output = cache_base / f"{assembly_name}.dll"

    def local_outputs() -> list[Path]:
        return sorted(
            (project.parent / "bin" / "Release").glob(f"net*/{assembly_name}.dll"),
            key=target_version,
            reverse=True,
        )

    source_mtime = max(source.stat().st_mtime for source in sources)
    fresh_local = [
        candidate
        for candidate in local_outputs()
        if candidate.stat().st_mtime >= source_mtime
    ]
    if fresh_local:
        return fresh_local[0]
    if cached_output.is_file():
        return cached_output
    if shutil.which("dotnet") is None:
        raise RecoveryError(f"dotnet is required to build the {assembly_name} helper")
    cache_base.mkdir(parents=True, exist_ok=True)
    command = [
        "dotnet",
        "build",
        str(project),
        "--configuration",
        "Release",
        "--nologo",
        "--verbosity",
        "minimal",
        "--output",
        str(cache_base),
        f"--property:BaseIntermediateOutputPath={cache_base / 'obj'}/",
    ]
    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RecoveryError(f"could not build {assembly_name}\n" + completed.stdout + completed.stderr)
    if not cached_output.is_file():
        raise RecoveryError(f"{assembly_name} built successfully but its output DLL was not found")
    return cached_output


def _metadata_dump_dll() -> Path:
    return _helper_dll(METADATA_PROJECT, "MetadataDump")


def _donor_index_dll() -> Path:
    return _helper_dll(DONOR_INDEX_PROJECT, "DonorIndex")


def _dump_metadata(assembly: Path) -> dict[str, Any]:
    helper = _metadata_dump_dll()
    completed = subprocess.run(
        ["dotnet", str(helper), str(assembly)],
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RecoveryError(f"metadata extraction failed for {assembly.name}: {completed.stderr.strip()}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RecoveryError(f"MetadataDump returned invalid JSON for {assembly.name}: {error}") from error


def _resolve_reference_managed(inputs: list[str] | None) -> list[Path]:
    resolved: list[Path] = []
    seen: set[Path] = set()
    for raw in inputs or []:
        path = Path(raw).expanduser().resolve()
        if path.is_file():
            if path.suffix.lower() != ".dll":
                raise RecoveryError(f"managed reference is not a DLL: {path}")
            candidates = [path]
        elif path.is_dir():
            candidates = sorted(
                (item for item in path.iterdir() if item.is_file() and GAME_ASSEMBLY_PATTERN.match(item.name)),
                key=lambda item: item.name.lower(),
            )
            if not candidates:
                raise RecoveryError(f"managed reference directory has no Assembly-CSharp DLLs: {path}")
        else:
            raise RecoveryError(f"managed reference not found: {path}")
        for candidate in candidates:
            candidate = candidate.resolve()
            if candidate not in seen:
                seen.add(candidate)
                resolved.append(candidate)
    return resolved


def _run_donor_index(targets: list[Path], donors: list[Path]) -> dict[str, Any]:
    helper = _donor_index_dll()
    command = ["dotnet", str(helper)]
    for target in targets:
        command.extend(["--target", str(target)])
    for donor in donors:
        command.extend(["--donor", str(donor)])
    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RecoveryError(f"cross-version donor indexing failed: {detail}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RecoveryError(f"DonorIndex returned invalid JSON: {error}") from error


def _decompile_assembly(ilspy: str, assembly: Path, managed_directory: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    command = [
        ilspy,
        "--disable-updatecheck",
        "--nested-directories",
        "--project",
        "--referencepath",
        str(managed_directory),
        "--outputdir",
        str(output),
        str(assembly),
    ]
    completed = subprocess.run(command, text=True, capture_output=True)
    return {
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _zip_member(zip_file: zipfile.ZipFile, name: str, maximum: int = 1_500_000_000) -> bytes:
    info = zip_file.getinfo(name)
    if info.file_size > maximum:
        raise RecoveryError(f"refusing oversized IPA member {name} ({info.file_size} bytes)")
    return zip_file.read(info)


def _choose_info_plist(names: list[str]) -> str:
    candidates = [
        name
        for name in names
        if re.fullmatch(r"Payload/[^/]+\.app/Info\.plist", name, re.IGNORECASE)
    ]
    if len(candidates) != 1:
        raise RecoveryError(f"expected one application Info.plist, found {len(candidates)}")
    return candidates[0]


def _unity_version(main_data: bytes | None) -> str | None:
    if not main_data:
        return None
    match = UNITY_VERSION_PATTERN.search(main_data[:4096])
    return match.group(0).decode("ascii") if match else None


def _extract_ipa(ipa: Path, output: Path) -> tuple[dict[str, Any], bytes, list[Path]]:
    managed_directory = output / "managed"
    managed_directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ipa) as archive:
        names = archive.namelist()
        plist_member = _choose_info_plist(names)
        try:
            info = plistlib.loads(_zip_member(archive, plist_member, maximum=20_000_000))
        except Exception as error:
            raise RecoveryError(f"could not parse {plist_member}: {error}") from error
        app_prefix = plist_member[: -len("Info.plist")]
        executable_name = info.get("CFBundleExecutable")
        if not isinstance(executable_name, str) or not executable_name:
            raise RecoveryError("Info.plist has no CFBundleExecutable")
        executable_member = app_prefix + executable_name
        if executable_member not in names:
            raise RecoveryError(f"IPA is missing its executable: {executable_member}")
        executable_data = _zip_member(archive, executable_member)

        managed_members = sorted(
            name
            for name in names
            if name.startswith(app_prefix + "Data/Managed/")
            and name.lower().endswith(".dll")
            and "/mono/" not in name.lower()
        )
        managed_paths: list[Path] = []
        managed_manifest: list[dict[str, Any]] = []
        for member in managed_members:
            data = _zip_member(archive, member)
            destination = managed_directory / Path(member).name
            destination.write_bytes(data)
            managed_paths.append(destination)
            managed_manifest.append(
                {
                    "name": destination.name,
                    "ipa_member": member,
                    "size": len(data),
                    "sha256": _sha256(data),
                }
            )

        main_member = app_prefix + "Data/mainData"
        main_data = _zip_member(archive, main_member) if main_member in names else None

    app = {
        "ipa": str(ipa.resolve()),
        "ipa_sha256": _sha256(ipa.read_bytes()),
        "plist_member": plist_member,
        "app_prefix": app_prefix,
        "bundle_identifier": info.get("CFBundleIdentifier"),
        "bundle_name": info.get("CFBundleDisplayName") or info.get("CFBundleName"),
        "bundle_version": info.get("CFBundleVersion"),
        "short_version": info.get("CFBundleShortVersionString"),
        "minimum_os_version": info.get("MinimumOSVersion"),
        "executable_name": executable_name,
        "executable_member": executable_member,
        "executable_size": len(executable_data),
        "executable_sha256": _sha256(executable_data),
        "unity_version": _unity_version(main_data),
        "managed_assemblies": managed_manifest,
    }
    return app, executable_data, managed_paths


def _select_slices(slices: list[MachOSlice], architecture: str | None) -> list[MachOSlice]:
    if architecture is None:
        return slices
    selected = [item for item in slices if item.architecture == architecture]
    if not selected:
        available = ", ".join(item.architecture for item in slices)
        raise RecoveryError(f"architecture {architecture!r} was not found; available: {available}")
    return selected


def _verify_binary_override(ipa_binary: bytes, override_binary: bytes) -> dict[str, Any]:
    try:
        original_slices = parse_macho(ipa_binary)
        override_slices = parse_macho(override_binary)
    except MachOError as error:
        raise RecoveryError(f"could not verify decrypted executable identity: {error}") from error

    originals = {(item.cpu_type, item.cpu_subtype): item for item in original_slices}
    verified: list[dict[str, Any]] = []
    for candidate in override_slices:
        key = (candidate.cpu_type, candidate.cpu_subtype)
        original = originals.get(key)
        if original is None:
            raise RecoveryError(
                f"decrypted executable architecture {candidate.architecture} is absent from the IPA"
            )
        if original.uuid is None or candidate.uuid is None:
            raise RecoveryError(
                f"cannot verify {candidate.architecture} as the same build because LC_UUID is missing"
            )
        if original.uuid != candidate.uuid:
            raise RecoveryError(
                f"decrypted executable UUID mismatch for {candidate.architecture}: "
                f"expected {original.uuid}, got {candidate.uuid}"
            )
        original_layout = [
            (
                segment.name,
                segment.vm_address,
                segment.vm_size,
                segment.file_offset,
                segment.file_size,
            )
            for segment in original.segments
        ]
        candidate_layout = [
            (
                segment.name,
                segment.vm_address,
                segment.vm_size,
                segment.file_offset,
                segment.file_size,
            )
            for segment in candidate.segments
        ]
        if original_layout != candidate_layout:
            raise RecoveryError(
                f"decrypted executable segment layout mismatch for {candidate.architecture}"
            )
        original_encryption = [(item.offset, item.size) for item in original.encryption]
        candidate_encryption = [(item.offset, item.size) for item in candidate.encryption]
        if original_encryption != candidate_encryption:
            raise RecoveryError(
                f"decrypted executable encryption-range mismatch for {candidate.architecture}"
            )
        verified.append(
            {
                "architecture": candidate.architecture,
                "uuid": candidate.uuid,
                "verification": "LC_UUID, CPU subtype, segment layout, and encryption range",
            }
        )
    return {
        "verified": True,
        "method": "mach-o-build-identity",
        "architectures": verified,
    }


def _write_global_inventory(path: Path, module: AotModule) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["index", "name_address", "value_address", "name", "name_storage_encrypted"]
        )
        for entry in module.entries:
            writer.writerow(
                [
                    entry.index,
                    f"0x{entry.name_address:08x}",
                    f"0x{entry.value_address:08x}",
                    entry.name or "",
                    int(entry.name_storage_encrypted),
                ]
            )


def _label_for_method(method: dict[str, Any]) -> str:
    token = str(method["token"]).removeprefix("0x")
    raw = f"aot_{token}_{method['declaringType']}_{method['name']}"
    label = re.sub(r"[^A-Za-z0-9_$]", "_", raw)
    label = re.sub(r"_+", "_", label).strip("_")
    if not label or label[0].isdigit():
        label = "aot_" + label
    return label[:240]


def _write_method_map(directory: Path, assembly_name: str, methods: list[dict[str, Any]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    enriched = []
    for method in methods:
        copy = dict(method)
        copy["label"] = _label_for_method(method)
        enriched.append(copy)
    _write_json(directory / f"{assembly_name}.method-map.json", enriched)
    fields = [
        "token",
        "rid",
        "aot_index",
        "address",
        "raw_address",
        "thumb",
        "estimated_size",
        "label",
        "declaringType",
        "name",
        "fullName",
        "returnType",
    ]
    with (directory / f"{assembly_name}.method-map.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for method in enriched:
            row = dict(method)
            row["address"] = f"0x{int(method['address']):08x}"
            row["raw_address"] = f"0x{int(method['raw_address']):08x}"
            writer.writerow(row)


def _write_combined_labels(directory: Path, methods: list[dict[str, Any]]) -> None:
    if not methods:
        return
    directory.mkdir(parents=True, exist_ok=True)
    sorted_methods = sorted(methods, key=lambda method: int(method["address"]))
    with (directory / "radare2-labels.r2").open("w", encoding="utf-8") as handle:
        handle.write("# Generated by unity3-aot-recover\n")
        for method in sorted_methods:
            label = _label_for_method(method)
            address = int(method["address"])
            size = int(method.get("estimated_size") or 0)
            handle.write(f"f {label} {size} @ 0x{address:x}\n")
            handle.write(f"af @ 0x{address:x}\n")
            handle.write(f"afn {label} @ 0x{address:x}\n")
    with (directory / "ghidra-method-map.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(["address", "raw_address", "thumb", "size", "label", "signature", "token"])
        for method in sorted_methods:
            writer.writerow(
                [
                    f"0x{int(method['address']):x}",
                    f"0x{int(method['raw_address']):x}",
                    int(bool(method["thumb"])),
                    method.get("estimated_size") or "",
                    _label_for_method(method),
                    method["fullName"],
                    method["token"],
                ]
            )
    with (directory / "ghidra-method-map.tsv").open("w", encoding="utf-8") as handle:
        handle.write("address\traw_address\tthumb\tsize\tlabel\tsignature\ttoken\n")
        for method in sorted_methods:
            signature = str(method["fullName"]).replace("\t", " ").replace("\n", " ")
            handle.write(
                "0x{address:x}\t0x{raw:x}\t{thumb}\t{size}\t{label}\t{signature}\t{token}\n".format(
                    address=int(method["address"]),
                    raw=int(method["raw_address"]),
                    thumb=int(bool(method["thumb"])),
                    size=method.get("estimated_size") or "",
                    label=_label_for_method(method),
                    signature=signature,
                    token=method["token"],
                )
            )


def _game_metadata(managed_paths: list[Path], output: Path) -> tuple[list[dict[str, Any]], list[str]]:
    metadata: list[dict[str, Any]] = []
    errors: list[str] = []
    for assembly in managed_paths:
        if not GAME_ASSEMBLY_PATTERN.match(assembly.name):
            continue
        try:
            record = _dump_metadata(assembly)
            metadata.append(record)
            _write_json(output / "metadata" / f"{assembly.stem}.json", record)
        except RecoveryError as error:
            errors.append(str(error))
    return metadata, errors


def _decompile_game_assemblies(
    managed_paths: list[Path], output: Path, explicit_ilspy: str | None
) -> tuple[list[dict[str, Any]], str | None]:
    ilspy = _find_ilspy(explicit_ilspy)
    if ilspy is None:
        return [], "ilspycmd was not found; managed metadata was still recovered"
    results = []
    managed_directory = output / "managed"
    log_directory = output / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    for assembly in managed_paths:
        if not GAME_ASSEMBLY_PATTERN.match(assembly.name):
            continue
        result = _decompile_assembly(
            ilspy,
            assembly,
            managed_directory,
            output / "csharp-skeletons" / assembly.stem,
        )
        (log_directory / f"ilspy-{assembly.stem}.stdout.log").write_text(
            result["stdout"], encoding="utf-8"
        )
        (log_directory / f"ilspy-{assembly.stem}.stderr.log").write_text(
            result["stderr"], encoding="utf-8"
        )
        results.append(
            {
                "assembly": assembly.name,
                "exit_code": result["exit_code"],
                "output": str(output / "csharp-skeletons" / assembly.stem),
            }
        )
    return results, None


def _write_donor_index(output: Path, report: dict[str, Any]) -> None:
    directory = output / "reference-donor"
    _write_json(directory / "index.json", report)
    fields = [
        "targetAssembly",
        "targetAssemblySha256",
        "targetToken",
        "targetRid",
        "targetDeclaringType",
        "targetFullName",
        "targetRetOnlyBody",
        "donorAssembly",
        "donorAssemblySha256",
        "donorToken",
        "donorRid",
        "donorDeclaringType",
        "donorFullName",
        "donorHasBodyBeyondRetStub",
        "donorCodeSize",
        "donorInstructionCount",
        "sameFieldShape",
        "sameMethodShape",
        "confidenceTier",
        "ambiguousDonorCount",
    ]
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "matches.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report.get("matches", []))


def _decompile_reference_assemblies(
    donors: list[Path], output: Path, explicit_ilspy: str | None
) -> tuple[list[dict[str, Any]], str | None]:
    ilspy = _find_ilspy(explicit_ilspy)
    if ilspy is None:
        return [], "ilspycmd was not found; the donor index was still recovered"
    results: list[dict[str, Any]] = []
    log_directory = output / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    for donor in donors:
        digest = _sha256(donor.read_bytes())
        identity = f"{donor.stem}-{digest[:8]}"
        destination = output / "reference-donor" / "csharp" / identity
        result = _decompile_assembly(ilspy, donor, donor.parent, destination)
        (log_directory / f"ilspy-donor-{identity}.stdout.log").write_text(
            result["stdout"], encoding="utf-8"
        )
        (log_directory / f"ilspy-donor-{identity}.stderr.log").write_text(
            result["stderr"], encoding="utf-8"
        )
        results.append(
            {
                "assembly": donor.name,
                "sha256": digest,
                "exit_code": result["exit_code"],
                "output": str(destination),
            }
        )
    return results, None


def _markdown_report(manifest: dict[str, Any]) -> str:
    app = manifest["app"]
    architectures = manifest["architectures"]
    metadata = manifest["game_metadata"]
    donor = manifest.get("reference_donor")
    mapped = sum(
        mapping.get("mapped_method_count", 0)
        for architecture in architectures
        for mapping in architecture.get("method_maps", [])
    )
    encrypted = [item["architecture"] for item in architectures if item["encrypted"]]
    if mapped:
        outcome = (
            f"Recovered managed structure and mapped **{mapped:,}** MethodDef entries to native AOT functions. "
            "The generated Ghidra/radare2 maps are ready for native pseudocode export."
        )
    elif encrypted:
        outcome = (
            "Recovered the complete managed type/signature structure, but the supplied native executable is "
            f"FairPlay-encrypted for {', '.join(encrypted)}. A same-build decrypted executable is required "
            "before ARM method bodies can be mapped or decompiled."
        )
    else:
        outcome = (
            "Recovered managed structure, but no usable Unity Mono AOT method-address table was found in "
            "the supplied executable."
        )

    lines = [
        f"# {app.get('bundle_name') or app['executable_name']} recovery report",
        "",
        "## Outcome",
        "",
        outcome,
        "",
        "## Build identity",
        "",
        f"- Bundle: `{app.get('bundle_identifier')}`",
        f"- App version: `{app.get('short_version') or app.get('bundle_version')}`",
        f"- Unity version: `{app.get('unity_version') or 'unknown'}`",
        f"- Executable SHA-256: `{app.get('executable_sha256')}`",
        "",
        "## Architectures",
        "",
        "| Architecture | Encrypted | AOT modules | Function starts |",
        "|---|---:|---:|---:|",
    ]
    for architecture in architectures:
        lines.append(
            "| {architecture} | {encrypted} | {modules} | {functions:,} |".format(
                architecture=architecture["architecture"],
                encrypted="yes" if architecture["encrypted"] else "no",
                modules=len(architecture.get("aot_modules", [])),
                functions=architecture.get("function_start_count", 0),
            )
        )
    lines.extend(
        [
            "",
            "## Managed game assemblies",
            "",
            "| Assembly | Types | Methods | `ret`-only bodies |",
            "|---|---:|---:|---:|",
        ]
    )
    for assembly in metadata:
        lines.append(
            f"| {assembly['name']} | {assembly['typeCount']:,} | {assembly['methodCount']:,} | "
            f"{assembly['retOnlyBodies']:,} |"
        )
    lines.extend(
        [
            "",
            "The DLL bodies are Unity's AOT reference stubs; fields, types, inheritance, signatures, tokens, "
            "P/Invoke declarations, and serialized class structure remain useful and are exported under `metadata/`.",
            "",
        ]
    )
    if any(item.get("exit_code") == 0 for item in manifest.get("decompilation", [])):
        lines.extend(
            [
                "ILSpy exported C# skeletons for the successfully decompiled assemblies under `csharp-skeletons/`.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "C# skeletons were not produced in this run; see the decompilation fields in `manifest.json`.",
                "",
            ]
        )
    if donor:
        lines.extend(
            [
                "## Cross-version donor index",
                "",
                "A separately supplied managed build has normalized method matches with CIL beyond the target's "
                "single-`ret` stub pattern. These are "
                "**porting references, not recovered bodies from this app build**. Even Tier A cannot prove that "
                "behavior stayed identical between versions.",
                "",
                "| Target assembly | Methods | Normalized identities | Donor bodies beyond `ret` stub | Tier A | Tier B | Tier C |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for target in donor.get("targets", []):
            lines.append(
                "| {assembly} | {methods:,} | {exact:,} | {bodies:,} | {tier_a:,} | {tier_b:,} | {tier_c:,} |".format(
                    assembly=target["assembly"],
                    methods=target["targetMethodCount"],
                    exact=target["exactSignatureMatches"],
                    bodies=target["donorBodiesBeyondRetStub"],
                    tier_a=target["tierA"],
                    tier_b=target["tierB"],
                    tier_c=target["tierC"],
                )
            )
        lines.extend(
            [
                "",
                "Tier A matches normalized method identity plus declaring type field and method surfaces; Tier B "
                "matches identity and the field surface; Tier C matches normalized method identity only. Ambiguity and "
                "both assembly hashes are retained per method in `reference-donor/index.json` and `matches.csv`.",
                "",
            ]
        )
        if any(item.get("exit_code") == 0 for item in manifest.get("reference_decompilation", [])):
            lines.extend(
                [
                    "ILSpy exported the supplied donor C# under `reference-donor/csharp/`. Use the CSV to select "
                    "candidate methods by target token and confidence tier.",
                    "",
                ]
            )
    lines.extend(
        [
            "## Native recovery artifacts",
            "",
            "Each architecture directory contains a thin Mach-O slice, AOT global-table inventories, and—when "
            "the executable is decrypted—token-to-address JSON/CSV plus Ghidra and radare2 label files.",
            "",
        ]
    )
    if not mapped and encrypted:
        lines.extend(
            [
                "## Required next input",
                "",
                "Provide the decrypted main executable from this exact app build. The recovery CLI accepts it "
                "with `--binary /path/to/decrypted-executable`; it does not need another asset dump. A binary "
                "from a different version will not match the preserved MethodDef tokens.",
                "",
            ]
        )
    lines.extend(
        [
            "## Accuracy boundary",
            "",
            "A native decompiler reconstructs control flow and expressions, not the developers' original C# "
            "formatting, comments, local-variable names, or every high-level construct. Combining native "
            "pseudocode with the preserved managed metadata produces a practical porting source base, but it "
            "is not byte-for-byte original source.",
            "",
        ]
    )
    return "\n".join(lines)


def recover(args: argparse.Namespace) -> dict[str, Any]:
    ipa = Path(args.ipa).expanduser().resolve()
    if not ipa.is_file():
        raise RecoveryError(f"IPA not found: {ipa}")
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)

    app, ipa_executable, managed_paths = _extract_ipa(ipa, output)
    game_assemblies = [path for path in managed_paths if GAME_ASSEMBLY_PATTERN.match(path.name)]
    reference_paths = _resolve_reference_managed(args.reference_managed)
    binary_path = Path(args.binary).expanduser().resolve() if args.binary else None
    if binary_path is not None and not binary_path.is_file():
        raise RecoveryError(f"decrypted executable not found: {binary_path}")
    executable_data = binary_path.read_bytes() if binary_path else ipa_executable
    binary_verification = (
        _verify_binary_override(ipa_executable, executable_data)
        if binary_path
        else {"verified": True, "method": "embedded IPA executable", "architectures": []}
    )
    app["analysis_binary"] = str(binary_path) if binary_path else app["executable_member"]
    app["analysis_binary_sha256"] = _sha256(executable_data)
    app["analysis_binary_is_override"] = binary_path is not None
    app["analysis_binary_verification"] = binary_verification

    metadata, metadata_errors = _game_metadata(managed_paths, output)
    metadata_by_module = {
        sanitize_module_name(record["name"]): record for record in metadata
    }
    if args.no_decompile:
        decompilation, decompilation_error = [], "skipped by --no-decompile"
    else:
        decompilation, decompilation_error = _decompile_game_assemblies(
            managed_paths, output, args.ilspycmd
        )

    reference_donor: dict[str, Any] | None = None
    reference_decompilation: list[dict[str, Any]] = []
    reference_decompilation_error: str | None = None
    if reference_paths:
        donor_report = _run_donor_index(game_assemblies, reference_paths)
        _write_donor_index(output, donor_report)
        reference_donor = {
            key: value for key, value in donor_report.items() if key != "matches"
        }
        reference_donor["index"] = "reference-donor/index.json"
        reference_donor["matchesCsv"] = "reference-donor/matches.csv"
        if args.no_decompile:
            reference_decompilation_error = "skipped by --no-decompile"
        else:
            reference_decompilation, reference_decompilation_error = _decompile_reference_assemblies(
                reference_paths, output, args.ilspycmd
            )

    try:
        slices = _select_slices(parse_macho(executable_data), args.arch)
    except MachOError as error:
        raise RecoveryError(f"could not parse native executable: {error}") from error

    architecture_manifests: list[dict[str, Any]] = []
    for image in slices:
        arch_directory = output / "native" / image.architecture
        arch_directory.mkdir(parents=True, exist_ok=True)
        thin_path = arch_directory / app["executable_name"]
        thin_path.write_bytes(image.data)
        modules = parse_aot_modules(image)
        module_manifests = []
        method_map_manifests = []
        combined_methods: list[dict[str, Any]] = []
        for module in modules:
            _write_global_inventory(
                arch_directory / "aot-globals" / f"{module.module_name}.csv", module
            )
            module_manifests.append(module.to_manifest(include_entries=False))
            metadata_record = metadata_by_module.get(module.module_name)
            if metadata_record is None:
                continue
            methods, error = build_method_map(image, module, metadata_record["methods"])
            map_record = {
                "module": module.module_name,
                "assembly": metadata_record["name"],
                "metadata_method_count": metadata_record["methodCount"],
                "aot_method_count": module.nmethods,
                "mapped_method_count": len(methods),
                "error": error,
            }
            method_map_manifests.append(map_record)
            if methods:
                _write_method_map(
                    arch_directory / "method-maps", metadata_record["name"], methods
                )
                combined_methods.extend(methods)
        _write_combined_labels(arch_directory / "labels", combined_methods)
        architecture_manifest = image.to_manifest()
        architecture_manifest.update(
            {
                "thin_binary": str(thin_path),
                "thin_binary_sha256": _sha256(image.data),
                "aot_modules": module_manifests,
                "method_maps": method_map_manifests,
                "mapped_method_count": len(combined_methods),
            }
        )
        architecture_manifests.append(architecture_manifest)

    manifest = {
        "tool": "unity3-aot-recover",
        "tool_version": __version__,
        "app": app,
        "game_metadata": [
            {key: value for key, value in record.items() if key != "methods"} for record in metadata
        ],
        "metadata_errors": metadata_errors,
        "decompilation": decompilation,
        "decompilation_error": decompilation_error,
        "reference_donor": reference_donor,
        "reference_decompilation": reference_decompilation,
        "reference_decompilation_error": reference_decompilation_error,
        "architectures": architecture_manifests,
    }
    mapped_count = sum(item["mapped_method_count"] for item in architecture_manifests)
    if mapped_count:
        manifest["recovery_state"] = "native-method-map-recovered"
    elif any(item["encrypted"] for item in architecture_manifests):
        manifest["recovery_state"] = "metadata-recovered-native-encrypted"
    else:
        manifest["recovery_state"] = "metadata-recovered-native-map-unavailable"

    _write_json(output / "manifest.json", manifest)
    (output / "REPORT.md").write_text(_markdown_report(manifest), encoding="utf-8")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="unity3-aot-recover",
        description=(
            "Recover C# metadata and Mono AOT method maps from old Unity iOS IPAs. "
            "FairPlay decryption is intentionally out of scope; pass an authorized, "
            "same-build decrypted executable with --binary."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            examples:
              python3 aot-recover.py game.ipa -o recovered/game
              python3 aot-recover.py game.ipa -o recovered/game --arch armv7 \\
                  --binary /path/to/decrypted/app
              python3 aot-recover.py game.ipa -o recovered/game \\
                  --reference-managed /path/to/later-build/Data/Managed
            """
        ),
    )
    parser.add_argument("ipa", nargs="?", help="source IPA")
    parser.add_argument("-o", "--output", help="artifact directory")
    parser.add_argument(
        "--binary",
        help="authorized decrypted executable whose Mach-O build identity matches the IPA",
    )
    parser.add_argument("--arch", help="analyze only this architecture (for example armv7)")
    parser.add_argument("--ilspycmd", help="path to ilspycmd")
    parser.add_argument("--no-decompile", action="store_true", help="skip ILSpy C# skeleton export")
    parser.add_argument(
        "--reference-managed",
        action="append",
        metavar="DLL_OR_DIRECTORY",
        help=(
            "index matching method bodies from another managed build as non-authoritative porting "
            "references; may be repeated"
        ),
    )
    parser.add_argument(
        "--print-resource-dir",
        action="store_true",
        help="print the installed helper/Ghidra resource directory and exit",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.print_resource_dir:
        print(RESOURCE_ROOT)
        return 0
    if not args.ipa:
        parser.error("the following argument is required: ipa")
    if not args.output:
        parser.error("the following argument is required: -o/--output")
    try:
        manifest = recover(args)
    except (RecoveryError, OSError, zipfile.BadZipFile) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"state: {manifest['recovery_state']}")
    print(f"report: {Path(args.output).expanduser().resolve() / 'REPORT.md'}")
    return 0
