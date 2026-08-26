#!/bin/bash
# run_fdroid_diff_build.sh
# Location: .github/scripts/run_fdroid_diff_build.sh
#
# Runs inside the F-Droid buildserver-trixie container.
# Executes the build, preserves both the newly built APK and the upstream reference APK.

set -uo pipefail

if [ -z "${BUILD_TARGET:-}" ]; then
  echo "BUILD_TARGET is not set" >&2
  exit 1
fi

. /etc/profile
export PATH="$fdroidserver:$PATH"
export PYTHONPATH="$fdroidserver:$fdroidserver/examples"
export PYTHONUNBUFFERED=true
export GRADLE_USER_HOME="$HOME/.gradle"

mkdir -p logs tmp unsigned diff_work

LOG_NAME="${BUILD_TARGET//:/_}"
LOG_FILE="logs/${LOG_NAME}_diff_build.log"

echo "==========================================" | tee -a "$LOG_FILE"
echo "==> Step 1: Fetch Source Libs for $BUILD_TARGET" | tee -a "$LOG_FILE"
echo "==========================================" | tee -a "$LOG_FILE"
fdroid fetchsrclibs --verbose "$BUILD_TARGET" 2>&1 | tee -a "$LOG_FILE" || true

echo "==========================================" | tee -a "$LOG_FILE"
echo "==> Step 2: Running F-Droid Build with Test Mode" | tee -a "$LOG_FILE"
echo "==========================================" | tee -a "$LOG_FILE"

# Run build with --test. We don't fail immediately on test mismatch so we can analyze diffs.
BUILD_EXIT_CODE=0
fdroid build --verbose --test --refresh-scanner --on-server --no-tarball "$BUILD_TARGET" 2>&1 | tee -a "$LOG_FILE" || BUILD_EXIT_CODE=$?

echo "F-Droid build command exited with code: $BUILD_EXIT_CODE" | tee -a "$LOG_FILE"

# Save exit code for later inspection if needed
echo "$BUILD_EXIT_CODE" > "logs/${LOG_NAME}_exit_code.txt"

exit 0
