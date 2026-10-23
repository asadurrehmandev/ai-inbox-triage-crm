"""Round-15 structure. The measurement set was hashed before these rules."""

import hashlib
import json
import re
import subprocess
from pathlib import Path

from app.classifier import (
    _operational_deadline,
    _outage_claim,
    _plain,
    _same_day_deadline,
    classify_rules,
    full_note_urgent,
    message_urgent,
)
from app.prepare import html_to_text, strip_injection_notes, strip_quotes

ROOT = Path(__file__).resolve().parents[1]
HELD = json.loads((ROOT / "data" / "hand_heldout_r15.json").read_text(encoding="utf-8"))


def _mail(row: dict) -> dict:
    return {
        "from_name": row["from_name"],
        "from_email": row["from_email"],
        "subject": row["subject"],
        "body": row["body"],
    }


def _full(row: dict) -> tuple[dict, str, str]:
    mail = _mail(row)
    full = strip_quotes(strip_injection_notes(_plain(mail)))
    body = strip_quotes(strip_injection_notes(html_to_text(row["body"])))
    return mail, full, body


def test_measurement_file_matches_its_hash_and_was_committed_alone():
    raw = (ROOT / "data" / "hand_heldout_r15.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    recorded = (ROOT / "data" / "hand_heldout_r15.sha256").read_text(encoding="utf-8").split()[0]
    assert digest == recorded
    assert digest == "e89b43caad93bf05744aebb917b58e0a9c7fa7e2b23209f227bd732ee439e5f3"
    assert len(HELD) >= 20
    intro = subprocess.check_output(
        ["git", "log", "--diff-filter=A", "--format=%H", "--", "data/hand_heldout_r15.json"],
        cwd=ROOT,
        text=True,
    ).splitlines()[0]
    names = [
        line
        for line in subprocess.check_output(
            ["git", "show", "--name-only", "--format=", intro],
            cwd=ROOT,
            text=True,
        ).splitlines()
        if line.strip()
    ]
    assert names == ["data/hand_heldout_r15.json", "data/hand_heldout_r15.sha256"]
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", intro, "HEAD", "--", "app/model_weights.json", "app/encoder_delta.npz"],
        cwd=ROOT,
        text=True,
    ).strip()
    assert changed == ""


def test_measurement_set_is_paraphrase_disjoint():
    from app.corpus import rows

    def grams(text: str, size: int = 6) -> set[tuple[str, ...]]:
        words = re.findall(r"\w+", text.lower(), flags=re.UNICODE)
        return {tuple(words[index : index + size]) for index in range(max(0, len(words) - size + 1))}

    corpus = set()
    blob = []
    for item in rows():
        blob.append(item["text"])
        corpus |= grams(item["text"])
    for path in (
        "data/hand_heldout.json",
        "data/hand_heldout_r12.json",
        "data/hand_heldout_r13.json",
        "data/hand_heldout_r14.json",
        "data/sample_emails.json",
        "data/eval_fresh.json",
        "data/eval_unseen.json",
    ):
        previous = json.loads((ROOT / path).read_text(encoding="utf-8"))
        for item in previous:
            body = item["body"] if isinstance(item, dict) else ""
            blob.append(body)
            corpus |= grams(body)
    joined = "\n".join(blob)
    banned = (
        "Neue Bankverbindung",
        "künftige Zahlungen",
        "Acil değil",
        "fora do ar",
        "çalışmıyor",
        "8 万元",
        "15,000 درهم",
    )
    for row in HELD:
        assert row["body"].strip() not in joined
        assert not (grams(row["body"]) & corpus)
        for phrase in banned:
            assert phrase not in row["body"]


def test_head_marks_service_down_without_an_english_phrase():
    urgent = [row for row in HELD if row["category"] == "urgent"]
    assert len(urgent) >= 12
    languages = {"pt": False, "ar": False, "zh": False, "ur": False}
    hit = 0
    for row in urgent:
        mail, full, _body = _full(row)
        assert full_note_urgent(full, mail) >= 0.60, row["id"]
        assert not _outage_claim(full), row["id"]
        assert not _operational_deadline(full), row["id"]
        assert not _same_day_deadline(full), row["id"]
        result = classify_rules(mail)
        assert result.category == "urgent", row["id"]
        hit += 1
        if row["id"] in {"p01", "p02", "p03", "p04"}:
            languages["pt"] = True
        if row["id"] in {"p05", "p06", "p07"}:
            languages["ar"] = True
        if row["id"] in {"p08", "p09", "p10"}:
            languages["zh"] = True
        if row["id"] in {"p11", "p12", "p13"}:
            languages["ur"] = True
    assert hit == len(urgent)
    assert languages == {"pt": True, "ar": True, "zh": True, "ur": True}


def test_a_hot_sentence_does_not_flip_a_calm_note():
    calm = [row for row in HELD if row["category"] != "urgent"]
    false_urgent = []
    for row in calm:
        mail, full, body = _full(row)
        result = classify_rules(mail)
        if result.category == "urgent":
            false_urgent.append(row["id"])
        if row["bucket"] == "support":
            assert result.category == "support", row["id"]
            assert "urgent" not in result.secondary_categories
        if row["id"] == "p19":
            assert message_urgent(full, body, mail) >= 0.60
            assert full_note_urgent(full, mail) < 0.60
            assert result.category != "urgent"
    assert false_urgent == []


def test_digit_amounts_keep_an_unlisted_currency_word():
    leads = [row for row in HELD if row["bucket"] == "lead"]
    assert len(leads) >= 3
    for row in leads:
        result = classify_rules(_mail(row))
        assert result.category == "lead", row["id"]
        assert result.budget == row["budget"], row["id"]
        assert result.name == row["name"], row["id"]
        assert result.company == row["company"], row["id"]
        assert not str(result.budget).startswith("$"), row["id"]
    quantity = next(row for row in HELD if row["id"] == "p23")
    result = classify_rules(_mail(quantity))
    assert result.budget is None
    assert result.category != "lead"
    assert result.category != "urgent"
