#!/usr/bin/env python3
"""
PDFSeparator.py

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
    python3 src/PDFSeparator.py mysongs.pdf --dry-run
    python3 src/PDFSeparator.py mysongs.pdf --outdir ./songs

Guitar-chord lines are removed from the output; each RTF holds only the
title, section labels (CHORUS/VERSE etc.) and the lyrics.

REQUIREMENTS
------------
    PyMuPDF (pymupdf) is recommended for layout-aware extraction:
        pip install pymupdf
    poppler-utils (pdftotext) is used as a fallback if PyMuPDF is absent.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys

from typing import Any, List, Sequence, Tuple

# Matches the recurring footer credit line at the START of a line only,
# tolerating spacing/spelling variants seen in the source ("BLD Newark",
# "BLD  Newark", "BLD Nwark"), with optional surrounding "+" and an
# optional trailing credit/page-number suffix. Anchoring to a line start
# stops a stray "+ BLD Newark +" snippet inside body lyrics from splitting
# mid-song. (We deliberately don't anchor the end: -layout sometimes joins
# the footer's trailing credit lines onto the same physical line.)
FOOTER_RE = re.compile(
    r'^\s*\+?\s*BLD\s+(?:N\s*wark|Newark)\s*\+?',
    re.IGNORECASE | re.MULTILINE,
)

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
    # Base: note name (A-G, optional #/b) followed by one or more suffix
    # segments. Supported suffixes (case-insensitive overall, but m/M are
    # deliberately kept case-distinct):
    #   maj / maj7 / maj9        (maj13 is NOT matched)
    #   min / min7
    #   m / m7 / m9 / m13       (lowercase m only)
    #   dim / dim7
    #   aug
    #   sus / sus2 / sus4
    #   add / add9 / add11       (add13 is NOT matched)
    #   M7 / M9 / M13           (uppercase M, digit required; bare M is NOT matched)
    #   b5 / b9 / b13
    #   #5 / #9
    #   7 / 9 / 11 / 13
    # Known gaps (not matched):
    #   maj11, maj13, add13, M11, M, m11
    r'^[A-G](#|b)?'
    r'(?:maj7?|min7?|(?-i:m(?:7|9|13)?)|dim7?|aug|sus[24]?|add[679]?|(?-i:M(?:7|9|13))|b[59]?|#[59]?|[79])*'
    r'\d*(?:/(?:[A-G](#|b)?)?\d*)?$',
    re.IGNORECASE,
)
SECTION_MARKER_RE = re.compile(
    r'^\s*-?\s*\(?(?:CHORUS|CHORUSES|REFRAIN|REFRAINS|VERSE|VERSES|BRIDGE|BRIDGES|INTRO|INTROS|END|ENDS|REPEAT|REPEATS)'
    r'\.?:?\s*(?:I{1,3}V?|IV|V|VI{0,3}|[1-9]\d*)?\)?\s*-?\s*$'
    r'|^\s*-?\s*(I{1,3}V?|IV|V|VI{0,3})\s*-?\s*$',
    re.IGNORECASE,
)
# A line made up of nothing but stray punctuation/symbols (extraction
# artifacts) -- not a real title line.
SYMBOL_ONLY_RE = re.compile(r'^[\\/*.,;:!?\-–—\s]+$')


def _is_chord_only(line_stripped: str) -> bool:
    """True if every meaningful token in a line is a guitar-chord symbol.

    Tokens that are pure separators/repeat counts ("x2", dashes) are ignored.
    Requiring ALL meaningful tokens to be chords (rather than a majority
    threshold) avoids misreading a lyric line -- e.g. a two-word chorus hook
    -- as a chord line and ending a multi-line title early.
    """
    meaningful = []
    for tok in line_stripped.split():
        core = tok.strip("(),.*")
        if core in ("-", "–", "—") or re.match(r'^\d?x$|^x\d$', core, re.IGNORECASE):
            continue
        meaningful.append(core)
    return bool(meaningful) and all(CHORD_WORD_RE.match(c) for c in meaningful)


def is_chord_line(line: str) -> bool:
    """True if a line is a guitar-chord line. Kept distinct from section
    markers so callers can strip chords while keeping CHORUS/VERSE labels."""
    stripped = line.strip()
    if not stripped:
        return False
    if SECTION_MARKER_RE.match(stripped):
        return False
    return _is_chord_only(stripped)


def is_chord_or_marker_line(line: str) -> bool:
    """True if a line looks like a guitar-chord line or a section marker
    (CHORUS/VERSE/roman numeral/etc), rather than title/lyric text --
    used to know where a multi-line title block ends."""
    stripped = line.strip()
    if not stripped:
        return False
    if SECTION_MARKER_RE.match(stripped):
        return True
    return _is_chord_only(stripped)


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


# For bodies we drop credit/reprint/page-number lines but keep blank lines
# (verse separation). We deliberately exclude the broad "bld" keyword from
# SKIP_KEYWORDS here so a lyric line that merely mentions "BLD" isn't lost.
BODY_SKIP_KEYWORDS = tuple(k for k in SKIP_KEYWORDS if k != "bld")


def is_body_skip_line(line: str) -> bool:
    """True if a non-blank body line is stray credit/reprint/page-number
    text that should be removed (blank lines are kept for verse layout)."""
    stripped = line.strip()
    if not stripped:
        return False  # keep blank line
    if PAGE_NUM_RE.match(stripped):
        return True
    if SYMBOL_ONLY_RE.match(stripped):
        return True
    lowered = stripped.lower()
    return any(kw in lowered for kw in BODY_SKIP_KEYWORDS)


def _is_chord_token(tok: str) -> bool:
    """True if a single extracted word is a guitar-chord symbol."""
    return _is_chord_only(tok)


def _group_words_into_lines(
    words: Sequence[Tuple[float, float, float, float, str, ...]],
    tol: float = 2.0,
) -> List[List[Tuple[float, float, float, float, str, ...]]]:
    """Group PyMuPDF words (x0,y0,x1,y1,text,...) into visual lines by y."""
    ws = sorted(words, key=lambda w: (w[1], w[0]))
    lines = []
    for w in ws:
        y = w[1]
        if lines and abs(y - lines[-1][0]) <= tol:
            lines[-1][1].append(w)
        else:
            lines.append([y, [w]])
    return lines


def _split_columns(
    words: List[Tuple[float, float, float, float, str, ...]],
    gap_threshold: float = 60.0,
) -> List[List[Tuple[float, float, float, float, str, ...]]]:
    """Split a page's words into left/right columns on a large horizontal gap."""
    if not words:
        return [words]
    xs = sorted(w[0] for w in words)
    gaps = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
    if not gaps:
        return [words]
    gi = max(range(len(gaps)), key=lambda i: gaps[i])
    if gaps[gi] < gap_threshold:
        return [words]
    cut = (xs[gi] + xs[gi + 1]) / 2
    return [
        [w for w in words if w[0] < cut],
        [w for w in words if w[0] >= cut],
    ]


