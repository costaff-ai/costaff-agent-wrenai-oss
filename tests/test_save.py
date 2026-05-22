"""Tests for tools.save — persistence of WrenAI outputs to shared folder.

Coverage goals:
- Path safety: bad filenames rejected with a clear error before any write.
- Roundtrip: written content is byte-identical readback.
- CSV serialisation: csv.DictWriter handles commas, quotes, embedded
  newlines, None values, and missing-key rows correctly.
- JSON serialisation: UTF-8 (Chinese chars) preserved; non-JSON-default
  types (date/decimal) flow through default=str; indent=0 = compact.
- Suffix enforcement: CSV requires .csv, JSON requires .json.
- Return shape: success returns path/bytes; error returns "error" only.
"""
from __future__ import annotations

import csv
import datetime
import io
import json

import pytest

from tools.save import (
    load_save_tools,
    wrenai_save_rows_as_csv,
    wrenai_save_rows_as_json,
    wrenai_save_to_shared,
)


# ----------------------------------------------------------- path safety

@pytest.mark.parametrize("bad", [
    "../etc/passwd",       # traversal
    "/abs/path.csv",       # absolute path
    "sub/dir/file.csv",    # nested
    "spaces not ok.csv",   # spaces
    "中文檔名.csv",         # non-ASCII
    "",                    # empty
    "with;semi.csv",       # punctuation outside [A-Za-z0-9._-]
    "trailing/",           # trailing slash
])
def test_save_to_shared_rejects_bad_filename(bad):
    r = wrenai_save_to_shared(bad, "x")
    assert "error" in r, f"should have rejected {bad!r}, got {r}"
    assert "[A-Za-z0-9._-]+" in r["error"]


def test_save_to_shared_rejects_none_content():
    r = wrenai_save_to_shared("ok.txt", None)
    assert "error" in r
    assert "None" in r["error"]


# --------------------------------------------------------- text roundtrip

def test_save_to_shared_writes_utf8_text(tmp_shared_root):
    payload = "hello 世界 ✓\nline2"
    r = wrenai_save_to_shared("note.txt", payload)
    assert "error" not in r
    assert r["path"].endswith("/costaff-agent-wrenai/note.txt")
    assert r["appended"] is False
    on_disk = (tmp_shared_root / "note.txt").read_text(encoding="utf-8")
    assert on_disk == payload
    assert r["bytes"] == len(payload.encode("utf-8"))


def test_save_to_shared_overwrite_default(tmp_shared_root):
    wrenai_save_to_shared("x.txt", "first")
    r2 = wrenai_save_to_shared("x.txt", "second")
    assert "error" not in r2
    assert (tmp_shared_root / "x.txt").read_text() == "second"
    assert r2["appended"] is False


def test_save_to_shared_append_mode(tmp_shared_root):
    wrenai_save_to_shared("log.txt", "line1\n")
    r2 = wrenai_save_to_shared("log.txt", "line2\n", append=True)
    assert r2["appended"] is True
    assert (tmp_shared_root / "log.txt").read_text() == "line1\nline2\n"


def test_save_to_shared_creates_dir_on_first_write(tmp_shared_root):
    assert not tmp_shared_root.exists()
    r = wrenai_save_to_shared("first.txt", "hi")
    assert "error" not in r
    assert tmp_shared_root.is_dir()


# --------------------------------------------------------- CSV serialisation

def test_save_rows_as_csv_basic(tmp_shared_root):
    rows = [
        {"state": "SP", "count": 41746},
        {"state": "RJ", "count": 12852},
    ]
    r = wrenai_save_rows_as_csv(rows, "states.csv")
    assert "error" not in r
    assert r["row_count"] == 2
    assert r["column_count"] == 2
    text = (tmp_shared_root / "states.csv").read_text()
    parsed = list(csv.DictReader(io.StringIO(text)))
    assert parsed == [
        {"state": "SP", "count": "41746"},
        {"state": "RJ", "count": "12852"},
    ]


def test_save_rows_as_csv_handles_quoting_and_commas(tmp_shared_root):
    """Commas, quotes, embedded newlines must NOT corrupt the CSV grid."""
    rows = [
        {"name": "Smith, John", "note": 'said "ok"', "addr": "line1\nline2"},
    ]
    r = wrenai_save_rows_as_csv(rows, "tricky.csv")
    assert "error" not in r
    parsed = list(csv.DictReader(io.StringIO((tmp_shared_root / "tricky.csv").read_text())))
    assert parsed == [{"name": "Smith, John", "note": 'said "ok"', "addr": "line1\nline2"}]


def test_save_rows_as_csv_none_becomes_empty_string(tmp_shared_root):
    rows = [{"a": 1, "b": None}, {"a": 2, "b": "x"}]
    wrenai_save_rows_as_csv(rows, "nulls.csv")
    text = (tmp_shared_root / "nulls.csv").read_text()
    # Verify the None row writes an empty value, not the literal "None".
    parsed = list(csv.DictReader(io.StringIO(text)))
    assert parsed[0]["b"] == ""
    assert parsed[1]["b"] == "x"


