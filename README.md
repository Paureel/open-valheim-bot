# Valheim AI · Luna + OpenJev

[![License: MIT](https://img.shields.io/badge/license-MIT-75e1d3?style=flat-square)](LICENSE)
[![macOS: Apple Silicon](https://img.shields.io/badge/macOS-Apple_Silicon-10151b?style=flat-square&logo=apple&logoColor=white)](docs/TUTORIAL.md)
[![Python: 3.12](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](docs/INSTALL.md)
[![OpenJev: 0.8B](https://img.shields.io/badge/OpenJev-0.8B-baa6fa?style=flat-square)](docs/ARCHITECTURE.md)
[![GitHub stars](docs/media/stars.svg)](#star-history)

A local Valheim player with two cooperating systems: **Luna** chooses goals and
dialogue; **OpenJev 0.8B** reads the game image on Apple Silicon and guides short
actions. A live brain observer shows what each system is doing.

## Watch it

[![Animated gameplay beside the live brain observer](docs/media/brain-showcase.gif)](docs/media/brain-showcase.mp4)

[Watch the one-minute video](docs/media/brain-showcase.mp4) · **Guided demonstration**.

Move lights up from measured movement; Talk lights up after successful chat delivery.

## Install

Requires an **Apple Silicon Mac** and the **official Steam version of Valheim 1.0.15**.

1. Install Steam/Valheim, native Python 3.12, and Codex with access to `gpt-5.6-luna`.
2. Download or clone this repository and keep it in a permanent folder.
3. Double-click **[`setup.command`](setup.command)** and choose **Prepare dependencies and build**.
4. Complete installation and character setup in **[Getting started](docs/TUTORIAL.md)**.

Terminal equivalent, from the repository folder:

```sh
./setup.command prepare
```

## Play and observe

Once setup is complete, keep Steam signed in, open `scripts/launch-game.command`,
select your character and join your world manually. Then:

```sh
./scripts/observe.sh                 # Keep running in a separate terminal
./scripts/start.sh --seconds 600     # Ten minutes of autonomous play
```

Open the [brain observer](http://127.0.0.1:8733) beside the game. Switch focus back
to Valheim within 30 seconds of starting. **Keep Valheim focused**: clicking the
observer, another app, or using movement/camera controls pauses the agent.
To stop immediately, press **F8** in-game or run:

```sh
./scripts/stop.sh
```

## Features

| Component | Behavior |
|---|---|
| Luna · System 2 | Chooses goals, plans actions and speaks in character |
| OpenJev · System 1 | Reads the game view to guide movement and interactions |
| Brain observer | Displays movement, speech and agent activity live |
| Gameplay controls | Movement, interaction, combat, inventory and recipe selection |
| Memory and personality | Separate memories for each world and an editable character profile |

Inventory controls operate on the character's own grid and visible recipes.
Combat is off on fresh installs. Remote player identities are unauthenticated,
so privileged remote commands are blocked; use the controls on your Mac.

The bridge, memory, and observer stay on your Mac. Luna receives game images and
dialogue through your Codex account when autonomous play starts and uses that
account's model allowance. OpenJev runs locally. Server passwords are entered only
in Valheim; none are needed by the installer or stored in the repository.

## Documentation

- [Getting started](docs/TUTORIAL.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Architecture](docs/ARCHITECTURE.md)

## Star history

![GitHub star history](docs/media/star-history.svg)

## Research and rights notice

An independent, unofficial research mod, with no affiliation or endorsement by
Valheim's creators. All rights in Valheim belong to Iron Gate AB, Coffee Stain
Publishing AB and their respective rights holders. Original project code is
[MIT licensed](LICENSE); third-party rights remain reserved. See the
[full research and rights notice](NOTICE.md).
