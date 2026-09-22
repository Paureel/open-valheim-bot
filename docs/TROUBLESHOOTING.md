# Troubleshooting

| Symptom | Meaning / next action |
|---|---|
| Setup cannot find Python | Install native arm64 Python 3.12, or use `./setup.command prepare --python '/path/to/python3.12'`. Rosetta Python cannot run the local MLX worker. |
| Setup cannot find Valheim | Use `--game-dir '/path/to/Valheim'` with the official native Steam folder containing `valheim.app`. Multiple libraries require an explicit selection. |
| `Unsupported game files` | This release pins Valheim 1.0.15 build 25390630. A different build requires review and adapter updates; do not bypass the hash check. |
| `Quit Valheim before installing` | Close the game completely and rerun the loader or bridge step. Preparation/check steps do not write into the game. |
| `BepInEx is already installed` | The assistant preserves existing loaders. Verify the compatible version and successful startup log, then use the bridge step. |
| Archive checksum or staging mismatch | Keep the rejected files for inspection outside `.tools/bepinex-staged`, remove the bad cached ZIP if indicated, then rerun preparation. Never disable verification. |
| Long pauses despite fast OpenJev | Check image freshness, route confidence, heading changes and planner activity in the journals. Reduce game rendering load if image processing is delayed. |
| `Bridge unreachable` | Valheim/plugin is not running. Memory tools still work. Use scripts/launch-game.command with Steam running; the normal Steam Play options were not changed. |
| `Unreviewed game assembly` | A game/Unity DLL changed since inspection. Re-inspect and update source bindings; no configuration bypass exists. |
| `Wrong world or character` | Compare the actual observed bridge identity with local settings. Do not broaden checks to accept every player/world. |
| `Emergency pause is latched` | Run `scripts/valheim-codex resume` only when ready to hand control back, or start a new supervised run. MCP/model actions cannot resume themselves. |
| `Observation expired` | Model turn exceeded the configured observation-age limit. The supervisor stops. Restart after checking the delay/model choice; do not allow unbounded stale decisions. |
| `Decision invalidated` | Stop/resume occurred, or an observation was replayed/expired. This is a safety rejection. |
| `Combat disabled` | Combat defaults to off. Both plugin and service read the private `settings.json` combat setting; restart both after changing it. |
| Owner commands ignored | This adapter marks remote relayed identities unverified. Remote owner commands are unavailable; use F8 or the local stop script. Never fix by trusting display names. |
| Chat cooldown/duplicate suppression | Use fewer, shorter messages. Failed sends do not consume the gateway cooldown. |
| Valheim launches without BepInEx | Check actual binary/Doorstop architecture and launch-script environment. The staged package is x86_64. Review current maintainer instructions and log. |
| Empty/black PNG | Check camera ownership, loaded world and current rendering; inspect frame-capture exceptions and restart after fixing the cause. |
| `Game is not focused` | Switch back to Valheim within the launcher's focus window. Focus loss intentionally pauses control. |
| `Vehicle controls require manual handling` | Disengage the boat/cart/doodad controls manually and restart the supervisor. Throttle is not a bounded movement key. |
| Port in use | Inspect only local listeners, stop an older service, or change both corresponding local port settings and restart. Never bind to 0.0.0.0 as a workaround. |
| MCP absent | `codex mcp get valheim-codex --json`; rerun install-local.py if absent. Reload/reopen Codex after registration. |
| MCP unexpectedly disconnects | A wrapper-owned service lives as long as that wrapper. A disconnect stops gameplay safely. For an independently managed service, run scripts/service.sh before opening MCP or starting the supervisor. |
| Codex login failure | Run the installed `codex login status`. If necessary authenticate normally. Never put passwords/tokens in chat or character files. |
| Codex protocol change | Regenerate schema from `codex app-server generate-json-schema --experimental --out ...`; re-check fields before changing launcher code. |
| No SDK / reference pack | Run scripts/bootstrap-toolchain.sh. It downloads Microsoft's SDK and NETStandard.Library.Ref into .tools only. |
| Test sockets denied inside Codex sandbox | Run scripts/test.sh in Terminal, or allow the test run's loopback socket permission. Tests bind 127.0.0.1 only and use no model or game. |

Useful commands:

```sh
cd /path/to/checkout
./scripts/valheim-codex doctor
./scripts/valheim-codex status
./scripts/valheim-codex stop
./scripts/valheim-codex shutdown
./scripts/valheim-codex --home .test-runtime/codex-smoke codex-smoke
./scripts/test.sh
```

Logs are rotated at 2 MB with four backups under app support. They record action
names, decisions, watchdog/stop events, writes, chat event metadata, and exception
classes. Dialogue is bounded in SQLite. Raw authentication headers and Codex
protocol dumps are not logged. The plugin's BepInEx log follows BepInEx's own
retention settings.
