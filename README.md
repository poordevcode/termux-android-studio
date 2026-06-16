<h1 align="center">📱 Termux Studio — Build Android Apps on Your Phone</h1>

<p align="center">
  <b>A complete, no-root Android build toolchain for <a href="https://termux.dev">Termux</a>.</b><br>
  Compile, sign, install, and launch real <code>.apk</code> files entirely on-device — no PC, no Android Studio, no root.
</p>

<p align="center">
  <img alt="Platform" src="https://img.shields.io/badge/platform-Termux%20(Android%2011%2B)-3DDC84?logo=android&logoColor=white">
  <img alt="Arch" src="https://img.shields.io/badge/arch-aarch64-blue">
  <img alt="Shell" src="https://img.shields.io/badge/CLI-bash%20%2B%20python-success?logo=gnubash&logoColor=white">
  <img alt="License" src="https://img.shields.io/badge/license-Apache--2.0-lightgrey">
  <a href="https://github.com/poordevcode/termux-android-studio/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/poordevcode/termux-android-studio?style=social"></a>
</p>

---

**Termux Studio** turns a stock Android phone into a self-contained Android development machine. It bundles a **self-built native aarch64 `aapt2`** (so it can parse modern **SDK 35/36/37** resources that Termux's packaged aapt2 cannot) and a friendly **`studio` CLI + TUI** that handles Gradle builds, signing, wireless `adb` install/launch, logcat, and multi-JDK management — the same things Android Studio does, but from a terminal on your phone.

> Keywords: build Android apps on Termux · compile APK on Android without root · Android Studio alternative on phone · Gradle build in Termux · native aarch64 aapt2 · on-device APK signing · Jetpack Compose on Android phone.

## ✨ Features

- 🏗️ **One-command builds** — `studio build` runs Gradle with the right toolchain (system Gradle, native aapt2, JDK pin) without touching your project's committed Android Studio config.
- 📦 **Native aarch64 `aapt2`** — self-built from AOSP source; parses **Android SDK 35/36/37** `resources.arsc` that Termux's stock aapt2 chokes on.
- ▶️ **Run on device like the green ▶** — `studio run` builds, installs and launches over **wireless `adb`** (Android 11+, no root/USB) or the system package installer, with verified-install detection.
- 🔐 **Release signing made easy** — pick a keystore alias after entering the password, remember keystore details, or **create a keystore step-by-step**; auto-signs with a debug key if you have none.
- 🏷️ **Smart APK naming** — release APKs are renamed to `<App Name>_<version>.apk`, or set your own with `--apk-name`.
- 📤 **Share from the terminal** — push the built APK straight to the Android share sheet (APK, or ZIP-wrapped for apps that reject APKs).
- ☕ **Multi-JDK** — install/manage **JDK 11/17/21** and auto-select the right one per project's Gradle/AGP.
- 🧩 **Imports "just work"** — clone any repo (`studio clone <url>`) and the compatibility adapter auto-adapts Gradle version, missing SDK levels, AGP and JDK — **reversibly**, so git stays pristine.
- 🖥️ **Interactive TUI** — `studio start` gives a menu-driven UI that remembers and auto-reopens your last project.
- 🆕 **Project generator** — `studio new "My App" --compose` scaffolds a ready-to-build Compose or XML/Views project.

## 📑 Table of Contents

- [Why this exists](#-why-this-exists)
- [Requirements](#-requirements)
- [Installation](#-installation)
- [Quick start](#-quick-start)
- [Command reference](#-command-reference)
- [How it works](#-how-it-works)
- [Rebuilding aapt2 from source](#-rebuilding-aapt2-from-source)
- [FAQ](#-faq)
- [Contributing](#-contributing)
- [License](#-license)

## 🤔 Why this exists

Building Android apps on a phone with Termux normally fails for three reasons, all of which Termux Studio solves:

| Blocker | What breaks | Fix |
|---|---|---|
| **aapt2 architecture/version** | AGP downloads an **x86_64** aapt2 (won't run on ARM); Termux's packaged aapt2 is too old to read **SDK 35+** resources | ships a **self-built native aarch64 aapt2** and wires it in via `aapt2FromMavenOverride` |
| **`./gradlew` is non-executable** | `/storage` is mounted `noexec`, so the Gradle wrapper can't run | uses the **system Gradle**, provisioning the project's version when the major differs |
| **JetBrains JDK pin** | `gradle-daemon-jvm.properties` pins a JBR that Termux lacks | moves it aside per-build (restored after) and pins Termux's OpenJDK |

Everything Termux-specific lives in `~/.gradle` and `~/.studio` — your repo and its Android Studio configuration are never modified.

## 📋 Requirements

- **Termux** (from [F-Droid](https://f-droid.org/packages/com.termux/) or GitHub — *not* the outdated Play Store build) on **Android 11+**, **aarch64**.
- ~3 GB free space for the SDK + Gradle + JDKs (downloaded by the installer).
- Optional: the **Termux:API** app for share/clipboard, and a one-time **Wireless debugging** pairing for `adb` install/launch/logcat.

## 🚀 Installation

```bash
pkg install -y git
git clone https://github.com/poordevcode/termux-android-studio.git ~/termux-studio
bash ~/termux-studio/install.sh
source ~/.bashrc
```

The installer pkg-installs the JDKs/Gradle, downloads + configures the Android SDK, overlays the native aapt2, installs the `studio` tooling, and writes your `~/.gradle/gradle.properties`. Flags: `-y` (non-interactive), `--no-sdk` (keep an existing SDK), `--build-aapt2` (compile aapt2 from source — needed on non-aarch64). Finish with `studio doctor` to verify.

## ⚡ Quick start

```bash
studio new "My App" --compose --build      # scaffold + build a Jetpack Compose app
studio run ~/AndroidStudioProjects/MyApp   # build → install → launch on device
studio start                               # interactive TUI (auto-reopens last project)
```

## 🧰 Command reference

| Command | What it does |
|---|---|
| `studio new [name] [--compose\|--xml] [--build]` | Scaffold a new project |
| `studio clone <git-url>` | Clone + import a repo (like AS "Get from VCS") |
| `studio load [path]` | Adapt an existing project for Termux |
| `studio build [path] [tasks…]` | Build (default `:app:assembleDebug`) |
| `studio build … assembleRelease --apk-name NAME` | Signed release with a custom output name |
| `studio run [path] [--release] [--logcat]` | Build, install & launch (adb or installer) |
| `studio jdk {list\|install\|use\|which}` | Manage build JDKs (11/17/21) |
| `studio adb pair` | One-time wireless-debugging setup (no root/USB) |
| `studio logcat [pkg\|path]` | Stream the app's logs |
| `studio doctor` | Diagnose the setup |
| `studio start` | Launch the interactive TUI |

## 🔬 How it works

- **Native aapt2** built from AOSP `platform-tools-35.0.2`, patched for Termux clang 21 / Android 14, is installed into `build-tools/36.0.0/aapt2` and referenced by `android.aapt2FromMavenOverride` — the single override modern AGP needs (d8/zipalign/apksigner come from AGP's own bundled tools).
- **Per-build isolation:** the JetBrains daemon-JVM pin is stashed outside the repo and restored on exit; any compatibility patch (SDK cap, AGP bump, dropped buildTools pin) is reverted after the build. `git status` stays clean.
- **Auto-JDK:** the compatibility adapter picks the lowest installed JDK that satisfies the effective Gradle + AGP versions, only overriding the default when needed.

## 🛠️ Rebuilding aapt2 from source

The shipped binary is in `prebuilt/aapt2-aarch64`. To reproduce it:

```bash
bash aapt2-build/clone_aapt2_src.sh        # clone the AOSP repos aapt2 needs (tag platform-tools-35.0.2)
bash aapt2-build/apply_aapt2_patches.sh    # Termux/clang-21 patches
# configure + build with cmake/ninja — see the scripts and README notes
```

Key flags: `--target=aarch64-linux-android34` (bionic fdsan), `-DFMT_CONSTEVAL=`, and `-DCMAKE_EXE_LINKER_FLAGS="--target=aarch64-linux-android34 -L/system/lib64 -llog"`. Output: `build-aapt2/bin/build-tools/aapt2` → copy over `prebuilt/aapt2-aarch64`.

## ❓ FAQ

**Does this need root?** No. Wireless `adb` uses Android 11+ self-pairing over loopback; installs otherwise go through the system package installer.

**Will it mess up my Android Studio project?** No. All Termux tweaks live in `~/.gradle`/`~/.studio`; in-repo build patches are reverted automatically.

**Sharing an APK to WhatsApp crashes / is rejected.** WhatsApp blocks raw `.apk` shares. Use the share menu's **ZIP** mode — the recipient unzips to get the installable APK. Other apps (Telegram, Drive, Bluetooth, Files) accept the APK directly.

**Which Android/SDK versions?** Android 11+ device; builds target up to **SDK 37** (capped to the native aapt2's max).

**Non-aarch64 device?** Run `install.sh --build-aapt2` to compile aapt2 for your architecture.

## 🤝 Contributing

Issues and PRs welcome — device/Android-version reports, additional templates, and aapt2 rebuilds for new SDK levels are especially useful. ⭐ **Star the repo** if it helped you build on your phone.

## 📄 License

[Apache-2.0](LICENSE). The bundled `aapt2` is built from the Android Open Source Project (Apache-2.0); see `NOTICE`.

---

<p align="center"><sub>Android app development on Termux • on-device APK builder • Android Studio for Android phones • no-root Gradle/AGP • aarch64 aapt2.</sub></p>