def extract_text_pymupdf(pdf_path: str) -> str:
    """Extract layout-aware text with PyMuPDF.

    Words are grouped into horizontal bands; bands consisting entirely of
    guitar-chord symbols (the chord line hovering above a lyric line) are
    dropped, leaving only lyric/section text. A blank line is inserted where
    vertical spacing indicates a gap (verse/page separation).
    """
    import pymupdf

    out = []
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            words = [w for w in page.get_text("words") if w[4].strip()]
            if not words:
                continue
            for col in _split_columns(words):
                lines = [
                    (y, sorted(ws, key=lambda w: w[0]))
                    for y, ws in _group_words_into_lines(col)
                ]
                ys = [y for y, _ in lines]
                gaps = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
                med = sorted(gaps)[len(gaps) // 2] if gaps else 13.0
                if med <= 0:
                    med = 13.0
                prev = None
                for y, ws in lines:
                    if prev is not None and (y - prev) > max(1.6 * med, 20):
                        out.append("")  # vertical gap -> blank line
                    toks = [w[4] for w in ws]
                    if toks and all(_is_chord_token(t) for t in toks):
                        prev = y
                        continue  # chord band -> drop it
                    out.append(" ".join(toks))
                    prev = y
            out.append("")  # page separator
    return "\n".join(out)


def pdf_to_text(pdf_path: str) -> str:
    """Extract text from a PDF, preferring layout-aware PyMuPDF extraction
    and falling back to `pdftotext -layout` (poppler-utils) if PyMuPDF is
    not installed or fails."""
    try:
        return extract_text_pymupdf(pdf_path)
    except Exception as exc:
        print(
            f"PyMuPDF extraction failed ({type(exc).__name__}: {exc}); "
            "falling back to pdftotext.",
            file=sys.stderr,
        )

    if not shutil.which("pdftotext"):
        print(
            "Could not extract text: neither PyMuPDF nor pdftotext "
            "(poppler-utils) is available.\n"
            "Install one with:  pip install pymupdf\n"
            "   or (macOS):     brew install poppler\n"
            "   or (Debian):    sudo apt install poppler-utils",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", pdf_path, "-"],
            capture_output=True, text=True, check=True, timeout=60,
        )
        return result.stdout
    except Exception as exc:
        print(
            f"pdftotext failed ({type(exc).__name__}: {exc}); "
            "cannot extract text.",
            file=sys.stderr,
        )
        sys.exit(1)


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


FRONT_MATTER_KEYWORDS = (
    "contents", "table of contents", "introduction", "foreword",
    "index", "songbook", "title page", "copyright",
)
# NOTE: "songbook" is intentionally broad because the book's own title page
# contains it; the tradeoff is that a real song titled "Songbook" would be
# dropped. For this specific PDF the tradeoff is acceptable.


def looks_like_front_matter(title: str) -> bool:
    """Heuristic: does this segment's first line look like a cover/contents
    page rather than a song title? Used to skip junk front matter that
    appears before the first footer.

    We require an actual front-matter keyword rather than any long string,
    so a legitimate (and possibly long) first-song title is never dropped.
    """
    low = title.lower()
    return any(kw in low for kw in FRONT_MATTER_KEYWORDS)


def split_into_songs(full_text: str):
    """Split the extracted PDF text into per-song dicts.

    Returns (songs, warnings): songs is a list of {"title", "body"} in
    document order (guitar-chord lines stripped from the body); warnings is
    a list of human-readable notes (skipped front matter, etc.).
    """
    # Form feeds ('\x0c') are page-break artifacts from pdftotext; strip them
    # up front so they can't leak into titles/bodies or count as text.
    full_text = full_text.replace("\x0c", "")

    warnings = []

    # Split on the footer marker. segments[0] = text before the first footer
    # (front matter or song 1's raw text). segments[i] for i>0 = leftover
    # page-number/blank lines followed by song (i+1)'s raw text.
    segments = FOOTER_RE.split(full_text)

    songs = []
    for seg_index, seg in enumerate(segments):
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
        # line, nor a section marker (CHORUS/VERSE/roman numeral/etc),
        # nor a stray credit/reprint/page-number line -- this lets
        # genuine two-line titles (e.g. "ALIVE, ALIVE, ALIVE" /
        # "FOREVERMORE") merge, while stopping before the song's chords
        # start or a separator/credit line intrudes.
        title_lines = [lines[idx].strip()]
        idx += 1
        while (
            idx < len(lines)
            and lines[idx].strip()
            and not is_chord_or_marker_line(lines[idx])
            and not is_skip_line(lines[idx])
        ):
            title_lines.append(lines[idx].strip())
            idx += 1
        # Skip a single trailing blank line right after the title, if present.
        if idx < len(lines) and not lines[idx].strip():
            idx += 1

        title = " ".join(title_lines)

        # Front matter (contents/title page) before the first footer would
        # otherwise look like a normal song; drop it and tell the user.
        if seg_index == 0 and looks_like_front_matter(title):
            warnings.append(
                f'Skipped leading segment that looks like front matter: "{title[:60]}"'
            )
            continue

        # Build the body: drop guitar-chord lines and stray credit / page
        # number / reprint lines (which can appear at the end of a song, not
        # just at a segment start), but keep blank lines (verse separation)
        # and section markers such as CHORUS/VERSE.
        body_lines = []
        for l in lines[idx:]:
            if is_chord_line(l):
                continue
            if is_body_skip_line(l):
                continue  # drop stray credit/page-number/reprint lines
            body_lines.append(l)
        body = "\n".join(body_lines).strip("\n")
        songs.append({"title": title, "body": body})

    return songs, warnings


def escape_rtf(text: str) -> str:
    out = []
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch == "{":
            out.append("\\{")
        elif ch == "}":
            out.append("\\}")
        elif ch == "\n":
            out.append("\\line")
        elif ch == "\r":
            pass  # normalize Windows CRLF
        elif ch == "\t":
            out.append("\\tab")
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
    ap.add_argument("--outdir", default=os.path.join(os.getcwd(), "songs"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="overwrite existing RTF files instead of refusing")
    args = ap.parse_args()

    if not os.path.isfile(args.pdf_path):
        print(f"File not found: {args.pdf_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Reading {args.pdf_path} ...")
    text = pdf_to_text(args.pdf_path)
    songs, warnings = split_into_songs(text)
    print(f"Detected {len(songs)} song(s).\n")

    for w in warnings:
        print(f"note: {w}")

    if args.dry_run:
        for i, song in enumerate(songs, start=1):
            preview_line = next((l for l in song["body"].split("\n") if l.strip()), "")
            print(f"{i:>4}. {song['title']!r}  preview: {preview_line.strip()[:60]!r}")
        print("\nDry run complete. No files written.")
        return

    os.makedirs(args.outdir, exist_ok=True)

    # Resolve all output paths up front so the overwrite guard checks the
    # exact files that will be written (with de-duplication applied).
    used_names = {}
    out_paths = []
    for song in songs:
        base = sanitize_filename(song["title"])
        if base == "Untitled":
            print(f"note: '{song['title'][:40]}' had no usable title; saved as 'Untitled'")
        base = dedupe_filename(base, used_names)
        out_paths.append(os.path.join(args.outdir, base + ".rtf"))

    if not args.force:
        conflicts = [p for p in out_paths if os.path.exists(p)]
        if conflicts:
            print(
                "The following RTF files already exist "
                "(re-run with --force to overwrite):\n"
                + "\n".join(f"  {p}" for p in conflicts),
                file=sys.stderr,
            )
            sys.exit(1)

    for song, out_path in zip(songs, out_paths):
        write_rtf(out_path, song["title"], song["body"])

    print(f"Wrote {len(songs)} RTF file(s) to {args.outdir}/")


if __name__ == "__main__":
    main()