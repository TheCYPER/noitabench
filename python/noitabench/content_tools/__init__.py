"""Generators for the data files under `content/` that are derived from the research data.

Each generator is a plain script with a `build()` function (pure: returns the data) and a `main()`
(writes the file, or compares with `--check`). Run them with
`python -m noitabench.content_tools.<name>`.
"""
