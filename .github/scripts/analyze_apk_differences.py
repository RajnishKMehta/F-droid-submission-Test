#!/usr/bin/env python3
"""
analyze_apk_differences.py

Do APK ko deeply compare karta hai — built (CI/F-Droid wali) aur reference
(upstream release wali) — aur jitna zyada ho sake utna human-readable data
generate karta hai:

  1. RAW comparison — dono APK ko plain unzip karke har file ka SHA256 +
     size record karta hai. Isse pata chalta hai kaunsi files IDENTICAL,
     DIFFERENT, sirf-built-me, ya sirf-reference-me hain.

  2. SEMANTIC (human-readable) comparison — apktool se dono APK ko
     decompile karta hai:
       - classes*.dex  -> smali (readable bytecode text)
       - AndroidManifest.xml -> asli readable XML
       - resources.arsc + res/*  -> readable XML tree
     Phir dono decompiled trees ka poora diff banata hai.

  3. Har ALAG differing file ke liye ek ALAG human-readable diff report
     banata hai (diffs/<file>.diff.txt) — dex ho to smali-diff, resource
     ho to XML-diff, koi bhi aur opaque binary ho to hex-level diff.

  4. Ek summary.md jisme sab kuchh compile hota hai — kitni files match
     hui, kitni alag hain, kaunsi sirf-ek-taraf hain, sab kuchh table
     format me.

Usage:
    analyze_apk_differences.py <built_apk> <reference_apk> <output_dir>
"""
import difflib
import hashlib
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_zip_inventory(apk_path: Path, extract_dir: Path) -> Dict[str, dict]:
    """APK ko plain unzip karke har file ka sha256 + size record karo."""
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(apk_path) as zf:
        zf.extractall(extract_dir)

    inventory = {}
    for root, _, files in os.walk(extract_dir):
        for name in files:
            full = Path(root) / name
            rel = full.relative_to(extract_dir).as_posix()
            inventory[rel] = {
                "sha256": sha256_of(full),
                "size": full.stat().st_size,
                "abs_path": str(full),
            }
    return inventory


def run_apktool_decompile(apk_path: Path, out_dir: Path, log_path: Path) -> bool:
    """apktool se APK decompile karo — dex->smali, arsc/manifest->readable XML.

    apktool missing ho ya kisi bhi wajah se launch na ho paye, to yeh
    crash nahi karta — False return karta hai taaki caller hex-diff
    fallback use kar sake (poora script fail nahi hona chahiye sirf
    isliye ki apktool available nahi hai).
    """
    if out_dir.exists():
        subprocess.run(["rm", "-rf", str(out_dir)], check=False)
    cmd = ["apktool", "d", "-f", "-o", str(out_dir), str(apk_path)]
    try:
        with open(log_path, "w") as log:
            result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
        return result.returncode == 0
    except (FileNotFoundError, OSError) as exc:
        log_path.write_text(f"apktool chala nahi paya: {exc}\n")
        return False


def sanitize_filename(rel_path: str) -> str:
    return rel_path.replace("/", "__")


def hex_diff(path_a: Path, path_b: Path, out_file: Path, max_bytes: int = 2_000_000) -> None:
    """Opaque binary files (jo apktool decode nahi karta) ke liye readable hex-diff."""

    def hexdump(p: Path) -> List[str]:
        data = p.read_bytes()[:max_bytes]
        lines = []
        for i in range(0, len(data), 16):
            chunk = data[i:i + 16]
            hexpart = " ".join(f"{b:02x}" for b in chunk)
            asciipart = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            lines.append(f"{i:08x}  {hexpart:<47}  {asciipart}")
        return lines

    lines_a = hexdump(path_a)
    lines_b = hexdump(path_b)

    diff_lines = list(difflib.unified_diff(
        lines_a, lines_b,
        fromfile=f"reference/{path_a.name}",
        tofile=f"built/{path_b.name}",
        lineterm="",
    ))

    with open(out_file, "w") as f:
        f.write(f"# Hex-level diff -- {path_a.name}\n")
        f.write(f"# (Pehle {max_bytes} bytes tak truncate kiya hai agar file bade se badi hai)\n\n")
        if diff_lines:
            f.write("\n".join(diff_lines))
        else:
            f.write(
                "(Hex-dump lines ka textual diff nahi bana -- lekin SHA256 mismatch "
                "hai, matlab byte-level par dono files alag hain. Sizes aur hashes "
                "summary.md me dekho.)\n"
            )


