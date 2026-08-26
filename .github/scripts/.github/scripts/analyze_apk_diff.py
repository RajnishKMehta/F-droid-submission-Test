#!/usr/bin/env python3
"""
analyze_apk_diff.py
Location: .github/scripts/analyze_apk_diff.py

Deep APK Diff & Human-Readable Decompilation Engine:
1. Locates Rebuilt APK and Reference APK.
2. Identifies all added, removed, and modified files inside the APKs.
3. Converts modified binary files into human-readable representations:
   - classes*.dex -> Disassembled Bytecode/Smali dump
   - AndroidManifest.xml & layout XMLs -> Decoded Human-Readable XML
   - resources.arsc -> Decoded Resource Table Dump
   - *.so (Native Libraries) -> Symbols, Headers & Strings Dump
   - Assets / Config / Text -> Direct Text Diff
4. Generates unified per-file diffs (.diff) for each differing file.
5. Produces comprehensive Markdown & JSON analysis summaries.
6. Generates full Diffoscope HTML/Text reports if available.
"""

import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


def calculate_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        return res.returncode, res.stdout, res.stderr
    except Exception as e:
        return -1, "", str(e)


def decode_binary_xml(apk_path: Path, xml_path_in_apk: str) -> str:
    """Decodes binary XML using aapt2/aapt/apktool or fallback."""
    # Attempt 1: aapt2 dump xmltree
    if shutil.which("aapt2"):
        code, out, _ = run_cmd(["aapt2", "dump", "xmltree", str(apk_path), "--file", xml_path_in_apk])
        if code == 0 and out.strip():
            return out

    # Attempt 2: aapt dump xmltree
    if shutil.which("aapt"):
        code, out, _ = run_cmd(["aapt", "dump", "xmltree", str(apk_path), xml_path_in_apk])
        if code == 0 and out.strip():
            return out

    # Fallback: extract raw text if already text, or raw strings
    with zipfile.ZipFile(apk_path, "r") as z:
        try:
            raw_bytes = z.read(xml_path_in_apk)
            # Filter printable strings from binary
            printable = "".join(chr(b) if 32 <= b <= 126 or b in (10, 13, 9) else " " for b in raw_bytes)
            return "\n".join(line.strip() for line in printable.splitlines() if line.strip())
        except Exception:
            return "[Unable to decode XML]"


def decode_resources_arsc(apk_path: Path) -> str:
    """Dumps resources.arsc table into readable text."""
    if shutil.which("aapt2"):
        code, out, _ = run_cmd(["aapt2", "dump", "resources", str(apk_path)])
        if code == 0 and out.strip():
            return out
    if shutil.which("aapt"):
        code, out, _ = run_cmd(["aapt", "dump", "resources", str(apk_path)])
        if code == 0 and out.strip():
            return out
    return "[Resources table dump unavailable (aapt2/aapt missing)]"


def disassemble_dex(dex_bytes: bytes, temp_dex_path: Path) -> str:
    """Disassembles DEX into human readable bytecode instructions."""
    temp_dex_path.write_bytes(dex_bytes)
    
    # Attempt 1: dexdump
    if shutil.which("dexdump"):
        code, out, _ = run_cmd(["dexdump", "-d", "-f", "-h", str(temp_dex_path)])
        if code == 0 and out.strip():
            return out

    # Attempt 2: baksmali
    if shutil.which("baksmali"):
        out_dir = temp_dex_path.parent / "smali_out"
        shutil.rmtree(out_dir, ignore_errors=True)
        code, _, _ = run_cmd(["baksmali", "disassemble", str(temp_dex_path), "-o", str(out_dir)])
        if code == 0 and out_dir.exists():
            combined = []
            for smali_file in sorted(out_dir.rglob("*.smali")):
                combined.append(f"--- File: {smali_file.name} ---")
                combined.append(smali_file.read_text(errors="replace"))
            return "\n".join(combined)

    # Fallback: extract string pool and class descriptors from dex
    strings = []
    curr = []
    for b in dex_bytes:
        if 32 <= b <= 126:
            curr.append(chr(b))
        else:
            if len(curr) >= 4:
                strings.append("".join(curr))
            curr = []
    return "=== String & Symbol Pool Extraction ===\n" + "\n".join(strings)


