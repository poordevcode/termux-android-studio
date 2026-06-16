#!/data/data/com.termux/files/usr/bin/bash
# Clone only the AOSP repos needed to build aapt2, at the platform-tools-35.0.2 tag.
set -u
SRC="$HOME/android-sdk-tools-src/src"
TAG="platform-tools-35.0.2"
BASE="https://android.googlesource.com/platform"
mkdir -p "$SRC"

# path|gitpath
REPOS="
core|system/core
selinux|external/selinux
boringssl|external/boringssl
libbase|system/libbase
base|frameworks/base
native|frameworks/native
logging|system/logging
incremental_delivery|system/incremental_delivery
fmtlib|external/fmtlib
pcre|external/pcre
libpng|external/libpng
expat|external/expat
protobuf|external/protobuf
abseil-cpp|external/abseil-cpp
googletest|external/googletest
libziparchive|system/libziparchive
soong|build/soong
unwinding|system/unwinding
"

for entry in $REPOS; do
  p="${entry%%|*}"; g="${entry##*|}"
  dest="$SRC/$p"
  if [ -d "$dest/.git" ] || [ -d "$dest" ]; then
    echo "[skip] $p already present"
    continue
  fi
  url="$BASE/$g"
  echo "==== cloning $p ($g) @ $TAG ===="
  if git clone -c advice.detachedHead=false --depth 1 --branch "$TAG" "$url" "$dest" 2>&1 | tail -2; then
    echo "[ok] $p @ $TAG"
  else
    echo "[warn] tag missing for $p, falling back to default branch"
    rm -rf "$dest"
    git clone --depth 1 "$url" "$dest" 2>&1 | tail -2 && echo "[ok] $p @ default"
  fi
done
echo "ALL CLONES DONE"
du -sh "$SRC" 2>/dev/null
