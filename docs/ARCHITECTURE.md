# Luna, OpenJev and the brain observer

The player combines an asynchronous planner with a local visual controller.
Luna chooses goals and dialogue; OpenJev classifies the current game image.
Deterministic control code turns those classifications and intentions into normal
game inputs through the bridge. See [sources and versions](PROVENANCE.md) for
upstream projects and dependency revisions.

## System 2: Luna

`gpt-5.6-luna` with low reasoning chooses bounded intentions, conversation and
memories. The supervisor requests the next intention while local control is
running. The planner receives the bound character identity and the editable
character profile, so there is no fixed default character name.

Luna runs through the user's Codex account. Game images and dialogue are sent to
that service during autonomous play. The gameplay planner has tool execution
disabled; its structured decisions are validated by the local controller.

## System 1: OpenJev on Apple Silicon

| Setting | Value |
|---|---|
| Upstream | [AlexWortega/openjev](https://huggingface.co/AlexWortega/openjev) |
| Checkpoint | `qwen3.5-0.8b-nli-v2s-long` |
| Revision | `f004f37e52695d6ddfb914a64dbf93942839ba1e` |
| Weight SHA-256 | `cf6d62a341c0c804f9a926eec71aefc9859adb28978736e757b49bce35d9b8f8` |
| Runtime | Native MLX with arm64 Python 3.12 |
| Computation | FP16, with 8-bit language weights and unquantized vision/classifier weights |
| Local files | `.tools/system-one/` and `.tools/models/openjev-0.8b/` |

This is a three-way classifier, not a text generator. The native port preserves
the trained classification head, tokenizer, NLI template and last-token pooling.
It scores candidate statements about the rendered view; control logic decides
whether to move, turn, interact or stop.

One shared image/premise prefix is evaluated per frame. Attention K/V and hybrid
recurrent states are expanded into the candidate batch. Caches are not reused
across different images or candidate continuations. The model runs in a separate
process with at most one frame request outstanding, targeting two decisions per
second. The worker limits unused GPU buffers to 512 MiB.

The standard image profile uses 384×216 thumbnails. The optional compact profile
uses 256×144 thumbnails and a 32768-pixel processor minimum:

```sh
VALHEIM_SYSTEM_ONE_IMAGE_PROFILE=compact ./scripts/start.sh --seconds 600
```

`requirements-system-one.txt` pins dependencies. `scripts/setup-system-one.py`
downloads the checkpoint and verifies its weight hash. Developers can compare the
native scores with the reference implementation using
`scripts/validate-system-one.py` and their own image files.

## Game bridge and local control

Captures use the actual final framebuffer, including the camera effects and HUD.
Full-resolution pixels stay on the GPU while downscaling; the smaller image is
read back asynchronously when supported. Textures remain alive until the GPU copy
completes, and PNG encoding runs in a background task. Freshness checks include
the age of the captured pixels.

Continuous inputs renew atomically with 800 ms leases and a 900 ms schema maximum.
Fresh image validation, smooth per-frame steering and independent physics-hook
expiry bound each action. Stop epochs, session identifiers and intention revisions
reject stale work. Death, focus loss, F8, physical takeover and local stop take
priority over model decisions.

Inventory and crafting skills operate through normal UI callbacks and verify
item/output changes. Gathering reports inventory gain. Combat uses local visual
target confidence and the normal crosshair caption. See the
[adapter reference](ADAPTER.md) for the control paths and available operations.

World-scoped SQLite memory, private settings and run journals live in
`~/Library/Application Support/ValheimCodex/`. Private loopback tokens authenticate
local control commands. Remote chat does not grant privileged control.

## Brain observer

`scripts/observe.sh` serves a read-only page at `http://127.0.0.1:8733`.
The supervisor publishes a bounded activity feed to private `run/brain.json`.

- **See** follows completed local perception; a stale result cannot cause movement.
- **Move** follows measured body velocity. Pushing against an obstacle is not movement.
- **Talk** begins after successful in-game chat delivery.
- **Plan** follows planner starts/results; intention regions show accepted intentions.
- Other control regions follow accepted actions or successful inventory calls.

Stopped runs and missing or stale producer heartbeats extinguish activity.
The diagram represents controller functions, not literal model neurons. The
observer serves fixed assets and a read-only snapshot endpoint; it exposes no
tokens, game commands or arbitrary files. Visible browser polling is every 250 ms
and slows while hidden. The controller does not depend on the browser.

## Sessions and recording

```sh
./scripts/start.sh --shadow --seconds 30
./scripts/start.sh --seconds 600
./scripts/stop.sh
```

Shadow mode keeps controls paused and sends no speech. Autonomous mode uses both
models. `--legacy` selects the serial planner loop explicitly. All runs are bounded
and release controls on exit; the game remains visible.

The [recording utility](RECORDING.md) captures actual game-camera frames and
synchronizes the observer to recorded timestamps. Guided recordings are labeled
as guided demonstrations.
