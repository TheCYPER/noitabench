# Web Client Guidelines

> This directory was the `trellis init` "frontend" template. For this project it covers `web/`: the replay viewer, the comparison and report pages, the world preview page and (from week 3) the human play client.

| Guide | Covers | Status |
|---|---|---|
| [Directory Structure](./directory-structure.md) | Layout of `web/` | Filled |
| [Component Guidelines](./component-guidelines.md) | Renderer and page structure | Filled |
| [State Management](./state-management.md) | Playback state, loaded runs | Filled |
| [Type Safety](./type-safety.md) | Parsing recording files | Filled |
| [Hook Guidelines](./hook-guidelines.md) | Not applicable (no React) | Filled |
| [Quality Guidelines](./quality-guidelines.md) | Tests and review gates | Filled |

The data formats it reads are defined in [../backend/contracts.md](../backend/contracts.md) sections 2, 4 and 5. The web client contains **no game logic**.
