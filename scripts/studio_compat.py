#!/usr/bin/env python3
"""
studio_compat.py - make imported Android projects build with the Termux toolchain.

When you import a project that was made for a different (usually older) toolchain,
three things commonly break on this device:

  * Gradle version   - the project's wrapper pins a Gradle the system one differs from.
                       We can't run ./gradlew (/storage is noexec), so we provision the
                       requested Gradle into ~/.studio/gradle (an executable FS) and use it.
  * Android SDK level - compileSdk/targetSdk/buildTools the project needs aren't installed.
                       We auto-install them with sdkmanager. Levels above what our native
                       aapt2 understands are capped (reversibly).
  * AGP version       - only matters when we have to fall back to the system Gradle for a
                       project whose AGP is too old for it; then we bump AGP (reversibly).

Everything that edits a tracked file is REVERSIBLE: the original is stashed outside the
repo (~/.studio/compat-stash/<key>) and `--restore` puts it back, so git — and the
Android Studio config — stay pristine, exactly like the daemon-JVM handling in `studio`.

Modes:
  --check     analyse and print findings; change nothing
  --prepare   apply non-destructive provisioning + reversible patches; print chosen
              Gradle launcher path on stdout (everything else on stderr)
  --restore   undo any reversible patches applied by --prepare
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

HOME = os.path.expanduser("~")
STUDIO_DIR = os.path.join(HOME, ".studio")
GRADLE_CACHE = os.path.join(STUDIO_DIR, "gradle")
STASH_ROOT = os.path.join(STUDIO_DIR, "compat-stash")

SYSTEM_GRADLE = "9.5.1"          # the gradle on PATH (see termux-android-build-setup)
AAPT2_MAX_SDK = 37               # highest resources.arsc our native aapt2 parses
TARGET_AGP = "9.2.1"             # known-good AGP for this device (matches studio_new.py)
MIN_AGP_FOR_GRADLE9 = (8, 9)     # AGP below this tends to break on Gradle 9.x
GRADLE_MIN_FOR_JDK21 = (8, 5)    # Gradle below this can't run on our default JDK 21
GRADLE_DIST = "https://services.gradle.org/distributions/gradle-{v}-bin.zip"
JVM_DIR = "/data/data/com.termux/files/usr/lib/jvm"   # Termux openjdk-* install root

C = {"g": "\033[92m", "y": "\033[93m", "r": "\033[91m",
     "c": "\033[96m", "b": "\033[1m", "e": "\033[0m"}


# --- all human output goes to stderr; stdout is reserved for the GRADLE_BIN result ---
def say(msg):  print(msg, file=sys.stderr)
def info(m):   say(f"{C['c']}{m}{C['e']}")
def ok(m):     say(f"{C['g']}✔ {m}{C['e']}")
def warn(m):   say(f"{C['y']}! {m}{C['e']}")
def err(m):    say(f"{C['r']}✘ {m}{C['e']}")


def ver_tuple(s):
    """'8.13.1' -> (8, 13, 1); robust to junk."""
    nums = re.findall(r"\d+", s or "")
    return tuple(int(n) for n in nums) if nums else ()


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


# ----------------------------------------------------------------- detection

def detect_gradle_version(proj):
    wp = os.path.join(proj, "gradle", "wrapper", "gradle-wrapper.properties")
    txt = read(wp)
    if not txt:
        return None
    m = re.search(r"gradle-([\d.]+)-(?:bin|all)\.zip", txt)
    return m.group(1).rstrip(".") if m else None


def _candidate_build_files(proj):
    """Root + every module's build script (depth-limited), plus the version catalog."""
    files = []
    for rel in ("build.gradle", "build.gradle.kts",
                "gradle/libs.versions.toml"):
        p = os.path.join(proj, rel)
        if os.path.isfile(p):
            files.append(p)
    # module build files (e.g. app/build.gradle); skip build/ output dirs
    for entry in sorted(os.listdir(proj)):
        d = os.path.join(proj, entry)
        if not os.path.isdir(d) or entry in (".git", "build", "gradle", ".gradle"):
            continue
        for name in ("build.gradle", "build.gradle.kts"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                files.append(p)
    return files


def detect_agp(proj):
    """Return (version_str, file_path, matched_substring) or (None, None, None)."""
    toml = os.path.join(proj, "gradle", "libs.versions.toml")
    txt = read(toml)
    if txt:
        m = re.search(r'(?m)^\s*agp\s*=\s*"([\d.]+)"', txt)
        if m:
            return m.group(1), toml, m.group(0)
    for p in (os.path.join(proj, "build.gradle"),
              os.path.join(proj, "build.gradle.kts")):
        txt = read(p)
        if not txt:
            continue
        # plugins { id 'com.android.application' version '8.x' }  and the Kotlin-DSL
        # form  id("com.android.application") version "8.x"  (closing quote/paren between).
        m = re.search(r'com\.android\.(?:application|library)["\')\s]+version\s+["\']([\d.]+)["\']', txt)
        if m:
            return m.group(1), p, m.group(0)
        # legacy buildscript classpath
        m = re.search(r'com\.android\.tools\.build:gradle:([\d.]+)', txt)
        if m:
            return m.group(1), p, m.group(0)
    return None, None, None


def _ints_for(key, txt):
    out = []
    for m in re.finditer(key + r'(?:Version)?\s*(?:=\s*)?[("\s]*([0-9]{2})\b', txt):
        out.append(int(m.group(1)))
    return out


def detect_sdks(proj):
    """Collect literal compileSdk/targetSdk values and any pinned buildToolsVersion."""
    compile_sdks, target_sdks, buildtools = set(), set(), set()
    for p in _candidate_build_files(proj):
        txt = read(p)
        if not txt:
            continue
        for v in _ints_for("compileSdk", txt):
            compile_sdks.add(v)
        for v in _ints_for("targetSdk", txt):
            target_sdks.add(v)
        for m in re.finditer(r'buildToolsVersion\s*(?:=\s*)?["\']([\d.]+)["\']', txt):
            buildtools.add(m.group(1))
    return compile_sdks, target_sdks, buildtools


def installed_platforms(sdk):
    d = os.path.join(sdk, "platforms")
    out = set()
    if os.path.isdir(d):
        for n in os.listdir(d):
            m = re.match(r"android-(\d+)$", n)
            if m:
                out.add(int(m.group(1)))
    return out


def installed_buildtools(sdk):
    d = os.path.join(sdk, "build-tools")
    return set(os.listdir(d)) if os.path.isdir(d) else set()


# ----------------------------------------------------------------- stash (reversible edits)

def proj_key(proj):
    return re.sub(r"[/ ]", "_", proj.strip("/"))


def stash_dir(proj):
    return os.path.join(STASH_ROOT, proj_key(proj))


def _manifest_path(proj):
    return os.path.join(stash_dir(proj), "manifest.json")


def _load_manifest(proj):
    txt = read(_manifest_path(proj))
    if not txt:
        return {"files": [], "gradle": None}
    try:
        return json.loads(txt)
    except ValueError:
        return {"files": [], "gradle": None}


def _save_manifest(proj, man):
    os.makedirs(stash_dir(proj), exist_ok=True)
    with open(_manifest_path(proj), "w") as f:
        json.dump(man, f)


def patch_file(proj, path, new_text):
    """Back up `path` (once) outside the repo, then overwrite it with new_text."""
    man = _load_manifest(proj)
    rel = os.path.relpath(path, proj)
    if rel not in [e["rel"] for e in man["files"]]:
        bak = os.path.join(stash_dir(proj), rel.replace("/", "__") + ".orig")
        os.makedirs(os.path.dirname(bak), exist_ok=True)
        shutil.copy2(path, bak)
        man["files"].append({"rel": rel, "bak": bak})
        _save_manifest(proj, man)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_text)