def disassemble_native_so(so_bytes: bytes, temp_so_path: Path) -> str:
    """Extracts symbols, sections, and disassembly from ELF .so binaries."""
    temp_so_path.write_bytes(so_bytes)
    output = []

    # Symbol Table / Readelf
    if shutil.which("readelf"):
        _, out_h, _ = run_cmd(["readelf", "-h", str(temp_so_path)])
        _, out_s, _ = run_cmd(["readelf", "-s", "--wide", str(temp_so_path)])
        output.append("=== ELF Header ===\n" + out_h)
        output.append("=== Symbol Table ===\n" + out_s)
    elif shutil.which("nm"):
        _, out_nm, _ = run_cmd(["nm", "-D", str(temp_so_path)])
        output.append("=== Dynamic Symbols (nm) ===\n" + out_nm)

    # Disassembly (objdump)
    if shutil.which("objdump"):
        _, out_obj, _ = run_cmd(["objdump", "-d", "--no-show-raw-insn", str(temp_so_path)])
        if out_obj.strip():
            output.append("=== Disassembly ===\n" + out_obj[:500000])  # limit size

    # Fallback strings
    if not output:
        strings = []
        curr = []
        for b in so_bytes:
            if 32 <= b <= 126:
                curr.append(chr(b))
            else:
                if len(curr) >= 4:
                    strings.append("".join(curr))
                curr = []
        output.append("=== Extracted Strings ===\n" + "\n".join(strings))

    return "\n\n".join(output)


