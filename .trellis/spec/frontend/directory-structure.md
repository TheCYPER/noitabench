# Directory Structure

```
web/
  index.html          landing page linking the tools
  replay.html         open a run directory (or files), play it back with a decision timeline
  compare.html        1–4 runs side by side, synced by frame or by decision
  report.html         composite score and capability profile from profile.json (1–4 profiles)
  preview.html        world preview: world PNG + JSON markers
  play.html           human play client (pause mode, plain HTTP to noitabench.play)
  js/
    format/           readers for materials.json, world files, cogbench-rec/0, harness run files
    render/           canvas renderer shared by every page
    replay/           timeline, decision panel, transcript grouping, costs (replay and compare)
    compare/          compare-page axis and panes
    report/           profile parsing, chart data, section renderers, loading
    play/             play-page keymap, gestures, HUD, panels, API client
    pages/            one entry module per page
    ui/               small DOM helpers
  css/                app.css plus replay.css, report.css, play.css
  vendor/             pinned third-party files (for example a deflate decoder), with their licence
```

Plain ES modules, no bundler, so a page opens from `python -m http.server` or the project's own server.
