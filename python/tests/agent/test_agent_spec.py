"""The command table: checking, normalising, the text grammar and the tool schemas."""

from __future__ import annotations

import json

import pytest
from noitabench.agent import COMMANDS, CommandError, parse_decision, tool_schemas, validate_command
from noitabench.agent.grammar import split_statements
from noitabench.agent.vocab import EVENT_TYPES, MAX_TICKS

TABLE = {  # tick-design 4.3: every command of the table
    "move", "walk_to", "jump", "fly", "aim", "fire", "kick", "wait", "drink", "pour", "fill",
    "throw", "pickup", "drop", "swap_wand", "edit_wand", "inspect",
}  # fmt: skip


def test_the_table_has_every_command_of_the_design() -> None:
    assert TABLE <= set(COMMANDS)
    memory = {n for n in COMMANDS if n.startswith("memory_")}
    assert memory == {"memory_write", "memory_read", "memory_search", "memory_edit", "memory_list"}


def test_directions_are_normalised() -> None:
    assert validate_command("move", {"direction": "RIGHT"}).args == {"direction": "right"}
    assert validate_command("move", {"direction": -1}).args == {"direction": "left"}
    assert validate_command("jump").args == {}
    assert validate_command("jump", {"direction": "none"}).args == {"direction": "up"}
    with pytest.raises(CommandError, match="one of left, right"):
        validate_command("move", {"direction": "up"})


@pytest.mark.parametrize(
    ("name", "args", "needle"),
    [
        ("dance", {}, "unknown command"),
        ("walk_to", {}, "`x` is required"),
        ("walk_to", {"x": "ten"}, "whole number"),
        ("walk_to", {"x": True}, "whole number"),
        ("walk_to", {"x": 1.5}, "whole number"),
        ("walk_to", {"x": 1, "color": 2}, "unknown argument `color`"),
        ("kick", {"x": 1}, "takes no arguments"),
        ("swap_wand", {"wand": -1}, "at least 0"),
        ("drink", {"amount": 0}, "between 1"),
        ("drink", {"amount": "some"}, "whole number"),
        ("memory_write", {"path": "a"}, "`text` is required"),
        ("memory_write", {"path": "a", "text": 3}, "must be text"),
        ("memory_write", {"path": "a", "text": "b", "append": "yes"}, "true or false"),
    ],
)
def test_bad_commands_are_refused_with_a_message(name: str, args: dict, needle: str) -> None:
    with pytest.raises(CommandError, match=needle) as err:
        validate_command(name, args)
    assert err.value.code in {"unknown_command", "bad_argument"}


def test_numbers_that_are_whole_are_accepted_as_integers() -> None:
    assert validate_command("walk_to", {"x": 180.0}).args == {"x": 180}
    assert validate_command("aim", {"angle": 30}).args == {"angle": 30}
    assert validate_command("aim", {"angle": 30.5}).args == {"angle": 30.5}


def test_until_in_all_its_forms_gives_the_same_dict() -> None:
    want = {"until": {"ticks": 3, "blocked": True}}
    for raw in (
        {"until": {"ticks": 3, "blocked": True}},
        {"until": "ticks=3,blocked"},
        {"until": ["blocked", {"ticks": 3}]},
        {"ticks": 3, "blocked": True},
        {"until": {"ticks": 3}, "blocked": True},
    ):
        assert validate_command("fire", raw).args == want


def test_until_conditions_are_checked() -> None:
    assert validate_command("wait", {"until": {"ticks": MAX_TICKS}}).args["until"] == {
        "ticks": MAX_TICKS
    }
    with pytest.raises(CommandError, match="between 1 and 30"):
        validate_command("wait", {"ticks": MAX_TICKS + 1})
    with pytest.raises(CommandError, match="more than 0"):
        validate_command("move", {"direction": "left", "distance": 0})
    with pytest.raises(CommandError, match="no condition `soon`"):
        validate_command("wait", {"until": {"soon": True}})
    with pytest.raises(CommandError, match="no event type 'reaction'"):
        validate_command("wait", {"event": "reaction"})
    with pytest.raises(CommandError, match="flag"):
        validate_command("fire", {"until": {"target_dead": 3}})
    assert validate_command("wait", {"event": ["damage", "damage", "pickup"]}).args["until"] == {
        "event": ["damage", "pickup"]
    }
    assert validate_command("fire", {"until": {"blocked": False}}).args == {}


def test_walk_to_keeps_x_as_its_target_and_other_commands_read_it_as_a_condition() -> None:
    assert validate_command("walk_to", {"x": 50}).args == {"x": 50}
    assert validate_command("move", {"direction": "right", "x": 50}).args == {
        "direction": "right",
        "until": {"x": 50},
    }


def test_aim_needs_exactly_one_form() -> None:
    assert validate_command("aim", {"x": 3, "y": 4}).args == {"x": 3, "y": 4}
    assert validate_command("aim", {"target": "longleg"}).args == {"target": "longleg"}
    assert validate_command("aim", {"entity": 7}).args == {"entity": 7}
    for bad in ({}, {"angle": 1, "entity": 2}, {"x": 3}):
        with pytest.raises(CommandError, match="aim:"):
            validate_command("aim", bad)


