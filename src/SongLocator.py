"""
Song Locator
A simple GUI to track the type of each song in your library.

Features:
- Add a single song (type optional -> defaults to "unset")
- Add multiple song titles at once (bulk paste, one per line, choose a type: PPTX, RTF, or TXT)
- Look up a song: exact match -> substring match -> fuzzy match (typo-tolerant)
- Data persisted as JSON in your home directory

Data format:
    { "song name": ["type1", "type2", ...] }
A song can exist in multiple formats (e.g. RTF and PPTX), so each entry
holds a list of types. The old single-string format is migrated on load.
"""

import json
import os
import difflib
import tempfile
import time
import tkinter as tk
from tkinter import messagebox

DB_FILE = os.path.expanduser("~/song_locations.json")
DEFAULT_TYPE = "unset"

# --- Dark theme ---
BG_COLOR = "#2b2b2b"
FG_COLOR = "white"
ENTRY_BG = "#3c3c3c"
BORDER_COLOR = "white"

# Tk fires <<Paste>> twice when Caps Lock is on; ignore duplicates within this window.
PASTE_DEBOUNCE_MS = 150


class PasteDebouncer:
    """Tracks paste timestamps to ignore duplicate <<Paste>> events.

    Tk fires <<Paste>> twice when Caps Lock is on. This debouncer ignores
    a second event that arrives within the debounce window.
    """

    def __init__(self, window_ms=PASTE_DEBOUNCE_MS):
        self.window_s = window_ms / 1000.0
        self._last = 0.0

    def is_duplicate(self, now=None):
        """Return True if this paste is a duplicate (within the window).

        Pass `now` (seconds) for deterministic testing.
        """
        if now is None:
            now = time.monotonic()
        if now - self._last < self.window_s:
            return True
        self._last = now
        return False


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def load_db():
    """Load the database, migrating old {name: type} format to {name: [types]}.

    Returns (db, warnings) where warnings is a list of human-readable notices
    about data repairs performed during load.
    """
    warnings = []

    if not os.path.exists(DB_FILE):
        return {}, warnings

    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        backup = DB_FILE + ".corrupt"
        try:
            os.replace(DB_FILE, backup)
        except OSError:
            pass
        warnings.append(
            f"Could not read {DB_FILE} ({e}). "
            f"It was moved to {backup} and a fresh database started."
        )
        return {}, warnings

    if not isinstance(data, dict):
        warnings.append(f"{DB_FILE} did not contain a valid song database. Starting fresh.")
        return {}, warnings

    # Migrate old format: {name: "type"} -> {name: ["type"]}
    for key, value in list(data.items()):
        if isinstance(value, str):
            data[key] = [value]
        elif not isinstance(value, list):
            data[key] = [DEFAULT_TYPE]

    # Repair keys where the song name was accidentally doubled (e.g. "abcabc").
    # Only consider names of at least 8 chars to avoid false positives on
    # short legitimate names like "mama".
    for key in list(data.keys()):
        if len(key) >= 8 and len(key) % 2 == 0:
            half = key[: len(key) // 2]
            if key == half * 2:
                if half in data:
                    for t in data[key]:
                        if t not in data[half]:
                            data[half].append(t)
                    del data[key]
                else:
                    data[half] = data[key]
                    del data[key]
                warnings.append(f'Fixed doubled song name: "{key}" -> "{half}"')

    return data, warnings


def save_db(db):
    """Atomically write the database to disk (temp file + rename)."""
    directory = os.path.dirname(DB_FILE) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2)
        os.replace(tmp_path, DB_FILE)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def reload_db():
    """Re-read the database from disk, discarding in-memory changes."""
    global db
    db, _ = load_db()


db, _startup_warnings = load_db()


# ---------------------------------------------------------------------------
# Core actions
# ---------------------------------------------------------------------------

def normalize_name(name):
    """Collapse internal whitespace and strip leading/trailing spaces."""
    return " ".join(name.split())


def format_types(types):
    return ", ".join(types)


def parse_types(raw):
    """Split a comma-separated type string into a cleaned list of types.

    Returns [] if the input is empty or contains only separators/whitespace.
    """
    return [t.strip() for t in raw.split(",") if t.strip()]


