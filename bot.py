"""Binance Square: RSS -> Gemini -> price/chart/logo image -> Square post.

GitHub Actions supplies secrets in environment variables. No credentials here.
Manual runs are previews unless PUBLISH=true. Scheduled runs can publish.
Demo: python bot.py --demo (offline image test, never publishes).
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import random
import re
import subprocess
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

COINS = {
    "BTC": {"name": "Bitcoin", "query": "Bitcoin cryptocurrency when:2d", "gecko": "bitcoin", "color": "#F7931A"},
    "ETH": {"name": "Ethereum", "query": "Ethereum cryptocurrency when:2d", "gecko": "ethereum", "color": "#7E91ED"},
    "BNB": {"name": "BNB", "query": "BNB Chain cryptocurrency when:2d", "gecko": "binancecoin", "color": "#F3BA2F"},

    "SOL": {"name":"Solana","query":"Solana SOL cryptocurrency","gecko":"solana","color":"#9271E9"},
    "XRP": {"name":"XRP","query":"XRP Ripple cryptocurrency","gecko":"ripple","color":"#A7BCD0"},
    "DOGE":{"name":"Dogecoin","query":"Dogecoin DOGE cryptocurrency","gecko":"dogecoin","color":"#C6A858"},
    "ADA": {"name":"Cardano","query":"Cardano ADA cryptocurrency","gecko":"cardano","color":"#4E9BE9"},
    "AVAX":{"name":"Avalanche","query":"Avalanche AVAX crypto","gecko":"avalanche-2","color":"#E84142"},
    "LINK":{"name":"Chainlink","query":"Chainlink LINK crypto","gecko":"chainlink","color":"#2A5ADA"},
    "DOT": {"name":"Polkadot","query":"Polkadot DOT cryptocurrency","gecko":"polkadot","color":"#E6007A"},
    "LTC": {"name":"Litecoin","query":"Litecoin LTC crypto","gecko":"litecoin","color":"#345D9D"},
    "UNI": {"name":"Uniswap","query":"Uniswap UNI crypto","gecko":"uniswap","color":"#FF5AB3"},
    "AAVE":{"name":"Aave","query":"Aave AAVE DeFi cryptocurrency","gecko":"aave","color":"#9E68BF"},
    "SUI": {"name":"Sui","query":"Sui Network SUI crypto","gecko":"sui","color":"#6FBCF0"},
    "NEAR":{"name":"NEAR Protocol","query":"NEAR Protocol crypto","gecko":"near","color":"#FFFFFF"},
    "TRX": {"name":"TRON","query":"TRON TRX crypto","gecko":"tron","color":"#E34B5E"},
    "ATOM":{"name":"Cosmos","query":"Cosmos ATOM cryptocurrency","gecko":"cosmos","color":"#5065A0"},
    "ARB": {"name":"Arbitrum","query":"Arbitrum ARB crypto","gecko":"arbitrum","color":"#56A0E8"},
    "OP":  {"name":"Optimism","query":"Optimism OP blockchain crypto","gecko":"optimism","color":"#FF0420"},
    "FIL": {"name":"Filecoin","query":"Filecoin FIL cryptocurrency","gecko":"filecoin","color":"#0090FF"},
    "XLM": {"name":"Stellar","query":"Stellar XLM crypto","gecko":"stellar","color":"#F2F2F2"},
    "HBAR":{"name":"Hedera","query":"Hedera HBAR cryptocurrency","gecko":"hedera-hashgraph","color":"#A9B2C2"},
    "APT": {"name":"Aptos","query":"Aptos APT crypto","gecko":"aptos","color":"#29B394"},
    "ETC": {"name":"Ethereum Classic","query":"Ethereum Classic ETC crypto","gecko":"ethereum-classic","color":"#4A9A73"},
}
HISTORY = Path("data/history.json")
PILOT_SYMBOL = os.getenv("PILOT_SYMBOL", "").strip().upper()
OUTPUT = Path("output") / (f"market_card_{PILOT_SYMBOL.lower()}.png" if PILOT_SYMBOL else "market_card.png")
BINANCE_SKILL = Path("binance-skills-hub/skills/binance/square-post")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
PUBLISH = os.getenv("PUBLISH", "false").lower() in ("1", "true", "yes")


def get_json(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "BinanceSquareMarketCard/1.0", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Market/News HTTP {error.code} from {urllib.parse.urlparse(url).netloc}") from error


def choose_symbols(history):
    """Choose less-recently posted coins; the pilot can force one coin."""
    if PILOT_SYMBOL:
        if PILOT_SYMBOL not in COINS:
            raise RuntimeError("Unsupported PILOT_SYMBOL: " + PILOT_SYMBOL)
        return [PILOT_SYMBOL]
    return sorted(COINS, key=lambda sym: (str(history.get("symbol:" + sym, "")), sym))[:6]


def fetch_stories(symbols):
    """Read RSS titles, not full articles. URLs stay out of public posts."""
    now = datetime.now(timezone.utc)
    stories = {}
    for symbol in symbols:
        coin = COINS[symbol]
        query = urllib.parse.quote(coin["query"] + " when:2d")
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                root = ET.fromstring(resp.read())
        except (urllib.error.URLError, ET.ParseError, TimeoutError) as exc:
            print(f"RSS warning [{symbol}]: {type(exc).__name__}")
            continue
        for item in root.findall("./channel/item")[:25]:
            raw_title = (item.findtext("title") or "").strip()
            date_string = item.findtext("pubDate") or ""
            try:
                pubdate = parsedate_to_datetime(date_string)
                if pubdate.tzinfo is None:
                    pubdate = pubdate.replace(tzinfo=timezone.utc)
                pubdate = pubdate.astimezone(timezone.utc)
            except (ValueError, TypeError, IndexError):
                continue
            if not raw_title or not now - timedelta(hours=48) <= pubdate <= now + timedelta(minutes=10):
                continue
            headline, separator, publisher = raw_title.rpartition(" - ")
            if not separator:
                headline, publisher = raw_title, "A news outlet"
            title_normalized = re.sub(r"[^a-z0-9]+", "", headline.casefold())
            if not title_normalized:
                continue
            fingerprint = hashlib.sha256(title_normalized.encode()).hexdigest()
            stories[fingerprint] = {
                "id": fingerprint,
                "symbol": symbol,
                "headline": headline.strip(),
                "publisher": publisher.strip(),
                "date": pubdate.isoformat(),
            }
    return sorted(stories.values(), key=lambda story: story["date"], reverse=True)


def load_history():
    try:
        data = json.loads(HISTORY.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_history(history, story):
    now = datetime.now(timezone.utc)
    history[story["id"]] = now.isoformat()
    history["symbol:" + story["symbol"]] = now.isoformat()
    cutoff = now - timedelta(days=14)
    cleaned = {}
    for key, stamp in history.items():
        if not isinstance(stamp, str):
            continue
        try:
            dt = datetime.fromisoformat(stamp)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt.astimezone(timezone.utc) >= cutoff:
                cleaned[key] = stamp
        except ValueError:
            continue
    history = cleaned
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(history, indent=2), encoding="utf-8")


def get_binance_market(symbol):
    """Unauthenticated Binance Spot endpoint; quotes are in USDT."""
    pair = f"{symbol}USDT"
    api = "https://data-api.binance.vision/api/v3"
    ticker = get_json(f"{api}/ticker/24hr?{urllib.parse.urlencode({'symbol': pair})}")
    klines = get_json(f"{api}/klines?{urllib.parse.urlencode({'symbol': pair, 'interval': '1h', 'limit': 168})}")
    prices = [float(candle[4]) for candle in klines]
    price = float(ticker["lastPrice"])
    change = float(ticker["priceChangePercent"])
    if len(prices) < 12 or not all(math.isfinite(p) and p > 0 for p in prices):
        raise RuntimeError("Binance supplied too few valid 7-day chart points")
    if not math.isfinite(price) or price <= 0 or not math.isfinite(change):
        raise RuntimeError("Invalid Binance ticker data")
    return {"symbol": symbol, "price": price, "change": change,
            "prices": prices, "quote": "USDT", "source": "Binance Spot", "asof": datetime.now(timezone.utc)}


def get_coingecko_market(symbol):
    """Optional fallback; a free Demo key increases reliability."""
    coin_id = COINS[symbol]["gecko"]
    base = "https://api.coingecko.com/api/v3"
    key = os.getenv("COINGECKO_DEMO_KEY", "").strip()
    headers = {"x-cg-demo-api-key": key} if key else {}
    market_url = f"{base}/coins/markets?{urllib.parse.urlencode({'vs_currency': 'usd', 'ids': coin_id})}"
    chart_url = f"{base}/coins/{coin_id}/market_chart?{urllib.parse.urlencode({'vs_currency': 'usd', 'days': 7})}"
    market = get_json(market_url, headers)
    chart = get_json(chart_url, headers)
    if not market:
        raise RuntimeError("CoinGecko returned no market record")
    prices = [float(row[1]) for row in chart.get("prices", [])]
    price = float(market[0]["current_price"])
    change = float(market[0]["price_change_percentage_24h"])
    if len(prices) < 12 or not all(math.isfinite(p) and p > 0 for p in prices):
        raise RuntimeError("CoinGecko supplied too few valid chart points")
    return {"symbol": symbol, "price": price, "change": change,
            "prices": prices, "quote": "USD", "source": "CoinGecko", "asof": datetime.now(timezone.utc)}


def get_market(symbol):
    try:
        return get_binance_market(symbol)
    except (RuntimeError, ValueError, KeyError, TypeError, urllib.error.URLError) as exc:
        print(f"Binance market warning: {exc}. Trying CoinGecko fallback.")
        try:
            return get_coingecko_market(symbol)
        except (RuntimeError, ValueError, KeyError, TypeError, urllib.error.URLError) as fallback_exc:
            raise RuntimeError(f"No usable live market data for {symbol}: {fallback_exc}") from fallback_exc


def gemini_post(story, market):
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY GitHub Secret")
    # Rotate editorial approach deterministically across news and coins.
    angles = (
        "Lead with the confirmed observable market fact and explain why it matters.",
        "Explain the difference between an interesting signal and a proven trend.",
        "Focus on the unanswered question and what evidence would clarify it.",
        "Offer a balanced bullish versus bearish interpretation without taking sides.",
    )
    index = int(hashlib.sha256(story["id"].encode()).hexdigest()[:2], 16) % len(angles)
    angle = angles[index]
    trend = story.get("trend") or {}
    extra = ""
    if trend.get("rank"):
        extra = f"CoinGecko trending-search rank at discovery: {trend['rank']} (not an investment rating)."
    prompt = f"""You are the editorial desk of an ORIGINAL English-language Binance Square crypto newsletter.
