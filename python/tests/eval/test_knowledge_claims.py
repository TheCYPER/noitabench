"""Claims: the fixed form of what a note says, and the file that holds them."""

from __future__ import annotations

import json

from noitabench.eval.knowledge.claims import (
    FORMAT,
    Claim,
    FileClaims,
    NoteClaims,
    check_fields,
    load_note_claims,
    normalise,
    parse_claim,
    save_note_claims,
)

NOTE = "Lava + water makes rock.\n  Oil   burns, I think.\nThe sludge poisons!"


def ok(raw: dict, note: str = NOTE) -> Claim:
    claim, why = parse_claim(raw, note)
    assert why is None, why
    assert claim is not None
    return claim


def refused(raw: object, note: str = NOTE) -> str:
    claim, why = parse_claim(raw, note)
    assert claim is None and why
    return why


def test_a_claim_keeps_its_subject_and_its_quote():
    c = ok({"kind": "reaction", "a": "lava", "b": "water", "out": ["rock"],
            "text": "Lava + water makes rock."})  # fmt: skip
    assert c.kind == "reaction" and c.fields == {"a": "lava", "b": "water", "out": ["rock"]}
    assert c.hedged is False and c.text == "Lava + water makes rock."
    assert c.as_dict()["hedged"] is False


def test_the_quote_may_differ_from_the_note_in_white_space_only():
    c = ok({"kind": "property", "material": "oil", "property": "burns", "hedged": True,
            "text": "Oil burns, I think."})  # fmt: skip
    assert c.hedged and c.text == "Oil burns, I think."
    assert normalise(" a \n b\t c ") == "a b c"
    assert "does not occur" in refused({"kind": "property", "material": "oil", "property": "burns",
                                        "text": "Oil does not burn"})  # fmt: skip
    # the case is the note's own
    assert "does not occur" in refused({"kind": "property", "material": "oil", "property": "burns",
                                        "text": "oil burns, i think."})  # fmt: skip


def test_a_quote_that_occurs_in_any_note_is_no_proof_that_the_note_says_it():
    """A model may not pass a claim off with a one-letter, punctuation or half-word `text`."""
    oil = {"kind": "property", "material": "oil", "property": "burns"}
    for trivial in ("o", "e", "。", "...", "!", "Oil", "I t", ". ."):
        assert "fewer than" in refused({**oil, "text": trivial}), trivial
    for cut in ("ater makes rock", "Lava + water makes roc", "il burns, I", "he sludge poisons"):
        assert "does not occur" in refused({**oil, "text": cut}), cut
    # a stretch that ends on punctuation, or starts inside a symbol, is a stretch of the note
    ok({**oil, "text": "Oil   burns, I think."})
    ok({**oil, "text": "+ water makes rock."})
    ok({**oil, "text": "Lava + water makes rock"})
    cjk = "水倒在岩浆上，岩浆凝成岩石。"
    assert "fewer than" in refused({**oil, "text": "岩浆"}, note=cjk)
    assert ok({**oil, "text": "岩浆上，岩浆"}, note=cjk).text == "岩浆上，岩浆"
    assert ok({**oil, "text": "岩浆上"}, note=cjk).text == "岩浆上"  # a short whole statement
    # a text taken from somewhere else (the instructions the model was given) is not in the note
    assert "does not occur" in refused({**oil, "text": "Extract what it says"}, note=cjk)


def test_a_claim_is_refused_for_an_unknown_key_value_or_kind():
    base = {
        "kind": "drink",
        "material": "toxic_sludge",
        "effect": "poisoned",
        "text": "The sludge poisons!",
    }
    ok(base)
    assert "unknown key" in refused({**base, "colour": "green"})
    assert "not in the vocabulary" in refused({**base, "effect": "explodes"})
    assert "not in the vocabulary" in refused({**base, "material": "mud"})
    assert "unknown kind" in refused({**base, "kind": "rumour"})
    assert "object" in refused("a string")
    assert "hedged" in refused({**base, "hedged": "yes"})
    assert "text is missing" in refused({k: v for k, v in base.items() if k != "text"})
    assert "longer" in refused({**base, "text": "x" * 201}, note="x" * 300)


def test_nulls_are_ignored_so_a_flat_schema_may_send_them():
    c = ok({"kind": "drink", "material": "toxic_sludge", "effect": "poisoned", "potion": None,
            "a": None, "hedged": None, "text": "The sludge poisons!"})  # fmt: skip
    assert c.fields == {"material": "toxic_sludge", "effect": "poisoned"} and not c.hedged