def _merge_types(existing, new_types):
    """Merge `new_types` into `existing` (a list), returning (added, skipped).

    The ``existing`` list is modified in place. Rules mirror ``add_song``:

    - A type already present is skipped.
    - "unset" is upgraded to a real type when one is added.
    - "unset" cannot be re-added to a song that already has real types.
    - A different real type is appended (a song can exist in multiple formats).
    """
    added = []
    skipped = []
    for song_type in new_types:
        if song_type in existing:
            skipped.append(song_type)
        elif DEFAULT_TYPE in existing and song_type != DEFAULT_TYPE:
            # Upgrade an "unset" entry to the newly entered type.
            existing.remove(DEFAULT_TYPE)
            existing.append(song_type)
            added.append(song_type)
        elif song_type == DEFAULT_TYPE:
            # Trying to add "unset" to a song that already has real types.
            skipped.append(song_type)
        else:
            # A different type - keep both (a song can exist in multiple formats).
            existing.append(song_type)
            added.append(song_type)
    return added, skipped


def add_song():
    name = normalize_name(name_entry.get())
    new_types = parse_types(type_entry.get())

    if not name:
        messagebox.showwarning("Missing info", "Enter a song name.")
        return

    if not new_types:
        new_types = [DEFAULT_TYPE]

    reload_db()
    key = name.lower()

    if key not in db:
        db[key] = list(new_types)
        message = f"Added: {name} -> {format_types(db[key])}"
    else:
        added, skipped = _merge_types(db[key], new_types)

        if added and skipped:
            message = f'Added {format_types(added)} to "{name}". Skipped: {format_types(skipped)}. Types: {format_types(db[key])}'
        elif added:
            message = f'Added {format_types(added)} to "{name}". Types: {format_types(db[key])}'
        elif skipped:
            message = f'"{name}" already has: {format_types(db[key])}'
        else:
            message = f'"{name}" unchanged. Types: {format_types(db[key])}'

    try:
        save_db(db)
    except OSError as e:
        messagebox.showerror("Save failed", f"Could not save database:\n{e}")
        return

    result_label.config(text=message)
    name_entry.delete(0, tk.END)
    type_entry.delete(0, tk.END)


def add_bulk_titles():
    raw_text = bulk_text.get("1.0", tk.END).strip()
    if not raw_text:
        return

    new_type = bulk_type_var.get()

    reload_db()
    lines = [normalize_name(line) for line in raw_text.splitlines() if line.strip()]
    added = []
    skipped = []

    for name in lines:
        key = name.lower()
        if key not in db:
            db[key] = [new_type]
            added.append(name)
        else:
            _added, _skipped = _merge_types(db[key], [new_type])
            if _added:
                added.append(name)
            else:
                skipped.append(name)

    try:
        save_db(db)
    except OSError as e:
        messagebox.showerror("Save failed", f"Could not save database:\n{e}")
        return

    bulk_text.delete("1.0", tk.END)

    summary = f"Added {len(added)} song(s) as {new_type}."
    if skipped:
        summary += f" Skipped {len(skipped)} already have {new_type}: {', '.join(skipped)}"
    result_label.config(text=summary)


def lookup_song():
    query = lookup_entry.get().strip().lower()
    if not query:
        result_label.config(text="Enter a song name to search.")
        return

    reload_db()

    # 1. Exact match
    if query in db:
        result_label.config(text=f'Found: "{query}" -> {format_types(db[query])}')
        return

    # 2. Substring match - query appears anywhere in a stored song name
    substring_matches = [key for key in db if query in key]
    if substring_matches:
        if len(substring_matches) == 1:
            best = substring_matches[0]
            result_label.config(text=f'Found: "{best}" -> {format_types(db[best])}')
        else:
            lines = [f'- "{m}" -> {format_types(db[m])}' for m in substring_matches]
            result_label.config(text="Multiple matches contain that:\n" + "\n".join(lines))
        return

    # 3. Fuzzy match - fallback for typos / near-misses
    fuzzy_matches = difflib.get_close_matches(query, db.keys(), n=3, cutoff=0.6)
    if not fuzzy_matches:
        result_label.config(text=f"Not found: '{lookup_entry.get()}'")
    elif len(fuzzy_matches) == 1:
        best = fuzzy_matches[0]
        result_label.config(text=f'Closest match "{best}" -> {format_types(db[best])}')
    else:
        lines = [f'- "{m}" -> {format_types(db[m])}' for m in fuzzy_matches]
        result_label.config(text="Multiple close matches:\n" + "\n".join(lines))


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

root = tk.Tk()
root.title("Song Locator")
root.geometry("440x620")
root.configure(bg=BG_COLOR)


