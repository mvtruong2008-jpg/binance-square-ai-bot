# X LEI 3.0 — Vận hành newsroom

Newsroom chạy trên GitHub Actions, không cần PC bật. Luồng: danh tính cặp giao dịch → thị trường và RSS → cụm sự kiện → chấm điểm → biên tập → kiểm duyệt → ảnh có quyền sử dụng → ghi nhật ký trước khi đăng → bộ đăng ảnh Binance chính thức.

## Chạy và quan sát

```powershell
python -m pip install -r requirements-newsroom.txt
python -m unittest discover -s tests -v
python -m unittest discover -s threads-trend-bot/tests -v
python -m newsroom --mode PREVIEW
```

Trong GitHub → Actions → **X LEI 3.0 - Autonomous Newsroom**, chọn Run workflow, mode PREVIEW. Tải artifact `x-lei-newsroom-<run-id>`, giải nén và mở `index.html`. Dashboard chứa coin xu hướng, nguồn tin và thời điểm gốc, hàng đợi, điểm, bản nháp, ảnh, lịch sử, lỗi, số request và token AI. Dashboard được tạo từ dữ liệu thật từng lượt, không cần server hoặc dịch vụ trả phí; không có nút quản trị giả. Không xuất bản dashboard lên Pages vì báo cáo có thể chứa bản nháp chưa đăng.

Lịch quét: phút **17 và 47 mỗi giờ UTC**. Giới hạn mỗi lượt: tối đa một bài; mặc định ít nhất 70 phút giữa hai ý định đăng, tối đa **20 trong cửa sổ 24 giờ**. Bài đang reserved/unknown cũng chiếm ngân sách để tránh đăng bù khi lỗi. Không có yêu cầu phải đủ 20 bài.

GitHub Actions có thể trễ hoặc bỏ lượt lúc tải cao; lịch không bảo đảm thời gian thực và repository công khai có thể bị tắt lịch khi lâu không hoạt động. Xem lần chạy gần nhất trong Actions. Quyền miễn phí của Actions/Gemini có thể đổi; không tự bật billing hoặc dịch vụ có phí.

## Secrets và quyền

Giữ nguyên `GEMINI_API_KEY`, `BINANCE_SQUARE_OPENAPI_KEY`, `COINGECKO_DEMO_KEY` hiện có. Không đọc/ghi giá trị Secrets ra code, log hoặc artifact. Tùy chọn `REDDIT_ACCESS_TOKEN`: chỉ dùng khi Reddit phê duyệt đúng mục đích; có thể hết hạn, khi đó nguồn tự báo lỗi và bị bỏ qua. Không bắt buộc Reddit để chạy.

`GH_TOKEN` trong Actions dùng `github.token`, chỉ cần `contents: write` ở job vận hành để ghi branch trạng thái. Pull request chỉ chạy test, không cấp Secrets. Không dùng `pull_request_target`. Bộ đăng Binance được pin commit `7d1b1f78d525f9e653b96819f91a549302fda1da`; rà soát lại trước khi nâng pin. Không đổi API đăng hiện tại.

`GEMINI_MODEL` có thể đặt bằng repository variable; mặc định giữ model cũ. Chủ tài khoản đã xác nhận dùng Gemini miễn phí; `free_ai_confirmed` lưu xác nhận đó. AI có trần sáu request/lượt và giới hạn output; HTTP ghi không tự retry. Nếu hết quota hoặc model không có, tin cần AI bị loại, market snapshot có số liệu kiểm tra vẫn hoạt động. Không suy đoán hạn mức còn lại hoặc chi phí hóa đơn khi nhà cung cấp không trả dữ liệu đó.

## Kích hoạt và dừng

1. Chạy test và PREVIEW trên nhánh phát triển; kiểm tra artifact và nguồn.
2. Merge mã đã qua kiểm tra vào `main`.
3. Khởi tạo journal: Run workflow, chọn `initialize_state=true`. Không đăng ở bước này. Có thể tạo branch `x-lei-state` với `state.json` schema v3 bằng API và nhập bài cũ khi chuyển đổi.
4. Đổi `newsroom/control.json` trên **main**: `enabled=true`, `stop=false`. Đây là công tắc hoạt động thật; lịch sẽ chọn LIVE. Push thay đổi control chỉ chạy PREVIEW, tránh đăng ngay vì một commit cấu hình.
5. Kiểm tra một lượt LIVE và journal có trạng thái `published` cùng ID bài thật.

**Dừng khẩn cấp:** đặt `stop=true` trong `newsroom/control.json` trên main, hoặc repository variable `X_LEI_STOP=true` để các lượt mới dừng. LIVE tải lại control từ default branch ngay trước đăng và sau khi reserve; không phụ thuộc file cũ trong checkout. Lệnh đã được Binance tiếp nhận có thể hoàn thành dù vừa bật stop. Journal vẫn bảo toàn.

