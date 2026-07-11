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

## Related-build donor experiment

A separately held Call of Mini Zombies 4.3.4 managed assembly (SHA-256 `13035bfa3c02cf307c06dff63549581ccf186015030d8c4bec4802966792f779`) was indexed as a cross-version reference:

| Target assembly | Normalized identities | Donor bodies beyond `ret` | Tier A | Tier B | Tier C |
|---|---:|---:|---:|---:|---:|
| Assembly-CSharp-firstpass | 685 | 623 | 505 | 99 | 19 |
| Assembly-CSharp | 1,866 | 1,593 | 493 | 270 | 830 |
| **Total** | **2,551** | **2,216** | **998** | **369** | **849** |

These counts identify candidates for porting; they do not turn 4.3.4 implementations into authoritative 2.0.2 source. The two builds still need native comparison before any method can be promoted beyond cross-version evidence.

This repository contains no game binaries, managed assemblies, assets, or reconstructed source.