def make_label(parent, text="", **kwargs):
    kwargs.setdefault("bg", BG_COLOR)
    kwargs.setdefault("fg", FG_COLOR)
    return tk.Label(parent, text=text, **kwargs)


def make_entry(parent, width=40):
    return tk.Entry(
        parent, width=width,
        bg=ENTRY_BG, fg=FG_COLOR,
        insertbackground=FG_COLOR,
        highlightbackground=BORDER_COLOR,
        highlightcolor=BORDER_COLOR,
        highlightthickness=1,
    )


def make_button(parent, text, command):
    return tk.Button(
        parent, text=text, command=command,
        fg=ENTRY_BG, bg=FG_COLOR,
        activebackground=ENTRY_BG, activeforeground=FG_COLOR,
        highlightbackground=BORDER_COLOR, highlightthickness=1,
    )


def install_debounced_paste(widget):
    """Replace the default paste with a debounced handler.

    Tk has a known quirk where <<Paste>> fires twice when Caps Lock is on,
    which caused song names to be doubled in the database. This handler
    ignores a second paste event that arrives within PASTE_DEBOUNCE_MS and
    performs the insert itself.
    """
    debouncer = PasteDebouncer()

    def on_paste(event):
        if debouncer.is_duplicate():
            return "break"  # duplicate paste event - ignore

        try:
            text = event.widget.clipboard_get()
        except tk.TclError:
            return "break"  # clipboard empty or unavailable

        w = event.widget
        # Replace any current selection.
        try:
            w.delete("sel.first", "sel.last")
        except tk.TclError:
            pass

        if isinstance(w, tk.Text):
            w.insert("insert", text)
        else:
            w.insert(tk.INSERT, text)

        return "break"  # prevent the default paste behavior

    widget.bind("<<Paste>>", on_paste)


# --- Add a single song ---
make_label(root, text="Add a song", font=("Helvetica", 12, "bold")).pack(pady=(10, 0))

make_label(root, text="Song name:").pack()
name_entry = make_entry(root)
install_debounced_paste(name_entry)
name_entry.pack()

make_label(root, text="Type (optional, comma-separated):").pack()
type_entry = make_entry(root)
install_debounced_paste(type_entry)
type_entry.pack()

make_button(root, "Add", add_song).pack(pady=5)

# --- Add multiple titles at once ---
make_label(root, text="Add multiple titles (one per line)",
           font=("Helvetica", 12, "bold")).pack(pady=(15, 0))

make_label(root, text="File type:").pack()
bulk_type_choices = ["PPTX", "RTF", "TXT"]
bulk_type_var = tk.StringVar(value=bulk_type_choices[0])
bulk_type_menu = tk.OptionMenu(root, bulk_type_var, *bulk_type_choices)
bulk_type_menu.config(
    bg=ENTRY_BG, fg=FG_COLOR,
    activebackground=ENTRY_BG, activeforeground=FG_COLOR,
    highlightbackground=BORDER_COLOR, highlightcolor=BORDER_COLOR,
    highlightthickness=1,
    anchor="w", width=18,
)
bulk_type_menu["menu"].config(
    bg=ENTRY_BG, fg=FG_COLOR,
    activebackground=FG_COLOR, activeforeground=ENTRY_BG,
)
bulk_type_menu.pack()

bulk_text = tk.Text(
    root, width=40, height=6,
    bg=ENTRY_BG, fg=FG_COLOR,
    insertbackground=FG_COLOR,
    highlightbackground=BORDER_COLOR,
    highlightcolor=BORDER_COLOR,
    highlightthickness=1,
)
install_debounced_paste(bulk_text)
bulk_text.pack()
make_button(root, "Add All", add_bulk_titles).pack(pady=5)

# --- Look up a song ---
make_label(root, text="Look up a song", font=("Helvetica", 12, "bold")).pack(pady=(15, 0))
lookup_entry = make_entry(root)
install_debounced_paste(lookup_entry)
lookup_entry.pack()
make_button(root, "Search", lookup_song).pack(pady=5)

result_label = tk.Label(
    root, text="", wraplength=400, fg=FG_COLOR, bg=BG_COLOR,
    justify="left", padx=8, pady=8,
    highlightbackground=BORDER_COLOR, highlightthickness=1,
)
result_label.pack(pady=10, fill="x", padx=10)

# Show any data-repair notices from the startup load.
for w in _startup_warnings:
    messagebox.showwarning("Data notice", w)

root.mainloop()