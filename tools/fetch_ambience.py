"""Regenerate src/squelch/assets/audio/ from an ambient-mixer template.

Run with:  uv run --project . python tools/fetch_ambience.py

The result is committed, so this runs about never — only to re-pull after
editing the mix on ambient-mixer.com. Keeping it in the repo is what makes
the asset directory reproducible rather than mysterious.

The mix is a set of independent loops, not a stream: the site's player
downloads every channel and sums them in the browser. This fetches the same
channel list the player fetches, downloads each mp3, and records the fader
positions in ambience.json so squelch can reproduce the mix itself.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
import urllib.request
from pathlib import Path

# The page embeds its template id in an `AmbientMixer.setup(<id>)` call. The
# id, not the pretty URL, is what the XML endpoint takes.
PAGE = "https://vehicles.ambient-mixer.com/air-traffic-control-with-plane"
TEMPLATE_XML = "https://xml.ambient-mixer.com/audio-template?id_template={}"
OUT = Path(__file__).resolve().parent.parent / "src" / "squelch" / "assets" / "audio"

# Cloudflare fronts both hosts and answers the stdlib's default User-Agent
# with a 403.
UA = "Mozilla/5.0 (compatible; squelch asset fetcher)"


def get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def tag(block: str, name: str) -> str:
    return re.search(rf"<{name}>(.*?)</{name}>", block, re.S).group(1)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def parse_license(page: str) -> dict:
    """The mix-level licence the page declares.

    Scraped rather than hard-coded: if the mix is re-published under
    different terms, the committed manifest must not keep asserting the old
    ones.
    """
    match = re.search(
        r'rel="license"\s+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S
    )
    if match is None:
        raise RuntimeError("no licence found on the page — do not ship the assets")
    return {"name": html.unescape(re.sub(r"<[^>]+>", "", match.group(2))).strip(),
            "url": match.group(1)}


def parse_credits(page: str) -> dict[str, str]:
    """Per-sample credit, keyed by the same name the template XML uses.

    The page lists these as `<li><strong>NAME</strong> by CREDIT</li>` under
    "List of audio files used". These are the only attribution the source
    publishes, and several samples are credited to named people, so this is
    the record squelch has to carry.
    """
    section = re.search(r"List of audio files used:(.*?)</ol>", page, re.S)
    if section is None:
        raise RuntimeError("no credits list found on the page")
    credits = {}
    for item in re.findall(r"<li>(.*?)</li>", section.group(1), re.S):
        text = html.unescape(re.sub(r"<[^>]+>", "", item))
        text = text.replace("\xa0", " ").strip().rstrip("+)").strip()
        name, _, credit = text.partition(" by ")
        credits[name.strip()] = credit.strip()
    return credits


def duration_of(path: Path) -> float:
    """Clip length, needed by the scheduler to place random events."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return round(float(out.stdout.strip()), 3)


def main() -> None:
    page = get(PAGE).decode("utf-8", "replace")
    template_id = int(re.search(r"AmbientMixer\.setup\((\d+)\)", page).group(1))
    xml = get(TEMPLATE_XML.format(template_id)).decode("utf-8", "replace")
    licence = parse_license(page)
    credits = parse_credits(page)

    OUT.mkdir(parents=True, exist_ok=True)
    channels = []
    for number, block in re.findall(r"<channel(\d)>(.*?)</channel\1>", xml, re.S):
        name = tag(block, "name_audio")
        path = OUT / f"{number}-{slugify(name)}.mp3"
        path.write_bytes(get(tag(block, "url_audio")))
        is_random = tag(block, "random") == "true"
        channels.append(
            {
                "file": path.name,
                "name": name,
                "duration_s": duration_of(path),
                # Fader positions, normalised: the site stores volume 0..100
                # and balance -100..100.
                "gain": int(tag(block, "volume")) / 100.0,
                "balance": int(tag(block, "balance")) / 100.0,
                "mode": "random" if is_random else "loop",
                "rate_per_hour": int(tag(block, "random_counter")) if is_random else None,
                # Displayed verbatim by the info modal. A stem with no credit
                # is a stem that cannot be shipped -- fail loudly here rather
                # than rendering a blank line to the user later.
                "credit": credits[name],
            }
        )
        print(f"{path.name}  {channels[-1]['duration_s']}s")

    manifest = {
        "source": PAGE,
        "template_id": template_id,
        "template_xml": TEMPLATE_XML.format(template_id),
        "retrieved": "2026-08-02",
        "license": licence,
        "note": (
            "gain and balance are the template's fader positions, normalised "
            "to 0..1 and -1..1. mode=loop plays continuously; mode=random "
            "fires discrete events at rate_per_hour. license and credit are "
            "as published by the source page and must be shown in-app."
        ),
        "channels": channels,
    }
    (OUT / "ambience.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {OUT / 'ambience.json'}")


if __name__ == "__main__":
    main()
