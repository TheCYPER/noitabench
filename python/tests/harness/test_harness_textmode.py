"""Finding the commands in a message of a model that has no tools."""

from __future__ import annotations

import pytest
from noitabench.harness.textmode import extract_decision, is_budget_request


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("walk_to(x=180)", "walk_to(x=180)"),
        (
            "I will go right.\nwalk_to(x=180); fire(until=target_dead)",
            "walk_to(x=180); fire(until=target_dead)",
        ),
        ("Plan:\n```\naim(target=4)\nfire\n```\nGood luck.", "aim(target=4)\nfire"),
        ("```python\nkick\n```", "kick"),
        ("Thinking...\n  `jump(right)`  ", "jump(right)"),
        ("walk_to(x=1)\nand then I rest\nkick", "kick"),  # only the last run of commands
        ("first\nmove(right)\nkick\n", "move(right); kick"),
        ("budget", "budget"),
        ("I think I should rest.", None),
        ("walk to the right please", None),
        ("fly_away(x=3)", None),  # not a command of the game
        ("", None),
        ("```\nnot a command here\n```\nwait", "wait"),
        # prose that merely starts with a command word is prose: the game would reject it, and
        # a rejected decision still costs one
        ("wait for the enemy to come closer.", None),
        ("walk_to is the best idea here", None),
        ("fire it", None),
        ("move right", None),
        ("wait.", None),
        ("I will go.\nwalk_to(x=3).\nwait for it", None),
        ("x = walk_to(3)", None),
        ("walk_to(3).extra", None),
        ("[kick]", None),
        ("walk_to(3)(4)", None),
        ("```\nwait for it\nkick\n```", "kick"),  # a block with prose in it is no block
        ("jump(direction=right);", "jump(direction=right);"),
        ("move(right)  # to the right", "move(right)  # to the right"),
    ],
)
def test_extract_decision(message: str, expected: str | None) -> None:
    assert extract_decision(message) == expected


def test_budget_requests() -> None:
    assert (
        is_budget_request("budget")
        and is_budget_request("budget()")
        and is_budget_request("budget ( )")
    )
    assert not is_budget_request("budget; kick") and not is_budget_request("kick")
    assert not is_budget_request("budgeting")
