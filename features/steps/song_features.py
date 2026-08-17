"""
Step definitions for the behavior-level feature (song_features.feature).

Each Given/When/Then maps to one or more unit-test groups from
tests/test_songlocator.py, which has been refactored into importable,
callable functions. A step that runs a test group fails if that group
produced any failed check.
"""
import importlib.util
import os

from behave import given, when, then

TESTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "tests")
)
TEST_MOD_PATH = os.path.join(TESTS_DIR, "test_songlocator.py")


def _load_test_module():
    """Import tests/test_songlocator.py by file path (works without __init__)."""
    spec = importlib.util.spec_from_file_location("test_songlocator", TEST_MOD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_groups(module, names):
    """Run the named test groups, failing the step if any check fails."""
    for name in names:
        before = module.failed
        getattr(module, name)()
        if module.failed != before:
            raise AssertionError(
                f"Test group '{name}' produced {module.failed - before} failing check(s)."
            )


# --- Scenario A: add a single song --------------------------------------
@given("the song database is ready")
def step_database_ready(context):
    context.t = _load_test_module()
    _run_groups(context.t, [
        "test_load_db_missing",
        "test_migration",
        "test_doubled_repair",
        "test_doubled_merge",
        "test_corrupt_json",
        "test_non_dict_json",
        "test_save_db",
    ])


@when("I add a song title with its type")
def step_add_song(context):
    _run_groups(context.t, ["test_normalize_name", "test_parse_types", "test_merge_types"])


@then("the song is saved with that type")
def step_add_song_saved(context):
    _run_groups(context.t, ["test_merge_types", "test_save_db"])


@then("adding the same type again is a no-op")
def step_same_type_noop(context):
    _run_groups(context.t, ["test_merge_types"])


@then("a song without a type is stored as unset")
def step_no_type_unset(context):
    _run_groups(context.t, ["test_parse_types", "test_duplicate_handling"])


# --- Scenario B: add many titles ----------------------------------------
@when("I add many titles at once with a chosen type")
def step_add_bulk(context):
    _run_groups(context.t, ["test_normalize_name", "test_merge_types"])


@then("each new title is saved with that type")
def step_bulk_saved(context):
    _run_groups(context.t, ["test_merge_types", "test_save_db"])


@then("titles that already have that type are skipped")
def step_bulk_skipped(context):
    _run_groups(context.t, ["test_merge_types"])


@then("a doubled paste does not create a duplicate entry")
def step_doubled_paste(context):
    _run_groups(context.t, ["test_paste_debouncer"])


# --- Scenario C: search for a song --------------------------------------
@given("the song database contains known songs")
def step_db_has_songs(context):
    context.t = _load_test_module()
    _run_groups(context.t, [
        "test_load_db_missing",
        "test_migration",
        "test_doubled_repair",
        "test_save_db",
    ])


@when("I search for an exact title")
def step_search_exact(context):
    _run_groups(context.t, ["test_search_exact"])


@then("the exact match is found")
def step_exact_found(context):
    _run_groups(context.t, ["test_search_exact"])


@when("I search for a partial title")
def step_search_substring(context):
    _run_groups(context.t, ["test_search_substring"])


@then("matching songs are found")
def step_substring_found(context):
    _run_groups(context.t, ["test_search_substring"])


@when("I search for a title with a typo")
def step_search_fuzzy(context):
    _run_groups(context.t, ["test_search_fuzzy"])


@then("the closest match is returned")
def step_fuzzy_found(context):
    _run_groups(context.t, ["test_search_fuzzy"])