#!/usr/bin/env python3
"""
find_reproducibility_diff_targets.py

(fdroid-reproducibility-diff-analysis.yml pipeline ke liye — is naam se
alag hai taaki ye purani find_changed_builds.py / fdroid-metadata-build-check.yml
pipeline se bilkul independent chale.)

PR me changed ho chuke `metadata/*.yml` files ko dekh kar batata hai ki
kaunse (appid, versionCode) build targets naye hain ya badal gaye hain.

Ek target "changed" tab count hota hai jab:
  - metadata file hi is PR me naya add hua ho, YA
  - us versionCode ka Build entry base branch me nahi tha, YA
  - us versionCode ke Build entry ke fields (commit, subdir, gradle, ...)
    base branch se alag hain

Output: ek JSON array, GitHub Actions matrix (`strategy.matrix.include`)
me seedha use karne layak:
  [{"appid": "moe.rukamori.archivetune", "versionCode": 140,
    "target": "moe.rukamori.archivetune:140"}, ...]

Env vars chahiye: BASE_SHA, HEAD_SHA (dono commits jinke beech diff lena hai)
"""
import json
import os
import subprocess
import sys

import yaml

BASE_SHA = os.environ["BASE_SHA"]
HEAD_SHA = os.environ["HEAD_SHA"]


def changed_metadata_files() -> list:
    """metadata/*.yml me se jo files is diff me touch hui hain (deleted chhod kar)."""
    result = subprocess.run(
        [
            "git", "diff", "--name-only", "--diff-filter=d",
            BASE_SHA, HEAD_SHA, "--", "metadata/*.yml",
        ],
        capture_output=True, text=True, check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def load_yaml_at_ref(ref: str, path: str):
    """Kisi bhi commit par file ka content nikalo; file wahan na ho to None."""
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return yaml.safe_load(result.stdout) or {}
    except yaml.YAMLError as exc:
        print(f"::warning::{path} @ {ref} parse nahi hui: {exc}", file=sys.stderr)
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
