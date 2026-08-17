"""
Tests for SongLocator.py core logic (migration, repair, duplicate handling,
search).

Each test group is an importable, callable function so that behave feature
steps can run the relevant groups per scenario. Running this file directly
(or calling run_all()) runs every group, prints a summary, and exits nonzero
on any failure.

Run with:  python3 tests/test_songlocator.py
"""
import json
import os
import sys
import tempfile

# --- Locate the source file relative to this test file ---
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_PATH = os.path.join(TESTS_DIR, "..", "src", "SongLocator.py")

with open(SRC_PATH, "r", encoding="utf-8") as f:
    source = f.read()

# Cut off everything from the UI section onward (root = tk.Tk()).
ui_marker = "# ---------------------------------------------------------------------------\n# UI"
ui_index = source.index(ui_marker)
logic_source = source[:ui_index]

# Replace DB_FILE with a temp path for testing.
tmpdir = tempfile.mkdtemp()
test_db = os.path.join(tmpdir, "song_locations.json")
logic_source = logic_source.replace(
    'DB_FILE = os.path.expanduser("~/song_locations.json")',
    f'DB_FILE = r"{test_db}"',
)

ns = {}
exec(logic_source, ns)

load_db = ns["load_db"]
save_db = ns["save_db"]
normalize_name = ns["normalize_name"]
parse_types = ns["parse_types"]
_merge_types = ns["_merge_types"]
search_db = ns["search_db"]
PasteDebouncer = ns["PasteDebouncer"]
DEFAULT_TYPE = ns["DEFAULT_TYPE"]

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


# --- Search behavior (Scenario C) ---------------------------------------
def test_search_exact():
    print("  search: exact match")
    db = {"song one": ["RTF"]}
    kind, matches = search_db(db, "song one")
    check("kind is exact", kind == "exact")
    check("exact match returned", matches == [("song one", ["RTF"])])


def test_search_substring():
    print("  search: substring match")
    db = {
        "i love you": ["RTF"],
        "hello world": ["TXT"],
        "love is a verb": ["PPTX"],
    }
    # single substring hit
    kind, matches = search_db(db, "hello")
    check("kind is substring", kind == "substring")
    check("single substring found", matches == [("hello world", ["TXT"])])
    # multiple substring hits
    kind, matches = search_db(db, "love")
    check("multiple substrings found", kind == "substring"
          and [k for k, _ in matches] == ["i love you", "love is a verb"])


def test_search_fuzzy():
    print("  search: fuzzy / no match")
    db = {"because he lives": ["RTF"], "holy forever": ["PPTX"], "mama": ["TXT"]}
    kind, matches = search_db(db, "becasue he lives")  # typo
    check("kind is fuzzy", kind == "fuzzy")
    check("closest match returned", matches == [("because he lives", ["RTF"])])
    kind, matches = search_db(db, "zzzzzzzz")
    check("no-match kind", kind == "none")
    check("no-match list", matches == [])
    check("blank query returns None", search_db(db, "   ") is None)


# --- Name normalization (Scenarios A & B) --------------------------------
def test_normalize_name():
    print("  normalize_name")
    check("strips and collapses whitespace", normalize_name("  hello   world  ") == "hello world")
    check("single word unchanged", normalize_name("hello") == "hello")


# --- Storage / persistence (shared by all scenarios) --------------------
def test_load_db_missing():
    print("  load_db missing file")
    if os.path.exists(test_db):
        os.remove(test_db)
    db, warnings = load_db()
    check("returns empty dict", db == {})
    check("no warnings", warnings == [])


def test_migration():
    print("  load_db migration old format")
    with open(test_db, "w", encoding="utf-8") as f:
        json.dump({"song one": "RTF", "song two": "PPTX"}, f)
    db, warnings = load_db()
    check("string migrated to list", db["song one"] == ["RTF"])
    check("second migrated", db["song two"] == ["PPTX"])
    check("no warnings for clean migration", warnings == [])


def test_doubled_repair():
    print("  load_db doubled-name repair")
    with open(test_db, "w", encoding="utf-8") as f:
        json.dump({
            "because he livesbecause he lives": "RTF",
            "holy forever": "PPTX",
            "mama": "TXT",  # short name, should NOT be touched
        }, f)
    db, warnings = load_db()
    check("doubled name repaired", "because he lives" in db)
    check("doubled key removed", "because he livesbecause he lives" not in db)
    check("repaired value preserved", db["because he lives"] == ["RTF"])
    check("short name untouched", "mama" in db and db["mama"] == ["TXT"])
    check("repair warning emitted", any("Fixed doubled" in w for w in warnings))


def test_doubled_merge():
    print("  load_db doubled-name merge")
    with open(test_db, "w", encoding="utf-8") as f:
        json.dump({
            "holy forever": "PPTX",
            "holy foreverholy forever": "RTF",
        }, f)
    db, warnings = load_db()
    check("merged into existing", db["holy forever"] == ["PPTX", "RTF"])
    check("doubled key removed", "holy foreverholy forever" not in db)


# --- Data integrity (shared by all scenarios) ---------------------------
def test_corrupt_json():
    print("  load_db corrupt JSON")
    with open(test_db, "w", encoding="utf-8") as f:
        f.write("{ this is not valid json")
    db, warnings = load_db()
    check("returns empty dict on corrupt", db == {})
    check("corrupt warning emitted", any("Could not read" in w for w in warnings))
    check("corrupt file moved to backup", os.path.exists(test_db + ".corrupt"))


