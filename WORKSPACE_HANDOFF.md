# Native-port workspace handoff (2026-07-11)

This is a machine-local continuation note for the two requested Linux ports.
It intentionally does **not** add IPAs, extracted assets, donor source, managed
game assemblies, or built players to this repository. Those third-party files
remain under `$HOME` and are identified here by path and hash.

The current players are newly compiled, donor-backed ports. They are not
decrypted or transcoded iOS executables, and cross-version donor bodies are not
authoritative recovery of the target's stripped AOT logic.

## Repository state

- Working repository: `$HOME/unity3-ios-aot-recover`
- Continuation commit: `832777a` (`Add donor-backed Unity reconstruction workflow`)
- Added tools:
  - `tools/sanitize_aot_stubs.py`
  - `tools/overlay_donor_sources.py`
  - `tools/copy_donor_support.py`
  - `tools/modernize_unity3_component_api.py`
- Tests: `python3 -m unittest discover -s tests -v` passes 16 tests.
- Workflow/provenance documentation: `docs/native-porting.md`

## Exact target inputs

| Target | Local IPA | SHA-256 | Exact scenes |
|---|---|---|---:|
| Dino Hunter Lite 1.0.1 | `$HOME/Downloads/com.trinitigame.callofminidinohunterlite-1.0.1-659207581-16100993 (1).ipa` | `284a6fa86f3e5952f63a2b4e090574f234c7f704efb11b851153fa4c27e891d8` | 4 |
| Call of Mini Zombies 2.0.2 | `$HOME/Downloads/com.trinitigame.callofminizombies-2.0.2-431213733-8240587 (1).ipa` | `44a0905b9d0384436870df37ef60572af6419de8f1775e460ba508958a58918d` | 34 |

The exact AssetRipper exports are:

- `$HOME/Downloads/recovered_dinohunterlite_ASSETS/ExportedProject`
- `$HOME/Downloads/recovered_comz_ASSETS/ExportedProject`

Both original Mach-O images are FairPlay encrypted over the executable range.
The retained managed assemblies expose metadata but have overwhelmingly
single-`ret` method bodies. No FairPlay bypass or same-build decrypted native
code was used.

## Donor inputs

### Dino

- Android 3.1.7 `Assembly-CSharp.dll`:
  `b693d9faa65de0ea0adc1dd9de16e6de475ba11d420a8f0083e9bca2d4346474`
- Android 3.1.7 `Assembly-CSharp-firstpass.dll`:
  `452cf239c98c59cd11b9c5199f047c0d6c3dd8d8f227cc41d70cb3d85aefa80a`
- Local managed directory: `$HOME/Downloads/dino-hunter-3.1.7-managed`
- C# 4 decompile roots:
  - `$HOME/unity3-native-builds/donors/dino-main-cs4`
  - `$HOME/unity3-native-builds/donors/dino-firstpass-cs4`

### Zombies

- Later desktop 4.3.4 `Assembly-CSharp.dll`:
  `13035bfa3c02cf307c06dff63549581ccf186015030d8c4bec4802966792f779`
- C# 4 decompile root: `$HOME/unity3-native-builds/donors/comz-all-cs4`
- Closer 1.8.3 Unity source archive:
  `$HOME/unity3-native-builds/donors/comz-1.8.3.rar`
- 1.8.3 archive SHA-256:
  `f0328f6370e237efee74951cb041812c7d8e335358b58307ca685fabb6efc20a`
- Extracted 1.8.3 source:
  `$HOME/unity3-native-builds/donors/comz-1.8.3-source`
- Closer source-only menu donor clone:
  `$HOME/unity3-native-builds/donors/comz-github-source`
- Menu donor upstream/commit:
  `https://github.com/SteavenGamerYT/Call-Of-Mini-Zombies-Unity-Source-Code.git`
  at `f0bfef8de0dcaa6b4e249cfe7e62894585570084`

Do not substitute the pre-existing native port binary as a deliverable. It was
not copied into either output below.

## Unity environment and build command

- Editor: `$HOME/Unity/2017.4.40f1/Editor/Unity`
- Runtime wrapper:
  `$HOME/.local/share/Steam/ubuntu12_32/steam-runtime/run.sh`
- Target: `Linux64`

The successful build shape is:

```bash
$HOME/.local/share/Steam/ubuntu12_32/steam-runtime/run.sh \
  $HOME/Unity/2017.4.40f1/Editor/Unity \
  -batchmode -nographics -quit \
  -projectPath PROJECT \
  -buildTarget Linux64 \
  -buildLinux64Player OUTPUT/Game.x86_64 \
  -logFile LOG
```

Unity must run outside the filesystem/network sandbox because the editor opens
local IPC sockets. Poll a yielded process session until it exits; abandoning a
live tool session kills Unity before it writes the player.

## Dino current state

