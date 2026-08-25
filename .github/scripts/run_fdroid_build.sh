#!/bin/bash
# run_fdroid_build.sh
#
# This script runs INSIDE the
# `registry.gitlab.com/fdroid/fdroidserver:buildserver-trixie`
# container (invoked via docker run; see the workflow file).
# This is the same image used by F-Droid's actual build server,
# so the SDK, build-tools, licenses, etc. are already available
# inside the image — nothing needs to be installed separately.
#
# Requires env var: BUILD_TARGET (e.g. "moe.rukamori.archivetune:140")
# CWD must be the repository root (/build), where the metadata/ folder exists.

set -euo pipefail

if [ -z "${BUILD_TARGET:-}" ]; then
  echo "BUILD_TARGET is not set" >&2
  exit 1
fi

# The image's /etc/profile sets the fdroidserver environment variables
# ($fdroidserver path, etc.) — exactly as it does in F-Droid's own CI jobs.
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
# --test        : Copies the signature from the reference binary (Binaries: url)
#                 and compares it — this is the reproducibility check
#                 that we debugged earlier.
#
# --on-server   : Tells F-Droid that we are already running inside the
#                 build server, so fdroid can internally perform its own
#                 privilege-drop / sudo-purge hardening before building
#                 untrusted source code — exactly like the real F-Droid CI.
#
# --refresh-scanner : Refreshes suss.json (malware/problem-pattern scanner data).
#
# --no-tarball  : Does not create a source tarball (we do not need to
#                 deploy the source repository).
fdroid build --verbose --test --refresh-scanner --on-server --no-tarball "$BUILD_TARGET" 2>&1 | tee -a "$LOG_FILE"
