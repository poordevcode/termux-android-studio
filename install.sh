#!/data/data/com.termux/files/usr/bin/bash
#
# Termux Studio — one-shot installer for a fresh (or reinstalled) Termux.
#
# This repo ships ONLY the things you cannot just download: the self-built native aarch64
# aapt2 (parses SDK 35/36/37 resources.arsc) and the `studio` toolchain (CLI + TUI + project
# generator + compatibility adapter). Everything else — JDKs, Gradle, the Android SDK — is
# downloaded here on demand.
#
# Usage:   git clone <this-private-repo> ~/termux-studio && bash ~/termux-studio/install.sh
#
# Flags:
#   -y, --yes        non-interactive (assume yes)
#   --build-aapt2    compile aapt2 from AOSP source instead of using the shipped prebuilt
#                    (slow; needs clang/cmake/ninja — use on non-aarch64 or to rebuild)
#   --no-sdk         skip the Android SDK download/setup (use what's already installed)
#   --help           show this help

set -o pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[✓]${NC} $*"; }
info() { echo -e "${CYAN}[i]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[✗]${NC} $*" >&2; }
step() { echo; echo -e "${BOLD}${CYAN}── $* ──${NC}"; }

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
HOME_DIR="${HOME:-/data/data/com.termux/files/home}"
SDK_DIR="$HOME_DIR/android-sdk"
JVM_DIR="$PREFIX/lib/jvm"
ARCH="$(uname -m)"

ASSUME_YES=0; BUILD_AAPT2=0; DO_SDK=1
for a in "$@"; do
    case "$a" in
        -y|--yes)      ASSUME_YES=1 ;;
        --build-aapt2) BUILD_AAPT2=1 ;;
        --no-sdk)      DO_SDK=0 ;;
        --help|-h)     sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) err "unknown flag: $a"; exit 1 ;;
    esac
done

confirm() {   # $1 prompt ; returns 0 on yes
    [ "$ASSUME_YES" = "1" ] && return 0
    read -rp "$(echo -e "${CYAN}$1 (y/N): ${NC}")" r; [[ "$r" =~ ^[Yy]$ ]]
}

echo -e "${CYAN}${BOLD}"
echo "════════════════════════════════════════════════"
echo "   Termux Studio — Android build env installer"
echo "════════════════════════════════════════════════"
echo -e "${NC}"
info "repo:    $REPO"
info "prefix:  $PREFIX"
info "sdk:     $SDK_DIR"
info "arch:    $ARCH"
echo
if [ "$ARCH" != "aarch64" ] && [ "$BUILD_AAPT2" = "0" ]; then
    warn "This device is '$ARCH', but the shipped aapt2 is aarch64-only."
    warn "Re-run with --build-aapt2 to compile it from source for this arch."
fi
confirm "Proceed with installation?" || { info "cancelled"; exit 0; }

# ───────────────────────────────────────────────── 1. Termux packages
step "1/6  Installing Termux packages"
pkg update -y && pkg upgrade -y || warn "pkg update had warnings (continuing)"
# Runtime deps. openjdk-11 too so studio's auto-JDK-selection has the full 11/17/21 set.
PKGS=(openjdk-21 openjdk-17 openjdk-11 gradle aapt2 d8 apksigner android-tools termux-api git curl python which file)
[ "$BUILD_AAPT2" = "1" ] && PKGS+=(clang cmake ninja binutils protobuf libexpat zlib)
info "installing: ${PKGS[*]}"
pkg install -y "${PKGS[@]}" || { err "package installation failed"; exit 1; }
ok "packages installed"
java -version 2>&1 | head -1 | sed 's/^/    /'
gradle -v 2>/dev/null | grep '^Gradle ' | head -1 | sed 's/^/    /'

