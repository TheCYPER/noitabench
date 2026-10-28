"""Static files: the web client, and only that."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import Client
from noitabench.play import PlayApp

REPO = Path(__file__).resolve().parents[3]


def test_root_goes_to_the_play_page(client: Client) -> None:
    res = client.get("/")
    assert res.status == 302 and res.headers["Location"] == "/web/play.html"


def test_a_favicon_request_is_not_an_error(client: Client) -> None:
    assert client.get("/favicon.ico").status == 204


def test_the_page_and_its_modules_are_served_with_the_right_types(client: Client) -> None:
    html = client.get("/web/play.html")
    assert html.status == 200 and html.headers["Content-Type"].startswith("text/html")
    assert b"js/pages/play.js" in html.body
    js = client.get("/web/js/pages/play.js")
    assert js.status == 200 and js.headers["Content-Type"].startswith("text/javascript")
    css = client.get("/web/css/play.css")
    assert css.status == 200 and css.headers["Content-Type"].startswith("text/css")
    assert client.get("/web/").status == 200  # the index


def test_responses_forbid_other_sites(client: Client) -> None:
    for path in ("/web/play.html", "/api/state"):
        h = client.get(path).headers
        csp = h["Content-Security-Policy"]
        assert "default-src 'self'" in csp and "connect-src 'self'" in csp
        assert h["Cache-Control"] == "no-store"
        assert h["X-Content-Type-Options"] == "nosniff"


def test_nothing_outside_web_is_served(client: Client) -> None:
    for path in (
        "/web/../content/reactions.json",
        "/web/%2e%2e/content/reactions.json",
        "/web/tests/fixtures/world_synthetic.json",
        "/web/.git/config",
        "/web/package.json/../../Cargo.toml",
        "/content/reactions.json",
        "/content/entities.json",
        "/python/noitabench/play/app.py",
        "/runs/",
        "/runs/play-3/decisions.jsonl",
        "/runs/play-3-world/world_3.json",
        "/web/../runs/play-3/meta.json",
        "/web/runs/play-3/meta.json",
        "/web/nothing.js",
    ):
        assert client.get(path).status == 404, path


def test_the_page_gets_colours_and_nothing_else_about_the_materials(client: Client) -> None:
    res = client.get("/content/materials.json")
    assert res.status == 200
    doc = res.json()
    full = json.loads((REPO / "content" / "materials.json").read_text())
    assert doc["format"] == full["format"] == "cogbench-materials/0"
    assert set(doc) == {"format", "materials"}
    assert [m["index"] for m in doc["materials"]] == [m["index"] for m in full["materials"]]
    assert [m["color"] for m in doc["materials"]] == [m["color"] for m in full["materials"]]
    for m in doc["materials"]:
        assert set(m) == {"index", "color"}, "no key, no name, no kind"
    text = res.body.decode("utf-8")
    for m in full["materials"]:  # not one name of any material, in any language
        for field in ("key", "name_zh", "name_en", "noita_id"):
            name = m.get(field)
            assert not name or len(name) < 3 or name not in text, (field, name)
    for word in ("density", "family", "tags", "drink_effect", "contact_damage", "autoignition"):
        assert word not in text
    for word in ("kind", "key", "name", "potion", "lively"):
        assert word not in text, word


def test_web_tests_stay_hidden_whatever_the_spelling(client: Client) -> None:
    """The file system of a Mac ignores case: `/web/TESTS/...` must not get around the rule."""
    for path in (
        "/web/TESTS/helpers.js",
        "/web/Tests/fixtures/world_synthetic.json",
        "/web/tests/helpers.js",
        "/web//tests/helpers.js",
        "/web/js/../tests/helpers.js",
    ):
        assert client.get(path).status == 404, path
    assert client.get("/web/js/pages/play.js").status == 200


def test_odd_paths_are_not_found_and_never_a_server_error(client: Client) -> None:
    for path in (
        "/web/play.html%00",
        "/web/pl%00ay.html",
        "/web/" + "a" * 5000,
        "/web/js/" + "b" * 300,
        "/web/..%5ccontent%5cmaterials.json",
        "/web/%252e%252e/content/materials.json",
        "/web/js",
        "/web/js/",
    ):
        res = client.get(path)
        assert res.status == 404, path
        assert res.json()["error"]["code"] == "not_found"


def test_static_serving_follows_no_link_out_of_web_and_none_into_tests(
    client: Client, app: PlayApp, tmp_path: Path
) -> None:
    root = tmp_path / "web"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "secret.js").write_text("secret")
    (root / "ok.js").write_text("fine")
    (root / "notes.xyz").write_text("not a kind of file the client uses")
    outside = tmp_path / "outside.js"
    outside.write_text("outside")
    (root / "out.js").symlink_to(outside)
    (root / "into_tests.js").symlink_to(root / "tests" / "secret.js")
    (root / "linkdir").symlink_to(root / "tests", target_is_directory=True)
    app.web_root = root.resolve()
    assert client.get("/web/ok.js").body == b"fine"
    for path in (
        "/web/out.js",
        "/web/into_tests.js",
        "/web/linkdir/secret.js",
        "/web/tests/secret.js",
        "/web/notes.xyz",
    ):
        assert client.get(path).status == 404, path
