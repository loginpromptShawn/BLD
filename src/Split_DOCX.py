#!/usr/bin/env python3
"""Split a songs file into one file per song.

The file type is chosen by its extension:

  * .docx -> processDOCX()  (bold + upsized runs = titles; writes one .rtf
                              per song).  Requires the python-docx library.
  * .txt  -> processTXT()   (tabbed lines are titles, the rest are lyrics);
                              backup plan / fallback for text input.

Usage:
    python3 src/Split_DOCX.py [input_file] [output_dir]
"""

import os
import re
import sys
from pathlib import Path


def decode_text(raw):
    """Decode bytes for the TXT path.

    Tries UTF-8 first, then Windows-1252, then Latin-1 (which never raises,
    so it acts as a guaranteed last resort). Returns a str.
    """
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def split_songs(text):
    """Return a list of (title, [lyric lines ...]) tuples."""
    songs = []
    current_title = None
    current_lines = []

    for raw_line in text.splitlines():
        line = raw_line.strip("\r")
        if line.startswith("\t"):
            # A new song heading.
            if current_title is not None:
                songs.append((current_title, current_lines))
            current_title = line.lstrip("\t").strip()
            current_lines = []
        else:
            if current_title is not None:
                current_lines.append(line)

    if current_title is not None:
        songs.append((current_title, current_lines))

    return songs


def safe_filename(title):
    """Turn a song title into a filesystem-safe base name."""
    # Replace characters that are illegal/awkward in file names.
    name = re.sub(r'[\\/:*?"<>|]', "_", title)
    name = re.sub(r"\s+", " ", name).strip()
    return name or "untitled"


def unique_filename(base_stem, ext, used_names):
    """Return a non-colliding filename like ``base.ext`` or ``base (2).ext``.

    ``used_names`` maps a base stem to how many times it has been produced so
    far and is mutated in place across calls, so repeated calls with the same
    stem yield unique ``(2)``/``(3)``/... suffixed names.
    """
    count = used_names.get(base_stem, 0)
    used_names[base_stem] = count + 1
    return f"{base_stem}.{ext}" if count == 0 else f"{base_stem} ({count + 1}).{ext}"


# ---------------------------------------------------------------------------
# DOCX handling (processDOCX)
# ---------------------------------------------------------------------------

# If a title paragraph starts with one of these liturgical-role labels
# followed by a colon, strip the label off for the "clean" song name used
# in the output RTF and filename. The full original title line is still
# preserved as a comment inside the RTF in case you want it.
ROLE_PREFIX_RE = re.compile(
    r"^\s*(processional|entrance|gathering|offertory|communion|recessional|"
    r"closing|opening|gospel|responsorial)\s+song\s*\d*\s*:\s*",
    re.IGNORECASE,
)

MIN_TITLE_SIZE_PT = 13.0  # fallback threshold if we can't infer a "default" size


def slugify(text, max_len=80):
    """Keep spaces; only strip characters that are unsafe in filenames."""
    text = re.sub(r'[\\/:*?"<>|]', "", text).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:max_len].strip() or "untitled"


def clean_title(raw_title):
    return ROLE_PREFIX_RE.sub("", raw_title).strip()


def rtf_escape(text):
    """Escape text for safe inclusion in RTF, including non-ASCII chars."""
    out = []
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch == "{":
            out.append("\\{")
        elif ch == "}":
            out.append("\\}")
        elif ch == "\t":
            # Trailing space terminates the control word (a following letter
            # would otherwise become part of it); the space is not rendered.
            out.append(r"\tab ")
        elif ord(ch) > 127:
            out.append(f"\\u{ord(ch)}?")
        else:
            out.append(ch)
    return "".join(out)


def detect_default_size(doc):
    """
    Try to find the most common explicit run font size in the document,
    to use as the 'lyrics' baseline. Falls back to MIN_TITLE_SIZE_PT logic
    if no explicit sizes are found anywhere (i.e. everything inherits from
    the style/doc default).
    """
    from collections import Counter

    sizes = Counter()
    for p in doc.paragraphs:
        for r in p.runs:
            if r.font.size is not None:
                sizes[r.font.size.pt] += 1
    if not sizes:
        return MIN_TITLE_SIZE_PT
    # Most common explicit size is very likely the *title* size (lyrics
    # usually don't set an explicit size at all). Use the smallest explicit
    # size seen minus a hair, floored so it stays a sensible threshold.
    smallest_explicit = min(sizes)
    return max(smallest_explicit - 0.1, MIN_TITLE_SIZE_PT - 1)


def is_title_paragraph(p, size_threshold):
    """A new song title is a non-empty paragraph that is BOLD and UPSIZED.

    Rather than inspecting only the first run (titles are frequently split
    across several runs by Word), we require that *any* run is bold and the
    paragraph's *largest* explicit run size meets the threshold.
    """
    if not p.runs:
        return False
    if not any(r.bold for r in p.runs):
        return False

    run_sizes = [r.font.size.pt for r in p.runs if r.font.size is not None]
    if not run_sizes:
        return False  # bold but no explicit size (e.g. [Chorus]/Refrain)
    return max(run_sizes) >= size_threshold and p.text.strip() != ""