Write exactly 2-4 natural sentences, 35-85 words, for curious investors (not a trading signal).
Cryptocurrency: {COINS[story['symbol']]['name']} (${story['symbol']})
Headline or MARKET SNAPSHOT label: {story['headline']}
RSS publisher or market-data origin: {story['publisher']}
Headline publication time UTC: {story['date']}
Current verified {market['source']} market data: spot price {market['price']:.8g} {market['quote']}; 24h price change {market['change']:+.2f}%.
{extra}
Editorial perspective: {angle}
Strict publication rules:
- First sentence: informative, crisp hook that is supported by the supplied facts, not clickbait.
- Do not invent news events, catalyst explanations, sources, quotes, partnerships or trade volume.
- RSS provides only one headline, not verified article text. Attribute any news claim to its publisher,
  using tentative language where appropriate. Never imply independent confirmation.
- When the headline is a MARKET SNAPSHOT, use ONLY the verified live price and 24h change.
  Avoid implying a new news event, volume surge or trending rank unless supplied.
- Give one real useful interpretation or an uncertainty to watch; no price targets, fake urgency,
  guaranteed returns, buy/sell calls, or unsubstantiated hype.
- Include the relevant coin cashtag once in context (e.g. ${story['symbol']}).
  Never exceed TWO cashtags. You may use one relevant hashtag, but do not force it.
