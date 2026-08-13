"""
Tests for SongLocator.py core logic (migration, repair, duplicate handling).

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


# --- Test 1: normalize_name ---
print("Test normalize_name:")
check("strips and collapses whitespace", normalize_name("  hello   world  ") == "hello world")
check("single word unchanged", normalize_name("hello") == "hello")

# --- Test 2: load_db on missing file ---
print("Test load_db missing file:")
db, warnings = load_db()
check("returns empty dict", db == {})
check("no warnings", warnings == [])

# --- Test 3: migration of old {name: type} format ---
print("Test migration old format:")
with open(test_db, "w", encoding="utf-8") as f:
    json.dump({"song one": "RTF", "song two": "PPTX"}, f)
db, warnings = load_db()
check("string migrated to list", db["song one"] == ["RTF"])
check("second migrated", db["song two"] == ["PPTX"])
check("no warnings for clean migration", warnings == [])

# --- Test 4: doubled-name repair ---
print("Test doubled-name repair:")
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

# --- Test 5: doubled name merging with existing entry ---
print("Test doubled-name merge:")
with open(test_db, "w", encoding="utf-8") as f:
    json.dump({
        "holy forever": "PPTX",
        "holy foreverholy forever": "RTF",
    }, f)
db, warnings = load_db()
check("merged into existing", db["holy forever"] == ["PPTX", "RTF"])
check("doubled key removed", "holy foreverholy forever" not in db)

# --- Test 6: corrupt JSON handling ---
print("Test corrupt JSON:")
with open(test_db, "w", encoding="utf-8") as f:
    f.write("{ this is not valid json")
db, warnings = load_db()
check("returns empty dict on corrupt", db == {})
check("corrupt warning emitted", any("Could not read" in w for w in warnings))
check("corrupt file moved to backup", os.path.exists(test_db + ".corrupt"))

# --- Test 7: non-dict JSON ---
print("Test non-dict JSON:")
with open(test_db, "w", encoding="utf-8") as f:
    json.dump(["not", "a", "dict"], f)
db, warnings = load_db()
check("returns empty dict for list", db == {})
check("non-dict warning emitted", any("valid song database" in w for w in warnings))

# --- Test 8: duplicate handling logic (simulating add_song) ---
print("Test duplicate handling:")
# Fresh db
db = {"song a": ["unset"], "song b": ["RTF"], "song c": ["RTF", "PPTX"]}

# Case: new song
key = "song new"
if key not in db:
    db[key] = ["unset"]
check("new song added as unset", db["song new"] == ["unset"])

# Case: existing with unset, add real type -> upgrade
key = "song a"
types = db[key]
if "RTF" in types:
    pass
elif "unset" in types:
    types.remove("unset")
    types.append("RTF")
check("unset upgraded to RTF", db["song a"] == ["RTF"])

# Case: existing with real type, add same type -> no change
key = "song b"
types = db[key]
if "RTF" in types:
    pass
check("same type no change", db["song b"] == ["RTF"])

# Case: existing with real type, add different type -> append (keep both)
key = "song b"
types = db[key]
if "PPTX" in types:
    pass
else:
    types.append("PPTX")
check("different type appended", db["song b"] == ["RTF", "PPTX"])

# Case: existing with real types, add unset -> no change
key = "song c"
types = db[key]
if "unset" in types:
    pass
check("unset not added to typed song", db["song c"] == ["RTF", "PPTX"])

# --- Test 9: save_db atomic write ---
print("Test save_db:")
save_db({"test": ["RTF"]})
with open(test_db, "r", encoding="utf-8") as f:
    saved = json.load(f)
check("save_db writes correctly", saved == {"test": ["RTF"]})
check("no temp files left", not [f for f in os.listdir(tmpdir) if f.endswith(".tmp")])

# --- Test 10: parse_types (comma-separated type input) ---
print("Test parse_types:")
check("single type", parse_types("RTF") == ["RTF"])
check("comma-separated types", parse_types("RTF, PPTX") == ["RTF", "PPTX"])
check("types with extra whitespace", parse_types("  RTF ,  PPTX  ") == ["RTF", "PPTX"])
check("empty string returns []", parse_types("") == [])
check("only commas returns []", parse_types(" , , ") == [])
check("mixed empty entries skipped", parse_types("RTF,,PPTX") == ["RTF", "PPTX"])

# --- Test 11: PasteDebouncer debounces duplicates but recovers ---
# Regression test for a units bug: the debounce window (150 ms) was being
# compared against time.monotonic() values in seconds, so 150 was treated
# as 150 *seconds* and every subsequent paste was ignored as a "duplicate".
print("Test PasteDebouncer:")
d = PasteDebouncer(window_ms=150)
check("window correctly converted to seconds", d.window_s == 0.15)
check("first paste accepted", d.is_duplicate(now=1.00) is False)
check("double-fire 50ms later ignored", d.is_duplicate(now=1.05) is True)
# Key regression: a paste that arrives after the debounce window has elapsed
# must be accepted again (it is NOT a duplicate of the earlier paste). With
# the buggy units, now=1.20 would still be within the mistaken 150-second
# window and pasting would silently stop working.
check("paste 200ms after first accepted again", d.is_duplicate(now=1.20) is False)
check("double-fire of recovered paste ignored", d.is_duplicate(now=1.25) is True)
check("paste long after previous accepted again", d.is_duplicate(now=2.00) is False)
check("empty window passes everything", PasteDebouncer(window_ms=0).is_duplicate(now=5.0) is False)

# --- Test 12: _merge_types (shared add-type logic) ---
# Exercises the upgrade/skip/append rules that both add_song and
# add_bulk_titles rely on when merging a type into an existing song entry.
print("Test _merge_types:")

# New song: type added, nothing skipped
existing = []
added, skipped = _merge_types(existing, ["PPTX"])
check("new type added", added == ["PPTX"] and skipped == [])

# Already has the type -> skip
existing = ["RTF"]
added, skipped = _merge_types(existing, ["RTF"])
check("same type skipped", added == [] and skipped == ["RTF"])
check("existing unchanged on skip", existing == ["RTF"])

# unset -> upgrade to a real type
existing = ["unset"]
added, skipped = _merge_types(existing, ["PPTX"])
check("unset upgraded", added == ["PPTX"] and skipped == [])
check("unset removed from existing", existing == ["PPTX"])

# different real type -> append both (song can have multiple formats)
existing = ["RTF"]
added, skipped = _merge_types(existing, ["PPTX"])
check("different type appended", added == ["PPTX"] and skipped == [])
check("both types kept", existing == ["RTF", "PPTX"])

# adding unset to an already-typed song -> skip
existing = ["RTF", "PPTX"]
added, skipped = _merge_types(existing, ["unset"])
check("unset not added to typed", added == [] and skipped == ["unset"])
check("typed song unchanged", existing == ["RTF", "PPTX"])

# mixed list: duplicates skipped, new types appended, unset skipped
existing = ["RTF"]
added, skipped = _merge_types(existing, ["RTF", "PPTX", "unset"])
check("mixed: PPTX added", added == ["PPTX"])
check("mixed: RTF and unset skipped", skipped == ["RTF", "unset"])
check("mixed: appended PPTX", existing == ["RTF", "PPTX"])

print(f"\n=== {passed} passed, {failed} failed ===")
sys.exit(1 if failed else 0)
