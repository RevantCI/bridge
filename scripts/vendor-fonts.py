#!/usr/bin/env python3
"""Vendor the bundled script fonts into public/fonts/ as WOFF2.

Bridge is local-first and builds offline, so the font files are committed to
the repo rather than fetched at build time. This script is the record of how
they were produced -- run it only to add a family or refresh a version, then
commit the result. See docs/plans/FONT_SUPPORT_PLAN.md for the design.

Two things here are deliberate and easy to get wrong:

1. The Noto families are only published as *variable* fonts, and a variable
   WOFF2 is roughly 3x the size of the static Regular+Bold pair Bridge
   actually uses (Tamil: 181 KB vs 66 KB). So each one is instanced at
   wght 400/700 with fontTools rather than shipped as-is. Instancing resolves
   variation deltas; it does not touch the glyph set or the GSUB/GPOS tables,
   and the script asserts that after every instance.

2. Nothing is subsetted. Complex-script shaping lives in GSUB/GPOS, and a
   subsetter that drops the wrong lookup breaks Tamil conjuncts or Hebrew
   mark positioning in a way that looks like a rendering bug rather than a
   font bug. Not worth the ~100 KB.

Vijaya and Nirmala UI are Microsoft fonts that ship with Windows; they are
named in the CSS stack but must never be bundled -- Microsoft grants no
redistribution right. Everything downloaded here is OFL 1.1.

Usage:  python scripts/vendor-fonts.py [--output public/fonts]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import urllib.parse
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

# Pinned so a re-run reproduces the committed bytes instead of silently
# picking up whatever upstream shipped since.
GF_COMMIT = "5e35378e6bda803962ee6fd257e444a7d459660d"
GF_RAW = f"https://raw.githubusercontent.com/google/fonts/{GF_COMMIT}/ofl"

EZRA_VERSION = "2.51"
EZRA_ZIP = f"https://software.sil.org/downloads/r/ezra/EzraSIL-{EZRA_VERSION}.zip"

# Variable Noto families, instanced to a static Regular/Bold pair.
# (output stem, google-fonts dir, variable filename, css family, covers)
VARIABLE = [
    ("NotoSerifTamil", "notoseriftamil", "NotoSerifTamil[wdth,wght].ttf",
     "Noto Serif Tamil", "Tamil"),
    ("NotoSerifDevanagari", "notoserifdevanagari", "NotoSerifDevanagari[wdth,wght].ttf",
     "Noto Serif Devanagari", "Hindi, Marathi, Nepali"),
    ("NotoSerifBengali", "notoserifbengali", "NotoSerifBengali[wdth,wght].ttf",
     "Noto Serif Bengali", "Bengali, Assamese"),
    ("NotoSerifTelugu", "notoseriftelugu", "NotoSerifTelugu[wght].ttf",
     "Noto Serif Telugu", "Telugu"),
    ("NotoSerifKannada", "notoserifkannada", "NotoSerifKannada[wght].ttf",
     "Noto Serif Kannada", "Kannada"),
    ("NotoSerifMalayalam", "notoserifmalayalam", "NotoSerifMalayalam[wght].ttf",
     "Noto Serif Malayalam", "Malayalam"),
    ("NotoSerifGujarati", "notoserifgujarati", "NotoSerifGujarati[wght].ttf",
     "Noto Serif Gujarati", "Gujarati"),
    ("NotoSerifGurmukhi", "notoserifgurmukhi", "NotoSerifGurmukhi[wght].ttf",
     "Noto Serif Gurmukhi", "Punjabi"),
    ("NotoSerifOriya", "notoseriforiya", "NotoSerifOriya[wght].ttf",
     "Noto Serif Oriya", "Odia"),
    ("NotoNastaliqUrdu", "notonastaliqurdu", "NotoNastaliqUrdu[wght].ttf",
     "Noto Nastaliq Urdu", "Urdu"),
]

# Already published as statics upstream.
# (output stem, google-fonts dir, filename, css family, covers)
STATIC = [
    ("GentiumPlus-Regular", "gentiumplus", "GentiumPlus-Regular.ttf",
     "Gentium Plus", "Polytonic Greek (UGNT)"),
    ("GentiumPlus-Bold", "gentiumplus", "GentiumPlus-Bold.ttf",
     "Gentium Plus", "Polytonic Greek (UGNT)"),
]

WEIGHTS = [(400, "Regular"), (700, "Bold")]


def fetch(url: str) -> bytes:
    print(f"  GET {url}")
    with urllib.request.urlopen(url, timeout=180) as response:
        return response.read()


def gf_url(directory: str, filename: str) -> str:
    return f"{GF_RAW}/{directory}/{urllib.parse.quote(filename)}"


def shaping_signature(font: TTFont) -> tuple:
    """What must survive instancing: the glyph set and the shaping tables."""
    return (
        len(font.getGlyphOrder()),
        "GSUB" in font,
        "GPOS" in font,
        "GDEF" in font,
        len(font["GSUB"].table.LookupList.Lookup) if "GSUB" in font else 0,
        len(font["GPOS"].table.LookupList.Lookup) if "GPOS" in font else 0,
    )


def write_woff2(font: TTFont, path: Path) -> int:
    font.flavor = "woff2"
    font.save(str(path))
    return path.stat().st_size


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=Path("public/fonts"), type=Path)
    args = parser.parse_args()

    out: Path = args.output
    out.mkdir(parents=True, exist_ok=True)

    rows: list[tuple[str, str, str, str, int]] = []  # file, family, covers, source, bytes

    for stem, gf_dir, filename, family, covers in VARIABLE:
        print(family)
        raw = fetch(gf_url(gf_dir, filename))
        source_sha = hashlib.sha256(raw).hexdigest()

        base = TTFont(io.BytesIO(raw))
        axes = {a.axisTag: (a.minValue, a.maxValue) for a in base["fvar"].axes}
        expected = shaping_signature(base)
        wght_min, wght_max = axes["wght"]

        for weight, label in WEIGHTS:
            if not wght_min <= weight <= wght_max:
                print(f"  !! no wght {weight} (range {wght_min}-{wght_max}) -- skipped")
                continue
            pins = {"wght": weight}
            if "wdth" in axes:
                pins["wdth"] = 100  # default width; Bridge never varies it
            font = instancer.instantiateVariableFont(
                TTFont(io.BytesIO(raw)), pins, inplace=True, updateFontNames=True
            )
            actual = shaping_signature(font)
            if actual != expected:
                raise SystemExit(
                    f"{family} {label}: instancing changed the glyph set or shaping "
                    f"tables ({actual} != {expected}). Refusing to ship a font whose "
                    "complex-script behaviour may have changed."
                )
            path = out / f"{stem}-{label}.woff2"
            size = write_woff2(font, path)
            print(f"  -> {path.name}  {size / 1024:.1f} KB")
            rows.append((
                path.name, family, covers,
                f"google/fonts@{GF_COMMIT[:7]} `ofl/{gf_dir}/{filename}` "
                f"(sha256 {source_sha[:16]}), instanced to wght {weight}",
                size,
            ))

    for stem, gf_dir, filename, family, covers in STATIC:
        print(f"{family} ({filename})")
        raw = fetch(gf_url(gf_dir, filename))
        source_sha = hashlib.sha256(raw).hexdigest()
        path = out / f"{stem}.woff2"
        size = write_woff2(TTFont(io.BytesIO(raw)), path)
        print(f"  -> {path.name}  {size / 1024:.1f} KB")
        rows.append((
            path.name, family, covers,
            f"google/fonts@{GF_COMMIT[:7]} `ofl/{gf_dir}/{filename}` "
            f"(sha256 {source_sha[:16]})",
            size,
        ))

    # Ezra SIL ships one weight only -- there is no bold cut. Hebrew source
    # text is never bolded in Bridge, so this is not a gap.
    print("Ezra SIL")
    raw_zip = fetch(EZRA_ZIP)
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as archive:
        ttf = archive.read(f"EzraSIL{EZRA_VERSION}/SILEOT.ttf")
        licenses = archive.read(f"EzraSIL{EZRA_VERSION}/Licenses.txt")
    source_sha = hashlib.sha256(ttf).hexdigest()
    path = out / "EzraSIL-Regular.woff2"
    size = write_woff2(TTFont(io.BytesIO(ttf)), path)
    print(f"  -> {path.name}  {size / 1024:.1f} KB")
    rows.append((
        path.name, "Ezra SIL", "Hebrew with pointing and cantillation (UHB)",
        f"SIL `EzraSIL-{EZRA_VERSION}.zip` `SILEOT.ttf` (sha256 {source_sha[:16]})",
        size,
    ))
    # Ezra is OFL 1.1 *plus* MIT for its Hebrew layout intelligence, so its
    # own licence file ships verbatim rather than being folded into OFL.txt.
    (out / "EzraSIL-Licenses.txt").write_bytes(licenses)

    print("licences")
    (out / "OFL.txt").write_bytes(fetch(gf_url("notoseriftamil", "OFL.txt")))
    (out / "GentiumPlus-OFL.txt").write_bytes(fetch(gf_url("gentiumplus", "OFL.txt")))

    total = sum(row[4] for row in rows)
    lines = [
        "# Bundled fonts",
        "",
        f"Generated by `scripts/vendor-fonts.py` on {date.today().isoformat()}.",
        "Do not edit by hand -- re-run the script and commit its output.",
        "",
        "These files are committed rather than downloaded at build time because",
        "Bridge is local-first and must build and run with no network access.",
        "",
        "## Why these are here and Vijaya is not",
        "",
        "Vijaya and Nirmala UI cover Indic scripts on Windows and are named first",
        "in `--font-indic` (`src/index.css`), but they are Microsoft fonts licensed",
        "only for use on a licensed Windows install -- **never add them to this",
        "directory or to the installer.** The faces below are the redistributable",
        "floor for macOS/Linux dev machines and stripped Windows installs.",
        "",
        "## Licences",
        "",
        '* `OFL.txt` -- SIL Open Font License 1.1, covering every `Noto*` file here.',
        '  Copyright the Noto Project Authors; Reserved Font Name "Noto".',
        '* `GentiumPlus-OFL.txt` -- OFL 1.1 for Gentium Plus. Copyright SIL',
        '  International; Reserved Font Names "Gentium" and "SIL".',
        '* `EzraSIL-Licenses.txt` -- OFL 1.1 for Ezra SIL (Reserved Font Names',
        '  "Ezra" and "SIL"), plus the MIT/X11 licence covering its Hebrew layout',
        "  intelligence (c) Ralph Hancock and John Hudson.",
        "",
        "## Files",
        "",
        "| File | Family | Covers | KB | Source |",
        "|---|---|---|---:|---|",
    ]
    for name, family, covers, source, size in rows:
        lines.append(f"| `{name}` | {family} | {covers} | {size / 1024:.0f} | {source} |")
    lines += [
        "",
        f"Total: {len(rows)} files, {total / 1024:.0f} KB.",
        "",
        "The Noto families are published upstream only as variable fonts; each is",
        "instanced here to a static Regular/Bold pair, about a third of the size of",
        "the variable original. Nothing is subsetted -- complex-script shaping",
        "depends on the full GSUB/GPOS tables, and the script asserts the glyph set",
        "and lookup counts are unchanged after every instance.",
        "",
        "Ezra SIL has no bold cut upstream; Hebrew source text is never bolded in",
        "Bridge, so only the regular weight is bundled.",
        "",
    ]
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"\n{len(rows)} font files, {total / 1024:.0f} KB total, in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
