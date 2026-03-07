#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
echo "Building Vulkan compute shader and runner (best-effort)"
if command -v glslangValidator >/dev/null 2>&1; then
  echo "Compiling shader.comp -> shader.spv"
  glslangValidator -V "$HERE/shader.comp" -o "$HERE/shader.spv"
else
  echo "glslangValidator not found. Install Vulkan SDK or glslangValidator to compile shaders. Skipping shader compilation."
fi

CC=${CC:-gcc}
if command -v "$CC" >/dev/null 2>&1; then
  echo "Compiling runner.c -> runner"
  CFLAGS="-O2"
  LDFLAGS="-lvulkan"
  # If VULKAN_SDK is set, prefer its include and lib paths
  if [ -n "${VULKAN_SDK:-}" ]; then
    CFLAGS="$CFLAGS -I${VULKAN_SDK}/include"
    LDFLAGS="$LDFLAGS -L${VULKAN_SDK}/lib"
  fi
  "$CC" $CFLAGS -o "$HERE/runner" "$HERE/runner.c" $LDFLAGS 2>/dev/null || echo "Could not link libvulkan; runner may not be usable."
else
  echo "No C compiler found; skipping runner build."
fi

echo "Build script done. If runner and shader.spv exist you can run the runner to execute the compute test (requires Vulkan libs)."