def find_matching_decompiled_path(rel_apk_path: str, decompiled_root: Path) -> Optional[Path]:
    """
    APK ke andar ka raw path (classes2.dex, AndroidManifest.xml, res/xml/foo.xml)
    apktool ke decompiled tree ke corresponding path/dir se map karo.
    """
    name = Path(rel_apk_path).name

    if name == "classes.dex":
        candidate = decompiled_root / "smali"
        return candidate if candidate.exists() else None

    if name.startswith("classes") and name.endswith(".dex"):
        n = name[len("classes"):-len(".dex")]
        candidate = decompiled_root / f"smali_classes{n}"
        return candidate if candidate.exists() else None

    if name == "AndroidManifest.xml" and "/" not in rel_apk_path:
        candidate = decompiled_root / "AndroidManifest.xml"
        return candidate if candidate.exists() else None

    if name == "resources.arsc":
        candidate = decompiled_root / "res"
        return candidate if candidate.exists() else None

    if rel_apk_path.startswith("res/"):
        candidate = decompiled_root / rel_apk_path
        return candidate if candidate.exists() else None

    return None


def diff_directory_or_file(path_a: Path, path_b: Path, out_file: Path, label: str) -> None:
    """apktool se decompile hui smali/res directories (ya single files) ka readable text diff."""
    if path_a.is_dir() or path_b.is_dir():
        cmd = ["diff", "-ruN", str(path_a), str(path_b)]
    else:
        cmd = ["diff", "-u", str(path_a), str(path_b)]

    with open(out_file, "w") as f:
        f.write(f"# Human-readable diff -- {label}\n")
        f.write(f"# reference: {path_a}\n# built:     {path_b}\n\n")
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) != 4:
        print("Usage: analyze_apk_differences.py <built_apk> <reference_apk> <output_dir>", file=sys.stderr)
        sys.exit(1)

    built_apk = Path(sys.argv[1]).resolve()
    reference_apk = Path(sys.argv[2]).resolve()
    out_dir = Path(sys.argv[3]).resolve()

    if not built_apk.is_file():
        print(f"Built APK nahi mili: {built_apk}", file=sys.stderr)
        sys.exit(1)
    if not reference_apk.is_file():
        print(f"Reference APK nahi mili: {reference_apk}", file=sys.stderr)
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    diffs_dir = out_dir / "diffs"
    diffs_dir.mkdir(exist_ok=True)
    raw_built_dir = out_dir / "raw_built"
    raw_ref_dir = out_dir / "raw_reference"
    decompiled_built_dir = out_dir / "decompiled_built"
    decompiled_ref_dir = out_dir / "decompiled_reference"

    # --- 1) Raw file-level inventory ---
    print("==> Raw zip listing nikal rahe hain (SHA256 ke saath)...")
    inv_built = extract_zip_inventory(built_apk, raw_built_dir)
    inv_ref = extract_zip_inventory(reference_apk, raw_ref_dir)

    all_paths = sorted(set(inv_built) | set(inv_ref))
    identical, different, only_built, only_ref = [], [], [], []
    for p in all_paths:
        in_b, in_r = p in inv_built, p in inv_ref
        if in_b and in_r:
            (identical if inv_built[p]["sha256"] == inv_ref[p]["sha256"] else different).append(p)
        elif in_b:
            only_built.append(p)
        else:
            only_ref.append(p)

    print(f"    {len(identical)} identical, {len(different)} different, "
          f"{len(only_built)} sirf-built-me, {len(only_ref)} sirf-reference-me")

    # --- 2) apktool decompile (human-readable form) ---
    print("==> apktool se dono APK decompile kar rahe hain (human-readable ke liye)...")
    ok_built = run_apktool_decompile(built_apk, decompiled_built_dir, out_dir / "apktool_built.log")
    ok_ref = run_apktool_decompile(reference_apk, decompiled_ref_dir, out_dir / "apktool_reference.log")
    if not (ok_built and ok_ref):
        print("    apktool decompile me kuchh dikkat aayi -- apktool_*.log dekho. "
              "Un files ke liye hex-diff fallback use hoga.")

    # --- 3) Har differing file ke liye ALAG human-readable diff ---
    print(f"==> {len(different)} differing files ke liye alag-alag human-readable diff bana rahe hain...")
    per_file_reports = []
    for rel_path in different:
        safe_name = sanitize_filename(rel_path)
        b_info, r_info = inv_built[rel_path], inv_ref[rel_path]
        out_file = diffs_dir / f"{safe_name}.diff.txt"

        matched_built = find_matching_decompiled_path(rel_path, decompiled_built_dir) if ok_built else None
        matched_ref = find_matching_decompiled_path(rel_path, decompiled_ref_dir) if ok_ref else None

        if matched_built and matched_ref:
            diff_directory_or_file(matched_ref, matched_built, out_file, rel_path)
            diff_type = "human-readable (apktool decoded)"
        else:
            hex_diff(Path(r_info["abs_path"]), Path(b_info["abs_path"]), out_file)
            diff_type = "hex-level (binary, apktool decode nahi kar paya)"

        per_file_reports.append({
            "path": rel_path,
            "built_size": b_info["size"],
            "reference_size": r_info["size"],
            "built_sha256": b_info["sha256"],
            "reference_sha256": r_info["sha256"],
            "diff_type": diff_type,
            "diff_file": str(out_file.relative_to(out_dir)),
        })

    # --- 4) Poora decompiled-tree semantic diff (sabse zyada detail) ---
    print("==> Poora decompiled-tree semantic diff bana rahe hain...")
    full_diff_file = out_dir / "full_semantic_diff.txt"
    if ok_built and ok_ref:
        with open(full_diff_file, "w") as f:
            f.write("# Poora apktool-decompiled tree diff -- reference vs built\n\n")
            subprocess.run(
                ["diff", "-ruN", str(decompiled_ref_dir), str(decompiled_built_dir)],
                stdout=f, stderr=subprocess.STDOUT,
            )
    else:
        full_diff_file.write_text(
            "apktool decompile fail hui thi, is liye full semantic diff nahi ban paya.\n"
            "apktool_built.log / apktool_reference.log dekho.\n"
        )

    # --- 5) summary.md ---
    print("==> summary.md likh rahe hain...")
    summary_path = out_dir / "summary.md"
    with open(summary_path, "w") as f:
        f.write("# APK Difference Analysis\n\n")
        f.write(f"- **Built APK:** `{built_apk.name}` (sha256: `{sha256_of(built_apk)}`)\n")
        f.write(f"- **Reference APK:** `{reference_apk.name}` (sha256: `{sha256_of(reference_apk)}`)\n\n")

        f.write("## Overview\n\n")
        f.write("| Metric | Count |\n|---|---|\n")
        f.write(f"| Total files (union) | {len(all_paths)} |\n")
        f.write(f"| Identical | {len(identical)} |\n")
        f.write(f"| **Different** | **{len(different)}** |\n")
        f.write(f"| Only in built | {len(only_built)} |\n")
        f.write(f"| Only in reference | {len(only_ref)} |\n\n")

        if per_file_reports:
            f.write("## Differing Files\n\n")
            f.write("| File | Built size | Reference size | Diff type | Report |\n")
            f.write("|---|---|---|---|---|\n")
            for r in sorted(per_file_reports, key=lambda x: -x["built_size"]):
                f.write(f"| `{r['path']}` | {r['built_size']} B | {r['reference_size']} B | "
                        f"{r['diff_type']} | `{r['diff_file']}` |\n")
            f.write("\n")

        if only_built:
            f.write("## Sirf Built APK me (Reference me nahi)\n\n")
            for p in only_built:
                f.write(f"- `{p}` ({inv_built[p]['size']} B)\n")
            f.write("\n")

        if only_ref:
            f.write("## Sirf Reference APK me (Built me nahi)\n\n")
            for p in only_ref:
                f.write(f"- `{p}` ({inv_ref[p]['size']} B)\n")
            f.write("\n")

        f.write("## Output Files Ka Guide\n\n")
        f.write("- `full_semantic_diff.txt` — poore decompiled tree ka combined diff (sabse zyada detail)\n")
        f.write("- `diffs/` — har differing file ka ALAG human-readable diff report\n")
        f.write("- `raw_built/`, `raw_reference/` — dono APK ka plain unzip (raw files)\n")
        f.write("- `decompiled_built/`, `decompiled_reference/` — apktool se decode kiya hua poora tree\n")

    print(f"Analysis complete. Summary: {summary_path}")
    print(f"  {len(different)} files differ; {len(per_file_reports)} alag diff report bane.")


if __name__ == "__main__":
    main()
