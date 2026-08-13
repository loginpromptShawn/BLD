# Songs Splitter

Splits a file containing multiple songs into one output file per song.

The input type is chosen by extension:

* `.docx` → `processDOCX()` — **implemented**. Detects songs by **bold +
  upsized** title paragraphs (yielding linear reading order even in
  multi-column layouts) and writes one **`.rtf`** file per song into the
  output directory. Requires [`python-docx`](https://python-docx.readthedocs.io/)
  (`pip install python-docx`). Placeholder stand-ins like a bold (but not
  upsized) `[Chorus]` / `Refrain` are correctly *not* treated as titles.
* `.txt` → `processTXT()` — splits on **tabbed** title lines and writes one
  **`.txt`** file per song. Backup plan / fallback for text input.

## Rules (text files)

* A **song title** is any line that begins with a **tab** character.
* All following non-tabbed lines are that song's lyrics, until the next
  tabbed title line is reached.

## Usage

```sh
python3 src/Split_DOCX.py songs.docx outdir   # DOCX -> one .rtf per song
python3 src/Split_DOCX.py path/in.txt outdir  # text input (backup plan)
```

If no input argument is given, the tool looks in the project root and uses
`songs.docx` (primary input) if present, otherwise `songs.txt` (backup). Split
files are written into `src/output/` by default.

For DOCX input, song files are named after a "clean" title (a leading
liturgical label like `Processional Song:` is stripped), e.g.
`Sing A New Song Unto the Lord.rtf`.

## Tests

```sh
python3 -m unittest discover -s tests -v
```


