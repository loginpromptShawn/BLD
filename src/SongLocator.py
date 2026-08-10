"""
Song Locator
A simple GUI to track the type of each song in your library.

Features:
- Add a single song (type optional -> defaults to "unset")
- Add multiple song titles at once (bulk paste, one per line, no type needed)
- Look up a song: exact match -> substring match -> fuzzy match (typo-tolerant)
- Data persisted as JSON in your home directory
"""

import json
import os
import difflib
import tkinter as tk
from tkinter import messagebox

DB_FILE = os.path.expanduser("~/song_locations.json")
DEFAULT_TYPE = "unset"

RESULT_FG = "white"
RESULT_BG = "#2b2b2b"  # dark background so white text stays readable


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return {}


def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)


db = load_db()


# ---------------------------------------------------------------------------
# Core actions
# ---------------------------------------------------------------------------

def add_song():
    name = name_entry.get().strip()
    song_type = type_entry.get().strip()

    if not name:
        messagebox.showwarning("Missing info", "Enter a song name.")
        return

    if not song_type:
        song_type = DEFAULT_TYPE

    db[name.lower()] = song_type
    save_db(db)
    result_label.config(text=f"Added: {name} -> {song_type}")
    name_entry.delete(0, tk.END)
    type_entry.delete(0, tk.END)


def add_bulk_titles():
    raw_text = bulk_text.get("1.0", tk.END).strip()
    if not raw_text:
        return

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    added = []
    skipped = []

    for name in lines:
        key = name.lower()
        if key in db:
            skipped.append(name)
            continue
        db[key] = DEFAULT_TYPE
        added.append(name)

    save_db(db)
    bulk_text.delete("1.0", tk.END)

    summary = f"Added {len(added)} song(s)."
    if skipped:
        summary += f" Skipped {len(skipped)} already in library."
    result_label.config(text=summary)


def lookup_song():
    query = lookup_entry.get().strip().lower()
    if not query:
        return

    # 1. Exact match
    if query in db:
        result_label.config(text=f"Found: {db[query]}")
        return

    # 2. Substring match - query appears anywhere in a stored song name
    substring_matches = [key for key in db if query in key]
    if substring_matches:
        if len(substring_matches) == 1:
            best = substring_matches[0]
            result_label.config(text=f'Found: "{best}": {db[best]}')
        else:
            lines = [f'- "{m}" -> {db[m]}' for m in substring_matches]
            result_label.config(text="Multiple matches contain that:\n" + "\n".join(lines))
        return

    # 3. Fuzzy match - fallback for typos / near-misses
    fuzzy_matches = difflib.get_close_matches(query, db.keys(), n=3, cutoff=0.5)
    if not fuzzy_matches:
        result_label.config(text=f"Not found: '{lookup_entry.get()}'")
    elif len(fuzzy_matches) == 1:
        best = fuzzy_matches[0]
        result_label.config(text=f'Closest match "{best}": {db[best]}')
    else:
        lines = [f'- "{m}" -> {db[m]}' for m in fuzzy_matches]
        result_label.config(text="Multiple close matches:\n" + "\n".join(lines))


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

root = tk.Tk()
root.title("Song Locator")
root.geometry("440x560")

# --- Add a single song ---
tk.Label(root, text="Add a song", font=("Helvetica", 12, "bold")).pack(pady=(10, 0))

tk.Label(root, text="Song name:").pack()
name_entry = tk.Entry(root, width=40)
name_entry.pack()

tk.Label(root, text="Type (optional):").pack()
type_entry = tk.Entry(root, width=40)
type_entry.pack()

tk.Button(root, text="Add", command=add_song).pack(pady=5)

# --- Add multiple titles at once ---
tk.Label(root, text="Add multiple titles (one per line, no type)",
         font=("Helvetica", 12, "bold")).pack(pady=(15, 0))
bulk_text = tk.Text(root, width=40, height=6)
bulk_text.pack()
tk.Button(root, text="Add All", command=add_bulk_titles).pack(pady=5)

# --- Look up a song ---
tk.Label(root, text="Look up a song", font=("Helvetica", 12, "bold")).pack(pady=(15, 0))
lookup_entry = tk.Entry(root, width=40)
lookup_entry.pack()
tk.Button(root, text="Search", command=lookup_song).pack(pady=5)

result_label = tk.Label(
    root, text="", wraplength=400, fg=RESULT_FG, bg=RESULT_BG,
    justify="left", padx=8, pady=8
)
result_label.pack(pady=10, fill="x", padx=10)

root.mainloop()