# Legacy Unity iOS Mono AOT architecture

## Recovery model

The targeted Unity 3.x iOS layout has two complementary inputs:

1. `Data/Managed/*.dll` preserves ECMA-335 metadata: types, fields, inheritance, signatures, attributes, P/Invoke declarations, and MethodDef rows.
2. The app's Mach-O executable statically links Mono AOT modules containing native ARM implementations and lookup tables.

Unity's iOS build pipeline may reduce ordinary managed bodies to a single `ret`. A normal .NET decompiler can then reconstruct class structure, but not behavior.

## AOT registration

Legacy static modules export symbols shaped like:

```text
_mono_aot_module_Assembly_CSharp_info
```

The symbol points to a static globals table. That table begins with a globals-hash pointer followed by `(name pointer, value pointer)` pairs and a null pair terminator. Once its `__TEXT` strings are readable, entries identify `mono_aot_file_info`, `method_addresses`, `methods`, `methods_end`, and related tables.

## MethodDef mapping

The historical Mono AOT compiler adds normal assembly methods first, in MethodDef row order, and gives them their zero-based token index. Extra generic instances and wrappers are added later. For an ordinary MethodDef:

```text
AOT index      = MethodDef RID - 1
native pointer = method_addresses[AOT index]
```

The mapper preserves the raw pointer, clears the low ARM Thumb bit for the canonical address, validates that address against an executable segment, and estimates the function boundary from `LC_FUNCTION_STARTS` plus other AOT pointers.

Reference implementation evidence:

- [Unity Mono `collect_methods`](https://github.com/Unity-Technologies/mono/blob/unity-4.1/mono/mini/aot-compiler.c)
- [Unity Mono AOT runtime table loading](https://github.com/Unity-Technologies/mono/blob/unity-4.1/mono/mini/aot-runtime.c)

## Encryption boundary

An App Store IPA may contain `LC_ENCRYPTION_INFO` with a nonzero `cryptid`. The load command identifies the file range protected by FairPlay. Module descriptor pointers in `__DATA` and dynamic symbols in `__LINKEDIT` may remain readable while method code, names, and address tables in `__TEXT` are encrypted.

The tool reports those plaintext facts but does not attempt to interpret the protected range. A same-build executable already decrypted through an authorized workflow can be passed with `--binary`. Before mapping, the tool requires its CPU subtype, `LC_UUID`, segment layout, and encryption range to match an original IPA slice. Some dumpers leave `cryptid` unchanged, so table readability is validated independently of that flag.

## Accuracy limits

Native decompilation does not reproduce original comments, formatting, local-variable names, or every high-level C# construct. The practical preservation output is:

- authoritative managed type/signature metadata;
- deterministic method identity and address mapping;
- labeled C-like native pseudocode;
- extracted assets handled by separate Unity tooling.