def split_into_songs(doc_path):
    """Return a list of song dicts parsed from a .docx file."""
    # Lazy import so the TXT path (and tests) don't require python-docx.
    from docx import Document

    doc = Document(doc_path)
    size_threshold = detect_default_size(doc)

    paragraphs = doc.paragraphs
    title_indices = [
        i for i, p in enumerate(paragraphs) if is_title_paragraph(p, size_threshold)
    ]

    if not title_indices:
        raise ValueError(
            "No title paragraphs detected (bold + upsized text). "
            "Check that titles are formatted as bold + larger font, "
            "or adjust MIN_TITLE_SIZE_PT / detection logic."
        )

    songs = []
    for idx, start in enumerate(title_indices):
        end = title_indices[idx + 1] if idx + 1 < len(title_indices) else len(paragraphs)
        raw_title = paragraphs[start].text.strip()

        body_lines = []
        for p in paragraphs[start + 1 : end]:
            text = p.text.rstrip()
            # Skip pure separator/divider lines (---- or ____ etc.)
            if re.fullmatch(r"[-_=]{5,}\s*", text.strip()):
                continue
            body_lines.append(text)

        # Trim leading/trailing blank lines
        while body_lines and body_lines[0].strip() == "":
            body_lines.pop(0)
        while body_lines and body_lines[-1].strip() == "":
            body_lines.pop()

        songs.append(
            {
                "raw_title": raw_title,
                "title": clean_title(raw_title),
                "body_lines": body_lines,
            }
        )

    return songs


def write_rtf(song, out_path):
    """Write a single song to an RTF file at out_path."""
    title = song["title"]
    body_lines = song["body_lines"]

    parts = []
    parts.append(r"{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0 Calibri;}}")
    parts.append(r"\f0")

    # Title: bold, larger (28 half-points = 14pt)
    parts.append(r"\pard\b\fs28 " + rtf_escape(title) + r"\b0\fs22\par")
    parts.append(r"\par")

    # Body: regular weight, smaller (22 half-points = 11pt)
    for line in body_lines:
        if line.strip() == "":
            parts.append(r"\par")
        else:
            parts.append(rtf_escape(line) + r"\par")

    parts.append("}")

    Path(out_path).write_text("\n".join(parts), encoding="utf-8")


def processTXT(input_path, output_dir):
    """Read a text file and split it into one file per song."""
    with open(input_path, "rb") as fh:
        raw = fh.read()

    text = decode_text(raw)
    songs = split_songs(text)

    if not songs:
        print("No songs found (no tabbed title lines).")
        return 1

    os.makedirs(output_dir, exist_ok=True)

    used_names = {}
    for title, lines in songs:
        content = title + "\n\n" + "\n".join(lines) + "\n"
        out_path = os.path.join(
            output_dir, unique_filename(safe_filename(title), "txt", used_names)
        )
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(content)
        print("Wrote: %s" % out_path)

    print("Split %d song(s) into %s" % (len(songs), output_dir))
    return 0


def processDOCX(input_path, output_dir):
    """Split a DOCX file into one .rtf file per song.

    Requires the python-docx library. Songs are identified by bold, upsized
    title paragraphs; output is written into output_dir.
    """
    try:
        # Confirm the dependency is available before doing real work.
        from docx import Document  # noqa: F401
    except ImportError:
        print("python-docx is required for DOCX input.")
        print("Install it with: pip install python-docx")
        return 1

    try:
        songs = split_into_songs(input_path)
    except ValueError as exc:
        print(str(exc))
        return 1
    except Exception as exc:  # e.g. corrupt/unreadable .docx
        print(f"Failed to read DOCX: {exc}")
        return 1

    if not songs:
        print("No songs detected in the DOCX.")
        return 1

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Detected {len(songs)} song(s):\n")
    used_names = {}
    for i, song in enumerate(songs, start=1):
        out_path = out_dir / unique_filename(slugify(song["title"]), "rtf", used_names)
        write_rtf(song, out_path)
        print(f"  {i:02d}. {song['title']!r}  ->  {out_path.name}  ({len(song['body_lines'])} lines)")
        if song["title"] != song["raw_title"]:
            print(f"       (original title line: {song['raw_title']!r})")

    print(f"\nDone. Files written to: {out_dir.resolve()}")
    return 0


def resolve_input_path(argv, script_dir):
    """Choose the input file.

    If an input was given on the command line, use it. Otherwise pick the
    first existing default in ``<repo root>`` -- DOCX (the primary input)
    first, then the TXT backup.
    """
    if argv:
        return argv[0]
    root = os.path.normpath(os.path.join(script_dir, ".."))
    for name in ("songs.docx", "songs.txt"):
        candidate = os.path.join(root, name)
        if os.path.isfile(candidate):
            return candidate
    return os.path.join(root, "songs.txt")


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_path = resolve_input_path(argv, script_dir)
    output_dir = argv[1] if len(argv) > 1 else os.path.join(script_dir, "output")

    if not os.path.isfile(input_path):
        print(f"Input file not found: {input_path}")
        return 1

    ext = os.path.splitext(input_path)[1].lower()
    if ext == ".docx":
        return processDOCX(input_path, output_dir)
    # Backup: treat anything else (e.g. .txt, no extension) as text.
    return processTXT(input_path, output_dir)


if __name__ == "__main__":
    sys.exit(main())

