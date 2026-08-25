#!/usr/bin/env python3
"""
find_changed_builds.py

Looks at the `metadata/*.yml` files changed in the PR and determines
which (appid, versionCode) build targets are new or have changed.

This works similarly to F-Droid's own
`tools/find-changed-builds.py` in the fdroiddata repository, so we build
exactly the same commit/version that an F-Droid reviewer/CI would build.

A target is considered "changed" when:
  - The metadata file itself was newly added in this PR, OR
  - The Build entry for that versionCode did not exist in the base branch, OR
  - Fields in the Build entry (commit, subdir, gradle, etc.) differ from
    the base branch.

Output: A JSON array that can be used directly with a GitHub Actions
matrix (`strategy.matrix.include`):
  [{"appid": "moe.rukamori.archivetune", "versionCode": 140,
    "target": "moe.rukamori.archivetune:140"}, ...]

Required environment variables: BASE_SHA, HEAD_SHA
(both commits between which the diff should be calculated)
"""
import json
import os
import subprocess
import sys

import yaml

BASE_SHA = os.environ["BASE_SHA"]
HEAD_SHA = os.environ["HEAD_SHA"]


def changed_metadata_files() -> list[str]:
    """Return metadata/*.yml files that were modified in this diff, excluding deleted files."""
    result = subprocess.run(
        [
            "git", "diff", "--name-only", "--diff-filter=d",
            BASE_SHA, HEAD_SHA, "--", "metadata/*.yml",
        ],
        capture_output=True, text=True, check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def load_yaml_at_ref(ref: str, path: str):
    """Retrieve a file's content from any Git commit; return None if the file does not exist there."""
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return yaml.safe_load(result.stdout) or {}
    except yaml.YAMLError as exc:
        print(f"::warning::{path} @ {ref} could not be parsed: {exc}", file=sys.stderr)
        return None


def builds_by_versioncode(meta: dict) -> dict:
    out = {}
    for build in (meta or {}).get("Builds", []) or []:
        vc = build.get("versionCode")
        if vc is not None:
            out[vc] = build
    return out


def main() -> None:
    targets = []
    for path in changed_metadata_files():
        appid = os.path.splitext(os.path.basename(path))[0]

        head_meta = load_yaml_at_ref(HEAD_SHA, path)
        if head_meta is None:
            # The file was deleted in the PR or could not be parsed.
            # There is nothing to build.
            continue

        base_meta = load_yaml_at_ref(BASE_SHA, path)
        head_builds = builds_by_versioncode(head_meta)
        base_builds = builds_by_versioncode(base_meta) if base_meta else {}

        for vc, build in sorted(head_builds.items()):
            if vc not in base_builds or base_builds[vc] != build:
                targets.append({
                    "appid": appid,
                    "versionCode": vc,
                    "target": f"{appid}:{vc}",
                })

    print(json.dumps(targets))


if __name__ == "__main__":
    main()
