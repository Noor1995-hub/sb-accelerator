from vaultlib import msgstate
from test_vaultlib_vault import make_vault


def test_first_run_starts_at_local_yesterday_midnight(tmp_path):
    root = make_vault(tmp_path)
    result = msgstate.cursor(root, now="2026-09-30T18:47:00Z", timezone="Europe/Brussels", utc_offset=None)
    assert result == {"since": "2026-09-28T22:00:00Z", "first_run": True, "gaps": [], "closed": []}


def test_the_cursor_never_moves_backwards(tmp_path):
    root = make_vault(tmp_path)
    msgstate.advance(root, newest="2026-09-30T18:40:00Z", new_gaps=[], filled=[], now="2026-09-30T18:50:00Z")
    msgstate.advance(root, newest="2026-09-30T10:00:00Z", new_gaps=[], filled=[], now="2026-09-30T19:10:00Z")
    assert msgstate.cursor(root, now="2026-09-30T19:20:00Z", timezone="UTC", utc_offset=None)["since"] == "2026-09-30T18:40:00Z"


def test_gaps_get_ids_are_filled_and_close_after_seven_days(tmp_path):
    root = make_vault(tmp_path)
    msgstate.advance(root, newest="2026-09-30T18:40:00Z", now="2026-09-30T18:50:00Z", filled=[],
                     new_gaps=[{"source": "inbox", "from": "2026-09-27T00:00:00Z", "to": "2026-09-28T09:00:00Z"},
                               {"source": "teams", "from": "2026-09-20T00:00:00Z", "to": "2026-09-21T00:00:00Z"}])
    open_ = msgstate.cursor(root, now="2026-09-30T19:00:00Z", timezone="UTC", utc_offset=None)
    assert [g["id"] for g in open_["gaps"]] == ["1"]
    assert [g["source"] for g in open_["closed"]] == ["teams"]
    assert [g["id"] for g in msgstate.load(root)["gaps"]] == ["1"]
    msgstate.advance(root, newest=None, new_gaps=[], filled=["1"], now="2026-10-01T18:50:00Z")
    assert msgstate.load(root)["gaps"] == []
    assert msgstate.cursor(root, now="2026-10-01T19:00:00Z", timezone="UTC", utc_offset=None)["gaps"] == []


def test_requeue_is_taken_once(tmp_path):
    root = make_vault(tmp_path)
    msgstate.requeue_add(root, "acme-industries-operating-model", "2026-09-30-messages")
    assert msgstate.requeue_take(root) == [{"slug": "acme-industries-operating-model", "log": "2026-09-30-messages"}]
    assert msgstate.requeue_take(root) == []


def test_a_broken_state_file_loads_as_empty(tmp_path):
    root = make_vault(tmp_path)
    path = root / msgstate.STATE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{", encoding="utf-8")
    assert msgstate.load(root)["cursor"] is None


def test_a_stale_cursor_is_clamped_to_seven_days_once(tmp_path):
    root = make_vault(tmp_path)
    msgstate.advance(root, newest="2026-09-10T08:00:00Z", new_gaps=[], filled=[], now="2026-09-10T08:10:00Z")
    now = "2026-09-30T08:00:00Z"
    result = msgstate.cursor(root, now=now, timezone="UTC", utc_offset=None)
    assert result["since"] == "2026-09-23T08:00:00Z"
    assert msgstate.load(root)["closed_unread"] == [
        {"source": "all", "from": "2026-09-10T08:00:00Z", "to": "2026-09-23T08:00:00Z"}]
    assert msgstate.cursor(root, now=now, timezone="UTC", utc_offset=None)["since"] == "2026-09-23T08:00:00Z"
    assert len(msgstate.load(root)["closed_unread"]) == 1


def test_an_explicit_since_is_not_clamped(tmp_path):
    root = make_vault(tmp_path)
    result = msgstate.cursor(root, now="2026-09-30T08:00:00Z", timezone="UTC", utc_offset=None,
                             since="2026-09-10T08:00:00Z")
    assert result["since"] == "2026-09-10T08:00:00Z"
    assert msgstate.load(root)["closed_unread"] == []


def _write_state(root, text):
    path = root / msgstate.STATE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_a_malformed_state_heals_to_empty(tmp_path):
    for bad in ('{"version": 1, "cursor": "garbage"}', '{"version": 1, "gaps": [{"id": "1"}]}'):
        root = make_vault(tmp_path / str(abs(hash(bad))))
        _write_state(root, bad)
        assert msgstate.load(root)["cursor"] is None
        assert msgstate.load(root)["gaps"] == []
        out = msgstate.advance(root, newest="2026-09-30T18:40:00Z", new_gaps=[], filled=[], now="2026-09-30T18:50:00Z")
        assert out["cursor"] == "2026-09-30T18:40:00Z"
