#!/usr/bin/env python3
"""
split_songs_v2.py

Splits this specific songbook-style PDF (chord charts + lyrics, one song
after another) into individual RTF files, one per song.

HOW IT DETECTS SONG BOUNDARIES
-------------------------------
This PDF is a chord/lyrics songbook. Font size does NOT reliably separate
titles from lyrics here (chord lines are printed just as large as titles),
but every single song in the book ends with a consistent footer credit
line:

        + BLD Newark +
        REPRINT MAR'97
        001 / DISC 1

(with small spelling/spacing variations -- "BLD  Newark", "BLD Nwark",
extra/missing page-number line, etc.) This script finds every occurrence
of that footer, treats it as the end of one song, and takes the first
non-blank line(s) immediately following the previous footer as the next
song's title.

USAGE
-----
    python3 split_songs_v2.py mysongs.pdf --dry-run
    python3 split_songs_v2.py mysongs.pdf --outdir ./songs

REQUIREMENTS
------------
    poppler-utils (pdftotext) must be installed and on PATH.
"""

import argparse
import os
import re
import subprocess
import sys

# Matches the recurring footer credit line, tolerating spacing/spelling
# variants seen in the source ("BLD Newark", "BLD  Newark", "BLD Nwark").
FOOTER_RE = re.compile(r'\+\s*BLD\s+N\s*wark\s*\+|\+\s*BLD\s+Newark\s*\+', re.IGNORECASE)

# A leftover page-number / disc-number line right after a footer, e.g.
# "001 / DISC 1" or a bare "039".
PAGE_NUM_RE = re.compile(
    r'^\d{1,4}\s*/\s*(DISC|PRAISE)\s*\d*$'
    r'|^(DISC|PRAISE)\s*\d+\s*/\s*\d{1,4}$'
    r'|^\d{1,4}$',
    re.IGNORECASE,
)

# Keywords that mark a leftover credit/reprint line (not part of a title),
# checked as a substring against the stripped, lowercased line.
SKIP_KEYWORDS = ("reprint", "printed", "ccli", "praise ministry", "reprinted by", "bld")


CHORD_WORD_RE = re.compile(
    r'^[A-G](#|b)?(maj7?|min7?|m7?|dim7?|aug|sus\d?|add\d?|M7?9?)*\d*(/[A-G](#|b)?\d*)?$'
)
SECTION_MARKER_RE = re.compile(
    r'^(\(?(CHORUS|REFRAIN|VERSE|BRIDGE|INTRO|END|REPEAT)S?\.?:?\s*(I{1,3}V?|IV|V|VI{0,3})?\)?'
    r'|I{1,3}V?|IV|V|VI{0,3})$',
    re.IGNORECASE,
)
# A line made up of nothing but stray punctuation/symbols (extraction
# artifacts) -- not a real title line.
SYMBOL_ONLY_RE = re.compile(r'^[\\/*.,;:!?\-–—\s]+$')


def is_chord_or_marker_line(line: str) -> bool:
    """True if a line looks like a guitar-chord line or a section marker
    (CHORUS/VERSE/roman numeral/etc), rather than title/lyric text --
    used to know where a multi-line title block ends."""
    stripped = line.strip()
    if not stripped:
        return False
    if SECTION_MARKER_RE.match(stripped):
        return True
    tokens = stripped.split()
    total = len(tokens)
    matched = 0
    for tok in tokens:
        core = tok.strip("(),.*")
        if core in ("-", "–", "—") or re.match(r'^\d?x$|^x\d$', core, re.IGNORECASE):
            matched += 1
            continue
        if CHORD_WORD_RE.match(core):
            matched += 1
    return total > 0 and (matched / total) >= 0.6


def is_skip_line(line: str) -> bool:
    stripped = line.strip().strip("\x0c")
    if not stripped:
        return True
    if PAGE_NUM_RE.match(stripped):
        return True
    if SYMBOL_ONLY_RE.match(stripped):
        return True
    lowered = stripped.lower()
    return any(kw in lowered for kw in SKIP_KEYWORDS)