def test_save_rows_as_csv_columns_from_first_row(tmp_shared_root):
    """Columns are locked to first row's keys; extras in later rows drop."""
    rows = [
        {"a": 1, "b": 2},
        {"a": 3, "b": 4, "c": "ignored"},  # `c` should be dropped
    ]
    r = wrenai_save_rows_as_csv(rows, "fixed.csv")
    assert r["column_count"] == 2
    text = (tmp_shared_root / "fixed.csv").read_text()
    assert "c" not in text.splitlines()[0]
    assert "ignored" not in text


def test_save_rows_as_csv_missing_key_in_later_row(tmp_shared_root):
    """A key missing in a later row writes empty for that cell."""
    rows = [
        {"a": 1, "b": 2},
        {"a": 3},  # missing "b"
    ]
    wrenai_save_rows_as_csv(rows, "gappy.csv")
    parsed = list(csv.DictReader(io.StringIO((tmp_shared_root / "gappy.csv").read_text())))
    assert parsed[1]["b"] == ""


def test_save_rows_as_csv_rejects_empty():
    r = wrenai_save_rows_as_csv([], "x.csv")
    assert "error" in r
    assert "empty" in r["error"]


def test_save_rows_as_csv_requires_csv_suffix():
    r = wrenai_save_rows_as_csv([{"a": 1}], "no_suffix")
    assert "error" in r and ".csv" in r["error"]
    r2 = wrenai_save_rows_as_csv([{"a": 1}], "wrong.txt")
    assert "error" in r2


def test_save_rows_as_csv_accepts_upper_suffix(tmp_shared_root):
    """`.CSV` (uppercase) is fine — endswith check is case-insensitive."""
    r = wrenai_save_rows_as_csv([{"a": 1}], "shout.CSV")
    assert "error" not in r


# --------------------------------------------------------- JSON serialisation

def test_save_rows_as_json_basic(tmp_shared_root):
    rows = [{"state": "SP", "count": 41746}]
    r = wrenai_save_rows_as_json(rows, "states.json")
    assert "error" not in r
    assert r["row_count"] == 1
    parsed = json.loads((tmp_shared_root / "states.json").read_text())
    assert parsed == rows


def test_save_rows_as_json_preserves_chinese(tmp_shared_root):
    """ensure_ascii=False is critical — Chinese chars must stay as-is."""
    rows = [{"地區": "台北", "客戶數": 1234}]
    wrenai_save_rows_as_json(rows, "zh.json")
    raw = (tmp_shared_root / "zh.json").read_text(encoding="utf-8")
    assert "台北" in raw
    assert "\\u" not in raw  # not escaped


def test_save_rows_as_json_indent_zero_is_compact(tmp_shared_root):
    rows = [{"a": 1}, {"a": 2}]
    wrenai_save_rows_as_json(rows, "compact.json", indent=0)
    text = (tmp_shared_root / "compact.json").read_text()
    # Compact JSON is single-line; indented is multi-line.
    assert "\n" not in text.strip()


def test_save_rows_as_json_default_indent_2_is_pretty(tmp_shared_root):
    rows = [{"a": 1}, {"a": 2}]
    wrenai_save_rows_as_json(rows, "pretty.json")
    text = (tmp_shared_root / "pretty.json").read_text()
    assert "\n  " in text  # 2-space indent visible


def test_save_rows_as_json_non_serializable_via_default_str(tmp_shared_root):
    """date / Decimal / unknown types flow through default=str instead
    of raising — important because WrenAI rows often contain dates."""
    rows = [{"day": datetime.date(2026, 5, 22), "n": 1}]
    r = wrenai_save_rows_as_json(rows, "dated.json")
    assert "error" not in r
    parsed = json.loads((tmp_shared_root / "dated.json").read_text())
    assert parsed[0]["day"] == "2026-05-22"


def test_save_rows_as_json_rejects_empty():
    r = wrenai_save_rows_as_json([], "x.json")
    assert "error" in r
    assert "empty" in r["error"]


def test_save_rows_as_json_requires_json_suffix():
    r = wrenai_save_rows_as_json([{"a": 1}], "no_suffix")
    assert "error" in r and ".json" in r["error"]


# --------------------------------------------------------- return shape

def test_success_shape_text(tmp_shared_root):
    r = wrenai_save_to_shared("ok.txt", "hi")
    assert set(r.keys()) == {"path", "bytes", "appended"}
    assert isinstance(r["bytes"], int)


def test_success_shape_csv(tmp_shared_root):
    r = wrenai_save_rows_as_csv([{"a": 1}], "ok.csv")
    assert set(r.keys()) >= {"path", "bytes", "appended", "row_count", "column_count"}


def test_success_shape_json(tmp_shared_root):
    r = wrenai_save_rows_as_json([{"a": 1}], "ok.json")
    assert set(r.keys()) >= {"path", "bytes", "appended", "row_count"}


def test_error_shape_has_only_error_key():
    r = wrenai_save_to_shared("../bad", "x")
    assert list(r.keys()) == ["error"]


# --------------------------------------------------------- entry point

def test_load_save_tools_returns_three_callables():
    tools = load_save_tools()
    assert len(tools) == 3
    names = {t.__name__ for t in tools}
    assert names == {
        "wrenai_save_to_shared",
        "wrenai_save_rows_as_csv",
        "wrenai_save_rows_as_json",
    }
