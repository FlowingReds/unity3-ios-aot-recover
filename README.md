# Unity 3 iOS Mono AOT Recover

[![CI](https://github.com/iHawksPro/unity3-ios-aot-recover/actions/workflows/ci.yml/badge.svg)](https://github.com/iHawksPro/unity3-ios-aot-recover/actions/workflows/ci.yml)

Recover managed structure and deterministic native-method maps from pre-IL2CPP Unity iOS applications.

Old Unity iOS builds commonly retain .NET metadata in `Data/Managed`, replace CIL implementations with `ret` stubs, and place the real code in statically linked Mono AOT modules inside the Mach-O executable. This tool joins those pieces back together.

## Capabilities

- extracts application/build identity, Unity version, and managed assemblies from an IPA;
- exports C# type/signature skeletons with ILSpy;
- records exact MethodDef tokens and stripped-body coverage with Mono.Cecil;
- parses thin and fat 32-bit ARM Mach-O executables without third-party Python packages;
- detects `LC_ENCRYPTION_INFO` and refuses to describe encrypted bytes as recovered code;
- discovers legacy `_mono_aot_module_*_info` registrations and static global tables;
- maps ordinary managed methods using `AOT index = MethodDef RID - 1` when a same-build decrypted executable is supplied;
- emits JSON/CSV method maps plus ARM/Thumb-aware Ghidra and radare2 labels;
- indexes CIL bodies beyond the target's single-`ret` stub pattern using scope-aware normalized method identities, structural confidence tiers, and ambiguity tracking;
- exports related-build C# as an explicitly non-authoritative porting reference;
- automates per-method Ghidra C-like pseudocode export.

It does **not** bypass FairPlay or download application binaries. Use it only with software you own or are authorized to inspect.

## Requirements

- Python 3.10+
- .NET 10 SDK/runtime for the bundled managed-analysis helpers
- [`ilspycmd`](https://github.com/icsharpcode/ILSpy) for C# skeletons
- [Ghidra](https://github.com/NationalSecurityAgency/ghidra) for native pseudocode

The Python parser itself uses only the standard library.

## Install

```bash
git clone https://github.com/iHawksPro/unity3-ios-aot-recover.git
cd unity3-ios-aot-recover
python3 -m pip install .
```

You can also run `python3 aot-recover.py` directly from a checkout.

## Quick start

```bash
unity3-aot-recover /path/to/game.ipa -o /path/to/recovered/game
```

If you have an authorized decrypted executable from the **exact same build**:

```bash
unity3-aot-recover /path/to/game.ipa \
  -o /path/to/recovered/game \
  --arch armv7 \
  --binary /path/to/decrypted/main-executable
```

The override is accepted only when its Mach-O CPU subtype, `LC_UUID`, segment layout, and encryption range match an original IPA slice. A decrypted thin slice from a fat IPA is supported.

Use `--no-decompile` when ILSpy is unavailable. See [architecture and method mapping](https://github.com/iHawksPro/unity3-ios-aot-recover/blob/main/docs/architecture.md) for the format details.

If another version or platform retains CIL beyond the target's single-`ret` pattern, add it as a reference:

```bash
unity3-aot-recover /path/to/game.ipa \
  -o /path/to/recovered/game \
  --reference-managed /path/to/related-build/Data/Managed
```

You may repeat `--reference-managed` or pass a DLL directly. These bodies are never labeled as exact recovery: [the donor-index model](https://github.com/iHawksPro/unity3-ios-aot-recover/blob/main/docs/donor-index.md) records what matched and how strong the structural evidence is.

## Reconstructing a buildable Unity project

The repository also includes small helpers for assembling an authorized,
donor-backed Unity project from locally recovered material. They sanitize
stripped decompiler stubs, overlay matching donor source without replacing
target `.meta` files, copy explicitly separated donor-only dependencies, and
modernize selected Unity 3 APIs for Unity 2017.

These helpers do not decrypt FairPlay, translate the original ARM executable,
or establish that code from another build is the target's original logic. See
[donor-backed native porting](docs/native-porting.md) for the provenance model,
limitations, and command examples.

The current machine-local continuation state for the two validated case-study
ports is recorded in [the workspace handoff](WORKSPACE_HANDOFF.md). It contains
paths and hashes only; third-party game content and players are not committed.

## Output

```text
recovered/game/
├── REPORT.md
├── manifest.json
├── managed/
├── metadata/
├── csharp-skeletons/
├── reference-donor/                 # when --reference-managed is supplied
│   ├── index.json
│   ├── matches.csv
│   └── csharp/
└── native/
    └── armv7/
        ├── main-executable
        ├── aot-globals/
        ├── method-maps/                 # after a decrypted run
        └── labels/
            ├── ghidra-method-map.tsv
            └── radare2-labels.r2
```

## Ghidra export

After a successful decrypted run:

```bash
/path/to/ghidra/support/analyzeHeadless /tmp/ghidra-project unity3-aot \
  -import "$ARCH_DIR/main-executable" \
  -scriptPath "$PWD/aot_recover/resources/ghidra" \
  -postScript ApplyAotMethodMap.java "$ARCH_DIR/labels/ghidra-method-map.tsv" \
  -postScript ExportAotPseudoC.java "$ARCH_DIR/pseudocode"
```

The Java importer works in ordinary headless Ghidra. A Python importer is also included for PyGhidra-enabled sessions.

For an installed package, locate those scripts with:

```bash
unity3-aot-recover --print-resource-dir
```

## Validated case studies

- [Call of Mini Zombies 2.0.2](https://github.com/iHawksPro/unity3-ios-aot-recover/blob/main/docs/case-studies/call-of-mini-zombies-2.0.2.md)
- [Call of Mini Dino Hunter Lite 1.0.1](https://github.com/iHawksPro/unity3-ios-aot-recover/blob/main/docs/case-studies/call-of-mini-dino-hunter-lite-1.0.1.md)

These case studies contain hashes and structural findings only. No IPAs, executable code, assets, managed binaries, or reconstructed third-party source are included.

## Development

```bash
python3 -m unittest discover -s tests -v
dotnet build aot_recover/resources/MetadataDump/MetadataDump.csproj --configuration Release --nologo
dotnet build aot_recover/resources/DonorIndex/DonorIndex.csproj --configuration Release --nologo
```

Automated synthetic fixtures cover Mach-O parsing, encryption commands, static AOT globals, Thumb addresses, MethodDef mapping, function-size boundaries, and all three donor confidence tiers. The Ghidra Java importer and pseudocode exporter were manually smoke-tested headlessly with Ghidra 12.1.2; Ghidra is not installed in CI.

## License

MIT. Third-party applications and their contents remain subject to their respective owners' rights.