def pdf_to_text(pdf_path: str) -> str:
    result = subprocess.run(
        ["pdftotext", "-layout", pdf_path, "-"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def sanitize_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip(" .") or "Untitled"


def dedupe_filename(base: str, used: dict) -> str:
    if base not in used:
        used[base] = 1
        return base
    used[base] += 1
    return f"{base} ({used[base]})"


def split_into_songs(full_text: str):
    """
    Returns a list of {"title": str, "body": str} in document order.
    """
    # Split on the footer marker. segments[0] = song 1's raw text (title
    # at top). segments[i] for i>0 = leftover page-number/blank lines
    # followed by song (i+1)'s raw text.
    segments = FOOTER_RE.split(full_text)

    songs = []
    for seg in segments:
        lines = seg.split("\n")

        # Skip leading page-number lines, form feeds, blank lines, and
        # any stray credit lines before the real title starts.
        idx = 0
        while idx < len(lines) and is_skip_line(lines[idx]):
            idx += 1

        if idx >= len(lines):
            continue  # nothing usable in this segment (e.g. trailing tail)

        # Title collection: take the first line, then keep absorbing
        # further lines only while they're neither blank, nor a chord
        # line, nor a section marker (CHORUS/VERSE/roman numeral/etc) --
        # this lets genuine two-line titles (e.g. "ALIVE, ALIVE, ALIVE" /
        # "FOREVERMORE") merge, while stopping before the song's chords
        # start even when there's no blank line separating them.
        title_lines = [lines[idx].strip()]
        idx += 1
        while (
            idx < len(lines)
            and lines[idx].strip()
            and not is_chord_or_marker_line(lines[idx])
        ):
            title_lines.append(lines[idx].strip())
            idx += 1
        # Skip a single trailing blank line right after the title, if present.
        if idx < len(lines) and not lines[idx].strip():
            idx += 1

        title = " ".join(title_lines)
        body = "\n".join(lines[idx:]).strip("\n")
        songs.append({"title": title, "body": body})

    return songs


def escape_rtf(text: str) -> str:
    out = []
    for ch in text:
        if ch in ("\\", "{", "}"):
            out.append("\\" + ch)
        elif ord(ch) > 127:
            out.append(f"\\u{ord(ch)}?")
        else:
            out.append(ch)
    return "".join(out)


def write_rtf(path: str, title: str, body: str):
    body_lines = body.split("\n")
    body_rtf = "\\par\n".join(escape_rtf(l) for l in body_lines)
    title_rtf = escape_rtf(title)
    rtf = (
        r"{\rtf1\ansi\deff0"
        r"{\fonttbl{\f0 Calibri;}{\f1 Courier New;}}"
        r"\f0\fs28\b " + title_rtf + r"\b0\fs24\par\par" + "\n"
        r"\f1\fs20 " + body_rtf +
        "\n}"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(rtf)


def main():
    ap = argparse.ArgumentParser(description="Split this songbook PDF into per-song RTF files.")
    ap.add_argument("pdf_path")
    ap.add_argument("--outdir", default="./songs")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.isfile(args.pdf_path):
        print(f"File not found: {args.pdf_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Reading {args.pdf_path} ...")
    text = pdf_to_text(args.pdf_path)
    songs = split_into_songs(text)
    print(f"Detected {len(songs)} song(s).\n")

    if args.dry_run:
        for i, song in enumerate(songs, start=1):
            preview_line = next((l for l in song["body"].split("\n") if l.strip()), "")
            print(f"{i:>4}. {song['title']!r}  preview: {preview_line.strip()[:60]!r}")
        print("\nDry run complete. No files written.")
        return

    os.makedirs(args.outdir, exist_ok=True)
    used_names = {}
    for song in songs:
        base = sanitize_filename(song["title"])
        base = dedupe_filename(base, used_names)
        out_path = os.path.join(args.outdir, base + ".rtf")
        write_rtf(out_path, song["title"], song["body"])

    print(f"Wrote {len(songs)} RTF file(s) to {args.outdir}/")
#shawn

if __name__ == "__main__":
    main()