- Project: `$HOME/unity3-native-builds/projects/dino-native`
- Player:
  `$HOME/unity3-native-builds/dist/CallOfMiniDinoHunterLite-1.0.1-native/CallOfMiniDinoHunterLite.x86_64`
- Package size: about 100 MiB
- Launcher SHA-256:
  `3b38fab256bfbb2b17896ebccf56b0fa8ba9da5cbd6a891eac703e65434bd7dc`
- Current `Assembly-CSharp.dll` SHA-256:
  `19fa70bc1b1d0b5b9e66b2984ee8d1ec836b7b925b682c28d9d3e9ee5ffd1bd8`
- Latest successful build log:
  `$HOME/unity3-native-builds/logs/dino-native-build-6.log`
- Latest headless runtime log:
  `$HOME/unity3-native-builds/logs/dino-native-smoke-5.log`
- Latest graphical runtime log:
  `$HOME/unity3-native-builds/logs/dino-native-graphical-3.log`

What works now:

- zero C# compile errors and a successful Linux64 link;
- platform-safe desktop replacements for Android device bridge calls;
- retired server login bypassed only on desktop/Linux;
- recovered local weapon, buff, mob, wave, level, AI, task, item, character,
  drop-group, load-tip, IAP, and achievement configs load from exact resources;
- desktop startup enters bundled level 1001 / `SceneForest`;
- the two first gameplay NREs (missing optional skill UI fields and missing
  event-binding objects) are guarded;
- smoke 5 reaches `PreLoadGameEffect` and contains no managed exception.

The next check is a clean graphical screenshot of `SceneForest` and input
verification. The prior graphical window reached the gameplay initialization
path, but its screenshot was taken from the wrong Hyprland workspace.

There are still 65 explicit unavailable-body throws across 33 Dino source
files. Treat them as known recovery gaps and continue compiler/runtime-guided
repair only when a reachable path hits one.

## Zombies current state

- Project: `$HOME/unity3-native-builds/projects/comz-final`
- Player:
  `$HOME/unity3-native-builds/dist/CallOfMiniZombies-2.0.2-native/CallOfMiniZombies.x86_64`
- Package size: about 854 MiB
- Launcher SHA-256:
  `3b38fab256bfbb2b17896ebccf56b0fa8ba9da5cbd6a891eac703e65434bd7dc`
- Current `Assembly-CSharp.dll` SHA-256:
  `d79fc8172c3ba6b605570dabe604f14035af0ff3317e71a13dec2ec5ca4d4e18`
- Latest successful build log:
  `$HOME/unity3-native-builds/logs/comz-final-build-3.log`
- Latest clean headless runtime log:
  `$HOME/unity3-native-builds/logs/comz-final-player-smoke-3.log`
- Graphical diagnostic log:
  `$HOME/unity3-native-builds/logs/comz-final-graphical-1.log`

What works now:

- zero C# compile errors and a successful Linux64 link with all 34 exact scenes;
- corrected legacy Unity APIs, donor/target enum collisions, constructor and
  pathfinding signatures;
- absent mobile notification prefab is safely ignored on desktop;
- initial `TrinitiUI` scene transitions to the exact `StartMenuUI` scene;
- no managed exception is logged during the transition.

Current blocker:

- `StartMenuUI` renders black because its exact serialized component points to
  `StartMenuUIScript`, whose target AOT body is stripped. The source-only donor
  clone above has a full class with the matching 2.0.2 field layout
  (`background_tip`, `Tem_Ad`, fade state) and matching position constants.
  Transplant only the compatible method bodies/constants while retaining the
  exact target `.meta` GUID and assets. Use 1.8.3 `UIResourceMgr` bodies only
  where required. Then rebuild, verify a visible menu, activate the local play
  path, and continue into a tutorial/game scene.

There are currently 131 explicit unavailable-body throws across 59 Zombies
source files. The 1.8.3 source tree has direct implementations for 18 of those
files, including `GameUIScript`, `MapUI`, `ArenaMenuUI`, several quests,
pathfinding, and legacy UI support. Overlay selectively; its behavior is donor
evidence, not exact 2.0.2 recovery.

## Validation commands

```bash
# Headless player smoke test; timeout 124 means it stayed alive intentionally.
timeout 25 OUTPUT/Game.x86_64 \
  -batchmode -nographics -logFile LOG

# Review managed failures after each run.
rg -i 'exception|notimplemented|nullreference|error|failed|crash|abort' LOG

# Confirm the player and managed assembly are newly produced Linux artifacts.
file OUTPUT/Game.x86_64
sha256sum OUTPUT/Game.x86_64 OUTPUT/Game_Data/Managed/Assembly-CSharp.dll
```

For graphical testing on this workstation, use `DISPLAY=:1`, a windowed
1280x720 player, `hyprctl clients -j` to find the XWayland window, and `grim`
to capture its actual workspace/geometry. Close temporary windows after each
test.

