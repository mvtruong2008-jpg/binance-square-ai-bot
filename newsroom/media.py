"""Only explicitly licensed media, otherwise original data graphics."""
from __future__ import annotations

import hashlib
import io
import textwrap
import urllib.parse
from pathlib import Path

from PIL import Image, ImageDraw
from bot import font, ellipsize
from .hunters import clean


def commons(http, coin):
    """Search Commons metadata, accepting only assets requiring no attribution."""
    query = urllib.parse.urlencode({"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
                                    "gsrsearch": coin["name"] + " cryptocurrency", "gsrlimit": 4, "prop": "imageinfo",
                                    "iiprop": "url|extmetadata", "iiurlwidth": 1200})
    data = http.json("https://commons.wikimedia.org/w/api.php?" + query)
    for page in data.get("query", {}).get("pages", {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        license_name = meta.get("LicenseShortName", {}).get("value", "")
        attribution = meta.get("AttributionRequired", {}).get("value", "true")
        name = coin["name"].casefold()
        if (license_name not in {"CC0", "Public domain"} or attribution.lower() != "false"
                or name not in page.get("title", "").casefold() or info.get("url", "").lower().endswith(".svg")):
            continue
        url = info.get("thumburl") or info.get("url", "")
        if urllib.parse.urlsplit(url).hostname != "upload.wikimedia.org":
            continue
        yield {"url": url, "license": "CC0", "license_url": meta.get("LicenseUrl", {}).get("value") or "https://creativecommons.org/publicdomain/zero/1.0/",
               "creator": clean(meta.get("Artist", {}).get("value", "Wikimedia Commons contributor")),
               "source_url": info.get("descriptionurl", ""), "coin_ids": [coin["id"]]}


def image_check(path):
    path = Path(path)
    with Image.open(path) as image:
        if image.width < 800 or image.height < 450 or image.width > 8000 or image.height > 8000:
            raise ValueError("Image dimensions rejected")
        image.verify()
    if path.stat().st_size > 8_000_000:
        raise ValueError("Image too large")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def produce(http, topic, cfg, output, layout):
    coin = topic["market"]
    path = Path(output) / (topic["id"] + ".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    # No assumption that an official/social image is licensed merely because it is public.
    assets = list(cfg.get("approved_media", []))
    if topic["sources"]:
        assets.extend(http.optional("Wikimedia licensed search", lambda: list(commons(http, coin)), []))
    for asset in assets:
        if (coin["id"] not in asset.get("coin_ids", []) or asset.get("license") not in {"CC0", "owned"}
                or not asset.get("license_url") or not asset.get("creator")):
            continue
        def download():
            body = http.request(asset["url"], limit=8_000_000, retries=1)
            with Image.open(io.BytesIO(body)) as image:
                if image.width * image.height > 32_000_000:
                    raise ValueError("Image too large")
                image.convert("RGB").save(path, "PNG")
            digest = image_check(path)
            return {**asset, "path": path.name, "sha256": digest, "original": False}
        media = http.optional("Licensed image", download, None)
        if media:
            return media
    variant = layout % 3
    bg, fg, muted = (11, 18, 32), (241, 245, 249), (156, 172, 193)
    accent = (59, 221, 172) if coin["change"] >= 0 else (251, 121, 141)
    image = Image.new("RGB", (1200, 675), bg)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 15, 675), fill=accent)
    draw.text((54, 35), "X LEI  /  " + topic["kind"], font=font(25, True), fill=accent)
    draw.text((54, 79), ellipsize(draw, coin["name"] + "  /  " + coin["pair"], 1090, font(28, True)), font=font(28, True), fill=fg)
    if variant == 0:
        draw.text((54, 140), f"{coin['price']:,.6g} USDT", font=font(65, True), fill=fg)
        draw.text((54, 230), f"{coin['change']:+.2f}% / 24h", font=font(32), fill=accent)
        chart(draw, coin["prices"], (60, 310, 1135, 525), accent)
        draw.text((60, 538), "Closed hourly candles / last 25 hours", font=font(17), fill=muted)
    elif variant == 1:
        for y, label, value in ((160, "SPOT PRICE", f"{coin['price']:,.6g} USDT"),
                                (290, "24H CHANGE", f"{coin['change']:+.2f}%"),
                                (420, "CLOSED HOUR VOLUME / BASELINE", f"{coin['volume_ratio']:.2f}x")):
            draw.rounded_rectangle((54, y-10, 1140, y+105), radius=18, fill=(23, 35, 53))
            draw.text((80, y), label, font=font(18), fill=muted)
            draw.text((80, y+30), value, font=font(43, True), fill=fg)
    else:
        title = topic["title"] if topic["sources"] else f"{coin['change']:+.2f}% in 24 hours"
        lines = textwrap.wrap(title, width=44)[:4]
        for i, line in enumerate(lines):
            draw.text((54, 150+i*57), ellipsize(draw, line, 1090, font(40, True)), font=font(40, True), fill=fg)
        draw.text((54, 425), f"{coin['price']:,.6g} USDT  |  {coin['change']:+.2f}% / 24h", font=font(32), fill=accent)
        draw.text((54, 495), "Observed data. No price forecast.", font=font(24), fill=muted)
    draw.line((54, 580, 1140, 580), fill=(54, 67, 88), width=2)
    draw.text((54, 600), "Binance Spot / " + coin["asof"][:16].replace("T", " ") + " UTC", font=font(19), fill=muted)
    draw.text((54, 631), "Original X LEI graphic / market observations only", font=font(16), fill=muted)
    image.save(path, "PNG", optimize=True)
    return {"path": path.name, "sha256": image_check(path), "original": True,
            "license": "owned", "creator": "X LEI", "source": "Binance Spot public data", "layout": variant}


def chart(draw, prices, box, color):
    left, top, right, bottom = box
    low, high = min(prices), max(prices)
    span = max(high - low, high * .001)
    points = [(left+i*(right-left)/(len(prices)-1), bottom-(value-low)/span*(bottom-top)) for i, value in enumerate(prices)]
    for y in range(top, bottom+1, 50):
        draw.line((left, y, right, y), fill=(36, 48, 67))
    draw.line(points, fill=color, width=5)
