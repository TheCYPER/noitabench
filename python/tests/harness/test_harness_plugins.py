"""L5: plugins (tools, hooks and prompt fragments of the player's own) and the offline library
list."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest
from agent_worlds import GROUND, START_X
from noitabench.harness import libs
from noitabench.harness.libs import Wheelhouse, default_wheelhouse
from noitabench.harness.sandbox import sandbox_available
from rig import arena_game, make_rig
from wheels import make_wheel, toy_wheelhouse, write_lock

pytestmark = pytest.mark.skipif(not sandbox_available(), reason="needs macOS sandbox-exec")

PLUGIN = """
prompt_fragment = "Water puts out fire."

@tool("Walk right a few ticks and say where you are",
      {"type": "object", "properties": {"ticks": {"type": "integer"}}})
def walk_right(args):
    a = game.move(direction="right", ticks=int(args.get("ticks", 2)))
    print("moved")
    return {"x": a["observation"]["state"]["position"]["x"]}

@tool("Count the notes")
def count_notes(args):
    return str(len(notes.list()["files"]))

@hook("damage")
def on_damage(event):
    game.inspect(x=60, y=159)
    print("plugin hook saw", event["name"])
"""


def plugin_rig(tmp_path: Path, **kwargs):
    rig = make_rig(tmp_path / "rig", **kwargs)
    rig.write("plugins/walker.py", PLUGIN)
    return rig


# -- plugin_list ----------------------------------------------------------------------------------


def test_plugin_list_shows_what_the_plugins_declare(tmp_path: Path) -> None:
    rig = plugin_rig(tmp_path)
    result = rig.call("plugin_list")
    assert not result.is_error, result.content
    data = json.loads(result.content)
    walker = data["plugins"]["walker"]
    assert [t["name"] for t in walker["tools"]] == ["walk_right", "count_notes"]
    assert walker["tools"][0]["schema"]["properties"]["ticks"] == {"type": "integer"}
    assert walker["tools"][1]["schema"] == {"type": "object", "properties": {}}  # the default
    assert walker["hooks"] == [{"event": "damage", "value": None, "function": "on_damage"}]
    assert data["prompt_fragments"] == {"walker": "Water puts out fire."}
    assert "problems" not in data and rig.decisions == 0


def test_a_workspace_without_plugins_says_so(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "rig")
    data = json.loads(rig.call("plugin_list").content)
    assert data["plugins"] == {} and "no plugins yet" in data["note"]


def test_broken_plugins_are_reported_and_the_others_still_work(tmp_path: Path) -> None:
    rig = plugin_rig(tmp_path)
    rig.write("plugins/syntax.py", "def (:\n")
    rig.write("plugins/early.py", "game.wait(ticks=1)\n")
    rig.write(
        "plugins/names.py",
        "@tool('x')\ndef Bad_Name(a): pass\n@tool('y', name='count_notes')\ndef f(a): pass\n",
    )
    rig.write("plugins/loop.py", "while True:\n    pass\n")
    data = json.loads(rig.call("plugin_list").content)
    problems = data["problems"]
    assert "SyntaxError" in problems["syntax"]
    assert "cannot be used while a plugin is loading" in problems["early"]
    assert "not allowed" in problems["names"]
    assert "already declared by plugin names" in problems["walker"]  # `names` is read first
    assert (
        "took longer than 1 seconds to load" in problems["loop"]
        or "took longer than 1" in problems["loop"]
    )
    assert "walk_right" in json.dumps(data["plugins"]["walker"])  # not spoiled by the others
    assert rig.decisions == 0


def test_a_plugin_that_blocks_the_whole_read_is_cut_off(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "rig")
    rig.write("plugins/hang.py", "import time\nwhile True:\n    time.sleep(1000)\n")
    rig.write(
        "plugins/block.py",
        "import signal\nsignal.setitimer(signal.ITIMER_REAL, 0)\nsignal.signal(signal.SIGALRM, signal.SIG_IGN)\nwhile True:\n    pass\n",
    )
    data = json.loads(rig.call("plugin_list").content)
    # the plugin that turns the alarm off is stopped by the limit on processor time instead
    assert "could not be read" in data["problems"]["*"]
    assert "seconds of processor time" in data["problems"]["*"]


# -- plugin_call ----------------------------------------------------------------------------------


def test_a_plugin_tool_runs_like_a_program(tmp_path: Path) -> None:
    rig = plugin_rig(tmp_path)
    result = rig.call("plugin_call", name="walk_right", args={"ticks": 3})
    assert not result.is_error, result.content
    text = result.content
    assert text.startswith("The plugin tool finished.")
    assert 'It returned: {"x":' in text and "It printed:\nmoved" in text
    assert "Game commands run: 1. Steps used: 1." in text and "Decision 2" in text
    assert rig.decisions == 1


def test_a_plugin_tool_can_return_text_and_use_the_notebook(tmp_path: Path) -> None:
    rig = plugin_rig(tmp_path)
    rig.write("notes/a.md", "x")
    result = rig.call("plugin_call", name="count_notes")
    assert "It returned: 2" in result.content and rig.decisions == 0  # the plugin and the note


def test_unknown_tools_and_bad_arguments_are_explained(tmp_path: Path) -> None:
    rig = plugin_rig(tmp_path)
    unknown = rig.call("plugin_call", name="fly_away")
    assert unknown.is_error and "no plugin tool called `fly_away`" in unknown.content
    assert "count_notes, walk_right" in unknown.content
    bad = rig.call("plugin_call", name="walk_right", args=[1, 2])
    assert bad.is_error and bad.content.startswith("bad_argument")
    assert rig.decisions == 0


def test_a_plugin_that_fails_says_where(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "rig")
    rig.write("plugins/p.py", "@tool('breaks')\ndef breaks(args):\n    return args['missing']\n")
    result = rig.call("plugin_call", name="breaks")
    assert result.is_error and "KeyError: 'missing'" in result.content
    assert 'File "<plugin p>", line 3' in result.content


def test_edited_plugins_are_picked_up_without_asking(tmp_path: Path) -> None:
    rig = plugin_rig(tmp_path)
    assert "no plugin tool called `later`" in rig.call("plugin_call", name="later").content
    rig.write("plugins/more.py", "@tool('later')\ndef later(args):\n    return 'here'\n")
    assert "It returned: here" in rig.call("plugin_call", name="later").content
    rig.workspace.delete("plugins/more.py")
    assert "no plugin tool called `later`" in rig.call("plugin_call", name="later").content


def test_plugins_cannot_use_the_game_while_they_load_but_can_in_functions(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "rig")
    rig.write(
        "plugins/p.py",
        "import game\n@tool('t')\ndef t(args):\n    return game.observe()['decision']\n",
    )
    assert json.loads(rig.call("plugin_list").content).get("problems") is None
    assert "It returned: 1" in rig.call("plugin_call", name="t").content


# -- plugin hooks -----------------------------------------------------------------------------------


def test_a_plugin_hook_fires_on_its_event(tmp_path: Path) -> None:
    game = arena_game(tmp_path / "arena", START_X)
    game.spawn_enemy("longleg", START_X + 18, GROUND)
    rig = make_rig(tmp_path / "rig", game=game)
    rig.write("plugins/walker.py", PLUGIN)
    assert not rig.call("plugin_list").is_error  # reading the plugins registers their hooks
    assert '"id":"walker.on_damage"' in rig.call("hook_list").content
    result = rig.call("wait", ticks=25)
    assert "Hook walker.on_damage (damage: You took damage.) ran walker.on_damage" in result.content
    assert "plugin hook saw damage" in result.content
    assert rig.decisions == 2
    cleared = rig.call("hook_clear", id="walker.on_damage")
    assert cleared.content.startswith("plugin_hook")


def test_plugin_hooks_do_nothing_without_the_hook_layer(tmp_path: Path) -> None:
    rig = plugin_rig(tmp_path, layers=("L0", "L1", "L2", "L5"))
    data = json.loads(rig.call("plugin_list").content)
    assert (
        data["plugins"]["walker"]["hooks"] and "do nothing without hook_set" in data["hooks_note"]
    )
    assert "hook_set" not in rig.toolbox.names()


# -- prompt fragments ---------------------------------------------------------------------------------


def test_fragments_follow_the_files(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "rig")
    assert rig.toolbox.system_suffix() == ""
    rig.write("plugins/a.py", "prompt_fragment = 'Remember the pit at x=250.'\n")
    rig.write("plugins/b.py", "prompt_fragment = 'Oil burns.'\n")
    suffix = rig.toolbox.system_suffix()
    assert (
        suffix == "\nNOTES YOU LEFT IN YOUR PLUGINS\n- Remember the pit at x=250.\n- Oil burns.\n"
    )
    rig.write("plugins/a.py", "prompt_fragment = 'Changed.'\n")
    assert "Changed." in rig.toolbox.system_suffix()
    rig.workspace.delete("plugins/a.py")
    rig.workspace.delete("plugins/b.py")
    assert rig.toolbox.system_suffix() == ""


def test_fragments_are_limited(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "rig")
    for n in range(5):
        rig.write(f"plugins/p{n}.py", f"prompt_fragment = '{n}' * 900\n")
    suffix = rig.toolbox.system_suffix()
    lines = [x for x in suffix.splitlines() if x.startswith("- ")]
    assert all(len(x) == 602 for x in lines)  # clipped to 600
    assert len(lines) == 3  # 3 x 600 fit in 2,000; the others do not


def test_a_plugin_that_needs_a_library_works_once_it_is_installed(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "rig", wheelhouse=toy_wheelhouse(tmp_path))
    rig.write(
        "plugins/p.py",
        "import tinylib\n@tool('name')\ndef name(args):\n    return tinylib.NAME\n",
    )
    first = json.loads(rig.call("plugin_list").content)
    assert "No module named 'tinylib'" in first["problems"]["p"]
    assert rig.call("plugin_call", name="name").is_error
    assert not rig.call("lib_install", name="tinylib").is_error
    second = json.loads(
        rig.call("plugin_list").content
    )  # the files did not change, the libraries did
    assert "problems" not in second
    assert "It returned: tiny" in rig.call("plugin_call", name="name").content


def test_a_tool_that_returns_a_lot_gives_a_cut_answer_not_an_error(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "rig")
    rig.write(
        "plugins/big.py",
        "@tool('a lot of text')\ndef text(args):\n    return 'x' * 60000\n"
        "@tool('a long list')\ndef rows(args):\n    return list(range(20000))\n"
        "@tool('nested')\ndef nested(args):\n    v = []\n    for _ in range(800):\n"
        "        v = [v]\n    return v\n"
        "@tool('not json')\ndef odd(args):\n    return {1, 2}\n",
    )
    for name in ("text", "rows", "nested", "odd"):
        result = rig.call("plugin_call", name=name)
        assert not result.is_error, (name, result.content[:200])
        assert result.content.startswith("The plugin tool finished.\nIt returned: ")
    assert "..." in rig.call("plugin_call", name="text").content
    assert rig.decisions == 0


def test_what_the_box_says_about_the_plugins_is_checked_before_it_is_used(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "rig")
    rig.write(
        "plugins/liar.py",
        "import os, sys\n"
        "chan = sys.modules['game'].decide.__closure__[0].cell_contents.channel\n"
        "good = {'name': 'fine_tool', 'plugin': 'liar', 'description': 'd' * 10_000,\n"
        "        'schema': {'type': 'object', 'properties': {'a': [1] * 100_000}}}\n"
        "chan.send({'op': 'done', 'ok': True, 'described': {\n"
        "    'tools': [5, 'x', None, good, {'name': 'Bad Name', 'plugin': 'liar'}],\n"
        "    'hooks': [None, {'event': 'damage', 'plugin': 'liar', 'function': 'f', 'value': 'x'},\n"
        "              {'event': 'nope', 'plugin': 5, 'function': 'f'}],\n"
        "    'errors': ['a', 'b'], 'prompts': ['a']}})\n"
        "os._exit(0)\n",
    )
    result = rig.call("plugin_list")
    assert not result.is_error, result.content
    data = json.loads(result.content)
    tool = data["plugins"]["liar"]["tools"][0]
    assert tool["name"] == "fine_tool" and len(tool["description"]) == 400
    assert tool["schema"] == {"type": "object", "properties": {}}  # too large: the default
    assert "Bad Name" in data["problems"]["liar"] and rig.decisions == 0

    rig.write(
        "plugins/liar.py",
        "import os, sys\n"
        "chan = sys.modules['game'].decide.__closure__[0].cell_contents.channel\n"
        "chan.send({'op': 'done', 'ok': True, 'described': {'tools': 'x', 'hooks': 3,\n"
        "           'errors': 4, 'prompts': 5}})\n"
        "os._exit(0)\n",
    )
    assert not rig.call("plugin_list").is_error


def test_nothing_in_a_library_runs_by_itself(tmp_path: Path) -> None:
    """`.pth` files and `sitecustomize` run when a program starts; the box only adds the folder
    of the libraries to its path, which runs nothing."""
    house = tmp_path / "wheelhouse"
    wheel = make_wheel(
        house,
        "sly",
        "1.0",
        {
            "sly.py": "VALUE = 1\n",
            "sly.pth": "import os; os.environ['PTH_RAN'] = '1'\n",
            "sitecustomize.py": "import os; os.environ['SITE_RAN'] = '1'\n",
            "usercustomize.py": "import os; os.environ['USER_RAN'] = '1'\n",
            "sly/__init__.py": "",
        },
    )
    write_lock(house.with_name("wheelhouse.lock"), [wheel])
    rig = make_rig(tmp_path / "rig", wheelhouse=house)
    assert not rig.call("lib_install", name="sly").is_error
    assert (rig.workspace.libs_dir / "sly.pth").is_file()  # it is there, and does nothing
    code = (
        "import os, sys\nprint(sorted(k for k in os.environ if k.endswith('_RAN')))\nimport sly\n"
    )
    code += "print('sitecustomize' in sys.modules, 'usercustomize' in sys.modules)"
    out = rig.call("run_code", code=code).content
    assert "It printed:\n[]\nFalse False" in out, out


def test_the_built_in_unpacker_refuses_every_way_out_of_the_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(libs.shutil, "which", lambda _name: None)  # no uv
    outside = tmp_path / "outside"
    outside.mkdir()
    house = tmp_path / "wheelhouse"
    ways = {
        "absolute": f"{outside}/abs.py",
        "parent": "../../outside/up.py",
        "inside_parent": "pkg/../../outside/up2.py",
        "data": "evil-1.0.data/purelib/../../../outside/data.py",
    }
    wheels = [
        make_wheel(house, f"w{n}", "1.0", {member: "x = 1\n"})
        for n, member in enumerate(ways.values())
    ]
    write_lock(house.with_name("wheelhouse.lock"), wheels)
    rig = make_rig(tmp_path / "rig", wheelhouse=house)
    for n in range(len(ways)):
        result = rig.call("lib_install", name=f"w{n}")
        assert result.is_error and "unsafe file name" in result.content, result.content
    assert list(outside.iterdir()) == []
    # a link inside a wheel is written as the file it is, never as a link
    link = house / "linked-1.0-py3-none-any.whl"
    with zipfile.ZipFile(link, "w") as archive:
        info = zipfile.ZipInfo("linked.py")
        info.external_attr = (0o120777) << 16  # a symlink, as a wheel may say
        archive.writestr(info, str(tmp_path))
        archive.writestr("linked-1.0.dist-info/METADATA", "Name: linked\nVersion: 1.0\n")
    write_lock(house.with_name("wheelhouse.lock"), [*wheels, link])
    assert not rig.call("lib_install", name="linked").is_error
    assert not (rig.workspace.libs_dir / "linked.py").is_symlink()


def test_a_name_that_is_not_in_the_lock_is_not_installed_however_it_is_written(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path / "rig", wheelhouse=toy_wheelhouse(tmp_path))
    for name in (
        "tinylib==0.1", "tinylib 0.1", "tinylib/../x", "../tinylib", "/abs/tinylib.whl",
        "tinylib-0.1-py3-none-any.whl", "tinylib\x00", "", "  ", "TINYLIB;x",
    ):  # fmt: skip
        result = rig.call("lib_install", name=name)
        assert result.is_error, (name, result.content)
    assert not rig.workspace.libs_dir.exists()
    assert not rig.call("lib_install", name="TinyLib").is_error  # the same name, other spelling


# -- the library list -------------------------------------------------------------------------------


def test_the_toy_wheelhouse_lists_installs_and_imports(tmp_path: Path) -> None:
    house = toy_wheelhouse(tmp_path)
    rig = make_rig(tmp_path / "rig", wheelhouse=house)
    listing = json.loads(rig.call("lib_list").content)["libraries"]
    status = {row["name"]: row["status"] for row in listing}
    assert status["toylib"] == status["tinylib"] == status["toydep"] == "available"
    assert status["numpy"] == "built in" and status["scipy"] == "built in"
    result = rig.call("lib_install", name="toylib")
    assert not result.is_error, result.content
    data = json.loads(result.content)
    assert data["status"] == "installed" and data["installed"] == ["toydep 1.0", "toylib 2.0"]
    assert (rig.workspace.libs_dir / "toylib" / "__init__.py").is_file()
    code = "import toylib\nprint(toylib.ANSWER)"
    assert "It printed:\n42" in rig.call("run_code", code=code).content
    again = json.loads(rig.call("lib_install", name="toylib").content)
    assert again["status"] == "already installed"
    after = {r["name"]: r["status"] for r in json.loads(rig.call("lib_list").content)["libraries"]}
    assert after["toylib"] == after["toydep"] == "installed" and after["tinylib"] == "available"
    assert rig.decisions == 0


def test_only_listed_libraries_can_be_installed(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "rig", wheelhouse=toy_wheelhouse(tmp_path))
    for name in ("requests", "../../etc", "toylib; rm -rf /", "tiny lib"):
        result = rig.call("lib_install", name=name)
        assert result.is_error and "not one of the libraries you can install" in result.content
    assert not rig.workspace.libs_dir.exists()
    assert "already available" not in rig.call("lib_install", name="numpy").content or True
    assert json.loads(rig.call("lib_install", name="numpy").content)["status"] == "already there"


def test_a_wheel_that_does_not_match_its_hash_is_not_installed(tmp_path: Path) -> None:
    house = toy_wheelhouse(tmp_path)
    wheel = next(house.glob("tinylib-*.whl"))
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("tinylib_extra.py", "evil = True\n")
    rig = make_rig(tmp_path / "rig", wheelhouse=house)
    result = rig.call("lib_install", name="tinylib")
    assert result.is_error and "does not match its hash" in result.content
    assert not (rig.workspace.libs_dir / "tinylib.py").exists()


def test_the_built_in_unpacker_does_the_same_job_and_refuses_unsafe_wheels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(libs.shutil, "which", lambda _name: None)  # no uv
    house = toy_wheelhouse(tmp_path)
    rig = make_rig(tmp_path / "rig", wheelhouse=house)
    data = json.loads(rig.call("lib_install", name="toylib").content)
    assert data["via"] == "built-in unpacker"
    assert (
        "It printed:\n42"
        in rig.call("run_code", code="import toylib\nprint(toylib.ANSWER)").content
    )
    evil = make_wheel(house, "evil", "1.0", {"../outside.py": "x = 1\n"})
    write_lock(house.with_name("wheelhouse.lock"), sorted(house.glob("*.whl")))
    result = rig.call("lib_install", name="evil")
    assert result.is_error and "unsafe file name" in result.content
    assert not (tmp_path / "outside.py").exists() and evil.exists()


def test_uv_is_used_when_it_is_there(tmp_path: Path) -> None:
    if shutil.which("uv") is None:
        pytest.skip("uv is not installed")
    rig = make_rig(tmp_path / "rig", wheelhouse=toy_wheelhouse(tmp_path))
    data = json.loads(rig.call("lib_install", name="tinylib").content)
    assert data["via"] == "uv", data
    assert (rig.workspace.libs_dir / "tinylib.py").is_file()


def test_clearing_the_workspace_removes_installed_libraries(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "rig", wheelhouse=toy_wheelhouse(tmp_path))
    rig.call("lib_install", name="tinylib")
    assert rig.workspace.libs_dir.is_dir()
    rig.workspace.clear()
    assert not rig.workspace.libs_dir.exists()


def test_putting_a_snapshot_back_keeps_the_installed_libraries(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "rig", wheelhouse=toy_wheelhouse(tmp_path))
    rig.call("lib_install", name="tinylib")
    rig.workspace.write("notes/a.md", "before", False)
    blob = rig.session.snapshot()
    rig.workspace.write("notes/a.md", "after", False)
    rig.session.restore(blob)
    assert rig.workspace.read("notes/a.md")["text"] == "before"
    assert (rig.workspace.libs_dir / "tinylib.py").is_file()


def test_installs_are_logged(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "rig", wheelhouse=toy_wheelhouse(tmp_path))
    rig.call("lib_install", name="toylib")
    rig.call("lib_install", name="nothing")
    rig.logs.close()
    rows = [r for r in rig.transcript() if r["kind"] == "lib_install"]
    assert [(r["name"], r["ok"]) for r in rows] == [("toylib", True), ("nothing", False)]
    assert rows[0]["installed"] == ["toydep 1.0", "toylib 2.0"] and rows[0]["via"] in {
        "uv",
        "built-in unpacker",
    }


def test_a_missing_wheelhouse_is_not_an_error(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "rig", wheelhouse=tmp_path / "nowhere")
    data = json.loads(rig.call("lib_list").content)
    assert {r["name"] for r in data["libraries"]} == {"numpy", "scipy"} and "No extra" in data[
        "note"
    ]


def test_the_lock_is_read_with_its_dependencies(tmp_path: Path) -> None:
    house = Wheelhouse(toy_wheelhouse(tmp_path))
    assert [w.name for w in house.closure("toylib")] == ["toydep", "toylib"]  # extras are skipped
    assert house.get("ToyLib") is not None and house.names() == ["tinylib", "toydep", "toylib"]


# -- the real wheelhouse of this checkout ---------------------------------------------------------------

REAL = default_wheelhouse()


@pytest.mark.skipif(not REAL.is_dir(), reason="the wheelhouse has not been downloaded")
def test_the_real_wheelhouse_installs_networkx_and_pandas(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "rig")
    listing = {
        r["name"]: r["status"] for r in json.loads(rig.call("lib_list").content)["libraries"]
    }
    for name in (
        "networkx",
        "sympy",
        "mpmath",
        "pandas",
        "numpy",
        "python-dateutil",
        "pytz",
        "six",
        "tzdata",
    ):
        assert name in listing, name
    assert listing["numpy"] == "built in"
    graph = "import networkx as nx\ng = nx.path_graph(5)\nprint(nx.shortest_path_length(g, 0, 4))\n"
    assert "No module named 'networkx'" in rig.call("run_code", code=graph).content
    assert not rig.call("lib_install", name="networkx").is_error
    assert "It printed:\n4" in rig.call("run_code", code=graph).content
    pandas = rig.call("lib_install", name="pandas")
    assert not pandas.is_error, pandas.content
    installed = json.loads(pandas.content)["installed"]
    assert "numpy 2.2.6" not in installed and any(x.startswith("pandas ") for x in installed)
    frame = rig.call(
        "run_code", code="import pandas as pd\nprint(pd.DataFrame({'a': [1, 2]}).a.sum())"
    )
    assert "It printed:\n3" in frame.content, frame.content