`enabled=true` chặn bộ đăng legacy trong `bot.py`, `pilot_bot.py`, `binance_batch.py`; hai workflow cũ và mới dùng cùng concurrency group. Chuyển về bot cũ: dừng newsroom trước, đối soát unknown rồi đặt enabled=false, stop=false. Chỉ một hệ đăng được hoạt động. Dữ liệu và tính năng Threads vẫn giữ nguyên.

## Dữ liệu và mức xác minh

- Danh sách coin động dựa trên instrument Binance đang TRADING và CoinGecko Binance tickers → coin ID/name. Ba trang instrument ưu tiên volume được cập nhật mỗi ngày; không có nghĩa là toàn bộ token trên thế giới. 24 danh tính đã kiểm tra trước đây tiếp tục dùng khi CoinGecko lỗi. Symbol mơ hồ, xung đột ID hoặc không xác minh được bị bỏ qua.
- Giá lấy từ Binance Spot public market-data, quote **USDT**, không giả làm USD. Ticker phải mới trong 5 phút. Volume spike dùng **giờ đã đóng gần nhất / trung bình 24 giờ đã đóng trước đó**, không đánh tráo volume 24h thành tốc độ tăng. Giá lên/xuống theo biến động 24h. Lượt quét 30 phút có thể lỡ biến động trong phút.
- RSS trực tiếp từ CoinDesk, Cointelegraph, Decrypt, Fed, SEC, ECB và Ethereum Foundation. Chỉ dùng tiêu đề và permalink nhà xuất bản, thời gian rõ ràng, trong sáu giờ. RSS không cung cấp toàn văn; không tuyên bố đã đọc bài. Nguồn nào chặn truy cập được ghi lỗi; nguồn khác vẫn chạy. Có thể thêm feed chính thức đã kiểm tra vào config.
- Listing/delisting/unlock/airdrop/upgrade/whale/macro/regulation được phân loại bằng dấu hiệu trong tin; không suy đoán lịch unlock hoặc giao dịch cá voi từ giá. Tin cần hai nhóm nhà xuất bản khác nhau hoặc một nguồn gốc chính thức. Hai tên báo chưa chắc độc lập: AI rà lại cùng sự kiện, dẫn lại cùng nguồn, phủ định và thời gian; nếu không đủ rõ thì bỏ.
- Nhận diện token dùng tên đầy đủ hoặc cashtag; từ thông thường như “near” không khớp NEAR Protocol. Tin macro dùng giá BTC phải ghi đó là thông tin thị trường riêng, không quy kết quan hệ nhân quả.
- Điểm 100: mới 25 + cộng đồng 25 + thị trường 20 + độ tin cậy 20 + khác biệt 10. Xem từng thành phần trên dashboard. Không có social/rank thì điểm cộng đồng bằng 0. Ngưỡng mặc định 65, có thể chỉnh config.
- Social: X API tính phí nên không gọi; Square chưa có discovery/analytics API được xác nhận nên không scrape private endpoint. Reddit OAuth đọc top/hot bài có tương tác, lưu **net score**, comments, từ khóa, cashtag và chênh lệch score/giờ giữa hai quan sát; không gọi đó là lượt thích hoặc engagement toàn thị trường. Bài xã hội là ý kiến, không tự thành bằng chứng sự kiện.

Không có bộ tự động nào bảo đảm “không bao giờ có tin sai”. Hai lượt Gemini cùng model không tương đương hai nhà kiểm chứng độc lập; headline có thể thiếu ngữ cảnh và nguồn chính thức vẫn có thể sai. Hệ thống giảm rủi ro bằng ràng buộc bằng chứng, từ chối thiếu dữ liệu và nhật ký kiểm tra. Với tình huống đòi hỏi xác minh toàn văn/chuyên gia, giữ PREVIEW và duyệt tay.

## Nội dung và ảnh

Tin có Gemini viết lại một câu từ bằng chứng, một lượt review riêng, kiểm tra số mới phát sinh, sao chép sáu từ liên tiếp, cashtag, URL, dữ liệu cũ, giật gân và trùng nội dung. Giá và phần trăm chèn bằng code từ dữ liệu đã kiểm tra. Market-only dùng câu mở đầu luân phiên và diễn giải có giới hạn để không bịa nguyên nhân. Tất cả nội dung 2–4 câu tiếng Anh, tối đa hai cashtag; không mua/bán hoặc hứa lợi nhuận. Sáu dạng bài được chọn theo bằng chứng, WHALE WATCH chỉ khi có tin cá voi đạt chuẩn.

