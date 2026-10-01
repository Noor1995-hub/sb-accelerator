"""Routing of message groups. Made-up fixtures only."""
from vaultlib import markdown, msgroute, person, project
from test_vaultlib_vault import make_vault

OWNER = {"morgan.ellery@northwind.example"}


def add_project(root, slug, name, entity, stakeholders=(), keywords=()):
    folder = root / "30-projects" / slug
    folder.mkdir(parents=True)
    fm = {"type": "project", "project-name": name, "slug": slug, "status": "active",
          "project-type": "initiative", "entity": entity, "owner": "morgan-ellery",
          "stakeholders": list(stakeholders), "key-people": [], "created": "2026-09-01",
          "last-updated": "2026-09-01"}
    if keywords:
        fm["keywords"] = list(keywords)
    (folder / "index.md").write_text(markdown.emit_frontmatter(fm), encoding="utf-8")


def add_meeting(root, stem, entities, emails):
    fm = {"type": "meeting", "entities": entities, "projects": [], "attendee-emails": emails}
    (root / "20-meetings" / f"{stem}.md").write_text(markdown.emit_frontmatter(fm), encoding="utf-8")


def grp(label, participants, kind="mail", chat_type=None, texts=("hello",), names=None, sources=("inbox",),
        direct=False, direct_to=()):
    return {"gid": label[:8], "key": f"{kind}:{label}", "date": "2026-09-30", "kind": kind,
            "chat_type": chat_type, "label": label, "participants": list(participants),
            "names": names or {}, "messages": [{"id": t, "at": "", "from": None, "text": t} for t in texts],
            "owner_wrote": False, "direct": direct, "direct_to": list(direct_to), "sources": list(sources)}


def test_entity_domains_need_two_meetings_and_skip_home_domains(tmp_path):
    root = make_vault(tmp_path)
    add_meeting(root, "01-09-26-a", ["acme-industries"], ["jordan.reyes@acme.example", "morgan.ellery@northwind.example"])
    add_meeting(root, "02-09-26-b", ["acme-industries"], ["sam.lee@acme.example"])
    add_meeting(root, "03-09-26-c", ["acme-industries"], ["once@other.example"])
    assert msgroute.entity_domains(root, ["northwind.example"]) == {"acme-industries": {"acme.example"}}


def test_a_domain_is_strong_only_when_it_names_one_project(tmp_path):
    root = make_vault(tmp_path)
    add_meeting(root, "01-09-26-a", ["acme-industries"], ["a@acme.example"])
    add_meeting(root, "02-09-26-b", ["acme-industries"], ["b@acme.example"])
    add_project(root, "acme-industries-operating-model", "Operating model", "acme-industries")
    g = grp("Quick question", ["jordan.reyes@acme.example"])
    msgroute.route(root, [g], home_domains=["northwind.example"], owner_addresses=OWNER, today="2026-09-30")
    assert g["projects"] == ["acme-industries-operating-model"] and g["projects_weak"] == []
    add_project(root, "acme-industries-rollout", "Rollout", "acme-industries")
    g2 = grp("Quick question", ["jordan.reyes@acme.example"])
    msgroute.route(root, [g2], home_domains=["northwind.example"], owner_addresses=OWNER, today="2026-09-30")
    assert set(g2["projects"]) == set(g2["projects_weak"]) == {"acme-industries-operating-model", "acme-industries-rollout"}


def test_a_keyword_in_the_subject_is_strong_and_in_the_text_is_weak(tmp_path):
    root = make_vault(tmp_path)
    add_project(root, "acme-industries-operating-model", "Operating model", "acme-industries", keywords=["P-2317"])
    strong = grp("Status P-2317", ["x@else.example"])
    weak = grp("Update", ["x@else.example"], texts=("about p-2317 again",))
    none = grp("Update", ["x@else.example"], texts=("about P-23170",))
    msgroute.route(root, [strong, weak, none], home_domains=[], owner_addresses=OWNER, today="2026-09-30")
    assert strong["projects"] == ["acme-industries-operating-model"] and strong["projects_weak"] == []
    assert weak["projects_weak"] == ["acme-industries-operating-model"]
    assert none["projects"] == []


def test_people_creation_rule_and_enrichment(tmp_path):
    root = make_vault(tmp_path)
    person.ensure(root, "Sam Lee", "2026-09-01")
    one = grp("Sam Lee", ["sam.lee@acme.example"], kind="chat", chat_type="oneOnOne",
              names={"sam.lee@acme.example": "Sam Lee"}, sources=("teams",), direct=True)
    sent = grp("Proposal", ["priya.nathan@contoso.example"], sources=("sent",), direct=True,
               direct_to=["priya.nathan@contoso.example"])
    cc = grp("Newsletter", [f"p{i}@acme.example" for i in range(9)])
    result = msgroute.route(root, [one, sent, cc], home_domains=[], owner_addresses=OWNER, today="2026-09-30")
    assert result["emails_set"] == ["sam-lee"]
    assert result["created"] == ["priya-nathan"]
    assert one["people"] == ["sam-lee"] and sent["people"] == ["priya-nathan"] and cc["people"] == []


def test_the_owner_is_never_routed_or_created(tmp_path):
    root = make_vault(tmp_path)
    g = grp("Hi", ["morgan.ellery@northwind.example"], sources=("sent",), direct=True)
    result = msgroute.route(root, [g], home_domains=[], owner_addresses=OWNER, today="2026-09-30")
    assert result["created"] == [] and g["people"] == []


def test_a_stakeholder_link_is_weak_and_only_for_exactly_one_project(tmp_path):
    root = make_vault(tmp_path)
    person.ensure(root, "Sam Lee", "2026-09-01", email="sam.lee@acme.example")
    add_project(root, "acme-industries-rollout", "Rollout", "acme-industries", stakeholders=["sam-lee"])
    g = grp("Lunch", ["sam.lee@acme.example"])
    msgroute.route(root, [g], home_domains=[], owner_addresses=OWNER, today="2026-09-30")
    assert g["projects_weak"] == ["acme-industries-rollout"]


def test_only_direct_recipients_of_a_small_sent_mail_get_a_new_note(tmp_path):
    root = make_vault(tmp_path)
    crowd = [f"member.{n}@acme.example" for n in ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot")]
    g = grp("Q4 planning", crowd + ["priya.nathan@contoso.example"], sources=("inbox", "sent"), direct=True,
            direct_to=["priya.nathan@contoso.example"])
    result = msgroute.route(root, [g], home_domains=[], owner_addresses=OWNER, today="2026-09-30")
    assert result["created"] == ["priya-nathan"]


def test_role_and_long_local_parts_never_become_a_person():
    for address in ("no-reply@acme.example", "do.not.reply@acme.example", "noreply.team@acme.example",
                    "info.benelux@acme.example", "hr.team@acme.example", "sales.desk@acme.example",
                    "notifications.bot@acme.example", "anna.maria.de.vries@acme.example"):
        assert msgroute._name_from_address(address) is None, address
    assert msgroute._name_from_address("priya.nathan@contoso.example") == "Priya Nathan"
    assert msgroute._name_from_address("jan.de.vries@contoso.example") == "Jan De Vries"
