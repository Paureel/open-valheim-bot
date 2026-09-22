#!/usr/bin/env python3
"""Record a daily aggregate GitHub star count and render private-repo-safe SVGs."""
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "docs/media"


def record_sample(samples, day, stars):
    """Replace today's sample without inventing history or assuming counts grow."""
    if type(stars) is not int or stars < 0:
        raise ValueError("GitHub star count must be a nonnegative integer")
    dt.date.fromisoformat(day)
    by_day = {}
    for sample in samples:
        date = sample["date"]
        dt.date.fromisoformat(date)
        count = sample["stars"]
        if type(count) is not int or count < 0 or date > day:
            raise ValueError("Invalid saved star sample")
        by_day[date] = count
    by_day[day] = stars
    return [{"date": date, "stars": count} for date, count in sorted(by_day.items())]


def badge_svg(stars):
    count = f"{stars:,}"
    right = max(30, len(count) * 8 + 14)
    width = 48 + right
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" role="img" aria-label="stars: {count}">
<title>stars: {count}</title>
<path fill="#555" d="M0 0h48v20H0z"/><path fill="#d4a72c" d="M48 0h{right}v20H48z"/>
<g fill="#fff" text-anchor="middle" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11">
<text x="24" y="14">stars</text><text x="{48 + right / 2}" y="14" fill="#10151b">{count}</text>
</g></svg>
'''


def chart_svg(samples):
    start = dt.date.fromisoformat(samples[0]["date"])
    end = dt.date.fromisoformat(samples[-1]["date"])
    span = (end - start).days
    top = max(4, math.ceil(max(s["stars"] for s in samples) / 4) * 4)
    points = []
    for sample in samples:
        offset = (dt.date.fromisoformat(sample["date"]) - start).days
        x = 430 if not span else 66 + offset / span * 730
        y = 190 - sample["stars"] / top * 112
        points.append((x, y))
    grid = []
    for i in range(5):
        y = 190 - i * 28
        value = top * i // 4
        grid.append(f'<path d="M66 {y}H796" stroke="#28323e"/><text x="52" y="{y+4}" text-anchor="end" fill="#9ca9b8" font-size="12">{value:,}</text>')
    curve = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    last_x, last_y = points[-1]
    labels = (f'<text x="430" y="215" text-anchor="middle">{end.isoformat()}</text>' if not span else
              f'<text x="66" y="215">{start.isoformat()}</text><text x="796" y="215" text-anchor="end">{end.isoformat()}</text>')
    stars = f'{samples[-1]["stars"]:,}'
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="840" height="250" viewBox="0 0 840 250" role="img" aria-labelledby="title description">
<title id="title">GitHub star history: {stars} stars</title>
<desc id="description">Daily star-count snapshots from {start.isoformat()} to {end.isoformat()}. {len(samples)} recorded days.</desc>
<rect x="0.5" y="0.5" width="839" height="249" rx="12" fill="#10151b" stroke="#303d4b"/>
<g font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif">
<text x="28" y="36" fill="#edf2f7" font-size="18" font-weight="600">GitHub stars</text>
<text x="28" y="56" fill="#9ca9b8" font-size="12">Daily snapshots · updated {end.isoformat()} UTC</text>
<text x="796" y="40" text-anchor="end" fill="#75e1d3" font-size="25" font-weight="600">{stars}</text>
{''.join(grid)}
<polyline points="{curve}" fill="none" stroke="#75e1d3" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
<circle cx="{last_x:.2f}" cy="{last_y:.2f}" r="4.5" fill="#75e1d3"/>
<g fill="#9ca9b8" font-size="12">{labels}</g>
</g></svg>
'''


def main():
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise SystemExit("Set GITHUB_REPOSITORY to owner/repository")
    response = subprocess.run(
        ["gh", "api", f"repos/{repository}", "--jq", ".stargazers_count"],
        check=True, capture_output=True, text=True,
    )
    stars = json.loads(response.stdout)
    data = MEDIA / "star-history.json"
    samples = json.loads(data.read_text()) if data.exists() else []
    day = dt.datetime.now(dt.timezone.utc).date().isoformat()
    samples = record_sample(samples, day, stars)
    # Prepare every output before writing: API/validation errors preserve old assets.
    outputs = {data: json.dumps(samples, indent=2) + "\n",
               MEDIA / "stars.svg": badge_svg(stars),
               MEDIA / "star-history.svg": chart_svg(samples)}
    for path, content in outputs.items():
        path.write_text(content)
    print(f"Updated star tracker: {stars} stars, {len(samples)} daily samples")


if __name__ == "__main__":
    main()