def test_edit_wand_and_inspect_and_drop_check_their_combinations() -> None:
    assert validate_command("edit_wand", {"op": "place", "wand": 0, "slot": 1, "spell": 0})
    assert validate_command("edit_wand", {"op": "swap", "wand": 0, "a": 0, "b": 1})
    with pytest.raises(CommandError, match="needs `spell`"):
        validate_command("edit_wand", {"op": "place", "wand": 0, "slot": 1})
    with pytest.raises(CommandError, match="does not use `a`"):
        validate_command("edit_wand", {"op": "take", "wand": 0, "slot": 1, "a": 0})
    with pytest.raises(CommandError, match="one of"):
        validate_command("inspect", {})
    with pytest.raises(CommandError, match="`slot` goes with `wand`"):
        validate_command("inspect", {"entity": 1, "slot": 0})
    with pytest.raises(CommandError, match="one of"):
        validate_command("drop", {})


# -- the text grammar -----------------------------------------------------------------------------


def test_statements_split_outside_quotes_and_brackets() -> None:
    assert split_statements("a(1); b(2)") == ["a(1)", "b(2)"]
    assert split_statements("memory_write('x', 'a;b'); kick") == [
        "memory_write('x', 'a;b')",
        "kick",
    ]
    assert split_statements("wait(until={'event': ['a', 'b']});") == [
        "wait(until={'event': ['a', 'b']})"
    ]


def test_line_ends_separate_commands_too() -> None:
    assert [c.name for c in parse_decision("aim(angle=10)\nfire(ticks=2)\n\nkick")] == [
        "aim",
        "fire",
        "kick",
    ]
    (c,) = parse_decision("memory_write('a', 'x\\ny')")  # an escaped newline stays in the text
    assert dict(c.args)["text"] == "x\ny"


def test_the_worked_example_decisions_parse() -> None:
    (c,) = parse_decision("walk_to(x=180)")
    assert (c.name, dict(c.args)) == ("walk_to", {"x": 180})
    (c,) = parse_decision("jump(right)")
    assert dict(c.args) == {"direction": "right"}
    aim, fire = parse_decision("aim(12); fire(until=target_dead)")
    assert dict(aim.args) == {"target": 12}
    assert dict(fire.args) == {"until": {"target_dead": True}}
    assert [c.name for c in parse_decision("kick; wait")] == ["kick", "wait"]


def test_words_numbers_lists_and_text_are_values() -> None:
    (c,) = parse_decision("aim(angle=-30)")
    assert dict(c.args) == {"angle": -30}
    (c,) = parse_decision("fire(until={'ticks': 2, 'event': ['damage']})")
    assert dict(c.args) == {"until": {"ticks": 2, "event": ["damage"]}}
    (c,) = parse_decision("memory_write('notes/a.md', 'oil burns; water does not', append=true)")
    assert dict(c.args) == {
        "path": "notes/a.md",
        "text": "oil burns; water does not",
        "append": True,
    }
    (c,) = parse_decision("aim(target=哈米斯)")  # a name is a word
    assert dict(c.args) == {"target": "哈米斯"}
    (c,) = parse_decision("fire(until=mana_empty)")
    assert dict(c.args) == {"until": {"mana_empty": True}}


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ;  ",
        "walk_to(",
        "1 + 2",
        "walk_to(x=1 + 2)",
        "walk_to(**{})",
        "walk_to(1, 2)",
        "move(right, direction=left)",
        "walk_to(x=open('f'))",
    ],
)
def test_text_that_is_not_a_command_is_refused(text: str) -> None:
    with pytest.raises(CommandError) as err:
        parse_decision(text)
    assert err.value.code in {"syntax", "bad_argument"}


def test_nothing_in_the_text_is_evaluated() -> None:
    with pytest.raises(CommandError):
        parse_decision("walk_to(x=__import__('os').getcwd())")


# -- tool schemas ---------------------------------------------------------------------------------


def test_every_command_is_a_tool_with_a_json_schema() -> None:
    tools = tool_schemas()
    assert [t["name"] for t in tools] == list(COMMANDS)
    json.dumps(tools)  # plain JSON
    by_name = {t["name"]: t for t in tools}
    walk = by_name["walk_to"]["inputSchema"]
    assert walk["required"] == ["x"] and walk["properties"]["x"]["type"] == "integer"
    assert set(by_name["wait"]["inputSchema"]["properties"]) >= {"until", "ticks", "event"}
    assert by_name["wait"]["inputSchema"]["properties"]["event"]["anyOf"][0]["enum"] == list(
        EVENT_TYPES
    )
    assert by_name["move"]["inputSchema"]["properties"]["direction"]["enum"] == ["left", "right"]
    for t in tools:
        assert t["description"] and t["inputSchema"]["type"] == "object"
