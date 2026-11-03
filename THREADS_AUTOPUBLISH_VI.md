# Threads AI: Tự đăng bài thật lên tài khoản đã cấp quyền

## Luồng đăng chính thức

1. Thu thập công khai Google Trends VN, Google News RSS, VnExpress RSS và Hacker News.
2. Lọc chủ đề mới và nhờ Gemini viết **2 bản nháp tiếng Việt có góc nhìn riêng**, không sao chép bài báo và không bịa số liệu.
3. Đọc các bài Threads gần đây của CHÍNH tài khoản đã ủy quyền để kiểm tra trùng lặp và giờ giãn cách.
4. Chỉ chọn **1 bài** phù hợp nhất, tạo Threads text container qua API chính thức `POST /me/threads`, rồi đăng bằng `POST /me/threads_publish`.
5. Lưu ID bài đã xuất bản vào GitHub Actions Artifact; **không ghi token vào log hay commit**.

## Quyền cần thiết

Bạn phải lưu GitHub Actions Secrets `THREADS_ACCESS_TOKEN` là **User Access Token** của Threads có hai quyền:
- `threads_basic`
- `threads_content_publish`

Đây là quyền **đăng bài**, khác với `threads_keyword_search` (tìm bài người khác). Nguồn nội dung của bot không dùng `threads_keyword_search`, nên không cần xét duyệt quyền tìm kiếm công khai để nghiên cứu từ Google Trends/RSS. Tuy nhiên việc Meta cấp quyền đăng còn tùy ứng dụng, tài khoản thử nghiệm, trạng thái App Mode và chính sách Meta.

Nếu API báo `THREADS_PUBLISH_PERMISSION_OR_TOKEN_ERROR`, token của bạn có thể thiếu quyền `threads_content_publish` hoặc App chưa được Meta cho phép dùng quyền đó. Khi đó cần cấp lại quyền qua Threads Login hoặc User Token Generator và cập nhật Secret. Không có cách hợp lệ để dùng Threads API đăng thay người dùng mà không có ủy quyền phù hợp.

## Các cách chạy

Workflow: https://github.com/mvtruong2008-jpg/binance-square-ai-bot/actions/workflows/threads-auto-publish.yml

- **Chạy thử không đăng:** Actions → Threads AI - Public Trends Auto Publisher → Run workflow, để `publish=false`.
- **Đăng thật một bài:** Run workflow, bật `publish=true`. Đây là thay đổi công khai và không thể hủy qua GitHub.
- **Kích hoạt từ tệp:** cập nhật `automation/threads-publish-trigger.txt` và dùng commit message chính xác `trigger:threads-one-publish`. Bản xem trước: `trigger:threads-one-preview`.
- **Lịch 4 lần/ngày:** 02:47 / 08:47 / 14:47 / 20:47 giờ Việt Nam. Ban đầu chưa bật đăng theo lịch: phải xác nhận đăng thử thành công; sau đó người quản lý bật `THREADS_AUTOPOST_ENABLED=true` trong GitHub Actions repository variables. GitHub cron có thể trễ hoặc bỏ lỡ lượt chạy.

### Quy tắc an toàn

- Mỗi lượt chạy tối đa 1 bài, không đăng nhiều bài liền nhau.
- Bỏ qua lượt nếu đã đăng một bài trong 4 giờ gần đây, hoặc thấy 6 bài trong 24 giờ qua từ tài khoản.
- Từ chối bản nháp trùng/gần giống các bài của chính tài khoản Threads.
- Bản nháp giới hạn 500 ký tự, không chứa URL hoặc @mention, không có lệnh tương tác ngoài chức năng đăng.
- Nếu có lỗi mạng trong lúc đăng, **không tự retry** vì bài có thể đã lên Threads; cần kiểm tra tài khoản.
- Đây không phải công cụ tìm bài Threads viral. Thống kê nguồn là **tín hiệu tìm kiếm hoặc tiêu đề tin tức công khai**, không đo lượt thích/độ hot trên Threads.
- Tài khoản có thể cần được ủy quyền lại khi token hết hạn.

## Tài liệu chính thức

- https://developers.facebook.com/documentation/threads/posts#single-thread-posts
- https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api
