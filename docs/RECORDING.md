# Guided gameplay recording

The [included showcase](media/brain-showcase.mp4) pairs directed gameplay with
the brain observer and is labeled **Guided demonstration**. Move follows measured
movement and Talk follows in-game chat delivery.

The recording helper requires an operator-reviewed route. Do not reuse a motion
plan in an unseen location. It limits each movement segment to four seconds,
renews only against fresh captured frames, stops on health loss or operator/game
pause, and releases controls at the end. It uses normal movement, jumping,
chat, and the character's own inventory. No spawning, teleporting or server changes.

Set up the optional recording environment with native Python 3.12:

```sh
python3.12 -m venv .tools/recording
.tools/recording/bin/python -m pip install -r requirements-recording.txt
```

A plan is a JSON list. Each step has an `at` time in seconds, optional `duration`
(up to four seconds), `forward` (-1 to 1), `yaw_rate` (-70 to 70), `button` (`jump`
or `none`), `speech`, `tool` (`open_inventory` or `close_inventory`), and `label`.
Use an empty plan for a passive guided capture. The recording lasts 60 seconds.

```sh
PYTHONPATH=src /usr/bin/python3 scripts/record-guided.py \
  --plan /absolute/path/to/reviewed-plan.json --output recordings/take
.tools/recording/bin/python scripts/render-recording.py recordings/take \
  --output recordings/brain-showcase.mp4
```
