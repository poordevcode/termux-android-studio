#!/data/data/com.termux/files/usr/bin/bash
# Apply only the patches needed to build aapt2 natively.
set -eu
ROOT="$HOME/android-sdk-tools-src"
cd "$ROOT"

echo "== 1. protobuf CMake patch =="
patch -p1 -N -r - < patches/protobuf_CMakeLists.txt.patch || echo "  (already applied?)"

echo "== 2. androidfw StringPiece patch =="
( cd src && patch -p1 -N -r - < ../patches/StringPiece.h.patch ) || echo "  (already applied?)"

echo "== 3. libbuildversion version header =="
mkdir -p src/soong/cc/libbuildversion/include
cp -f patches/misc/platform_tools_version.h src/soong/cc/libbuildversion/include/

echo "== 4. incremental_delivery sysprop =="
mkdir -p src/incremental_delivery/sysprop/include
cp -f patches/misc/IncrementalProperties.sysprop.h src/incremental_delivery/sysprop/include/
cp -f patches/misc/IncrementalProperties.sysprop.cpp src/incremental_delivery/sysprop/

echo "== 5. aapt2 proto import paths =="
sed -i 's#frameworks/base/tools/aapt2/Resources.proto#Resources.proto#g'         src/base/tools/aapt2/ApkInfo.proto
sed -i 's#frameworks/base/tools/aapt2/Configuration.proto#Configuration.proto#g'  src/base/tools/aapt2/Resources.proto
sed -i 's#frameworks/base/tools/aapt2/Configuration.proto#Configuration.proto#g'  src/base/tools/aapt2/ResourcesInternal.proto
sed -i 's#frameworks/base/tools/aapt2/Resources.proto#Resources.proto#g'          src/base/tools/aapt2/ResourcesInternal.proto

echo "== 6. abseil googletest path =="
sed -i 's#/usr/src/googletest#${CMAKE_SOURCE_DIR}/src/googletest#g' src/abseil-cpp/CMakeLists.txt

echo "== 7. symlink googletest into boringssl =="
ln -sfn "$ROOT/src/googletest" "$ROOT/src/boringssl/src/third_party/googletest"

echo "ALL PATCHES APPLIED"