- An authentic discussion question is OPTIONAL; ask one only if it adds value.
- Absolutely NO URLs, Markdown links, fake source blocks, or claims of exclusive insights.
- Return only the final post text; no preface, headings, or notes.
"""
    endpoint = "https://generativelanguage.googleapis.com/v1beta/models/" + urllib.parse.quote(GEMINI_MODEL, safe="") + ":generateContent"
    payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.60}}).encode()
    req = urllib.request.Request(endpoint, data=payload, method="POST", headers={
        "x-goog-api-key": api_key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            response = json.load(resp)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Gemini API HTTP {exc.code}: confirm model/quota in AI Studio") from exc
    try:
        text = "".join(part.get("text", "") for part in response["candidates"][0]["content"]["parts"])
    except (KeyError, TypeError, IndexError) as exc:
        raise RuntimeError("Gemini returned no usable text") from exc
    return ensure_coin_cashtag(text, story["symbol"])


def ensure_coin_cashtag(text, symbol):
    """Ensure monetization eligibility is not lost if AI omits the relevant symbol.

    The cashtag remains descriptive, never an instruction to trade.
    """
    cleaned = clean_post(text)
    target = "$" + symbol.upper()
    present = {value.upper() for value in re.findall(r"(?<!\w)\$[A-Za-z][A-Za-z0-9]*", cleaned)}
    if target.upper() not in present:
        cleaned = clean_post(target + ": " + cleaned)
    return cleaned


def clean_post(text):
    text = re.sub(r"\[([^\]]+)\]\(https?://[^)]*\)", r"\1", text)
    text = re.sub(r"(?i)\b(?:https?://|www\.)[^\s<>]+", "", text)
    text = re.sub(r"(?i)\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>]*)?", "", text)
    text = re.sub(r"(?im)^\s*(?:source|nguồn|link|references)\s*:\s*.*$", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip(" \n\"'`-–")
    cashtags = re.findall(r"(?<!\w)\$[A-Za-z][A-Za-z0-9]*", text)
    if len(cashtags) > 2:
        # Strip extra cashtags without changing ordinary sentences.
        for surplus in cashtags[2:]:
            text = text.replace(surplus, "", 1)
        text = re.sub(r"[ \t]{2,}", " ", text)
    if not 40 <= len(text) <= 1200 or "http" in text.lower():
        raise RuntimeError("Generated post failed text/URL safety validation")
    return text.strip()


def font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        path = "/usr/share/fonts/truetype/dejavu/" + name
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            return ImageFont.load_default()


def ellipsize(draw, text, max_width, chosen_font):
    if draw.textbbox((0, 0), text, font=chosen_font)[2] <= max_width:
        return text
    while text and draw.textbbox((0, 0), text + "...", font=chosen_font)[2] > max_width:
        text = text[:-1]
    return text.rstrip() + "..."


def logo_image(symbol):
    """CC0 coin icons, falling back to a letter badge if GitHub is offline."""
    url = f"https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/128/color/{symbol.lower()}.png"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CryptoCard/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read(300_000)
        icon = Image.open(io.BytesIO(data)).convert("RGBA")
        return icon.resize((116, 116), Image.Resampling.LANCZOS)
    except (OSError, ValueError, urllib.error.URLError):
        return None


def money(value):
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:,.3f}"
    return f"{value:,.5f}"


def create_card(story, market, path=OUTPUT):
    """Create a 1200x675 original infographic from real live market data."""
    W, H = 1200, 675
    base = Image.new("RGB", (W, H), (10, 16, 31))
    px = base.load()
    for y in range(H):
        for x in range(W):
            glow = max(0.0, 1 - math.hypot((x - 1030) / 950, (y - 70) / 820))
            px[x, y] = (int(9 + 12 * glow), int(17 + 14 * glow), int(34 + 19 * glow))
    draw = ImageDraw.Draw(base)
    accent = (34, 211, 151) if market["change"] >= 0 else (251, 113, 133)
    WHITE = (244, 247, 252)
    MUTED = (148, 163, 184)
    BORDER = (42, 55, 75)
    draw.rounded_rectangle((42, 26, 1158, 648), radius=28, outline=BORDER, width=2)
    draw.text((74, 54), "MARKET  /  CRYPTO BRIEF", fill=(239, 193, 72), font=font(22, True))
    utc = market["asof"].strftime("%d %b %Y  %H:%M UTC")
    time_w = draw.textbbox((0, 0), utc, font=font(18))[2]
    draw.text((1125 - time_w, 56), utc, fill=MUTED, font=font(18))
    draw.line((74, 101, 1125, 101), fill=BORDER, width=2)

    image = logo_image(story["symbol"])
    if image:
        base.paste(image, (83, 126), image)
    else:
        draw.ellipse((84, 130, 195, 241), fill=COINS[story["symbol"]]["color"])
        draw.text((107, 165), story["symbol"], fill=(19, 25, 35), font=font(27, True))
    draw.text((226, 127), COINS[story["symbol"]]["name"], fill=WHITE, font=font(45, True))
    draw.text((226, 185), f"{story['symbol']}  /  {market['quote']}", fill=MUTED, font=font(23))

    price_text = money(market["price"])
    price_font = font(57, True)
    price_width = draw.textbbox((0, 0), price_text, font=price_font)[2]
    draw.text((1125 - price_width, 116), price_text, fill=WHITE, font=price_font)
    pct_text = f"24H  {market['change']:+.2f}%"
    box_font = font(24, True)
    pct_width = draw.textbbox((0, 0), pct_text, font=box_font)[2]
    xleft = 1125 - pct_width - 34
    draw.rounded_rectangle((xleft, 197, 1125, 242), radius=15, fill=(27, 54, 54) if market["change"] >= 0 else (68, 35, 49))
    draw.text((xleft + 17, 204), pct_text, fill=accent, font=box_font)

    draw.text((78, 267), "7-DAY PRICE TREND", fill=MUTED, font=font(18, True))
    left, right, top, bottom = 87, 1119, 313, 477
    for i in range(4):
        yy = top + i * (bottom - top) / 3
        draw.line((left, yy, right, yy), fill=BORDER, width=1)
    vals = market["prices"]
    lo, hi = min(vals), max(vals)
    pad = max((hi - lo) * .1, hi * .001)
    lo -= pad
    hi += pad
    n = len(vals)
    points = [(left + i * (right - left) / max(1, n-1), bottom - (v - lo) / (hi - lo) * (bottom - top)) for i, v in enumerate(vals)]
    area = [(left, bottom)] + points + [(right, bottom)]
    draw.polygon(area, fill=(19, 46, 54) if market["change"] >= 0 else (60, 33, 53))
    draw.line(points, fill=accent, width=5, joint="curve")
    x_last, y_last = points[-1]
    draw.ellipse((x_last-7, y_last-7, x_last+7, y_last+7), fill=accent)
    draw.text((86, 493), "7 DAYS AGO", fill=MUTED, font=font(16))
    right_text = "LATEST"
    draw.text((right - draw.textbbox((0, 0), right_text, font=font(16))[2], 493), right_text, fill=MUTED, font=font(16))

    draw.line((74, 532, 1125, 532), fill=BORDER, width=2)
    headline = re.sub(r"\s+", " ", story["headline"]).strip()
    headline = ellipsize(draw, headline, 1030, font(24, True))
    draw.text((77, 545), headline, fill=WHITE, font=font(24, True))
    footer = f"CHART / {market['source']}  |  7D history  |  {market['quote']}  |  News summary based on published headlines"
    draw.text((77, 603), ellipsize(draw, footer, 1050, font(15)), fill=MUTED, font=font(15))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    base.save(path, "PNG", optimize=True)
    print(f"IMAGE: {path} ({path.stat().st_size // 1024} KB)")
    return path


def post_image(post_text, image_path):
    if not os.getenv("BINANCE_SQUARE_OPENAPI_KEY"):
        raise RuntimeError("Missing BINANCE_SQUARE_OPENAPI_KEY GitHub Secret")
    script = BINANCE_SKILL / "scripts/post-image.mjs"
    if not script.exists():
        raise RuntimeError(f"Official Binance script missing: {script}")
    # Pass an absolute path as the official script runs from its own folder.
    cmd = ["node", "scripts/post-image.mjs", "--text", post_text, "--images", str(Path(image_path).resolve())]
    result = subprocess.run(cmd, cwd=BINANCE_SKILL, capture_output=True, text=True, timeout=240)
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        raise RuntimeError("Binance image publish failed: " + result.stderr.strip()[-1400:])
    if result.stderr:
        print("Binance publisher note:", result.stderr[-400:])


def demo():
    # Deliberately synthetic test data -- no fake price is ever published.
    story = {"symbol": "BTC", "headline": "Sample graphic: test layout using synthetic market data"}
    prices = [100 + i * .025 + 3 * math.sin(i / 8) for i in range(168)]
    market = {"price": prices[-1], "change": 1.26, "prices": prices,
              "quote": "USDT", "source": "DEMO (SYNTHETIC)", "asof": datetime.now(timezone.utc)}
    create_card(story, market)
    print("DEMO only: generated image, no API calls, nothing published.")


def planned_story(history):
    """Load a short-lived Trend Hunter decision for this specific coin only."""
    path_str = os.environ.get("TREND_PLAN_PATH", "")
    if not path_str or not PILOT_SYMBOL:
        return None
    try:
        plan = json.loads(Path(path_str).read_text(encoding="utf-8"))
        created = datetime.fromisoformat(plan["generated_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - created.astimezone(timezone.utc)
        if age < timedelta(0) or age > timedelta(hours=2):
            print("TREND_PLAN_EXPIRED: falling back to regular RSS discovery.")
            return None
        item = plan["items"][PILOT_SYMBOL]
        news = item.get("news")
        if news and news.get("id") not in history and news.get("symbol") == PILOT_SYMBOL:
            story = dict(news)
        else:
            now = datetime.now(timezone.utc)
            story = {
                "id": "market:" + PILOT_SYMBOL + ":" + now.strftime("%Y%m%d%H%M"),
                "symbol": PILOT_SYMBOL,
                "headline": COINS[PILOT_SYMBOL]["name"] + " market snapshot",
                "publisher": "Live market data (not a news event)",
                "date": now.isoformat(),
            }
        story["trend"] = {"rank": item.get("trend_rank")}
        return story
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(f"TREND_PLAN_WARNING: {type(exc).__name__}; using original discovery.")
        return None


def main():
    if "--demo" in sys.argv:
        demo()
        return
    if "--list-coins" in sys.argv:
        print(", ".join(COINS))
        return
    history = load_history()
    symbols = choose_symbols(history)
    print("Coin candidates:", ", ".join(symbols))
    story = planned_story(history)
    if story:
        print("TREND_EDITORIAL_SOURCE:", "RSS" if story.get("publisher") != "Live market data (not a news event)" else "MARKET_ONLY")
    else:
        stories = [item for item in fetch_stories(symbols) if item["id"] not in history]
        if stories:
            order = {symbol: i for i, symbol in enumerate(symbols)}
            stories.sort(key=lambda item: (order[item["symbol"]], -datetime.fromisoformat(item["date"]).timestamp()))
            story = stories[0]
    if story:
        pass
    elif os.getenv("ALLOW_MARKET_ONLY", "false").lower() == "true":
        symbol = symbols[0]
        now = datetime.now(timezone.utc)
        story = dict(
            id="market:" + symbol + ":" + now.strftime("%Y%m%d%H%M"),
            symbol=symbol,
            headline=COINS[symbol]["name"] + " market snapshot",
            publisher="Live market data (not a news event)",
            date=now.isoformat(),
        )
        print("Market-only fallback: no recent unused RSS headline")
    else:
        print("SKIP: No unused recent news headline. No post sent.")
        return
    print("News:", story["symbol"], story["headline"], "|", story["publisher"])
    market = get_market(story["symbol"])
    print("Market:", market["source"], money(market["price"]), market["quote"], f"{market['change']:+.2f}%")
    post_text = gemini_post(story, market)
    print("\n=== CLEAN POST ===\n" + post_text + "\n")
    picture = create_card(story, market)
    if not PUBLISH:
        print("TEST MODE: Image and post generated, NOT published.")
        return
    post_image(post_text, picture)
    save_history(history, story)
    print("DONE: Image post publisher completed; headline recorded in history.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
