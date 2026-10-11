#!/bin/sh
# Build src/hwremap.so for the device (32-bit ARM, glibc 2.31) and regenerate hwremap-patch.sh.
#   ./build.sh        library + script
#   ./build.sh test   host tests of hwremap.c (ASan/UBSan, Linux, in Docker)
#   ./build.sh script library must already exist; rewrite the script only
set -eu
cd "$(dirname "$0")"

if [ "${1:-}" = test ]; then
    docker run --rm -v "$PWD/src":/w -w /w gcc:11 bash -euc \
        'gcc -O1 -g -Wall -Wextra -fsanitize=address,undefined test_hwremap.c -ldl -lpthread -o /tmp/t && /tmp/t'
    exit 0
fi

if [ "${1:-}" != script ]; then
    docker run --rm --platform linux/arm/v7 -v "$PWD/src":/b -w /b arm32v7/gcc:11-bullseye bash -euc \
        'gcc -O2 -Wall -Wextra -fPIC -shared -fvisibility=hidden -std=gnu11 hwremap.c -ldl -lpthread -o hwremap.so && strip hwremap.so'
fi

python3 build_script.py
