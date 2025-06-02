#!/usr/bin/env python3
# nasdaq_rule_filing_monitor.py
# Monitors https://listingcenter.nasdaq.com/rulebook/nasdaq/rulefilings
# and notifies Discord when a new row appears.
# ───────────────────────────────────────────────────────────────────────────

import itertools
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import requests
from bs4 import BeautifulSoup

# ──────────── SETTINGS ─────────────────────────────────────────────────────
CHECK_INTERVAL_SEC = 1          # poll frequency; 60 s keeps load tiny but fast
STATE_FILE         = Path("known_rows.json")
DISCORD_WEBHOOK    = (
    "https://discord.com/api/webhooks/"
    "1361772801802895430/THCcvPzFFArImOwC-RR6KJnfy_3bRRH6i-IH9PQZznKxgJIP46G4RoD9sfDB-VHvt8CJ"
)

# Base headers (everything except UA)
BASE_HEADERS: Dict[str, str] = {
    "accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
    "cache-control": "no-cache",
    "dnt": "1",
    "referer": "https://listingcenter.nasdaq.com/",
}

# Full raw list of UAs you provided
USER_AGENTS: List[str] = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Ubuntu Chromium/37.0.2062.94 Chrome/37.0.2062.94 Safari/537.36",
    "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/45.0.2454.85 Safari/537.36",
    "Mozilla/5.0 (Windows NT 6.1; WOW64; Trident/7.0; rv:11.0) like Gecko",
    "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:40.0) Gecko/20100101 Firefox/40.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_5) AppleWebKit/600.8.9 "
    "(KHTML, like Gecko) Version/8.0.8 Safari/600.8.9",
    "Mozilla/5.0 (iPad; CPU OS 8_4_1 like Mac OS X) AppleWebKit/600.1.4 "
    "(KHTML, like Gecko) Version/8.0 Mobile/12H321 Safari/600.1.4",
    # … if you have more, add them here …
]

# Small helper: inexpensive random UA every call
def random_headers() -> Dict[str, str]:
    return {**BASE_HEADERS, "user-agent": random.choice(USER_AGENTS)}


# Your rotating authenticated proxy pool
PROXY_CONFIG = [
    ("72.9.171.237",  12323, "14acfa7f9a57c", "74f453f102"),
    ("72.9.168.192",  12323, "14acfa7f9a57c", "74f453f102"),
    ("72.9.171.59",   12323, "14acfa7f9a57c", "74f453f102"),
    ("84.55.9.31",    12323, "14acfa7f9a57c", "74f453f102"),
    ("84.55.9.214",   12323, "14acfa7f9a57c", "74f453f102"),
    ("185.134.193.213",12323,"14acfa7f9a57c","74f453f102"),
    ("185.134.195.101",12323,"14acfa7f9a57c","74f453f102"),
    ("46.34.62.86",   12323, "14acfa7f9a57c", "74f453f102"),
    ("46.34.62.73",   12323, "14acfa7f9a57c", "74f453f102"),
    ("88.223.21.160", 12323, "14acfa7f9a57c", "74f453f102"),
    ("88.223.21.110", 12323, "14acfa7f9a57c", "74f453f102"),
    ("88.223.21.54",  12323, "14acfa7f9a57c", "74f453f102"),
    ("72.9.172.17",   12323, "14acfa7f9a57c", "74f453f102"),
    ("72.9.174.238",  12323, "14acfa7f9a57c", "74f453f102"),
    ("72.9.172.238",  12323, "14acfa7f9a57c", "74f453f102"),
    ("88.223.22.237", 12323, "14acfa7f9a57c", "74f453f102"),
    ("88.223.22.82",  12323, "14acfa7f9a57c", "74f453f102"),
    ("217.67.72.152", 12323, "14acfa7f9a57c", "74f453f102"),
    ("217.67.72.81",  12323, "14acfa7f9a57c", "74f453f102"),
    ("91.124.5.243",  12323, "14acfa7f9a57c", "74f453f102"),
]

# ──────────── INTERNAL UTILS ───────────────────────────────────────────────
_proxy_cycle = itertools.cycle(PROXY_CONFIG)  # simple round-robin iterator


def choose_proxy() -> Dict[str, str]:
    """
    Return a proxies={} dict suitable for `requests` using the next proxy.
    Format: {'http': 'http://user:pass@host:port', 'https': 'http://user:pass@host:port'}
    """
    host, port, user, pwd = next(_proxy_cycle)
    proxy_url = f"http://{user}:{pwd}@{host}:{port}"
    return {"http": proxy_url, "https": proxy_url}


def fetch_table(session: requests.Session) -> List[dict]:
    """Pull the table for the current year and return rows (dict with id + description)."""
    year = datetime.now().year
    url = "https://listingcenter.nasdaq.com/rulebook/nasdaq/rulefilings"
    resp = session.get(
        url,
        headers=random_headers(),
        timeout=30,
        proxies=choose_proxy()
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.select_one(f"#NASDAQ-tab-{year} > table")
    if not table:
        raise RuntimeError(f"Rule table for year {year} not found!")

    rows = []
    for tr in table.find_all("tr", id=True):
        # ID looks like SR-NASDAQ-2025-001
        row_id = tr["id"].strip()
        desc_cell = tr.find("td", attrs={"data-title": "Description"})
        if not desc_cell:  # Fallback: assume second cell is description
            tds = tr.find_all("td")
            desc_cell = tds[1] if len(tds) > 1 else None
        description = (
            desc_cell.get_text(strip=True).replace("\xa0", " ")
            if desc_cell else ""
        )
        rows.append({"id": row_id, "description": description})
    print(f"Fetched {len(rows)} rows for year {year}.")
    return rows


def load_known_ids() -> set:
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text()))
        except Exception:
            print("⚠️  Could not read state file, rebuilding from scratch.", file=sys.stderr)
    return set()


def save_known_ids(ids: set) -> None:
    with STATE_FILE.open("w") as fp:
        json.dump(sorted(ids), fp)


def notify_discord(row: dict) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    message = (
        f"🆕 **{row['id']}**\n"
        f"> {row['description']}\n"
        f"Detected at: `{timestamp}`"
    )
    try:
        # Use a standard header here; Discord expects JSON payload without custom UA requirements
        resp = requests.post(
            DISCORD_WEBHOOK,
            json={"content": message},
            timeout=15
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"❌ Discord notify failed: {e}", file=sys.stderr)


# ──────────── MAIN LOOP ────────────────────────────────────────────────────
def main() -> None:
    known_ids = load_known_ids()
    session = requests.Session()

    print("🔄 NASDAQ Rule-filing monitor started – polling every", CHECK_INTERVAL_SEC, "sec.")
    while True:
        try:
            rows = fetch_table(session)
            new_rows = [r for r in rows if r["id"] not in known_ids]
            if new_rows:
                # Process newest first (last row in table is usually newest)
                for row in reversed(new_rows):
                    print("→ New filing:", row["id"])
                    notify_discord(row)
                    known_ids.add(row["id"])
                save_known_ids(known_ids)
            else:
                print(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), "– no update.")
        except Exception as exc:
            print("⚠️  Error:", exc, file=sys.stderr)

        # Sleep the remaining time (simple blocking loop)
        time.sleep(CHECK_INTERVAL_SEC)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Exiting by user request.")
