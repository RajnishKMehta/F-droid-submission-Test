#!/bin/bash
# run_fdroid_build.sh
#
# Yeh script `registry.gitlab.com/fdroid/fdroidserver:buildserver-trixie`
# container ke ANDAR chalta hai (docker run se invoke hota hai, workflow
# file dekho). Yahi image F-Droid ka apna real build server use karta hai,
# is liye SDK/build-tools/license sab kuchh already isi image me maujood
# hai — hume kuchh alag se install nahi karna.
#
# Requires env var: BUILD_TARGET (jaise "moe.rukamori.archivetune:140")
# CWD honi chahiye repo root (/build), jaha metadata/ folder ho.

set -euo pipefail

if [ -z "${BUILD_TARGET:-}" ]; then
  echo "BUILD_TARGET set nahi hai" >&2
  exit 1
fi

# Image ka /etc/profile fdroidserver env vars set karta hai ($fdroidserver
# path waghera) — bilkul waisa hi jaisa F-Droid ke apne CI job me hota hai.
. /etc/profile
export PATH="$fdroidserver:$PATH"
export PYTHONPATH="$fdroidserver:$fdroidserver/examples"
export PYTHONUNBUFFERED=true
export GRADLE_USER_HOME="$HOME/.gradle"

mkdir -p logs tmp unsigned

LOG_NAME="${BUILD_TARGET//:/_}"
LOG_FILE="logs/${LOG_NAME}.log"

echo "==> fdroid fetchsrclibs $BUILD_TARGET" | tee -a "$LOG_FILE"
fdroid fetchsrclibs --verbose "$BUILD_TARGET" 2>&1 | tee -a "$LOG_FILE"

echo "==> fdroid build $BUILD_TARGET" | tee -a "$LOG_FILE"
# --test        : reference binary (Binaries: url) se signature-copy karke
#                 compare karta hai — yahi wo reproducibility check hai
#                 jo humne pehle debug kiya tha.
# --on-server   : batata hai ki hum already buildserver ke andar hain,
#                 to fdroid apna khud ka privilege-drop / sudo-purge
#                 hardening internally kar lega untrusted source build
#                 karne se pehle — bilkul jaisa asli F-Droid CI karta hai.
# --refresh-scanner : suss.json (malware/problem-pattern scanner data) fresh karta hai.
# --no-tarball  : source tarball nahi banata (hume repo/ deploy nahi karna).
fdroid build --verbose --test --refresh-scanner --on-server --no-tarball "$BUILD_TARGET" 2>&1 | tee -a "$LOG_FILE"
