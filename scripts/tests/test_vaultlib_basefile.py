"""The .base subset the Excel export needs (#272)."""
from pathlib import Path

import pytest

from vaultlib import basefile

TEMPLATE = Path(__file__).resolve().parents[2] / "plugin" / "template"


def test_reads_the_people_template():
    got = basefile.read((TEMPLATE / "50-people" / "People.base").read_text(encoding="utf-8"))
    assert got["display"]["note.person-name"] == "Name"
    assert got["display"]["formula.open"] == " "
    assert got["formulas"]["project-names"].startswith("if(projects, projects.map(")
    first = got["views"][0]
    assert first["name"] == "All"
    assert first["order"][:3] == ["formula.open", "person-name", "relationship"]


@pytest.mark.parametrize("rel", ["30-projects/Projects.base", "40-entities/Entities.base"])
def test_reads_every_table_template(rel):
    got = basefile.read((TEMPLATE / rel).read_text(encoding="utf-8"))
    assert got["views"] and all(v["order"] for v in got["views"])
    assert "state" in got["formulas"]


def test_comments_quotes_and_crlf():
    text = ('formulas:\r\n  # a comment\r\n  state: if(status, status.title(), "")\r\n'
            'properties:\r\n  formula.state:\r\n    displayName: "Status"\r\n'
            'views:\r\n  - type: table\r\n    name: \'My view\'\r\n    order:\r\n'
            '      - formula.state\r\n      - note.owner\r\n    sort:\r\n      - property: x\r\n')
    got = basefile.read(text)
    assert got["formulas"]["state"] == 'if(status, status.title(), "")'
    assert got["display"]["formula.state"] == "Status"
    assert got["views"] == [{"name": "My view", "order": ["formula.state", "note.owner"]}]


def test_no_views_raises():
    with pytest.raises(basefile.BaseFileError):
        basefile.read("filters:\n  and: []\n")
