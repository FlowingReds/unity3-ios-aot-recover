# Call of Mini Zombies 2.0.2

## Build identity

- Bundle: `com.trinitigame.callofminizombies`
- Version: `2.0.2`
- Unity: `3.5.0f5`
- Executable SHA-256: `69099b426858d38eb555ec621b1f99a14d9d7ad293b7ab8be601ba7560d4ebd1`
- Architectures: ARMv6 and ARMv7

## Managed structure

| Assembly | Types | Methods | `ret`-only bodies |
|---|---:|---:|---:|
| Assembly-CSharp-firstpass | 146 | 713 | 644 |
| Assembly-CSharp | 629 | 3,659 | 3,430 |

Seven Mono AOT modules are registered in each architecture. `Assembly_CSharp` reports 5,223 AOT slots; `Assembly_CSharp_firstpass` reports 1,568.

## Native status

Both slices use `LC_ENCRYPTION_INFO cryptid=1`, and the protected range covers the executable `__TEXT` content needed for method recovery. Module registrations and managed metadata were recovered, but native logic requires a same-build decrypted executable.

This repository contains no game binaries, managed assemblies, assets, or reconstructed source.
