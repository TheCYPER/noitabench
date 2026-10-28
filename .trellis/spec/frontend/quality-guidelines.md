# Quality Guidelines

- Format readers have unit tests (Node's built-in `node --test`) against small fixture files committed under `web/tests/fixtures/`, including one recording produced by the sim.
- Every page works at a laptop width and degrades gracefully on a phone; no horizontal page scroll.
- No external network requests at runtime except optional pinned CDN files listed in `web/vendor/README.md`.
- No game logic: the client only decodes and draws what the recording or the server sends.
