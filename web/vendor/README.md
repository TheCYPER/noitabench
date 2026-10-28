# vendor/

Empty on purpose. zlib payloads (`frames.bin` records, PNG data) are inflated with the browser's built-in
`DecompressionStream('deflate')`, so no third-party library, CDN file or network request is needed at runtime.

If a browser without `DecompressionStream` ever has to be supported, add a pinned inflate library here together
with its licence file, and list it in this README.
