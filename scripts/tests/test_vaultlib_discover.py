"""discover: the evidence list /setup-my-brain proposes from, and the check
that refuses anything the evidence does not hold.

Every fixture here is made up. Never paste real connector data into this
file: it is committed, and the clean-room rule applies to it in spirit.
"""
import json
from pathlib import Path

import pytest

from vaultlib import discover

OFFSET = "+02:00"


def write_rows(path: Path, rows, *, more=False) -> Path:
    lines = [json.dumps(row) for row in rows]
    if more:
        lines.append(json.dumps({"moreResults": True}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_window_counts_back_and_forward_from_the_local_day():
    result = discover.window(utc_offset=OFFSET, now="2026-09-23T10:00:00Z")
    assert result["local_today"] == "2026-09-23"
    assert result["calendar"] == {"utc_from": "2026-08-25T22:00:00Z",
                                  "utc_to": "2026-10-07T21:59:59Z"}
    assert result["mail"] == {"utc_from": "2026-08-25T22:00:00Z",
                              "utc_to": "2026-09-23T10:00:00Z"}
    assert result["page_caps"]["inbox"] == 20
    assert result["page_size"] == 25


def test_window_uses_the_owners_local_day_not_the_utc_day():
    result = discover.window(utc_offset=OFFSET, now="2026-09-22T23:30:00Z")
    assert result["local_today"] == "2026-09-23"


def test_window_refuses_an_empty_look_back():
    with pytest.raises(discover.DiscoverError, match="days-back"):
        discover.window(utc_offset=OFFSET, days_back=0, now="2026-09-23T10:00:00Z")


def test_read_items_drops_markers_and_reports_a_cap(tmp_path):
    path = write_rows(tmp_path / "m365_inbox.payload.json",
                      [{"subject": "a"}, {"subject": "b"}], more=True)
    rows, capped = discover._read_items(path)
    assert rows == [{"subject": "a"}, {"subject": "b"}]
    assert capped is True


def test_a_marker_that_is_not_last_is_not_a_cap(tmp_path):
    path = tmp_path / "m365_inbox.payload.json"
    path.write_text("\n".join([
        json.dumps({"subject": "a"}),
        json.dumps({"moreResults": True, "nextOffset": 25}),
        json.dumps({"subject": "b"}),
    ]) + "\n", encoding="utf-8")
    rows, capped = discover._read_items(path)
    assert [row["subject"] for row in rows] == ["a", "b"]
    assert capped is False


def test_an_empty_payload_file_is_no_rows(tmp_path):
    path = tmp_path / "m365_sent.payload.json"
    path.write_text("", encoding="utf-8")
    assert discover._read_items(path) == ([], False)


def test_a_broken_line_names_the_file(tmp_path):
    path = tmp_path / "m365_sent.payload.json"
    path.write_text('{"subject": "a"}\n{"subject": \n', encoding="utf-8")
    with pytest.raises(discover.DiscoverError, match="m365_sent.payload.json"):
        discover._read_items(path)


@pytest.mark.parametrize("value, expected", [
    ("  Priya.Nathan@Contoso.example ", "priya.nathan@contoso.example"),
    ({"address": "a@b.example"}, "a@b.example"),
    ({"email": "c@d.example"}, "c@d.example"),
    ({"emailAddress": {"address": "e@f.example"}}, "e@f.example"),
    ("Priya Nathan", None),
    (None, None),
])
def test_address_normalises_every_connector_shape(value, expected):
    assert discover._address(value) == expected


@pytest.mark.parametrize("address, expected", [
    ("jane.doe@x.example", "Jane Doe"),
    ("pieter-jan.coppe@x.example", "Pieter Jan Coppe"),
    ("t.suys@x.example", None),
    ("info@x.example", None),
])
def test_name_from_address_only_reads_plain_first_last(address, expected):
    assert discover._name_from_address(address) == expected


def test_subject_strips_reply_prefixes_and_spacing():
    assert discover._subject("RE: Fw:  Budget   2027 ") == "Budget 2027"


def test_noise_subjects_and_system_senders():
    assert discover._is_noise_subject("Accepted: Weekly exco")
    assert discover._is_noise_subject("Automatic reply: away")
    assert not discover._is_noise_subject("Weekly exco")
    assert discover._is_system("no-reply@shop.example")
    assert discover._is_system("azuredevops@microsoft.com")
    assert not discover._is_system("priya.nathan@contoso.example")


def test_language_needs_three_stop_words():
    assert discover._language("Dag Priya, dat is goed voor mij en ik kijk het na") == "nl"
    assert discover._language("Hi all, the update is ready for you") == "en"
    assert discover._language("Ok, thanks") is None


def test_own_words_cuts_the_quoted_reply():
    text = "Prima, doen we zo.\n________________\nFrom: Priya\nolder text"
    assert discover._own_words(text) == "Prima, doen we zo."
