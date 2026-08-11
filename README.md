# BLD — Songbook PDF → per-song RTF converter

Extracts each song from a chord/lyrics songbook PDF and writes it as its own
Rich Text Format (`.rtf`) file. Guitar-chord lines are stripped from the
output, so each RTF contains only the song title, section labels
(`CHORUS` / `VERSE`, etc.) and the lyrics.

## Requirements

- Python 3
- [PyMuPDF](https://pymupdf.readthedocs.io/) (**recommended**) — layout-aware
  PDF text extraction. It reads word positions so the tool can drop the chord
  lines that hover above the lyrics, without relying on regex heuristics.
  Install with `pip install pymupdf`.
- Optional fallback: [poppler-utils](https://poppler.freedesktop.org/)
  (`pdftotext -layout`) is used automatically only if PyMuPDF is not installed.

  - macOS (Homebrew): `brew install poppler`
  - Debian/Ubuntu: `sudo apt install poppler-utils`

## Usage

```
python3 src/PDFSeparator.py <input.pdf> [--outdir <dir>] [--dry-run] [--force]
```

### Parameters

| Argument | Description |
| --- | --- |
| `input.pdf` | **Required.** Path to the songbook PDF to split. |
| `--outdir <dir>` | Output directory for the generated `.rtf` files. Defaults to `./songs`. |
| `--dry-run` | Preview the detected songs (titles + first lyric line) without writing any files. |
| `--force` | Overwrite existing `.rtf` files in the output directory. Without this flag the tool refuses to write if a file would be overwritten. |

### Examples

Preview the songs without writing anything:

```
python3 src/PDFSeparator.py pdf/PRAISE1.pdf --dry-run
```

Write all songs as RTF files into `./songs`:

```
python3 src/PDFSeparator.py pdf/PRAISE1.pdf
```

Write into a custom directory, allowing overwrites:

```
python3 src/PDFSeparator.py pdf/PRAISE1.pdf --outdir ~/Downloads/songs --force
```

## Output

One `.rtf` file per song, named after the song title (with illegal filename
characters removed; duplicate titles get a ` (2)`, ` (3)`, … suffix). Each file
contains the song title, section labels, and lyrics — with guitar-chord lines
and the book's footer/credit lines removed.

## How it detects song boundaries

The book ends every song with a recurring footer credit line (e.g.
`+ BLD Newark +`, `REPRINT MAR'97`, `001 / DISC 1`). The tool splits the text
on that footer marker (tolerating small spelling/spacing variants) and treats
the block between markers as one song. A leading cover/contents page is
skipped automatically.

## Chord removal

With PyMuPDF, words are grouped into the horizontal bands they were typeset
in. A band made entirely of guitar-chord symbols (the chord line that sits
above a lyric line) is dropped, so only lyrics and section labels survive.
This is position-aware rather than a post-hoc regex guess, so it holds up
across different layouts. The `pdftotext` fallback relies on the regex-based
chord-line detection instead.

## Tests

```
python3 tests/test_pdfseparator.py
```

Runs unit checks plus an end-to-end test against `pdf/PRAISE1.pdf` (skipped
if `pdftotext` or the example PDF is unavailable).