#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
/usr/bin/python3 tools/fetch_native_dependencies.py --sources
base="$PWD/work"
prefix="$base/native-prefix"
export CMAKE_PREFIX_PATH="$prefix"
export LD_LIBRARY_PATH="$prefix/lib:${LD_LIBRARY_PATH:-}"
for project in libubox ubus uci ucode; do
  cmake -S "$base/native-locked-src/$project" -B "$base/native-locked-build/$project" \
    -DCMAKE_INSTALL_PREFIX="$prefix" -DCMAKE_INSTALL_LIBDIR=lib \
    -DCMAKE_PREFIX_PATH="$prefix" -DBUILD_LUA=OFF -DBUILD_EXAMPLES=OFF \
    -DDIGEST_SUPPORT=OFF > "$base/native-locked-build-$project.log" 2>&1
  cmake --build "$base/native-locked-build/$project" -j4 >> "$base/native-locked-build-$project.log" 2>&1
  cmake --install "$base/native-locked-build/$project" >> "$base/native-locked-build-$project.log" 2>&1
  echo "Built $project"
done
"$prefix/bin/ucode" -e 'print(require("uci"), require("ubus"), require("uloop"), "\n");'