def test_recipes_need_a_potion_or_an_effect_and_two_or_three_distinct_inputs():
    quote = {"text": "Lava + water makes rock."}
    assert "neither" in refused({"kind": "recipe", "inputs": ["oil", "sand"], **quote})
    ok({"kind": "recipe", "potion": "potion_crit", "inputs": ["oil", "sand"], **quote})
    ok({"kind": "recipe", "effect": "berserk", "inputs": ["oil", "sand", "coal"], **quote})
    assert "inputs" in refused(
        {"kind": "recipe", "potion": "potion_crit", "inputs": ["oil"], **quote}
    )
    assert "repeats" in refused(
        {"kind": "recipe", "potion": "potion_crit", "inputs": ["oil", "oil"], **quote}
    )
    assert "potion" in refused(
        {"kind": "recipe", "potion": "oil", "inputs": ["oil", "sand"], **quote}
    )
    ok({"kind": "no_recipe", "inputs": ["oil", "sand", "coal"], **quote})


def test_reactions_take_a_burning_cell_and_air_as_a_product():
    quote = {"text": "Lava + water makes rock."}
    c = ok({"kind": "reaction", "a": "water", "b": "burning", "out": ["steam", "air"], **quote})
    assert c.fields["b"] == "burning"
    assert ok({"kind": "reaction", "a": "water", "b": "lava", **quote}).fields["out"] == []
    assert "not in the vocabulary" in refused(
        {"kind": "reaction", "a": "air", "b": "lava", **quote}
    )
    ok({"kind": "no_reaction", "a": "sand", "b": "water", **quote})


def test_scene_claims_name_a_topic_and_one_of_its_values():
    quote = {"text": "Lava + water makes rock."}
    good = {"kind": "scene", "encounter": "E21", "topic": "nearest_bottle_to_door", **quote}
    ok({**good, "value": "toxic_sludge"})
    assert "value" in refused({**good, "value": "heal"})
    assert "topic" in refused({**good, "topic": "other", "value": "toxic_sludge"})
    assert "has no topic" in refused({**good, "encounter": "E02", "value": "toxic_sludge"})


def test_local_and_other_claims_are_kept_but_other_needs_a_paraphrase():
    quote = {"text": "Lava + water makes rock."}
    ok({"kind": "local", **quote})
    ok({"kind": "other", "paraphrase": "rock forms on lava", **quote})
    assert "paraphrase" in refused({"kind": "other", **quote})


def test_check_fields_is_what_lessons_use():
    assert check_fields("drink", {"material": "oil", "effect": "oiled"}) is None
    assert "unknown key" in check_fields("drink", {"material": "oil", "effect": "oiled", "x": 1})
    assert "unknown kind" in check_fields("nonsense", {})


# --------------------------------------------------------------------------------------- the file
def sample() -> NoteClaims:
    c = ok(
        {
            "kind": "property",
            "material": "oil",
            "property": "burns",
            "text": "Oil   burns, I think.",
        }
    )
    fc = FileClaims("a" * 64, len(NOTE), (c,), ({"reason": "text is missing", "raw": "{}"},))
    return NoteClaims(
        {"provider": "fake", "model": "m"}, 0.0123, 2, {"notes/a.md": fc}, {"notes/a.md": fc}
    )


def test_the_file_round_trips(tmp_path):
    doc = sample()
    path = save_note_claims(doc, tmp_path)
    assert path.name == "notes_claims.json"
    raw = json.loads(path.read_text())
    assert raw["format"] == FORMAT and set(raw) >= {
        "extractor",
        "cost_usd",
        "calls",
        "start",
        "end",
    }
    back = load_note_claims(tmp_path)
    assert back is not None and back.as_dict() == doc.as_dict()
    assert [(p, c.kind) for p, c in back.section("end")] == [("notes/a.md", "property")]


def test_an_unknown_start_is_left_out_of_the_file(tmp_path):
    doc = sample()
    doc.start = None
    save_note_claims(doc, tmp_path)
    assert "start" not in json.loads((tmp_path / "notes_claims.json").read_text())
    back = load_note_claims(tmp_path)
    assert back is not None and back.start is None and back.section("start") == []


def test_a_missing_or_foreign_or_damaged_file_loads_as_nothing_or_as_far_as_it_goes(tmp_path):
    assert load_note_claims(tmp_path) is None
    (tmp_path / "notes_claims.json").write_text("{nope")
    assert load_note_claims(tmp_path) is None
    (tmp_path / "notes_claims.json").write_text('{"format": "other/0"}')
    assert load_note_claims(tmp_path) is None
    good = sample().as_dict()
    good["end"]["files"]["notes/a.md"]["claims"].append({"kind": "drink", "material": "mud"})
    good["end"]["files"]["notes/b.md"] = 5
    (tmp_path / "notes_claims.json").write_text(json.dumps(good))
    back = load_note_claims(tmp_path)
    assert (
        back is not None
        and len(back.end["notes/a.md"].claims) == 1
        and "notes/b.md" not in back.end
    )
