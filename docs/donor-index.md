# Cross-version managed donor index

Some later Unity releases, Android/desktop builds, or preservation projects retain ordinary CIL bodies even when an old iOS build contains AOT `ret` stubs. `--reference-managed` makes that overlap usable without presenting it as source recovered from the target build.

## Match identity

A candidate must have the same normalized declaring type, method name, generic arity, ordered parameter types, return type, instance/static form, explicit-this flag, and calling convention. Type identities include their assembly scope; `Assembly-CSharp` and `Assembly-CSharp-firstpass` are deliberately canonicalized to one game scope because Unity commonly merges firstpass code in later builds. Every row retains both assembly SHA-256 hashes and both MethodDef tokens. When multiple donors match, the index records the candidate count and deterministically selects the strongest candidate whose CIL is more than the target-style single `ret` stub.

## Confidence tiers

All tiers are heuristics across builds, not proof of identical implementation:

| Tier | Required evidence |
|---|---|
| A | Normalized method identity, donor body beyond a single `ret`, and identical declaring-type field and method surfaces |
| B | Normalized method identity, donor body beyond a single `ret`, and identical declaring-type field surface |
| C | Normalized method identity and a donor body beyond a single `ret` |
| metadata-only | Normalized identity, but no body beyond the single-`ret` pattern |

Field comparison includes order, names, types, attributes, constant presence/value, base type, interfaces, and type attributes. Method-surface comparison includes every method identity, attributes, and implementation attributes on the declaring type.

“Beyond `ret`” is a precise filter for the AOT stub pattern seen in these targets, not a proof that a donor method is useful or non-stub logic; other placeholder bodies can pass it. Tier A can also hide changed constants, asset assumptions, server protocols, side effects, compiler transformations, or method logic. Treat donor C# as a porting aid and validate it against target-build native pseudocode when an authorized decrypted executable becomes available.

## Artifacts

- `reference-donor/index.json` is the full machine-readable report.
- `reference-donor/matches.csv` is a flat method-level join suitable for filtering by token, type, tier, or ambiguity.
- `reference-donor/csharp/` contains ILSpy output from the supplied donor; it is generated locally and should only be shared when licensing and authorization allow it.

The repository contains the indexer and synthetic fixtures, not third-party assemblies or reconstructed application source.
