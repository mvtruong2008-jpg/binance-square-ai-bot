# Threads AI Trend Bot — bản nháp tiếng Việt

**ĐÂY LÀ BẢN NHÁP. KHÔNG CÓ LỆNH ĐĂNG LÊN THREADS.**

## Đã xây dựng

- Sử dụng Meta Threads API chính thức để tìm bài TOP và RECENT theo 8 nhóm chủ đề tiếng Việt.
- Lọc tối đa 8 bài nguồn gần đây, ưu tiên chủ đề đa dạng.
- Dùng Gemini tạo 2 bản nháp mới, không chép hoặc chỉ viết lại lời người khác.
- Kiểm tra trùng lặp, độ dài, URL và mức độ tương đồng văn bản.
- Lưu drafts.md và drafts.json vào GitHub Actions Artifacts.
- Không gọi Threads publishing endpoints, không thả tim hoặc theo dõi tài khoản hàng loạt.

## Kết nối Threads API thật

Xem hướng dẫn từng bước: [META_SETUP_VI.md](META_SETUP_VI.md). Không gửi access token qua chat; chỉ lưu bằng GitHub Actions Secret `THREADS_ACCESS_TOKEN`.

## Tự động gia hạn Threads Token và tạo bản nháp theo lịch

Xem [TOKEN_MANAGER_VI.md](TOKEN_MANAGER_VI.md) để đổi token 1 giờ thành dài hạn 60 ngày, tự refresh mỗi tuần (cần GitHub PAT có quyền Secrets) và tùy chọn bật tạo bản nháp API thật 4 lần/ngày. Chưa tự đăng công khai.

## Chạy thử DEMO ngay

1. GitHub → Actions → Threads Trend Bot - Drafts Only.
2. Run workflow → source_mode = demo → Run workflow.
3. Mở run → tải tập tin threads-drafts trong Artifacts → xem drafts.md.

Dữ liệu demo gồm 16 ví dụ **tự dựng**, không phải bài thật và không phản ánh xu hướng mới nhất. Nếu Gemini API Key hợp lệ, hệ thống dùng Gemini; nếu Gemini không khả dụng ở chế độ demo, bot ghi rõ đang dùng bản nháp MẪU TĨNH. Không nhầm demo với nghiên cứu thực tế.

## Dùng Threads API thật

1. Mở https://developers.facebook.com/apps/ và tạo Meta App có Threads use case.
2. Thiết lập Threads Login/OAuth, xin quyền threads_basic và threads_keyword_search.
3. Tìm bài công khai của tài khoản khác có thể cần Meta App Review phê duyệt. Khi chưa được phê duyệt, tìm kiếm có thể chỉ bao gồm tài khoản thử nghiệm hoặc không có kết quả.
4. Vào GitHub Repository → Settings → Secrets and variables → Actions, thêm THREADS_ACCESS_TOKEN là Threads user access token của bạn. Không gửi khóa cho bất cứ ai.
5. Đảm bảo có GEMINI_API_KEY (GitHub Secret). Repository hiện tại có thể đã có từ bot Binance.
6. Chạy workflow với source_mode = api. Thiếu token/quyền sẽ báo lỗi; **KHÔNG tự dùng demo để giả làm tin thật**.

## Cảnh báo bảo mật quan trọng

**Repository chứa dự án này hiện là PUBLIC.** Artifact bản nháp, metadata nguồn và link nguồn có thể được truy cập trên GitHub. Không sử dụng cho nội dung riêng tư/bí mật; nên chuyển riêng sang kho PRIVATE trước khi vận hành với dữ liệu nhạy cảm. Tuyệt đối không đưa token, client secret, mật khẩu vào mã, log, README hay artifact.

TOP là **thứ tự xếp hạng tìm kiếm Meta**, không phải số liệu lượt thích/lượt xem. Bot không tự tuyên bố bài nào có số lượng tương tác cụ thể nếu API không cung cấp. Nội dung nguồn có thể sai; nên kiểm chứng trước khi đăng.

Workflow tự chạy khi thay đổi thư mục dự án trên main chỉ để tạo demo preview, không tự đăng công khai và không có lịch hẹn giờ.

## Tệp

- threads-trend-bot/trend_bot.py: tìm kiếm, chọn xu hướng, gọi Gemini, lưu bản nháp.
- threads-trend-bot/tests/test_trend_bot.py: kiểm thử ngoại tuyến.
- .github/workflows/threads-trend-drafts.yml: Actions chạy thử.
- threads-trend-bot/output/: kết quả tạm, không lưu trong mã nguồn.

## Tham khảo

- https://developers.facebook.com/docs/threads/
- https://www.postman.com/meta/threads/collection/dht3nzz/threads-api

Dự án được cách ly với Binance Square Bot về chức năng và workflow dù đang nằm cùng repository. Khi muốn một repository riêng biệt, hãy tạo PRIVATE repository và di chuyển các tệp này sang đó.
