"""`mac kitty dashboard` / `layout`, moved from claude-hooks/kitty (task:3f30d74d).

The JSON shapes below are the interface to claude-hooks: its hooks/dashboard_plan.py and
hooks/dashboard_turn.py write them, this renderer reads them. claude-hooks pins its side in
tests/test_dashboard_contract.py; change both together.
"""
import io
import json
import sqlite3
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mac.cli import default_registry, main  # noqa: E402
from mac.groups import _kitty_dashboard as dash  # noqa: E402
from mac.groups import kitty  # noqa: E402


@pytest.fixture
def paths(tmp_path, monkeypatch):
    for env in ("CLAUDE_SERVER_MEMORY_DB", "CLAUDE_DASHBOARD_NOTE",
                "CLAUDE_DASHBOARD_PLAN", "CLAUDE_DASHBOARD_TURN"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("CLAUDE_SERVER_MEMORY_DB", str(tmp_path / "sm.sqlite"))
    monkeypatch.setenv("CLAUDE_DASHBOARD_NOTE", str(tmp_path / "note.md"))
    monkeypatch.setenv("CLAUDE_DASHBOARD_PLAN", str(tmp_path / "plan.json"))
    monkeypatch.setenv("CLAUDE_DASHBOARD_TURN", str(tmp_path / "turn.json"))
    return dash.paths()


def _db(path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE server_memory (id INTEGER PRIMARY KEY, ts REAL, type TEXT, content TEXT, ref TEXT)")
    con.executemany("INSERT INTO server_memory (ts, type, content, ref) VALUES (?,?,?,?)", rows)
    con.commit()
    con.close()


def test_env_overrides_choose_the_files(paths, tmp_path):
    assert paths["db"] == tmp_path / "sm.sqlite" and paths["turn"] == tmp_path / "turn.json"


def test_shows_latest_task_and_last_n_oldest_first(paths):
    _db(paths["db"], [
        (1, "task", "old task", "aaa"), (2, "prompt", "p1", None), (3, "memories", "noise", None),
        (4, "tool", "t1", None), (5, "task", "new task", "bbb"), (6, "tool", "t2", None),
    ])
    out = dash.snapshot(2, 80, p=paths)
    assert out.splitlines()[0].startswith("★ new task") and "[bbb]" in out
    body = out.splitlines()[2:]
    assert len(body) == 2 and body[0].endswith("new task") and body[1].endswith("t2")
    assert "noise" not in out


def test_no_task_and_clipping(paths):
    _db(paths["db"], [(1, "prompt", "x" * 200, None)])
    out = dash.snapshot(5, 40, p=paths)
    assert "no task activation" in out
    assert max(len(l) for l in out.splitlines()) <= 40 and "…" in out


def test_missing_db_fails_soft(paths):
    assert dash.snapshot(5, 80, p=paths).startswith("dashboard: cannot read")


def test_note_shown_above_feed_and_absent_note_ignored(paths):
    _db(paths["db"], [(1, "tool", "t1", None)])
    assert "WAITING" not in dash.snapshot(5, 80, p=paths)
    paths["note"].write_text("PLAN: do x\n\nWAITING: your call on y\n")
    out = dash.snapshot(5, 80, p=paths).splitlines()
    assert out[0] == "PLAN: do x" and out[1] == "WAITING: your call on y"
    assert any(l.endswith("t1") for l in out)


# --- file contract with claude-hooks: plan / turn shapes -------------------------------------------

PLAN = {"title": "Move dashboard", "items": [{"text": "write verbs", "done": True},
                                              {"text": "write tests", "done": False}]}
TURN = {"prompt": "start implementing", "summary": "verbs written"}


def test_plan_shape_renders_progress_and_items(paths):
    paths["plan"].write_text(json.dumps(PLAN))
    out = "\n".join(dash.read_plan(paths["plan"], 80))
    assert "PLAN 1/2" in out and "Move dashboard" in out
    assert "[x] write verbs" in out and "[ ] write tests" in out


def test_next_shape_lists_only_pending_items(paths):
    paths["plan"].write_text(json.dumps(PLAN))
    out = dash.read_next(paths["plan"], 80)
    assert "NEXT 1 pending" in out and "write tests" in out and "write verbs" not in out


def test_turn_shape_renders_prompt_and_summary(paths):
    paths["turn"].write_text(json.dumps(TURN))
    out = dash.read_turn(paths["turn"], 60)
    assert "PROMPT" in out and "start implementing" in out
    assert "SUMMARY" in out and "verbs written" in out


@pytest.mark.parametrize("read", [
    lambda p: dash.read_turn(p, 40), lambda p: dash.read_next(p, 40), lambda p: dash.read_plan(p, 40)])
def test_absent_or_garbled_state_file_fails_soft(read, tmp_path):
    read(tmp_path / "absent.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    read(bad)


# --- verbs -----------------------------------------------------------------------------------------

def mac(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(["kitty", *argv], registry=default_registry(), out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_dashboard_once_prints_plain_text_not_json(paths):
    paths["turn"].write_text(json.dumps(TURN))
    code, out, _ = mac("dashboard", "--view", "turn", "--once")
    assert code == 0 and out.startswith("❯ PROMPT\n") and '\\n' not in out


def test_dashboard_once_missing_db_exits_zero(paths):
    code, out, _ = mac("dashboard", "--once")
    assert code == 0 and out.startswith("dashboard: cannot read")


def test_dashboard_live_returns_nothing_printed(paths):
    with mock.patch.object(dash, "run_live") as live:
        code, out, _ = mac("dashboard", "--view", "next", "-n", "3", "-i", "1")
    assert code == 0 and out == ""
    live.assert_called_once_with(3, 1.0, "next")


def test_layout_opens_turn_tab_then_next_vsplit(tmp_path):
    fake = mock.Mock(side_effect=["7\n", "8\n"])
    exe = tmp_path / "mac"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    with mock.patch.object(kitty, "_kitten", fake), mock.patch.object(kitty.shutil, "which", return_value=str(exe)):
        code, out, _ = mac("layout", "-i", "1")
    assert code == 0 and json.loads(out) == {"turn": 7, "next": 8}
    first, second = (c.args for c in fake.call_args_list)
    assert first[:4] == ("launch", "--type=tab", "--tab-title", "turn")
    assert first[4:] == (str(exe), "kitty", "dashboard", "--view", "turn", "-i", "1.0")
    assert second[:3] == ("launch", "--location=vsplit", "--keep-focus")
    assert second[-5:-2] == ("dashboard", "--view", "next")


def test_layout_without_an_executable_mac_fails(tmp_path):
    with mock.patch.object(kitty.shutil, "which", return_value=None), \
            mock.patch.object(kitty.os, "access", return_value=False):
        code, _, err = mac("layout")
    assert code != 0 and "cannot find an executable mac" in err
