#!/usr/bin/env python3
"""
nasdaq_rule_filing_monitor.py  –  2025-06-03 “lazy-cookie + full-async”

Keeps the lazy-cookie/IPRoyal/Bot-token logic, but re-adds the
asynchronous-overlap pattern (bounded concurrent cycles + parallel Discord
posts) from your earlier script.
"""

import asyncio, json, random, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set

import aiohttp
from selectolax.parser import HTMLParser

# ────────────── CONFIG ─────────────────────────────────────────────────────
CHECK_INTERVAL_SEC        = 1.0
MAX_CONCURRENT_REQUESTS   = 5          # cycle overlap limit
CONCURRENCY_LIMIT         = 10         # max simultaneous HTTP ops inside a run
STATE_FILE                = Path("known_rows.json")

DISCORD_BOT_TOKEN         = (
    "MTI4NTI0NjExMzU2NTI0OTYzMQ.GVB7mn."
    "BZzO9Pd5HuaISXEy_rtpa1bHuQ8mszXDxY9MfI"
)
DISCORD_CHANNEL_ID        = "1069624139649912882"

IPROYAL_ENDPOINT          = "geo.iproyal.com:12321"
IPROYAL_AUTH              = "dFxlOFzx7ob6oWMx:Rz471juID8qR9AXY"

BASE_HEADERS: Dict[str, str] = {
    "accept":
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,application/"
        "signed-exchange;v=b3;q=0.7",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
    "cache-control": "no-cache",
    "dnt": "1",
    "referer": "https://listingcenter.nasdaq.com/",
}

USER_AGENTS = [ln.strip() for ln in open("user-agents.txt", encoding="utf-8")
               if ln.strip()]

def rnd_headers() -> Dict[str, str]:
    return {**BASE_HEADERS, "user-agent": random.choice(USER_AGENTS)}

def proxy_url() -> str:
    return f"http://{IPROYAL_AUTH}@{IPROYAL_ENDPOINT}"

# ────────────── COOKIE BOOTSTRAP ───────────────────────────────────────────
async def bootstrap_cookies(sess: aiohttp.ClientSession,
                            hdrs: dict, proxy: str) -> Dict[str, str] | None:
    try:
        async with sess.head(
            "https://listingcenter.nasdaq.com/rulebook/nasdaq",
            headers=hdrs, proxy=proxy, timeout=10
        ) as r:
            r.raise_for_status()
            return {k: m.value for k, m in r.cookies.items()}
    except Exception as exc:
        print(f"⚠️ cookie bootstrap failed: {exc}")
        return None

# ────────────── HTML FETCH & PARSE ─────────────────────────────────────────
async def get_html(sess: aiohttp.ClientSession, hdrs: dict,
                   proxy: str, cookies=None) -> str | None:
    try:
        async with sess.get(
            "https://listingcenter.nasdaq.com/rulebook/nasdaq/rulefilings",
            headers=hdrs, proxy=proxy, cookies=cookies, timeout=20
        ) as r:
            r.raise_for_status()
            return await r.text()
    except Exception as exc:
        print(f"❌ download failed: {exc}")
        return None

async def fetch_table(sess: aiohttp.ClientSession) -> List[dict]:
    year  = datetime.now().year
    hdrs  = rnd_headers()
    proxy = proxy_url()

    # optimistic pass
    html = await get_html(sess, hdrs, proxy)
    if html is None or f"NASDAQ-tab-{year}" not in html:
        cookies = await bootstrap_cookies(sess, hdrs, proxy)
        html    = await get_html(sess, hdrs, proxy, cookies)
        if html is None:
            return []

    root  = HTMLParser(html)
    table = root.css_first(f"#NASDAQ-tab-{year} > table")
    if table is None:
        print("⚠️ no <table> in page")
        return []

    rows = [{"id": tr.attributes["id"],
             "description": (tr.css_first('td[data-title="Description"]')
                              or tr.css("td")[1]).text(strip=True)}
            for tr in table.css("tr[id]")]
    print(f"Fetched {len(rows)} rows for year {year}.")
    return rows

# ────────────── STATE PERSISTENCE ──────────────────────────────────────────
async def load_known() -> Set[str]:
    try:
        return set(json.loads(STATE_FILE.read_text()))
    except Exception:
        return set()

async def save_known(ids: Set[str]) -> None:
    STATE_FILE.write_text(json.dumps(sorted(ids)))

# ────────────── DISCORD (BOT TOKEN) ────────────────────────────────────────
async def push_discord(row: dict, sess: aiohttp.ClientSession) -> None:
    ts  = datetime.now(timezone.utc).isoformat()
    msg = f"🆕 **{row['id']}**\n> {row['description']}\nDetected: `{ts}`"

    url = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages"
    hdr = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
    try:
        async with sess.post(url, json={"content": msg}, headers=hdr,
                             timeout=10) as r:
            r.raise_for_status()
            print(f"✅ pushed {row['id']}")
    except Exception as exc:
        print(f"❌ discord failed: {exc}")

# ────────────── ONE CYCLE ──────────────────────────────────────────────────
HTTP_SEMAPHORE = asyncio.Semaphore(CONCURRENCY_LIMIT)

async def cycle(sess: aiohttp.ClientSession, known: Set[str]) -> None:
    async with HTTP_SEMAPHORE:            # cap parallel network ops
        t0   = time.perf_counter()
        rows = await fetch_table(sess)
        dt   = time.perf_counter() - t0

    if not rows:
        print(f"⚠️ zero rows (t {dt:.2f}s)")
        return

    fresh = [r for r in rows if r["id"] not in known]
    if not fresh:
        print(datetime.utcnow().strftime("%H:%M:%S"), f"– no new (t {dt:.2f}s)")
        return

    # parallel Discord pushes
    tasks = [asyncio.create_task(push_discord(r, sess)) for r in reversed(fresh)]
    await asyncio.gather(*tasks)

    known.update(r["id"] for r in fresh)
    await save_known(known)
    print(f"🔍 {len(fresh)} new rows (t {dt:.2f}s)")

# ────────────── DRIVER ─────────────────────────────────────────────────────
async def main_async() -> None:
    known   = await load_known()
    limiter = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=False, limit=None)) as sess:
        print(f"🔄 monitor – every {CHECK_INTERVAL_SEC}s (full-async, IPRoyal)")
        while True:
            # allow overlap up to MAX_CONCURRENT_REQUESTS cycles
            async with limiter:
                asyncio.create_task(cycle(sess, known))
            await asyncio.sleep(CHECK_INTERVAL_SEC)

def main() -> None:
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n👋 bye")

if __name__ == "__main__":
    main()
