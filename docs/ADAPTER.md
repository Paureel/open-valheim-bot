# Installed-game adapter

Implemented in `bridge/Plugin/GameAdapter.cs` against the official native Steam
Valheim **1.0.15**, build **25390630**. The relevant game
code is in `assembly_valheim.dll`, not `Assembly-CSharp.dll`; `ZInput` is in
`assembly_utils.dll`. The executable contains arm64 and x86_64 slices. Only native
Steam assemblies are supported.

## Compatibility checks

`reviewed-assemblies.json` pins ten inspected game/Unity assembly SHA-256 hashes.
`InstalledBindings.Verify()` checks them before installing Harmony patches or
opening the bridge port. `scripts/verify-bindings.py` checks the same hashes and
13 reflective/Harmony method/field signatures (plus runtime GUI shape checks) without executing game code.
The metadata inspector excludes nested `Version.Player`, which is not the actual
`Player` component. Any changed hash requires API inspection and a deliberate
source update; there is no user-configurable compatibility bypass.

`assembly_valheim.dll`:
`9e55b055e64832dbb021d349f9fb41ecae5e5262735a6a6de679e3a9cbedebc9`.
Local decompilations live only under ignored `.tools/decompiled/`; no proprietary
assembly or decompiled game source is redistributed in Git.

## Normal gameplay paths

| Function | Game API path |
|---|---|
| Movement/jump/crouch/attack/block | Prefix on local `Player.SetControls(Vector3, bool x11)`, called by the existing `PlayerController.FixedUpdate`. Arguments feed normal stamina, collision, combat and animation mechanics. Diagonal movement is normalized. |
| Look | `Player.SetMouseLook(Vector2)` applies ordinary yaw/pitch state and the game's pitch clamp. Positive yaw turns right; positive pitch looks up; deltas are degrees. |
| Interact | Refresh `Player.UpdateHover()`, then normal private `Player.Interact(currentHover, false, false)`. Uses normal aim, reach and occlusion. No object-ID targeting. |
| Hotbar | `Player.UseHotbarItem(1..8)` invokes the normal inventory item use path. |
| Inventory | `InventoryGui.Show/Hide` and normal `OnSelectedItem`/`OnRightClickItem` callbacks on the player's grid. Splitting uses the normal Split dialog and `OnSplitOk`; moves never use the modifier that drops items into the world. IDs expire on close and destination contents must match the supplied ID. |
| Recipes/crafting | Only entries in the currently displayed `m_availableRecipes` Craft list; select its real UI button and invoke the normal Craft button after checking requirements, station and capacity. Unity advances the normal craft timer. Completed output is verified by inventory count change. No direct `DoCrafting`, resource mutation or unknown recipe lookup. |
| Status | Own public health/stamina/eitr, hand items, foods, encumbrance, crouch/block/swim/death and current biome. No remote entity enumeration. |
| Vision | Actual final framebuffer capture, downscaled on the GPU with asynchronous readback when supported. Includes normal camera, effects and HUD. No extra camera or transform writes. |
| Incoming chat | Postfix on `Terminal.AddString(PlatformUserID, string, Talker.Type, bool)` only for `Chat.instance`. This is after `Chat.OnNewChatMessage`'s asynchronous permission and text-filtering callback. Same player-roster existence check as the display path. Console/help overloads and pings are excluded. |
| Outgoing chat | `Chat.SendText(Talker.Type, string)` uses the game's permissions, filtering, Talker/RPC delivery and ordinary character identity. No local UI substitute. Submission is not a delivery acknowledgment; another client must verify it. |
| World identity | Client's loaded `ZNet.World.m_uid`, formatted `world:<uid>`, plus `Player.GetPlayerName()`. No world seed or server password is collected. |

Game/Unity access is on the main thread. Captured chat is queued and drained by the
plugin's Update before entering the core event ring; capture timestamps are kept.
Dialogue from another world/character is not filed in the configured world's memory.

## Input and observation safety

The core maintains the authoritative emergency latch. Both frame processing and
the physics input hook enforce monotonic leases, at most 1.5 seconds. One-shot
jump/crouch/attack edges expire after 250 ms and are consumed once. Expired RPCs
never execute later. Stop releases attack, movement, sprint and block; the adapter
also clears ordinary auto-run and accounts for the player's toggle-block preference.
Crouch remains the normal persistent stance toggle, not a held key.

`travel_to` is a bounded intention toward a point selected in an exact delivered
image, not a longer held input. The supervisor renews a separate travel heartbeat
every 200ms. The plugin steers normal look/input locally, with a lease of at most
900ms (or the configured maximum if shorter), a ten-second intent budget and a
20m target limit. Arrival within 1.2m, blocked progress, own damage, water entry,
encumbrance, a fall, menu/focus/ownership loss, or expired heartbeat stops travel.
Heartbeats cannot create, resurrect or extend an intention. `halt` is a deliberate
stop without an emergency latch; the model may inspect, talk, wait or rest.

Delivered images carry a frame ID. Camera rays and own pose captured with that
image are retained for at most 20 seconds, so a pixel selected while walking is
projected using the image Luna saw. Ground projection assumes a plane at the
captured body's height; it is approximate on slopes and does not query terrain,
physics hits, enemies or world entities. Precise attacks/interactions are rejected
after significant own displacement from the observed view. Map tools manipulate
the normal explored-map UI and export no pins or terrain data.

F8, focus loss, physical movement/camera input, blocked UI, death, teleport/cutscene,
loss of the local player, and wrong world/character pause automation. Background
updates are enabled while the plugin is loaded so stop/health remain responsive;
the previous setting is restored on unload. Automation still requires foreground
focus. A suspended Unity thread can release only when it resumes; the physics hook
checks deadlines before reapplying controls.

Frames refresh twice per second, only in a valid player/input context, and are
rejected when older than 1.5 seconds or from a different world. The bridge itself
stores no screenshots. The supervisor saves private, per-run
observations, decisions, timings and action results under the runtime `playtests/` directory.

Boats/other doodad controllers are rejected because throttle can outlive a keypress.
Only a bridge-opened own inventory can remain ready while a panel is open. Other
menus still pause. Movement/combat/look/hotbar inputs are rejected until it closes.
Stop, focus loss, death and unload cancel any pending craft and close the owned
panel. Mouse clicks or inventory-close keys latch human takeover. Containers,
repair, upgrades, variants, building-piece placement and death recovery are not
implemented.

## Sender identity limitation

In this installed game, `UserInfo.UserId` is serialized in the sender's payload.
`ZRoutedRpc.RPC_RoutedRPC` also accepts `m_senderPeerID` from the routed payload;
its relay path does not bind that claimed original sender to the authenticated
transport peer before forwarding. On a dedicated-server client, the authenticated
peer is the server, not necessarily the player whose identity is claimed.

Consequently a platform-ID/roster match is useful context but insufficient proof
for owner controls. The bridge marks all captured remote identities unverified.
No owner/trusted privilege is granted on display-name or payload-ID similarity.
The strict default service policy blocks request-driven actions from such events.
The core's verified-owner command logic is unreachable for unauthenticated remote
chat in this adapter.

A secure remote-owner/trusted-player channel requires additional authenticated
identity evidence or an explicitly designed pairing mechanism. Local operator
commands are authenticated by private loopback tokens.
