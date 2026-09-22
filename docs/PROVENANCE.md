# Sources and versions

| Source | Revision / use |
|---|---|
| [myrcutio/ValheimMCP](https://github.com/myrcutio/ValheimMCP) | `676b1462addba5a7abdd3b82a7e2da64c6111bc6`, version 0.2.1. Starting point for BepInEx bootstrap, JSON/MCP HTTP, main-thread dispatch and camera readback patterns. MIT notice retained in `vendor/ValheimMCP`. |
| [itenev/valheim-ai-agent](https://github.com/itenev/valheim-ai-agent) | `b2dba56f92949de453f5080e5211a31488eabfdb`. Architecture reference for action routing, validation and the planner/bridge boundary. |
| [AlexWortega/openjev](https://huggingface.co/AlexWortega/openjev) | `f004f37e52695d6ddfb914a64dbf93942839ba1e`, checkpoint `qwen3.5-0.8b-nli-v2s-long`. Local visual classifier; native MLX port described in [ARCHITECTURE.md](ARCHITECTURE.md). |
| [Valheim BepInEx pack](https://thunderstore.io/c/valheim/p/denikson/BepInExPack_Valheim/) | 5.4.2350, x86_64 loader used through Rosetta. Downloaded separately during setup. |
| [Official Codex app-server docs](https://learn.chatgpt.com/docs/app-server) | Persistent thread start/resume and structured turn protocol. Local generated schemas define the installed protocol fields. |
| Codex CLI | Protocol bindings based on `0.155.0-alpha.9.2`. |
| Microsoft .NET SDK | 10.0.401, osx-arm64, installed locally under `.tools/dotnet`. Standard reference pack 2.1.0 from NuGet. |
| Official Steam Valheim | Native macOS 1.0.15, Steam build 25390630. Game assembly hashes and API bindings are pinned in the plugin. |

The JSON parser rejects duplicate keys, trailing data, excessive nesting, invalid
numbers and unescaped controls. Expired queued requests cannot execute after a
timeout, and the dispatcher does not reuse disposed wait handles.

The bridge provides typed actions through normal gameplay APIs. It does not
expose console/devcommands, arbitrary world cameras, omniscient nearby-entity
state or a mock-game fallback. Screen capture uses the final player framebuffer
with the game's post-processing and HUD.

Game DLLs and local reference decompilations are excluded from Git. The code in
`bridge/Plugin` is the project's adapter, not redistributed game source. Model
weights and toolchains are downloaded during setup and retain their own licenses.
The included gameplay video retains the rights of the game content's owners;
see the [research and rights notice](../README.md#research-and-rights-notice).
