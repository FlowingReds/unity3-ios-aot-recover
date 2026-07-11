# Donor-backed Unity project reconstruction

The scripts in `tools/` help turn locally recovered Unity project material into
a project that can be compiled by a newer Unity editor. This is a porting
workflow built on top of recovery output, not another form of exact source
recovery.

Use these helpers only with applications and related builds that you are
authorized to inspect. The repository contains no third-party game content.

## Keep the provenance layers separate

A reconstructed project can combine several kinds of evidence. They do not
have equal authority:

| Layer | What it can establish | Important limit |
|---|---|---|
| Exact target assets and serialized project data | Content extracted from the target build, subject to the extractor's fidelity | It does not reveal stripped method implementations |
| Exact target managed metadata | Types, fields, signatures, attributes, assembly identity, and MethodDef rows | A single-`ret` body contains no recoverable CIL behavior |
| Same-build native method map and pseudocode | Native implementation evidence when an authorized, matching decrypted executable is supplied | Native decompilation is not original C# source |
| Cross-version or cross-platform donor CIL | A candidate implementation and compatibility reference | Even a strong structural match does not prove identical behavior |
| Porting edits | Compatibility with a newer Unity/.NET/platform API | These are new implementation choices, not recovered facts |

An asset or metadata item extracted from the exact target should remain labeled
as target-derived. A method body copied from Android, desktop, a later release,
or any other related build must remain labeled as donor-derived. The
[`--reference-managed` donor index](donor-index.md) provides method-level match
evidence, but its confidence tiers are heuristics rather than proof of source
identity.

The helpers do not:

- decrypt FairPlay-protected executable ranges;
- recover a stripped method body from metadata alone;
- convert the original ARM iOS executable into a desktop executable;
- make a donor implementation authoritative because its filename or signature
  matches;
- guarantee that target assets are compatible with donor code or a newer Unity
  runtime.

A desktop player emitted after this process is a newly compiled port. It should
not be described as a decrypted, transcoded, or exact native build of the iOS
executable.

## Suggested workspace layout

Keep immutable inputs separate from generated and edited trees. For example:

```text
work/
├── target-project/                  # project reconstructed from the target
│   └── Assets/
├── donor-csharp/                    # ILSpy output from an authorized donor
├── provenance/                      # hashes, donor index, command log
└── build/                           # new editor/player output
```

Do not run donor overlays directly against the only copy of recovered target
source. Retain hashes or a read-only snapshot so every replacement can be
audited.

## Helper workflow

The examples below use generic paths and operate only on local files.

### 1. Sanitize stripped decompiler stubs

```bash
python3 tools/sanitize_aot_stubs.py \
  work/target-project/Assets/Scripts
```

`sanitize_aot_stubs.py` replaces ILSpy's invalid expression for a
value-returning, single-`ret` method with an explicit
`NotImplementedException`. It also replaces the C# 7 `return default; // stub`
marker with the same C# 4-compatible throw.

This makes the missing behavior visible at compile time/runtime boundaries; it
does not reconstruct that behavior. A remaining throw is a tracked recovery
gap, not a working implementation.

### 2. Overlay path-matched donor files

```bash
python3 tools/overlay_donor_sources.py \
  work/target-project/Assets/Scripts/Assembly-CSharp \
  work/donor-csharp/Assembly-CSharp
```

The first argument is the target source root and the second is the donor root.
Only donor `.cs` files with a matching relative path already present in the
target are copied. Target `.meta` files are not replaced, preserving Unity
script GUIDs and serialized references.

A path match is only a mechanical overlay rule. Before accepting a body, review
the donor index, version/platform differences, fields, constants, external
services, and asset assumptions. Files that exist only in the target remain in
place.

### 3. Copy donor-only support types separately

```bash
python3 tools/copy_donor_support.py \
  work/donor-csharp/Assembly-CSharp \
  work/target-project/Assets/Scripts/DonorSupport \
  --exclude-root work/target-project/Assets/Scripts/Assembly-CSharp \
  --exclude-root work/target-project/Assets/Plugins/Assembly-CSharp-firstpass
```

`copy_donor_support.py` copies donor files whose relative paths do not already
exist in any repeated `--exclude-root`. Keeping them under a visibly named
`DonorSupport` directory makes their origin reviewable and avoids common
cross-assembly duplicate-file overlays.

Donor-only support types may not exist in the target at all. Include only those
required by reviewed donor implementations, and record each inclusion. This
helper does not prove that an added type belongs to the target build.

### 4. Modernize removed Unity component APIs

```bash
python3 tools/modernize_unity3_component_api.py \
  work/target-project/Assets/Scripts \
  work/target-project/Assets/Plugins
```

Unity 3 exposed convenience properties such as `component.audio` and
`component.collider`; Unity 2017 requires `GetComponent<T>()`. The modernizer
rewrites only receivers it can conservatively identify as a `GameObject` or
`Component` from declarations in the supplied source corpus. It deliberately
leaves unrelated members such as `RaycastHit.collider`,
`ControllerColliderHit.collider`, and a custom `AudioInfo.audio` unchanged.

The pass also qualifies recognized `System.Math` members when a global game
`Math` type would shadow them, and adds `using UnityEngine.AI;` for unqualified
NavMesh references. Ambiguous expressions remain unchanged for compiler-guided
review. Run related source roots in one invocation so component subclasses can
be identified across files.

## Compile and validate

After the helper passes, compilation errors still need source-specific review.
Common remaining work includes removed Unity APIs, platform-only plugins,
namespace/type collisions between target and donor versions, changed enum
surfaces, and external service integrations.

Build with a legitimately installed Unity editor appropriate for the project
and target platform. A successful compile is not sufficient evidence of
behavioral equivalence. At minimum:

1. retain the exact-target scene order, script GUIDs, and serialized assets;
2. inventory every donor-overlaid and donor-only file;
3. inventory every unresolved stub and manual compatibility patch;
4. smoke-test scene loading, input, audio, persistence, and offline failure
   paths;
5. compare important behavior with same-build native evidence when authorized
   native pseudocode is available.

## Record a reproducible provenance manifest

Store enough information to reproduce and audit the port without bundling
third-party content:

- target application/build identity and cryptographic hashes;
- exact managed-assembly hashes and extraction-tool versions;
- donor version, platform, assembly hashes, and donor-index report;
- helper commands and the repository revision used;
- Unity editor version and build target;
- a list of donor-only files, manual changes, unresolved stubs, and known
  behavioral differences;
- hashes of the resulting player artifacts.

Do not publish extracted assets, managed binaries, reconstructed third-party
source, signing material, or purchaser data unless you have the rights to do
so. See the repository's [legal and third-party notice](../LEGAL.md).