Ảnh: danh sách ảnh được chủ sở hữu cấp quyền trong `approved_media` được xét trước; với tin, tìm Wikimedia Commons và chỉ nhận metadata CC0/public domain không bắt buộc attribution, tên coin khớp, URL upload đúng host. Không coi ảnh báo chí hoặc mạng xã hội công khai là được tái sử dụng. Không có ảnh hợp lệ thì tạo infographic gốc bằng Pillow, xoay ba bố cục; chart ghi rõ 25 giờ nến đã đóng. Lưu license, creator, nguồn và SHA-256; kiểm tra kích thước, dung lượng và hash trước đăng. Hiện không tự động dùng ảnh CC BY vì yêu cầu ghi nguồn/link giấy phép cần quy trình riêng.

## Chống trùng và đối soát

`x-lei-state/state.json` là nguồn sự thật của lịch sử LIVE, không phải Actions cache có thể mất. GitHub Contents API dùng SHA so sánh và đổi; xung đột dừng trước gửi bài. Ghi `reserved` thành công từ xa rồi mới gọi Binance. ID thành công thành `published`; timeout/thiếu ID thành `unknown`. Không tự retry lệnh publish không idempotent. Nếu ghi sau publish lỗi, journal vẫn có reserved và không gửi lại.

Hệ thống cung cấp **at-most-once attempt**, không tuyên bố exactly-once khi Binance chưa có idempotency key/read-back API được xác nhận. Unknown có thể là bài đã đăng hoặc chưa đăng. Đối soát trực tiếp Square; nếu đã đăng, cập nhật post_id/url/status trong journal. Không xóa journal để “sửa” lỗi. Lưu bản sao trước chỉnh tay. State branch thuộc repo công khai: chỉ lưu tin/bài công khai và thống kê; không lưu Secrets hoặc dữ liệu riêng.

Các bài legacy trước chuyển đổi cần nhập vào journal hoặc chờ đủ 24 giờ trước bật LIVE để tránh vượt trần tổng. Lịch sử cũ vẫn được giữ trong cache của workflow cũ; không xóa.

Journal nóng giữ 14 ngày; bài cũ được commit vào `archive/YYYY-MM-DD.json` trên state branch trước khi bỏ khỏi journal để dung lượng không tăng vô hạn. Dashboard hiện lịch sử gần nhất, archive giữ lịch sử lâu dài. Không xóa archive khi nâng cấp.

## Hiệu suất

Không có endpoint analytics Square đã xác nhận nên không tạo views/likes/shares giả. Có thể nhập export thật:

```json
[{"post_id":"ID_BAI_DA_DANG","source":"binance_export","observed_at":"2026-11-16T00:00:00+00:00","views":100,"likes":2,"comments":null,"shares":null,"coin_clicks":null}]
```

`python -m newsroom --mode LIVE --import-metrics metrics.json` cần token/quyền và vẫn tuân thủ mọi khóa đăng. Chỉ chấp nhận ID đã đăng, chỉ số nguyên không âm hoặc null. Export do quản trị viên nhập là dữ liệu tin cậy từ người vận hành; chương trình không chứng minh tính xác thực của file. Khi có tối thiểu năm bài có views và likes cho mỗi dạng, tỷ lệ like/view thật dùng để ưu tiên khi **đồng điểm chất lượng**; không tự hạ ngưỡng và không tối ưu theo số liệu chưa có.

Dashboard thống kê export thật theo dạng bài, coin, độ dài, bố cục ảnh và giờ UTC. `python -m newsroom --check-ai` kiểm tra kết nối Gemini và phản hồi JSON bằng một request, không đăng bài; workflow push chạy kiểm tra này trước PREVIEW.

## Nguồn kỹ thuật đã đối chiếu

- [Binance public market data](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md)
- [Binance Square publisher mã nguồn chính thức](https://github.com/binance/binance-skills-hub/tree/7d1b1f78d525f9e653b96819f91a549302fda1da/skills/binance/square-post)
- [CoinGecko ID list](https://docs.coingecko.com/reference/coins-list)
- [GitHub Actions schedule và giới hạn](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [X API pricing](https://docs.x.com/x-api/getting-started/pricing)
- [Reddit developer access](https://support.reddithelp.com/hc/en-us/articles/14945211791892-Developer-Platform-Accessing-Reddit-Data)
- [Wikimedia imageinfo](https://www.mediawiki.org/wiki/API:Imageinfo)

Không cần thêm framework crawler/LLM: urllib, ElementTree và GitHub platform đủ cho phạm vi này; tái sử dụng Pillow và bộ đăng Binance. Các thư viện client như PRAW/ccxt không giải quyết quyền truy cập, nên không thêm phụ thuộc không cần thiết.
