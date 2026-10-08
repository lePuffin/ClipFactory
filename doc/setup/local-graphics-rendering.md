# Local graphics renderer setup

This is the owner setup procedure for real local infographic and scientific
rendering. The normative contracts, supported templates, configuration
defaults and failure behavior are in
[CF-REQ-263–265](../specifications/08-visual-production.md) and
[ADR-019](../specifications/decisions/ADR-019-local-typed-graphics-renderers.md).
All five supported templates were exercised locally with synthetic data:
HyperFrames 0.8.141 / GSAP 3.14.2 and Manim 0.19.2 produced 720×1280,
30 FPS video that was probed, fully decoded and imported. This does not
establish live Story planning or end-to-end Run validation.

## Dependencies

- Install Node.js 22 LTS and npm as for the normal development setup.
- HyperFrames is a local Node package in `backend/renderers/hyperframes`.
  Source-controlled `package.json` and `package-lock.json` pin the supported
  package version. Install
  only from that lockfile:

  ```bash
  cd backend/renderers/hyperframes
  npm ci
  ```

  The project-owned `clipfactory-hyperframes` launcher at
  `HYPERFRAMES_PATH` invokes that local package and exposes no arbitrary
  command/template input from a VisualDraft. Do not install an unpinned global
  package or use a remote renderer service.
- Manim is isolated in a backend extra but always included by the root runtime.
  Install from the repository root:

  ```bash
  sudo apt-get update
  sudo apt-get install build-essential pkg-config libcairo2-dev libpango1.0-dev
  uv sync --locked
  ```

  The root `uv.lock` pins its compatible dependencies.
  `MANIM_PATH` resolves the executable from this environment.

## Runtime configuration

For a new installation copy `.env.example` to `.env`; do not overwrite an
existing credential-bearing `.env`. Set `NODE_PATH`,
`HYPERFRAMES_PACKAGE_DIR`, `HYPERFRAMES_PATH`, and `MANIM_PATH` to the local
install paths. `GRAPHICS_FPS` defaults to 30 and
`GRAPHICS_TIMEOUT_SECONDS` defaults to 180; their ranges and Run-snapshot
behavior are canonical in [18-configuration.md](../specifications/18-configuration.md).
Renderer output/work/recovery files stay under `DATA_DIR`; do not supply
output paths in a graphics payload.

Renderer paths are not discovered automatically. For launch from the repository
root, use absolute paths, replacing the example root with your installation:

```dotenv
NODE_PATH=node
HYPERFRAMES_PACKAGE_DIR=/mnt/c/repo/ClipFactory/backend/renderers/hyperframes
HYPERFRAMES_PATH=/mnt/c/repo/ClipFactory/backend/renderers/hyperframes/clipfactory-hyperframes.mjs
MANIM_PATH=/mnt/c/repo/ClipFactory/.venv/bin/manim
```

The root runtime always includes Manim and local Wan. Start from the repository root:

```bash
uv run clipfactory
```

After a successful install, `uv run --no-sync clipfactory`
also retains that environment, but does not install or verify dependencies.
HyperFrames requires local Chromium; provision it before offline rendering.
The native verification used an already-installed Chromium. The standard
system-package installation above was not executed on the verification host;
Manim was built using locally extracted Cairo/Pango development packages.

Run `clipfactory doctor` to check configured executable availability. A
missing renderer is an explicit configuration error, not a fake successful
render. Real HyperFrames and Manim integration checks must each render a
supported fixture, probe and fully decode it, and import its reusable Asset
with renderer and template provenance. Repeat these checks after renderer
dependency upgrades.
