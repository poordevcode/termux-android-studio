# Termux Studio

A complete on-device Android build toolchain for **Termux** (aarch64, Android 11+), built
without Android Studio or root. It compiles, signs, installs, and launches real APKs straight
from the phone.

This repository is **private on purpose** and intentionally small: it contains only the parts
that are **not downloadable** — the things that were built or written by hand:

| Path | What it is | Why it's here (not downloaded) |
|------|------------|--------------------------------|
| `prebuilt/aapt2-aarch64` | Self-built **native aarch64 aapt2** | Built from AOSP source; Google ships only x86_64, and Termux's packaged aapt2 is too old to parse SDK 35/36/37 `resources.arsc` |
| `bin/studio` | The `studio` CLI (build/run/clone/adb/jdk/keystore…) | Hand-written |
| `scripts/termux_studio.py` | The interactive TUI (`studio start`) | Hand-written |
| `scripts/studio_new.py` | New-project generator (Compose / XML templates) | Hand-written |
| `scripts/studio_compat.py` | Imported-project compatibility adapter (Gradle/SDK/AGP/JDK auto-adapt) | Hand-written |
| `aapt2-build/` | The exact clone + patch recipe to **rebuild** aapt2 from source | Hand-written |
| `config/gradle.properties` | Reference machine config | Hand-written |

Everything else — the JDKs (11/17/21), Gradle, the Android SDK (platforms, build-tools,
platform-tools) — is downloaded by `install.sh` on demand.

## Install on a new / reinstalled Termux

```bash
pkg install -y git
git clone <this-private-repo-url> ~/termux-studio
bash ~/termux-studio/install.sh
source ~/.bashrc
```

`install.sh` will:

1. `pkg install` the runtime deps (OpenJDK 11/17/21, Gradle, aapt2/d8/apksigner, android-tools, termux-api, git, python).
2. Download + set up the Android SDK (AndroidIDE prebuilt aarch64 pieces, then `sdkmanager` for platforms 36/37 and build-tools 36.0.0).
3. Overlay the shipped **native aarch64 aapt2** into `build-tools/36.0.0/aapt2` and `$PREFIX/bin/aapt2-aosp`.
4. Install the `studio` CLI, TUI, generator and compat adapter.
5. Write `~/.gradle/gradle.properties` (aapt2 override + JDK 21 pin) and the Android env in `~/.bashrc`.
6. Run `studio doctor` to verify.

Flags: `-y` (non-interactive), `--no-sdk` (keep the existing SDK), `--build-aapt2` (compile
aapt2 from source instead of using the prebuilt — needed on non-aarch64).

## Using it

```bash
studio start                              # interactive TUI (auto-reopens your last project)
studio new "My App" --compose --build     # scaffold + build a new project
studio clone <git-url>                    # import a repo like AS "Get from VCS"
studio build [path] [tasks…]              # build (auto-adapts Gradle/SDK/AGP/JDK)
studio run   [path] [--release] [--logcat]# build + install + launch (adb or installer)
studio jdk   {list|install|use|which}     # manage build JDKs (11/17/21)
studio adb   pair                         # one-time wireless-debugging setup (no root/USB)
studio doctor                             # diagnose the setup
```

Release builds auto-sign (debug keystore if none given), let you pick the keystore alias,
remember keystore details, can create a keystore step-by-step, rename the output to
`<App Label>_<version>.apk`, and offer to share it via the Android share sheet.

## Rebuilding aapt2 from source

The shipped binary was built from AOSP `platform-tools-35.0.2`. To reproduce it:

```bash
bash ~/termux-studio/aapt2-build/clone_aapt2_src.sh       # clones the ~18 AOSP repos aapt2 needs
bash ~/termux-studio/aapt2-build/apply_aapt2_patches.sh   # Termux/clang-21 patches
# then configure + build with cmake/ninja (see comments in the scripts and the notes below)
```

Build notes (Termux clang 21 / Android 14): protoc is built first; key flags are
`--target=aarch64-linux-android34` (bionic fdsan), `-DFMT_CONSTEVAL=`, and
`-DCMAKE_EXE_LINKER_FLAGS="--target=aarch64-linux-android34 -L/system/lib64 -llog"`. The result
is `build-aapt2/bin/build-tools/aapt2`; copy it over `prebuilt/aapt2-aarch64` to ship a new build.

## Notes

- Termux paths (`/data/data/com.termux/files/...`) are identical on every device, so absolute
  paths in the config port cleanly between phones.
- The toolchain never modifies a project's committed Android Studio config: Termux-only tweaks
  live in `~/.gradle` and `~/.studio`, and any in-repo patch made to build an imported project
  is reverted after the build.
