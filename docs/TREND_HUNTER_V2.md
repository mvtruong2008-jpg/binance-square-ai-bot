# AI Trend Hunter 2.0 — Binance Square

## What's new
- A live evidence-based selection layer ranks **eligible** supported spot coins every batch.
- Data: Binance market-only `/api/v3/ticker/24hr?symbols=[...]`, optional CoinGecko `/api/v3/search/trending`, and Google News RSS headlines. CoinGecko IDs are matched exactly to prevent similarly named coins from being mixed up.
- The strongest 10 market candidates are checked for recent RSS headlines (parallel, bounded). A candidate gets a freshness bonus only when a unique attributed headline is 2 minutes–36 hours old.
- The resulting `data/trend_plan.json` records each coin's evidence and is used by each per-coin publishing subprocess; the story is never fabricated when RSS is missing.
- Gemini uses one of four rotating editorial angles and must clearly distinguish a headline report from verified **current** Binance/CoinGecko market data.
- Logs report candidate scores and reasons, and Actions upload the trend plan alongside images.
- Existing 5 posts / 6 hours, 12-hour coin cooldown, 60-second gap, daily cap, existing credentials and square-post publisher stay intact.

## How scoring works
The experimental score is: up to **22** for 24-hour USDT quote turnover (log scale), **15** for absolute 24-hour price movement, **32** for CoinGecko trending-search rank, and **24** for a fresh RSS headline (smaller bonus for older headlines). It is a heuristic for selecting **topics**, not an estimate of returns, sentiment, future price, or Binance platform popularity. Never present the internal score as an investment rating.

## Secrets, limits and source outages
- No new credentials required. The existing `COINGECKO_DEMO_KEY` secret is used if present. Public Binance market data needs no exchange credentials. Binance Square publishing still uses `BINANCE_SQUARE_OPENAPI_KEY`.
- If a source is unavailable/rate-limited, the other source(s) still contribute. If all fail, rank reverts to previously eligible coin order. Publishing does not have to succeed if the existing market/publisher/Gemini APIs fail.
- The trending plan expires after 2 hours so that stale headline evidence is not reused.
- Original news ingestion supplies **RSS headlines only**, not full independently verified articles; the prompt requires attribution and no unsupported claims. Human spot-checks remain advisable for consequential headlines.
- The planner cannot observe Binance Square post views, quality comments, cashtag clicks or commissions through its existing publishing interface. Do not claim an automatic engagement-learning loop or CTR improvement until a reliable analytics feed is connected.

## Operations
- Feature flag in `.github/workflows/auto-post.yml`: `TREND_HUNTER_ENABLED: "true"`.
- To immediately revert selection logic without deleting work: set that environment variable to `"false"` and commit; the old coin rotation, RSS and Gemini publishing flow remain available.
- Offline tests: `python -m unittest discover -s tests -p "test_*.py" -v`; dependency `Pillow>=11,<13`.
- Scheduled live publishing uses 07:37, 13:37, 19:37, 01:37 in Vietnam, subject to GitHub Actions cron delays.
- Manual workflow run defaults to **preview only**. The heartbeat commit `trigger:binance-5post-preview` also generates previews without publishing.
- Each workflow artifact now includes `data/trend_plan.json` to allow manual review of selected coins and headline evidence.

## Analytics roadmap (not yet an automatic source)
Use Binance Square Creator Center to review genuine views, comments, follows, and any available W2E rewards per post. A later engagement-learning module should only be enabled when these measurements are accessible programmatically or supplied with permission. Raw click-through rate is unknown without impression + coin-click data. Optimizing a story for discussion must not create fake urgency, duplicate material, or engagement manipulation.

## References
- Binance market data: https://developers.binance.me/en/docs/products/spot/faqs/market_data_only
- CoinGecko API: https://docs.coingecko.com/
- GitHub Actions schedule semantics: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- Binance W2E terms: https://www.binance.com/en/square/post/377977188380155
