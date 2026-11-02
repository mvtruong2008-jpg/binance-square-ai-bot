import subprocess
import os
import json
import re
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

def get_news():
    query = urllib.parse.quote("Bitcoin Ethereum BNB cryptocurrency")
    url = (
        f"https://news.google.com/rss/search?q={query}"
        "&hl=en-US&gl=US&ceid=US:en"
    )
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        root = ET.fromstring(response.read())

    items = root.findall("./channel/item")[:5]
    return [
        {
            "title": item.findtext("title", ""),
            "date": item.findtext("pubDate", ""),
            "link": item.findtext("link", "")
        }
        for item in items
    ]

def generate_post(news):
    prompt = f"""
Create an original Binance Square crypto post in English.

News headlines:
{json.dumps(news, ensure_ascii=False)}

Rules:
- Write 2 to 4 short sentences.
- Use at most 2 cryptocurrency cashtags.
- Avoid financial advice and guaranteed profits.
- No invented numbers, quotes, prices or events.
- Attribute unverified headlines as reports.
- Use only information supported by the headlines.
- Do not include URLs, links, or source addresses in the post.
- Never display Google News RSS links.
- Write only the post content with relevant hashtags.
- Output the finished post only.
"""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{MODEL}:generateContent"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_KEY
        },
        method="POST"
    )
    with urllib.request.urlopen(request, timeout=60) as res:
        data = json.load(res)

    return data["candidates"][0]["content"]["parts"][0]["text"].strip()

news = get_news()

if not news:
    raise RuntimeError("No news found.")


# Remove URLs from AI-generated posts
post = re.sub(
    r"https?://[^\s<>]+",
    "",
    post
)

# Remove empty lines and extra spaces
post = "\n".join(
    line.strip()
    for line in post.splitlines()
    if line.strip()
).strip()

print("Post cleaned: URLs removed.")

if len(re.findall(r"\$[A-Za-z0-9]+", post)) > 2:
    raise RuntimeError("Too many cashtags.")

if not post or len(post) > 1500:
    raise RuntimeError("Invalid post length.")

print("=== AI GENERATED POST ===")
print(post)
print("=========================")

# Automatic Binance Square publishing
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

if DRY_RUN:
    print("TEST MODE: Post generated, not published.")
else:
    if not os.getenv("BINANCE_SQUARE_OPENAPI_KEY"):
        raise RuntimeError("Missing Binance Square API Key")

    print("Publishing to Binance Square...", flush=True)

    subprocess.run(
        [
            "node",
            "scripts/post-text.mjs",
            "--text",
            post
        ],
        cwd="binance-skills-hub/skills/binance/square-post",
        check=True,
        timeout=120
    )

    print("Binance publishing script finished.")

