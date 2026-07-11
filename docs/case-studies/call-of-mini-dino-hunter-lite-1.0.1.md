# Call of Mini Dino Hunter Lite 1.0.1

## Build identity

- Bundle: `com.trinitigame.callofminidinohunterlite`
- Version: `1.0.1`
- Unity: `3.5.6f4`
- Executable SHA-256: `4c53290f8773a63965caa1f11bd45887757ba3d3f512e0d58a43d2b675ed1140`
- Architecture: ARMv7

## Managed structure

| Assembly | Types | Methods | `ret`-only bodies |
|---|---:|---:|---:|
| Assembly-CSharp-firstpass | 230 | 1,759 | 1,603 |
| Assembly-CSharp | 1,172 | 7,123 | 6,830 |

Seven Mono AOT modules are registered. `Assembly_CSharp` reports 19,286 AOT slots; `Assembly_CSharp_firstpass` reports 2,877.

## Native status

The ARMv7 image uses `LC_ENCRYPTION_INFO cryptid=1`, and the protected range covers the executable `__TEXT` content needed for method recovery. Module registrations and managed metadata were recovered, but native logic requires a same-build decrypted executable.

## Related-build donor experiment

An [untrusted, user-uploaded Android 3.1.7 artifact](https://archive.org/details/zov_mini__ohota_na_dinozavrov_3_1_7_android_3_0) was handled locally as a static donor only. Its decoded manifest identifies package `com.trinitigame.android.callofminidinohunter`, version `3.1.7`; `mainData` identifies Unity `4.3.0f4`. The archive's advertised size, MD5, and SHA-1 were independently reproduced before extracting two managed assemblies:

- APK: 10,501,816 bytes; MD5 `9b515bf96f8814db38eafc605bbb4109`; SHA-1 `5f306a696300bbd179ebc40b0a06bd2fd161f938`
- `Assembly-CSharp-firstpass.dll`: SHA-256 `452cf239c98c59cd11b9c5199f047c0d6c3dd8d8f227cc41d70cb3d85aefa80a`
- `Assembly-CSharp.dll`: SHA-256 `b693d9faa65de0ea0adc1dd9de16e6de475ba11d420a8f0083e9bca2d4346474`

| Target assembly | Normalized identities | Donor bodies beyond `ret` | Tier A | Tier B | Tier C |
|---|---:|---:|---:|---:|---:|
| Assembly-CSharp-firstpass | 1,723 | 1,561 | 1,500 | 1 | 60 |
| Assembly-CSharp | 6,377 | 5,792 | 3,395 | 371 | 2,026 |
| **Total** | **8,100** | **7,353** | **4,895** | **372** | **2,086** |

Of those donor-body matches, 7,352 correspond to single-`ret` targets. This is unusually broad preservation coverage, but the full-versus-Lite and 1.0.1-versus-3.1.7 gaps still prevent any body from being labeled exact recovery without native comparison.

This repository contains no game binaries, managed assemblies, assets, or reconstructed source.
