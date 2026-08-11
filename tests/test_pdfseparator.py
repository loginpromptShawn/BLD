"""
Tests for PDFSeparator.py core logic (song splitting, chord removal,
front-matter handling, output helpers) plus an end-to-end check against the
example songbook PDF in pdf/PRAISE1.pdf.

The end-to-end portion needs `poppler-utils` (pdftotext) on PATH; it is
skipped (not failed) when pdftotext or the example PDF is unavailable.

Run with:  python3 tests/test_pdfseparator.py
"""
import os
import re
import shutil
import sys
import tempfile

# --- Locate the source file relative to this test file ---
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS_DIR)

sys.path.insert(0, os.path.join(ROOT, "src"))
import PDFSeparator as P  # noqa: E402

passed = 0
failed = 0


def check(desc, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {desc}")
    else:
        failed += 1
        print(f"  FAIL: {desc}")


# --- Chord / marker line detection ---
print("Chord & section-marker detection:")
check("multi-chord line is chord", P.is_chord_line("G                C") is True)
check("single chord is chord", P.is_chord_line("D7") is True)
check("slash chord is chord", P.is_chord_line("C/G") is True)
check("plain lyric is not chord", P.is_chord_line("Amazing grace how sweet the sound") is False)
check("section marker is not a removable chord", P.is_chord_line("CHORUS") is False)
check("marker still ends a title block", P.is_chord_or_marker_line("VERSE") is True)
check("two-word hook is not a chord line", P.is_chord_line("Holy Forever") is False)

# --- Front matter heuristic ---
print("Front-matter heuristic:")
check("contents page detected", P.looks_like_front_matter("SONGBOOK CONTENTS") is True)
check("long paragraph detected", P.looks_like_front_matter(
    "some very long run of words that is clearly not a song title at all") is True)
check("normal song title not front matter", P.looks_like_front_matter("Amazing Grace") is False)

# --- Filename helpers ---
print("Filename helpers:")
check("sanitize strips illegal chars", P.sanitize_filename('A/B:C*D?') == "ABCD")
check("sanitize collapses spaces", P.sanitize_filename("  A   B  ") == "A B")
check("sanitize strips dots", P.sanitize_filename("A...") == "A")
check("sanitize falls back to Untitled", P.sanitize_filename("  ") == "Untitled")
u = {}
check("dedupe first use", P.dedupe_filename("A", u) == "A")
check("dedupe second use", P.dedupe_filename("A", u) == "A (2)")

# --- Splitting, chord removal, front-matter, form feeds ---
print("split_into_songs (synthetic):")
t1 = (
    "AMAZING GRACE\n"
    "G                C\n"
    "Amazing grace how sweet the sound\n"
    "D7               G\n"
    "That saved a wretch like me.\n"
    "\n"
    "CHORUS\n"
    "C                G\n"
    "I once was lost but now am found\n"
    "\n"
    "+ BLD Newark +\n"
    "REPRINT MAR'97\n"
    "001 / DISC 1\n"
    "\n"
    "HOLY FOREVER\n"
    "Ab               Eb\n"
    "Holy holy holy\n"
    "G                C\n"
    "the angels sing.\n"
    "\n"
    "+ BLD Nwark +\n"
    "002 / DISC 2\n"
)
songs, warn = P.split_into_songs(t1)
check("two songs detected", len(songs) == 2)
check("song 1 title", songs[0]["title"] == "AMAZING GRACE")
check("song 2 title", songs[1]["title"] == "HOLY FOREVER")
check("chords stripped from song 1", "G                C" not in songs[0]["body"]
     and "D7" not in songs[0]["body"])
check("lyrics kept in song 1", "Amazing grace how sweet the sound" in songs[0]["body"])
check("section marker kept", "CHORUS" in songs[0]["body"])
check("footer/credit lines stripped", "REPRINT" not in songs[0]["body"]
     and "001 / DISC 1" not in songs[0]["body"])
check("no chords in song 2 body", "G                C" not in songs[1]["body"]
     and "Ab" not in songs[1]["body"])
check("no front-matter warning for normal doc", warn == [])

t2 = (
    "TEST SONG\n"
    "G  C\n"
    "Some lyrics + BLD Newark + more text here.\n"
    "D7\n"
    "End line.\n"
    "\n"
    "+ BLD Newark +\n"
    "003 / DISC 1\n"
    "\n"
    "NEXT SONG\n"
    "C\n"
    "Just a word.\n"
)
s2, _ = P.split_into_songs(t2)
check("anchored footer still yields two songs", len(s2) == 2)
check("mid-line footer mention did not split", "Some lyrics + BLD Newark + more text here." in s2[0]["body"])

t3 = (
    "BLD\n"
    "SONGBOOK\n"
    "CONTENTS\n"
    "1. Amazing Grace\n"
    "2. Holy Forever\n"
    "\n"
    "+ BLD Newark +\n"
    "001 / DISC 1\n"
    "\n"
    "HOLY FOREVER\n"
    "Ab  Eb\n"
    "Holy holy holy\n"
)
s3, w3 = P.split_into_songs(t3)
check("front matter dropped", len(s3) == 1 and s3[0]["title"] == "HOLY FOREVER")
check("front-matter warning emitted", any("front matter" in w for w in w3))

t4 = "GOOD SONG\n\x0cG  C\nLyrics here.\n\n+ BLD Newark +\n"
s4, _ = P.split_into_songs(t4)
check("form feed stripped, clean title", len(s4) == 1 and s4[0]["title"] == "GOOD SONG")

t5 = (
    "MAY THE WORDS\n"
    "G  C\n"
    "May the words of my mouth\n"
    "\n"
    "Reprinted by BLD Newark with permission\n"
    "REPRINT JULY'97\n"
    "\n"
    "+ BLD Newark +\n"
    "004 / DISC 1\n"
    "\n"
    "NEXT SONG\n"
    "D\n"
    "Just a word.\n"
)
s5, _ = P.split_into_songs(t5)
check("trailing credit lines stripped from body", "Reprinted by" not in s5[0]["body"]
     and "REPRINT JULY" not in s5[0]["body"])
check("lyric kept, credit gone", "May the words of my mouth" in s5[0]["body"])

# --- RTF / write helpers ---
print("RTF helpers:")
check("escape_rtf escapes braces/backslash", P.escape_rtf("a{b}\\c") == "a\\{b\\}\\\\c")
check("escape_rtf encodes non-ascii", P.escape_rtf("é") == "\\u233?")
tmpdir = tempfile.mkdtemp()
rtf_path = os.path.join(tmpdir, "x.rtf")
P.write_rtf(rtf_path, "A Song", "line1\nline2")
with open(rtf_path, "r", encoding="utf-8") as f:
    rtf = f.read()
check("rtf header present", rtf.startswith("{\\rtf1"))
check("rtf contains title", "A Song" in rtf)
check("rtf contains body lines", "line1" in rtf and "line2" in rtf)
os.remove(rtf_path)
os.rmdir(tmpdir)

# --- End-to-end against the real example PDF (needs pdftotext) ---
print("End-to-end against pdf/PRAISE1.pdf:")
pdf_path = os.path.join(ROOT, "pdf", "PRAISE1.pdf")
if not os.path.isfile(pdf_path):
    print("  SKIP: example PDF not found at pdf/PRAISE1.pdf")
elif shutil.which("pdftotext") is None:
    print("  SKIP: pdftotext (poppler-utils) not on PATH")
else:
    text = P.pdf_to_text(pdf_path)
    songs, warnings = P.split_into_songs(text)
    check("multiple songs detected", len(songs) > 10)
    for w in warnings:
        print(f"  note: {w}")
    # Every body must be non-empty, free of pure chord lines, and free of
    # the footer/credit footer text.
    all_bodies_good = True
    no_chords = True
    footer_gone = True
    for song in songs:
        if not song["body"].strip():
            all_bodies_good = False
        for ln in song["body"].split("\n"):
            if ln.strip() and P.is_chord_line(ln):
                no_chords = False
        low = song["body"].upper()
        if "BLD NEWARK" in low or "REPRINT" in low or re.search(r"\d+ / (DISC|PRAISE)", low):
            footer_gone = False
    check("every body has content", all_bodies_good)
    check("no chord-only lines remain in any body", no_chords)
    check("no footer/credit lines remain in any body", footer_gone)
    print(f"  (detected {len(songs)} songs from {os.path.basename(pdf_path)})")

print(f"\n=== {passed} passed, {failed} failed ===")
sys.exit(1 if failed else 0)