def convert_to_human_readable(
    filename: str,
    raw_bytes: bytes,
    apk_path: Path,
    temp_dir: Path
) -> str:
    """Converts any internal APK file into a clean human-readable text representation."""
    ext = os.path.splitext(filename).lower()
    
    # Binary XML
    if ext == ".xml":
        return decode_binary_xml(apk_path, filename)
    
    # Resource Table
    if filename == "resources.arsc":
        return decode_resources_arsc(apk_path)
    
    # DEX Bytecode
    if ext == ".dex":
        temp_dex = temp_dir / f"temp_{Path(filename).name}"
        return disassemble_dex(raw_bytes, temp_dex)
    
    # Native Shared Libraries
    if ext == ".so":
        temp_so = temp_dir / f"temp_{Path(filename).name}"
        return disassemble_native_so(raw_bytes, temp_so)
    
    # Text, JSON, Properties, Manifest, Proguard files
    if ext in [".txt", ".json", ".properties", ".pro", ".mf", ".version", ".proto"]:
        try:
            return raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return raw_bytes.decode("latin-1", errors="replace")

    # Generic Fallback: Hex dump + ASCII representation
    lines = []
    for i in range(0, min(len(raw_bytes), 100000), 16):
        chunk = raw_bytes[i:i+16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
        lines.append(f"{i:08x}  {hex_part:<48}  |{ascii_part}|")
    if len(raw_bytes) > 100000:
        lines.append(f"... [Truncated. Total length: {len(raw_bytes)} bytes]")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 3:
        print("Usage: analyze_apk_diff.py <rebuilt_apk_path> <reference_apk_path> [output_dir]")
        sys.exit(1)

    rebuilt_apk = Path(sys.argv)
    reference_apk = Path(sys.argv)
    output_base = Path(sys.argv) if len(sys.argv) > 3 else Path("diff_analysis_output")

    # Output subdirectories
    summary_dir = output_base / "summary"
    per_file_diffs_dir = output_base / "per_file_human_readable_diffs"
    decoded_rebuilt_dir = output_base / "decoded_rebuilt_files"
    decoded_ref_dir = output_base / "decoded_reference_files"
    diffoscope_dir = output_base / "diffoscope"

    for d in [summary_dir, per_file_diffs_dir, decoded_rebuilt_dir, decoded_ref_dir, diffoscope_dir]:
        d.mkdir(parents=True, exist_ok=True)

    temp_dir = output_base / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    print(f"==> Analyzing Differences:")
    print(f"    Rebuilt APK:   {rebuilt_apk}")
    print(f"    Reference APK: {reference_apk}")

    rebuilt_sha = calculate_sha256(rebuilt_apk)
    ref_sha = calculate_sha256(reference_apk)
    is_exact_match = (rebuilt_sha == ref_sha)

    report_data = {
        "is_reproducible": is_exact_match,
        "rebuilt_apk": {
            "name": rebuilt_apk.name,
            "size_bytes": rebuilt_apk.stat().st_size,
            "sha256": rebuilt_sha,
        },
        "reference_apk": {
            "name": reference_apk.name,
            "size_bytes": reference_apk.stat().st_size,
            "sha256": ref_sha,
        },
        "summary": {
            "total_files_rebuilt": 0,
            "total_files_reference": 0,
            "identical_files_count": 0,
            "added_files_count": 0,
            "removed_files_count": 0,
            "modified_files_count": 0,
        },
        "added_files": [],
        "removed_files": [],
        "modified_files": [],
    }

    with zipfile.ZipFile(rebuilt_apk, "r") as z_reb, zipfile.ZipFile(reference_apk, "r") as z_ref:
        reb_files = {name: z_reb.getinfo(name) for name in z_reb.namelist()}
        ref_files = {name: z_ref.getinfo(name) for name in z_ref.namelist()}

        report_data["summary"]["total_files_rebuilt"] = len(reb_files)
        report_data["summary"]["total_files_reference"] = len(ref_files)

        all_names = sorted(set(reb_files.keys()) | set(ref_files.keys()))

        for name in all_names:
            safe_name = name.replace("/", "_").replace("\\", "_")

            if name in reb_files and name not in ref_files:
                report_data["added_files"].append(name)
                # Save decoded added file
                raw = z_reb.read(name)
                decoded = convert_to_human_readable(name, raw, rebuilt_apk, temp_dir)
                (decoded_rebuilt_dir / f"{safe_name}.txt").write_text(decoded, errors="replace")
                (per_file_diffs_dir / f"ADDED_{safe_name}.diff").write_text(
                    f"--- /dev/null\n+++ {name}\n@@ Added in rebuilt APK @@\n" + decoded,
                    errors="replace"
                )

            elif name in ref_files and name not in reb_files:
                report_data["removed_files"].append(name)
                # Save decoded removed file
                raw = z_ref.read(name)
                decoded = convert_to_human_readable(name, raw, reference_apk, temp_dir)
                (decoded_ref_dir / f"{safe_name}.txt").write_text(decoded, errors="replace")
                (per_file_diffs_dir / f"REMOVED_{safe_name}.diff").write_text(
                    f"--- {name}\n+++ /dev/null\n@@ Removed in rebuilt APK @@\n" + decoded,
                    errors="replace"
                )

            else:
                # File exists in both, check binary content
                reb_raw = z_reb.read(name)
                ref_raw = z_ref.read(name)

                reb_file_hash = hashlib.sha256(reb_raw).hexdigest()
                ref_file_hash = hashlib.sha256(ref_raw).hexdigest()

                if reb_file_hash == ref_file_hash:
                    report_data["summary"]["identical_files_count"] += 1
                else:
                    report_data["modified_files"].append({
                        "file_name": name,
                        "rebuilt_size": len(reb_raw),
                        "reference_size": len(ref_raw),
                        "rebuilt_sha256": reb_file_hash,
                        "reference_sha256": ref_file_hash,
                    })

                    # Human-readable decompilation of both versions
                    reb_decoded = convert_to_human_readable(name, reb_raw, rebuilt_apk, temp_dir)
                    ref_decoded = convert_to_human_readable(name, ref_raw, reference_apk, temp_dir)

                    (decoded_rebuilt_dir / f"{safe_name}.txt").write_text(reb_decoded, errors="replace")
                    (decoded_ref_dir / f"{safe_name}.txt").write_text(ref_decoded, errors="replace")

                    # Generate line-by-line unified diff of human-readable content
                    diff_lines = list(difflib.unified_diff(
                        ref_decoded.splitlines(keepends=True),
                        reb_decoded.splitlines(keepends=True),
                        fromfile=f"Reference/{name}",
                        tofile=f"Rebuilt/{name}",
                        n=3
                    ))

                    diff_text = "".join(diff_lines)
                    if not diff_text.strip():
                        diff_text = (
                            f"# Binary differs (Hash mismatch) but high-level text representations are identical.\n"
                            f"# Reference SHA256: {ref_file_hash}\n"
                            f"# Rebuilt   SHA256: {reb_file_hash}\n"
                        )

                    (per_file_diffs_dir / f"DIFF_{safe_name}.diff").write_text(diff_text, errors="replace")

    report_data["summary"]["added_files_count"] = len(report_data["added_files"])
    report_data["summary"]["removed_files_count"] = len(report_data["removed_files"])
    report_data["summary"]["modified_files_count"] = len(report_data["modified_files"])

    # Generate Diffoscope HTML & Text reports if diffoscope is installed
    if shutil.which("diffoscope"):
        print("==> Generating Diffoscope reports...")
        run_cmd([
            "diffoscope",
            "--html", str(diffoscope_dir / "diffoscope_report.html"),
            "--text", str(diffoscope_dir / "diffoscope_report.txt"),
            str(reference_apk),
            str(rebuilt_apk)
        ])

    # Save JSON Report
    (summary_dir / "diff_analysis.json").write_text(json.dumps(report_data, indent=2))

    # Generate Markdown Summary Report
    md_lines = [
        "# F-Droid Reproducible Build Diff Analysis Report",
        "",
        f"**Verdict:** {' REPRODUCIBLE (Exact Match)' if is_exact_match else ' NOT REPRODUCIBLE (Differences Found)'}",
        "",
        "## 1. APK Hashes & Sizes",
        "| Attribute | Rebuilt APK | Reference (Upstream) APK |",
        "| :--- | :--- | :--- |",
        f"| **Filename** | `{rebuilt_apk.name}` | `{reference_apk.name}` |",
        f"| **Size (bytes)** | {rebuilt_apk.stat().st_size:,} | {reference_apk.stat().st_size:,} |",
        f"| **SHA-256** | `{rebuilt_sha}` | `{ref_sha}` |",
        "",
        "## 2. Internal Zip Entries Breakdown",
        f"- **Total Files in Rebuilt APK:** {report_data['summary']['total_files_rebuilt']}",
        f"- **Total Files in Reference APK:** {report_data['summary']['total_files_reference']}",
        f"- **Identical Files:** {report_data['summary']['identical_files_count']}",
        f"- **Modified Files:** {report_data['summary']['modified_files_count']}",
        f"- **Added Files:** {report_data['summary']['added_files_count']}",
        f"- **Removed Files:** {report_data['summary']['removed_files_count']}",
        "",
    ]

    if report_data["modified_files"]:
        md_lines.append("## 3. List of Modified Files (Differences Detected)")
        md_lines.append("| File Name | Rebuilt Size | Ref Size | Human-Readable Diff File |")
        md_lines.append("| :--- | :--- | :--- | :--- |")
        for mod in report_data["modified_files"]:
            fname = mod["file_name"]
            sname = fname.replace("/", "_").replace("\\", "_")
            md_lines.append(f"| `{fname}` | {mod['rebuilt_size']} B | {mod['reference_size']} B | `DIFF_{sname}.diff` |")
        md_lines.append("")

    if report_data["added_files"]:
        md_lines.append("## 4. Added Files in Rebuilt APK")
        for a in report_data["added_files"]:
            md_lines.append(f"- `{a}`")
        md_lines.append("")

    if report_data["removed_files"]:
        md_lines.append("## 5. Removed Files in Rebuilt APK")
        for r in report_data["removed_files"]:
            md_lines.append(f"- `{r}`")
        md_lines.append("")

    md_lines.append("## 6. Artifact Guide")
    md_lines.append("All decomposed human-readable diffs, decoded sources, and reports are uploaded as GitHub Actions artifacts:")
    md_lines.append("1. **`fdroid-diff-summary-...`**: High-level markdown analysis and structured JSON data.")
    md_lines.append("2. **`fdroid-per-file-readable-diffs-...`**: Granular `.diff` files for every differing section/file.")
    md_lines.append("3. **`fdroid-decoded-rebuilt-files-...`**: All decompiled/decoded text files of the Rebuilt APK.")
    md_lines.append("4. **`fdroid-decoded-reference-files-...`**: All decompiled/decoded text files of the Reference APK.")
    md_lines.append("5. **`fdroid-diffoscope-report-...`**: Full interactive HTML & text Diffoscope report.")

    (summary_dir / "REPRODUCIBILITY_DIFF_REPORT.md").write_text("\n".join(md_lines))
    print("==> Analysis Completed Successfully!")


if __name__ == "__main__":
    main()
