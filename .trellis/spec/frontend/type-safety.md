# Type Safety

- Plain JavaScript with JSDoc types on public functions; run `tsc --noEmit --allowJs --checkJs` in CI if available.
- Every reader validates the `format` string (`cogbench-rec/0`, `cogbench-world/0`, `cogbench-materials/0`) and fails with a visible message naming the file and the problem.
- Binary frame records are parsed with `DataView` in little-endian, checking that `w*h` matches the decompressed length.
- Unknown JSON fields are ignored; missing optional files are tolerated (contracts section 5).