def restore(proj):
    man = _load_manifest(proj)
    n = 0
    for e in man.get("files", []):
        src, dst = e["bak"], os.path.join(proj, e["rel"])
        if os.path.isfile(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
            n += 1
    sd = stash_dir(proj)
    if os.path.isdir(sd):
        shutil.rmtree(sd, ignore_errors=True)
    if n:
        ok(f"reverted {n} compatibility patch(es) — repo restored to its committed state")
    return n


# ----------------------------------------------------------------- provisioning

def sdkmanager(sdk):
    p = os.path.join(sdk, "cmdline-tools", "latest", "bin", "sdkmanager")
    return p if os.path.isfile(p) else None


def sdk_install(sdk, packages):
    mgr = sdkmanager(sdk)
    if not mgr:
        warn("sdkmanager not found — cannot auto-install SDK components")
        return False
    info(f"Installing SDK component(s): {', '.join(packages)}")
    env = dict(os.environ, ANDROID_HOME=sdk, ANDROID_SDK_ROOT=sdk)
    try:
        # `yes` accepts licenses non-interactively
        p = subprocess.run([mgr, f"--sdk_root={sdk}"] + packages,
                           env=env, input="y\n" * 50, text=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        return p.returncode == 0
    except Exception as e:  # noqa
        warn(f"sdkmanager failed: {e}")
        return False


def provision_gradle(version):
    """Return a path to a gradle launcher for `version`, downloading/caching if needed.
    Returns None on failure (caller falls back to the system gradle)."""
    target = os.path.join(GRADLE_CACHE, f"gradle-{version}")
    launcher = os.path.join(target, "bin", "gradle")
    if os.path.isfile(launcher):
        return launcher
    os.makedirs(GRADLE_CACHE, exist_ok=True)
    url = GRADLE_DIST.format(v=version)
    zpath = os.path.join(GRADLE_CACHE, f"gradle-{version}-bin.zip")
    info(f"Provisioning Gradle {version} (one-time download into ~/.studio/gradle)…")
    try:
        with urllib.request.urlopen(url, timeout=60) as r, open(zpath, "wb") as f:
            shutil.copyfileobj(r, f)
    except Exception as e:  # noqa
        warn(f"could not download Gradle {version}: {e}")
        return None
    try:
        shutil.unpack_archive(zpath, GRADLE_CACHE)
    except Exception as e:  # noqa
        warn(f"could not unpack Gradle {version}: {e}")
        return None
    finally:
        try:
            os.remove(zpath)
        except OSError:
            pass
    if os.path.isfile(launcher):
        os.chmod(launcher, 0o755)
        ok(f"Gradle {version} ready at {target}")
        return launcher
    warn(f"Gradle {version} unpacked but launcher missing")
    return None


# ----------------------------------------------------------------- JDK selection
#
# Different toolchains need different JDKs to RUN Gradle: AGP 8/9 needs JDK 17+, AGP 7 needs
# 11, and each Gradle version only runs on a window of JDKs (e.g. Gradle 8.0–8.4 can't run on
# JDK 21; Gradle 9 needs 17+). With openjdk 11/17/21 installed side by side we can pick the
# right one per build instead of force-modernising old projects. The chosen major is emitted
# as `JDK_MAJOR=<n>` on stdout (only when it differs from the default), and `studio build`
# applies it via -Dorg.gradle.java.home without touching the repo.

def installed_jdks():
    out = []
    if os.path.isdir(JVM_DIR):
        for n in os.listdir(JVM_DIR):
            m = re.match(r"java-(\d+)-openjdk$", n)
            if m and os.path.isfile(os.path.join(JVM_DIR, n, "bin", "java")):
                out.append(int(m.group(1)))
    return sorted(set(out))


def default_jdk_major():
    """The JDK major the global ~/.gradle pin uses (falls back to the highest installed)."""
    txt = read(os.path.join(HOME, ".gradle", "gradle.properties")) or ""
    m = re.search(r"(?m)^\s*org\.gradle\.java\.home=.*?java-(\d+)-openjdk", txt)
    if m:
        return int(m.group(1))
    js = installed_jdks()
    return js[-1] if js else 21


def gradle_jdk_window(gradle):
    """(min, max) JDK major a Gradle version can run on. Unknown -> permissive."""
    g = ver_tuple(gradle)
    if   g >= (9, 0): return 17, 24
    elif g >= (8, 5): return 8, 21
    elif g >= (8, 0): return 8, 19
    elif g >= (7, 6): return 8, 18
    elif g >= (7, 3): return 8, 17
    elif g >= (7, 0): return 8, 16
    elif g >= (5, 0): return 8, 15
    elif g:           return 8, 11
    return 8, 24


def agp_min_jdk(agp):
    """Lowest JDK major an AGP version is supported on."""
    a = ver_tuple(agp)
    if a >= (8, 0): return 17
    if a >= (7, 0): return 11
    return 8                       # 3.x–4.x officially want JDK 8


def have_jdk_for(agp, gradle):
    """True if some installed JDK can run this Gradle and satisfy this AGP."""
    gmin, gmax = gradle_jdk_window(gradle)
    need = max(gmin, agp_min_jdk(agp))
    return any(need <= j <= gmax for j in installed_jdks())


def recommend_jdk(agp, gradle):
    """Pick a JDK major for this toolchain, or None to keep the default. Returns the LOWEST
    installed JDK that satisfies both the Gradle window and the AGP minimum — the closest to
    what the (often older) toolchain actually expects — and only overrides when the default
    JDK falls outside that window."""
    installed = installed_jdks()
    if not installed:
        return None
    default = default_jdk_major()
    gmin, gmax = gradle_jdk_window(gradle)
    need = max(gmin, agp_min_jdk(agp))
    if need <= default <= gmax and default in installed:
        return None                # the default is already fine — don't override
    in_range = sorted(j for j in installed if need <= j <= gmax)
    if in_range:
        return in_range[0]
    below = sorted(j for j in installed if j <= gmax)
    if below:
        return below[-1]
    return None


# ----------------------------------------------------------------- planning

def analyse(proj, sdk):
    g = detect_gradle_version(proj)
    agp, agp_file, agp_match = detect_agp(proj)
    compile_sdks, target_sdks, buildtools = detect_sdks(proj)
    plats = installed_platforms(sdk)
    return {
        "gradle": g, "agp": agp, "agp_file": agp_file, "agp_match": agp_match,
        "compile_sdks": sorted(compile_sdks), "target_sdks": sorted(target_sdks),
        "buildtools": sorted(buildtools),
        "installed_platforms": sorted(plats),
        "installed_buildtools": sorted(installed_buildtools(sdk)),
    }


def print_check(a):
    info("===== Compatibility analysis =====")
    say(f"  Gradle (wrapper):  {a['gradle'] or '(none) -> system ' + SYSTEM_GRADLE}")
    say(f"  AGP:               {a['agp'] or '(not detected)'}"
        + (f"  [{os.path.basename(a['agp_file'])}]" if a['agp_file'] else ""))
    say(f"  compileSdk:        {a['compile_sdks'] or '(literal not found)'}")
    say(f"  targetSdk:         {a['target_sdks'] or '(literal not found)'}")
    say(f"  buildToolsVersion: {a['buildtools'] or '(default)'}")
    say(f"  SDK platforms here: {a['installed_platforms']}")
    say(f"  build-tools here:   {a['installed_buildtools']}")


# ----------------------------------------------------------------- prepare

def prepare(proj, sdk):
    a = analyse(proj, sdk)
    print_check(a)

    # 1) SDK platforms -------------------------------------------------------
    needed = set()
    for lvl in set(a["compile_sdks"]) | set(a["target_sdks"]):
        if lvl <= AAPT2_MAX_SDK and lvl not in a["installed_platforms"]:
            needed.add(lvl)
    if needed:
        pkgs = [f"platforms;android-{n}" for n in sorted(needed)]
        if sdk_install(sdk, pkgs):
            ok(f"installed missing platform(s): {sorted(needed)}")
        else:
            warn(f"could not install platform(s) {sorted(needed)} — build may fail")

    # 1b) buildToolsVersion pinned but missing -> drop the pin so AGP selects an installed
    #     one. (We don't fetch it: SDK build-tools ship x86_64 native binaries that won't run
    #     here anyway; only aapt2 matters and that's globally overridden to our native build.)
    for bt in a["buildtools"]:
        if bt not in a["installed_buildtools"]:
            _drop_buildtools_pin(proj, bt)

    # 1c) compileSdk/targetSdk above what aapt2 supports -> reversibly cap to 37
    too_high = [v for v in set(a["compile_sdks"]) | set(a["target_sdks"]) if v > AAPT2_MAX_SDK]
    if too_high:
        warn(f"SDK level(s) {sorted(too_high)} exceed our aapt2 max ({AAPT2_MAX_SDK}); capping for the build")
        _cap_sdk_levels(proj, AAPT2_MAX_SDK)

    # 2) Gradle launcher -----------------------------------------------------
    # Only provision a different Gradle when the MAJOR version differs from the system one:
    # within a major (e.g. 9.5 vs 9.5.1) the system Gradle is compatible, so don't download.
    gradle_bin = "gradle"            # default: system gradle on PATH
    req = a["gradle"]
    sys_major = ver_tuple(SYSTEM_GRADLE)[0]
    if req and ver_tuple(req) and ver_tuple(req)[0] != sys_major:
        if ver_tuple(req) >= GRADLE_MIN_FOR_JDK21:
            launcher = provision_gradle(req)
            if launcher:
                gradle_bin = launcher
                ok(f"using project's Gradle {req} (its AGP needs the matching major)")
            else:
                warn(f"falling back to system Gradle {SYSTEM_GRADLE}")
        elif have_jdk_for(a["agp"], req):
            # Older Gradle than our default can run, but we now have a JDK that *can* run it
            # (openjdk 11/17). Provision the project's real Gradle and run it on that JDK,
            # keeping its original AGP instead of force-bumping it.
            launcher = provision_gradle(req)
            if launcher:
                gradle_bin = launcher
                ok(f"using project's Gradle {req} on a compatible JDK (no AGP bump needed)")
            else:
                warn(f"falling back to system Gradle {SYSTEM_GRADLE}")
        else:
            warn(f"project wants Gradle {req}, and no installed JDK can run it "
                 f"— using system Gradle {SYSTEM_GRADLE} (run 'studio jdk install 17')")

    # 3) AGP fallback: only when we ended up on the system Gradle 9.x and AGP is too old
    using_system = (gradle_bin == "gradle")
    effective_agp = a["agp"]
    if using_system and a["agp"] and ver_tuple(a["agp"])[:2] < MIN_AGP_FOR_GRADLE9:
        _bump_agp(proj, a)
        effective_agp = TARGET_AGP

    # 4) JDK selection: choose a JDK that runs the *effective* Gradle + AGP. Only emit it when
    #    it differs from the global default (so unchanged behaviour for modern projects).
    effective_gradle = SYSTEM_GRADLE if using_system else (req or SYSTEM_GRADLE)
    jdk = recommend_jdk(effective_agp, effective_gradle)

    # machine-readable result: the only thing on stdout
    print(f"GRADLE_BIN={gradle_bin}")
    if jdk:
        info(f"selected JDK {jdk} for Gradle {effective_gradle}"
             + (f" / AGP {effective_agp}" if effective_agp else "")
             + " (override applied just for this build)")
        print(f"JDK_MAJOR={jdk}")
    return 0


def _drop_buildtools_pin(proj, bt):
    for p in _candidate_build_files(proj):
        txt = read(p)
        if not txt or f'buildToolsVersion' not in txt or bt not in txt:
            continue
        new = re.sub(r'(?m)^\s*buildToolsVersion\s*(?:=\s*)?["\']' + re.escape(bt) + r'["\'].*\n',
                     "", txt)
        if new != txt:
            patch_file(proj, p, new)
            ok(f"dropped pinned buildToolsVersion \"{bt}\" (uses installed default)")
            return


def _cap_sdk_levels(proj, cap):
    for p in _candidate_build_files(proj):
        txt = read(p)
        if not txt:
            continue
        def repl(m):
            return m.group(0).replace(m.group(1), str(cap)) if int(m.group(1)) > cap else m.group(0)
        new = re.sub(r'(?:compileSdk|targetSdk)(?:Version)?\s*(?:=\s*)?[("\s]*(\d{2})\b', repl, txt)
        if new != txt:
            patch_file(proj, p, new)
            ok(f"capped SDK level to {cap} in {os.path.basename(p)}")


def _bump_agp(proj, a):
    p, match, old = a["agp_file"], a["agp_match"], a["agp"]
    if not p or not match:
        warn(f"AGP {old} likely too old for Gradle {SYSTEM_GRADLE}, but couldn't locate it to patch")
        return
    txt = read(p)
    new_match = match.replace(old, TARGET_AGP)
    new = txt.replace(match, new_match, 1)
    if new != txt:
        patch_file(proj, p, new)
        ok(f"bumped AGP {old} -> {TARGET_AGP} for Gradle {SYSTEM_GRADLE} compatibility (reverted after build)")


# ----------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--sdk", default=os.environ.get(
        "ANDROID_HOME", os.path.join(HOME, "android-sdk")))
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--prepare", action="store_true")
    g.add_argument("--restore", action="store_true")
    args = ap.parse_args()

    proj = os.path.abspath(args.project)
    if not os.path.isdir(proj):
        err(f"no such project: {proj}")
        return 1

    if args.check:
        print_check(analyse(proj, args.sdk))
        return 0
    if args.restore:
        restore(proj)
        return 0
    return prepare(proj, args.sdk)


if __name__ == "__main__":
    sys.exit(main())
