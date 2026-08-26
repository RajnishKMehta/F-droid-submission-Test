#!/usr/bin/env python3
"""
find_changed_diff_builds.py
Location: .github/scripts/find_changed_diff_builds.py

Detects new or modified (appid, versionCode) build targets from metadata/*.yml
between BASE_SHA and HEAD_SHA for the Diff Analysis pipeline.
"""
import json
import os
import subprocess
import sys

import yaml

BASE_SHA = os.environ.get("BASE_SHA", "")
HEAD_SHA = os.environ.get("HEAD_SHA", "")


def changed_metadata_files() -> list[str]:
    if not BASE_SHA or not HEAD_SHA:
        return []
    result = subprocess.run(
        [
            "git", "diff", "--name-only", "--diff-filter=d",
            BASE_SHA, HEAD_SHA, "--", "metadata/*.yml",
        ],
        capture_output=True, text=True, check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def load_yaml_at_ref(ref: str, path: str):
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
            continue

        base_meta = load_yaml_at_ref(BASE_SHA, path)
        head_builds = builds_by_versioncode(head_meta)
        base_builds = builds_by_versioncode(base_meta) if base_meta else {}

        # Check for Binaries URL in head_meta
        binaries_url = head_meta.get("Binaries", "")

        for vc, build in sorted(head_builds.items()):
            if vc not in base_builds or base_builds[vc] != build:
                targets.append({
                    "appid": appid,
                    "versionCode": vc,
                    "target": f"{appid}:{vc}",
                    "binaries_url": build.get("binaries", binaries_url),
                })

    print(json.dumps(targets))


if __name__ == "__main__":
    main()