# ───────────────────────────────────────────────── 2. Android SDK
if [ "$DO_SDK" = "1" ]; then
    step "2/6  Setting up the Android SDK"
    mkdir -p "$SDK_DIR"

    MANIFEST_URL="https://raw.githubusercontent.com/AndroidIDEOfficial/androidide-tools/main/manifest.json"
    grab() {  # name url destdir
        local name="$1" url="$2" dest="$3" f="$HOME_DIR/$1.tar.xz"
        [ -z "$url" ] && { warn "no URL for $name (skipping)"; return 1; }
        info "downloading $name…"
        curl -L --connect-timeout 15 --retry 5 -o "$f" "$url" || { warn "download $name failed"; return 1; }
        mkdir -p "$dest"; tar xJf "$f" -C "$dest" && rm -f "$f"; ok "$name installed"
    }
    info "fetching AndroidIDE tools manifest (prebuilt aarch64 SDK pieces)…"
    MANIFEST="$(curl -sL "$MANIFEST_URL")"

    # android.jar platforms + cmdline-tools + aarch64 build-tools/platform-tools
    if [ ! -e "$SDK_DIR/platforms/android-34/android.jar" ] && [ ! -e "$SDK_DIR/platforms/android-35/android.jar" ]; then
        grab "android-sdk" "$(echo "$MANIFEST" | grep -o '"android_sdk": *"[^"]*"' | cut -d'"' -f4)" "$HOME_DIR" || true
    else info "SDK platforms already present"; fi
    if [ ! -x "$SDK_DIR/cmdline-tools/latest/bin/sdkmanager" ]; then
        grab "cmdline-tools" "$(echo "$MANIFEST" | grep -o '"cmdline_tools": *"[^"]*"' | cut -d'"' -f4)" "$SDK_DIR" || true
    else info "cmdline-tools already present"; fi
    if [ "$ARCH" = "aarch64" ] && [ ! -d "$SDK_DIR/build-tools/34.0.4" ]; then
        grab "build-tools" "$(echo "$MANIFEST" | grep -o '"_34_0_4": *"[^"]*build-tools[^"]*aarch64[^"]*"' | head -1 | cut -d'"' -f4)" "$SDK_DIR" || true
    fi
    if [ "$ARCH" = "aarch64" ] && [ ! -d "$SDK_DIR/platform-tools" ]; then
        grab "platform-tools" "$(echo "$MANIFEST" | grep -o '"_34_0_4": *"[^"]*platform-tools[^"]*aarch64[^"]*"' | head -1 | cut -d'"' -f4)" "$SDK_DIR" || true
    fi

    # Accept licenses + fix shebangs so sdkmanager runs under Termux.
    mkdir -p "$SDK_DIR/licenses"
    printf '\n24333f8a63b6825ea9c5514f83c2829b004d1fee\n' > "$SDK_DIR/licenses/android-sdk-license"
    printf '\n84831b9409646a918e30573bab4c9c91346d8abd\n' > "$SDK_DIR/licenses/android-sdk-preview-license"
    find "$SDK_DIR/cmdline-tools" -name 'sdkmanager' -o -name 'avdmanager' 2>/dev/null \
        | while read -r f; do termux-fix-shebang "$f" 2>/dev/null || true; done

    SM="$SDK_DIR/cmdline-tools/latest/bin/sdkmanager"
    if [ -x "$SM" ]; then
        export ANDROID_HOME="$SDK_DIR" ANDROID_SDK_ROOT="$SDK_DIR" JAVA_OPTS="-Djava.net.preferIPv4Stack=true"
        info "ensuring platforms 36/37 + build-tools 36.0.0 (android.jar is arch-independent)…"
        yes | "$SM" --licenses >/dev/null 2>&1 || true
        for pkg in "platform-tools" "platforms;android-36" "platforms;android-37" "build-tools;36.0.0"; do
            "$SM" "$pkg" >/dev/null 2>&1 && ok "sdk: $pkg" || warn "sdk: $pkg not installed (non-fatal)"
        done
    else
        warn "sdkmanager not found — platforms 36/37 not auto-installed"
    fi
    ok "Android SDK ready at $SDK_DIR"
else
    step "2/6  Skipping SDK setup (--no-sdk)"
fi

# ───────────────────────────────────────────────── 3. native aapt2
step "3/6  Installing the native aarch64 aapt2"
BT36="$SDK_DIR/build-tools/36.0.0"
mkdir -p "$BT36"
install_prebuilt_aapt2() {
    local src="$REPO/prebuilt/aapt2-aarch64"
    [ -f "$src" ] || { err "prebuilt aapt2 missing from repo ($src)"; return 1; }
    # back up any existing (likely x86_64) aapt2 before overlaying ours
    [ -f "$BT36/aapt2" ] && ! cmp -s "$src" "$BT36/aapt2" && cp -f "$BT36/aapt2" "$BT36/aapt2.orig.bak"
    cp -f "$src" "$BT36/aapt2"; chmod +x "$BT36/aapt2"
    cp -f "$src" "$PREFIX/bin/aapt2-aosp"; chmod +x "$PREFIX/bin/aapt2-aosp"
    # also overlay into 34.0.4 if present (AndroidIDE ships an older aapt2 there)
    [ -d "$SDK_DIR/build-tools/34.0.4" ] && { cp -f "$src" "$SDK_DIR/build-tools/34.0.4/aapt2"; chmod +x "$SDK_DIR/build-tools/34.0.4/aapt2"; }
    ok "aapt2 installed: $BT36/aapt2 ($("$BT36/aapt2" version 2>/dev/null | head -1))"
}
if [ "$BUILD_AAPT2" = "1" ]; then
    info "compiling aapt2 from AOSP source (this is slow)…"
    cp -f "$REPO/aapt2-build/clone_aapt2_src.sh"     "$HOME_DIR/clone_aapt2_src.sh"
    cp -f "$REPO/aapt2-build/apply_aapt2_patches.sh" "$HOME_DIR/apply_aapt2_patches.sh"
    chmod +x "$HOME_DIR"/clone_aapt2_src.sh "$HOME_DIR"/apply_aapt2_patches.sh
    warn "Follow the recipe in aapt2-build/ (clone → patch → cmake/ninja). See README 'Rebuilding aapt2'."
    warn "Falling back to the shipped prebuilt for now so the toolchain is usable."
    install_prebuilt_aapt2 || true
else
    install_prebuilt_aapt2 || exit 1
fi

# ───────────────────────────────────────────────── 4. studio toolchain
step "4/6  Installing the studio CLI + TUI"
install -m 755 "$REPO/bin/studio" "$PREFIX/bin/studio"
mkdir -p "$HOME_DIR/.studio"
install -m 755 "$REPO/scripts/studio_new.py"    "$HOME_DIR/.studio/studio_new.py"
install -m 644 "$REPO/scripts/studio_compat.py" "$HOME_DIR/.studio/studio_compat.py"
install -m 755 "$REPO/scripts/termux_studio.py" "$HOME_DIR/termux_studio.py"
ok "studio installed ($PREFIX/bin/studio, ~/.studio, ~/termux_studio.py)"

# ───────────────────────────────────────────────── 5. gradle.properties
step "5/6  Writing ~/.gradle/gradle.properties"
mkdir -p "$HOME_DIR/.gradle"
GP="$HOME_DIR/.gradle/gradle.properties"
[ -f "$GP" ] && cp -f "$GP" "$GP.bak.$(date +%s)" && info "backed up existing gradle.properties"
JDK21="$JVM_DIR/java-21-openjdk"
cat > "$GP" <<EOF
# Termux Android Build Configuration — written by termux-studio/install.sh

# Self-built native aarch64 aapt2 (parses SDK 35/36/37 resources.arsc, which Termux's
# packaged aapt2 cannot). Source/recipe in the termux-studio repo (aapt2-build/).
android.aapt2FromMavenOverride=$BT36/aapt2

# Force the Gradle daemon onto Termux's OpenJDK 21, overriding any project
# gradle/gradle-daemon-jvm.properties (which pins a JetBrains JDK only Studio ships).
org.gradle.java.home=$JDK21

# Performance tuning for on-device builds
org.gradle.daemon=true
org.gradle.parallel=true
org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
org.gradle.caching=true
kotlin.daemon.jvmargs=-Xmx1536m
android.useAndroidX=true
systemProp.java.net.preferIPv4Stack=true
EOF
ok "gradle.properties written (aapt2 override + JDK 21 pin)"

# .bashrc env (idempotent)
BRC="$HOME_DIR/.bashrc"; touch "$BRC"
if ! grep -q '# Android SDK Environment (termux-studio)' "$BRC"; then
    cat >> "$BRC" <<'ENVB'

# Android SDK Environment (termux-studio)
export ANDROID_HOME=$HOME/android-sdk
export ANDROID_SDK_ROOT=$HOME/android-sdk
export PATH=$PATH:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools
export JAVA_OPTS="-Djava.net.preferIPv4Stack=true"
# End Android SDK
ENVB
    ok "Android env appended to ~/.bashrc"
else
    info "~/.bashrc already has the Android env block"
fi

# ───────────────────────────────────────────────── 6. verify
step "6/6  Verifying with 'studio doctor'"
export ANDROID_HOME="$SDK_DIR" ANDROID_SDK_ROOT="$SDK_DIR"
studio doctor || true

echo
ok "Installation complete."
echo -e "Next:"
echo -e "  ${BOLD}source ~/.bashrc${NC}"
echo -e "  ${BOLD}studio start${NC}              # interactive TUI"
echo -e "  ${BOLD}studio new \"My App\" --compose --build${NC}"
echo -e "  ${BOLD}studio jdk list${NC}           # 11 / 17 / 21 available"
