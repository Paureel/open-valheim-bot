#!/usr/bin/env python3
"""Read the loaded client's identity; optionally back up and configure this player."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from valheim_codex.config import Config, private_write
from valheim_codex.protocol import LocalClient

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--apply', action='store_true', help='Back up and update local settings to the observed character/world')
args = parser.parse_args()
config = Config().initialize()
try:
    health = LocalClient(config, 'bridge').request('/health')
    world, character = health.get('world_id'), health.get('character_name')
    if not isinstance(world, str) or not world.startswith('world:') or not character:
        raise RuntimeError('Load the intended character into your world first')
    print(json.dumps({'world_id': world, 'character_name': character, 'paused': health.get('paused')}, indent=2))
    if args.apply:
        LocalClient(config, 'bridge').request('/control/stop', {})
        target = config.home / 'settings.json'
        backup = config.home / 'backups' / ('player-settings-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
        private_write(backup, target.read_text())
        settings = json.loads(target.read_text())
        settings.update(world_id=world, character_name=character)
        private_write(target, json.dumps(settings, indent=2) + '\n')
        print('Local settings updated. Restart Valheim and the local service to load them. Backup: ' + str(backup))
    else:
        print('Read-only preview. Use --apply after confirming this is the intended character/world.')
except (OSError, RuntimeError, ValueError) as exc:
    parser.exit(1, str(exc) + '\n')
