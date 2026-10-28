# Raw research material (not in the repository)

The documents and JSON tables in this folder were produced from a `raw/` folder that is
**not committed** (`.gitignore` excludes `.trellis/tasks/*/research/raw/`). It held about
28 MB of source material gathered in October 2026:

- `raw/game/`, `raw/gamedata/`, `raw/noitadata/`: data files unpacked from the game
  (materials and reaction XML, spell and gun Lua scripts, entity XML, Wang tile bitmaps);
- `raw/pages/`, `raw/*.wikitext`, `raw/*.html`: saved wiki pages and the GDC talk notes;
- `raw/repos/`, `raw/github/`: copies of open-source falling-sand engines and agent benchmarks
  that were read for prior art (only MIT, Apache and BSD code was used as inspiration).

It is left out because the game files and wiki text are not ours to redistribute, and because
nothing in the build or the tests reads them. The scripts in `scripts/` that regenerate the
tables expect the folder at `./.trellis/tasks/10-16-noita-cogbench/research/raw/` relative to
the repository root. Ask the maintainer if you need it.
