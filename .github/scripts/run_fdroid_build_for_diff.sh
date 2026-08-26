#!/bin/bash
# run_fdroid_build_for_diff.sh
#
# (fdroid-reproducibility-diff-analysis.yml pipeline ke liye — is naam se
# alag hai taaki ye purani run_fdroid_build.sh / fdroid-metadata-build-check.yml
# pipeline se bilkul independent chale.)
#
# Yeh script `registry.gitlab.com/fdroid/fdroidserver:buildserver-trixie`
# container ke ANDAR chalta hai. Build ke baad workflow file ek ALAG step
# me built APK aur reference (upstream) APK dhundh kar unka human-readable
# diff-analysis banata hai — wo is script ka kaam nahi hai, isliye is
# script ka core logic bilkul purane run_fdroid_build.sh jaisa hi hai.
#
# Requires env var: BUILD_TARGET (jaise "moe.rukamori.archivetune:140")
# CWD honi chahiye repo root (/build), jaha metadata/ folder ho.

set -euo pipefail

if [ -z "${BUILD_TARGET:-}" ]; then
  echo "BUILD_TARGET set nahi hai" >&2
  exit 1
fi

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
#                 compare karta hai. Iska diff-output hi humein batata hai
#                 ki files mismatch hain (jise agla workflow-step deeply
#                 analyze karega).
# --on-server   : batata hai ki hum already buildserver ke andar hain.
# --refresh-scanner : suss.json scanner data fresh karta hai.
# --no-tarball  : source tarball nahi banata.
fdroid build --verbose --test --refresh-scanner --on-server --no-tarball "$BUILD_TARGET" 2>&1 | tee -a "$LOG_FILE"