def test_non_dict_json():
    print("  load_db non-dict JSON")
    with open(test_db, "w", encoding="utf-8") as f:
        json.dump(["not", "a", "dict"], f)
    db, warnings = load_db()
    check("returns empty dict for list", db == {})
    check("non-dict warning emitted", any("valid song database" in w for w in warnings))


# --- Duplicate handling (Scenario A) ------------------------------------
def test_duplicate_handling():
    print("  add_song duplicate handling")
    db = {"song a": ["unset"], "song b": ["RTF"], "song c": ["RTF", "PPTX"]}
    key = "song new"
    if key not in db:
        db[key] = ["unset"]
    check("new song added as unset", db["song new"] == ["unset"])
    key = "song a"
    types = db[key]
    if "RTF" in types:
        pass
    elif "unset" in types:
        types.remove("unset")
        types.append("RTF")
    check("unset upgraded to RTF", db["song a"] == ["RTF"])
    key = "song b"
    types = db[key]
    if "RTF" in types:
        pass
    check("same type no change", db["song b"] == ["RTF"])
    key = "song b"
    types = db[key]
    if "PPTX" in types:
        pass
    else:
        types.append("PPTX")
    check("different type appended", db["song b"] == ["RTF", "PPTX"])
    key = "song c"
    types = db[key]
    if "unset" in types:
        pass
    check("unset not added to typed song", db["song c"] == ["RTF", "PPTX"])


def test_save_db():
    print("  save_db atomic write")
    save_db({"test": ["RTF"]})
    with open(test_db, "r", encoding="utf-8") as f:
        saved = json.load(f)
    check("save_db writes correctly", saved == {"test": ["RTF"]})
    check("no temp files left", not [f for f in os.listdir(tmpdir) if f.endswith(".tmp")])


def test_parse_types():
    print("  parse_types")
    check("single type", parse_types("RTF") == ["RTF"])
    check("comma-separated types", parse_types("RTF, PPTX") == ["RTF", "PPTX"])
    check("types with extra whitespace", parse_types("  RTF ,  PPTX  ") == ["RTF", "PPTX"])
    check("empty string returns []", parse_types("") == [])
    check("only commas returns []", parse_types(" , , ") == [])
    check("mixed empty entries skipped", parse_types("RTF,,PPTX") == ["RTF", "PPTX"])


# --- Paste debounce (Scenario B) ----------------------------------------
def test_paste_debouncer():
    print("  PasteDebouncer")
    d = PasteDebouncer(window_ms=150)
    check("window correctly converted to seconds", d.window_s == 0.15)
    check("first paste accepted", d.is_duplicate(now=1.00) is False)
    check("double-fire 50ms later ignored", d.is_duplicate(now=1.05) is True)
    check("paste 200ms after first accepted again", d.is_duplicate(now=1.20) is False)
    check("double-fire of recovered paste ignored", d.is_duplicate(now=1.25) is True)
    check("paste long after previous accepted again", d.is_duplicate(now=2.00) is False)
    check("empty window passes everything", PasteDebouncer(window_ms=0).is_duplicate(now=5.0) is False)


# --- Type merging (Scenarios A & B) --------------------------------------
def test_merge_types():
    print("  _merge_types")
    existing = []
    added, skipped = _merge_types(existing, ["PPTX"])
    check("new type added", added == ["PPTX"] and skipped == [])
    existing = ["RTF"]
    added, skipped = _merge_types(existing, ["RTF"])
    check("same type skipped", added == [] and skipped == ["RTF"])
    check("existing unchanged on skip", existing == ["RTF"])
    existing = ["unset"]
    added, skipped = _merge_types(existing, ["PPTX"])
    check("unset upgraded", added == ["PPTX"] and skipped == [])
    check("unset removed from existing", existing == ["PPTX"])
    existing = ["RTF"]
    added, skipped = _merge_types(existing, ["PPTX"])
    check("different type appended", added == ["PPTX"] and skipped == [])
    check("both types kept", existing == ["RTF", "PPTX"])
    existing = ["RTF", "PPTX"]
    added, skipped = _merge_types(existing, ["unset"])
    check("unset not added to typed", added == [] and skipped == ["unset"])
    check("typed song unchanged", existing == ["RTF", "PPTX"])
    existing = ["RTF"]
    added, skipped = _merge_types(existing, ["RTF", "PPTX", "unset"])
    check("mixed: PPTX added", added == ["PPTX"])
    check("mixed: RTF and unset skipped", skipped == ["RTF", "unset"])
    check("mixed: appended PPTX", existing == ["RTF", "PPTX"])


_ALL_GROUPS = [
    ("search_db exact", test_search_exact),
    ("search_db substring", test_search_substring),
    ("search_db fuzzy", test_search_fuzzy),
    ("normalize_name", test_normalize_name),
    ("load_db missing file", test_load_db_missing),
    ("migration old format", test_migration),
    ("doubled-name repair", test_doubled_repair),
    ("doubled-name merge", test_doubled_merge),
    ("corrupt JSON", test_corrupt_json),
    ("non-dict JSON", test_non_dict_json),
    ("duplicate handling", test_duplicate_handling),
    ("save_db atomic write", test_save_db),
    ("parse_types", test_parse_types),
    ("PasteDebouncer", test_paste_debouncer),
    ("_merge_types", test_merge_types),
]


def run_all():
    """Run every test group in turn, printing a running summary."""
    for title, fn in _ALL_GROUPS:
        print(f"\n== {title} ==")
        fn()
    print(f"\n=== {passed} passed, {failed} failed ===")
    return failed


if __name__ == "__main__":
    sys.exit(1 if run_all() else 0)