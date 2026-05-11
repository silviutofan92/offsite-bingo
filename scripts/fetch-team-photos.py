#!/usr/bin/env python3
"""
Build the team/ photo pack for the offsite-bingo Pong easter egg.

Modes:
  default (OFFSITE_BINGO_USE_PHOTOS unset / 0):
    Skip Slack entirely. For every roster entry generate team/<slug>.png
    (initials avatar). Public-safe. No PII written.

  OFFSITE_BINGO_USE_PHOTOS=1:
    For each roster entry, look up the email in ~/.local/share/offsite-bingo/roster.csv,
    call Slack users.lookupByEmail (requires SLACK_USER_TOKEN env var),
    and save image_512 -> team/<slug>.jpg when profile.is_custom_image is True.
    Fall through to initials .png otherwise.

File-type convention (do NOT change without re-reading the plan):
  team/<slug>.jpg  = real photo. SACRED. Never overwritten by this script.
                     (Lands here via Slack fetch or manual drop-in.)
  team/<slug>.png  = generated initials. REGENERABLE. Replaced every run.

Roster source-of-truth:
  Display names + slugs: ROSTER constant below (in this file).
  Emails: ~/.local/share/offsite-bingo/roster.csv (LOCAL ONLY, outside the repo).
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# --- Config -----------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
TEAM_DIR = REPO_ROOT / "team"
MANIFEST_PATH = TEAM_DIR / "manifest.js"

ROSTER_CSV_PATH = Path.home() / ".local" / "share" / "offsite-bingo" / "roster.csv"
USE_PHOTOS = os.environ.get("OFFSITE_BINGO_USE_PHOTOS", "0") == "1"
SLACK_TOKEN = os.environ.get("SLACK_USER_TOKEN", "").strip()

# Display name + slug only — NO emails here.
# Slug = email local-part with `.`→`-`. Becomes the filename and manifest key.
ROSTER: list[dict[str, str]] = [
    {"name": "Matthew Thomson", "slug": "matthew-thomson"},
    {"name": "Abdelhalim Dadouche", "slug": "abdelhalim-dadouche"},
    {"name": "Andrew Weaver", "slug": "andrew-weaver"},
    {"name": "Michael Shtelma", "slug": "michael-shtelma"},
    {"name": "Nikolay Manchev", "slug": "nikolay-manchev"},
    {"name": "Prashanth Babu", "slug": "prashanth-babu"},
    {"name": "Ryan Simpson", "slug": "ryan-simpson"},
    {"name": "Sepideh Ebrahimi", "slug": "sepideh-ebrahimi"},
    {"name": "Tomasz Bacewicz", "slug": "tomasz-bacewicz"},
    {"name": "Athulya Ramamoorthy", "slug": "athulya-ramamoorthy"},
    {"name": "Bilal Obeidat", "slug": "bilal-obeidat"},
    {"name": "Lars George", "slug": "lars-george"},
    {"name": "Laurent Léturgez", "slug": "laurent-leturgez"},
    {"name": "Louise Dilley", "slug": "louise-dilley"},
    {"name": "Matthieu Lamairesse", "slug": "matthieu-lamairesse"},
    {"name": "Silviu Tofan", "slug": "silviu-tofan"},
]

# Deterministic palette for initials backgrounds (Databricks-ish).
PALETTE = [
    (255, 54, 33),     # databricks orange-red
    (232, 119, 34),    # warm orange
    (58, 85, 96),      # slate
    (13, 29, 35),      # deep navy
    (78, 110, 84),     # forest
    (151, 71, 255),    # purple
    (52, 152, 219),    # blue
    (211, 84, 0),      # burnt
    (39, 174, 96),     # green
    (192, 57, 43),     # red
]

# --- Email lookup -----------------------------------------------------------

def load_emails() -> dict[str, str]:
    """Return {slug: email} from the local roster.csv.

    Only used when USE_PHOTOS is set. The file lives outside the repo;
    if it's missing we exit with a clear instruction.
    """
    if not ROSTER_CSV_PATH.exists():
        sys.exit(
            f"\nphotos-on mode requested but roster.csv is missing.\n"
            f"\nExpected at: {ROSTER_CSV_PATH}\n"
            f"\nCreate it with two columns (slug,email), one row per teammate, e.g.:\n"
            f"  slug,email\n"
            f"  silviu-tofan,silviu.tofan@databricks.com\n"
            f"  ...\n"
            f"\nThe slugs must match the ROSTER list in this script.\n"
        )
    out: dict[str, str] = {}
    with ROSTER_CSV_PATH.open("r", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            slug = (row.get("slug") or "").strip()
            email = (row.get("email") or "").strip()
            if slug and email:
                out[slug] = email
    return out


# --- Slack ------------------------------------------------------------------

def slack_lookup(email: str) -> dict | None:
    """Return Slack profile dict for an email, or None if not found."""
    if not SLACK_TOKEN:
        sys.exit(
            "photos-on mode requires SLACK_USER_TOKEN env var. "
            "Get a user token with users:read.email scope at api.slack.com."
        )
    url = "https://slack.com/api/users.lookupByEmail?" + urllib.parse.urlencode({"email": email})
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {SLACK_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)
    except Exception as e:
        print(f"  slack error for {email}: {e}", file=sys.stderr)
        return None
    if not data.get("ok"):
        print(f"  slack not-ok for {email}: {data.get('error')}", file=sys.stderr)
        return None
    return data.get("user", {}).get("profile", {})


def download(url: str, dest: Path) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            dest.write_bytes(resp.read())
        return True
    except Exception as e:
        print(f"  download failed {url}: {e}", file=sys.stderr)
        return False


# --- Initials avatar --------------------------------------------------------

def initial_letter(name: str) -> str:
    first = name.strip().split()[0]
    return first[0].upper() if first else "?"


def palette_color(slug: str) -> tuple[int, int, int]:
    h = hashlib.md5(slug.encode("utf-8")).digest()
    return PALETTE[h[0] % len(PALETTE)]


def find_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render_initials_png(name: str, slug: str, dest: Path) -> None:
    size = 256
    img = Image.new("RGB", (size, size), palette_color(slug))
    draw = ImageDraw.Draw(img)
    letter = initial_letter(name)
    font = find_font(size=160)
    bbox = draw.textbbox((0, 0), letter, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = (size - w) // 2 - bbox[0]
    y = (size - h) // 2 - bbox[1]
    draw.text((x, y), letter, fill=(255, 255, 255), font=font)
    img.save(dest, "PNG")


# --- Manifest ---------------------------------------------------------------

def write_manifest(entries: list[dict[str, str]]) -> None:
    payload = json.dumps(entries, ensure_ascii=False, indent=2)
    contents = (
        "// Auto-generated by scripts/fetch-team-photos.py. Do not hand-edit.\n"
        f"window.TEAM = {payload};\n"
    )
    MANIFEST_PATH.write_text(contents, encoding="utf-8")


# --- Main loop --------------------------------------------------------------

def main() -> int:
    TEAM_DIR.mkdir(parents=True, exist_ok=True)
    emails = load_emails() if USE_PHOTOS else {}

    mode = "photos-on" if USE_PHOTOS else "photos-off (initials only)"
    print(f"mode: {mode}, roster: {len(ROSTER)} people")

    entries: list[dict[str, str]] = []
    for r in ROSTER:
        slug = r["slug"]
        name = r["name"]
        jpg = TEAM_DIR / f"{slug}.jpg"
        png = TEAM_DIR / f"{slug}.png"

        # 1) JPG is sacred — never overwrite.
        if jpg.exists():
            print(f"  keep {slug}.jpg")
            entries.append({"name": name, "slug": slug, "file": f"{slug}.jpg"})
            continue

        # 2) Photos-on: try Slack.
        if USE_PHOTOS:
            email = emails.get(slug)
            if not email:
                print(f"  no email for {slug} — skipping Slack, will generate initials")
            else:
                profile = slack_lookup(email)
                if profile and profile.get("is_custom_image"):
                    url = profile.get("image_512") or profile.get("image_192")
                    if url and download(url, jpg):
                        print(f"  fetched {slug}.jpg from Slack")
                        entries.append({"name": name, "slug": slug, "file": f"{slug}.jpg"})
                        continue
                else:
                    print(f"  {slug}: no custom Slack image — falling through to initials")

        # 3) Initials PNG — always regenerated.
        render_initials_png(name, slug, png)
        print(f"  wrote {slug}.png (initials)")
        entries.append({"name": name, "slug": slug, "file": f"{slug}.png"})

    write_manifest(entries)
    print(f"\nwrote {MANIFEST_PATH} with {len(entries)} entries")
    return 0


if __name__ == "__main__":
    # urllib.parse is imported lazily so the default mode has no network dependencies at parse time
    import urllib.parse  # noqa: E402
    sys.exit(main())
