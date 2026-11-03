# Kết nối Threads API thật — hướng dẫn từng bước

**Tài liệu Threads API KHÔNG phải API token.** Chỉ chủ tài khoản có thể đăng nhập Meta, cấp quyền và tạo token.

## Bước 1 — Tạo Meta Threads App

1. Đăng nhập https://developers.facebook.com/apps/.
2. Chọn Create App (Tạo ứng dụng).
3. Đặt tên gợi ý: Threads Trend Research VN, điền email liên hệ chính chủ.
4. Chọn use case **Access the Threads API** (Truy cập API Threads). Tên menu có thể thay đổi.
5. Hoàn tất tạo app (Meta có thể yêu cầu xác minh người dùng).

Chỉ yêu cầu quyền cần thiết cho dự án: **threads_basic**, **threads_keyword_search**.
**KHÔNG cần threads_content_publish** vì giai đoạn này chỉ tạo bản nháp.

## Bước 2 — Tạo Threads Tester và cấp quyền

1. Trong Meta App Dashboard, mở Use cases → Access the Threads API → Customize → Settings (hoặc mục Threads API Settings).
2. Tại phần **User Token Generator**, **Add or Remove Threads Testers** nếu chưa có tài khoản.
3. Nhập username Threads của bạn, thêm tài khoản làm tester.
4. Trên Threads của bạn, vào **Settings → Account → Website permissions → Invitations** (tên có thể khác trên phiên bản mới) và **Accept** lời mời.
5. Trở lại Meta Developer Dashboard → Threads API Settings → User Token Generator → **Generate Access Token**, xác nhận bằng tài khoản Threads.

Lưu ý: Token là thông tin đăng nhập rất nhạy cảm. **KHÔNG gửi token, App Secret, ảnh chứa token hoặc đường link có token trong chat.**

## Bước 3 — Lưu token trong GitHub Secrets

1. Vào https://github.com/mvtruong2008-jpg/binance-square-ai-bot/settings/secrets/actions
2. Nhấn **New repository secret**.
3. Name: THREADS_ACCESS_TOKEN
4. Secret: dán token Threads vừa tạo trong Meta. Nhấn **Add secret**.

Token không được đưa vào mã nguồn hay mục Variables công khai. Repository này hiện là PUBLIC, nên KHÔNG lưu token vào tệp hoặc GitHub Issues.

## Bước 4 — Kiểm tra token bằng workflow có sẵn

1. Mở https://github.com/mvtruong2008-jpg/binance-square-ai-bot/actions/workflows/threads-api-verify.yml
2. Chọn **Run workflow** (nhánh main), nhấn Run.
3. Mở lượt chạy để xem kết quả:

- PROFILE_OK: token có thể đọc profile đã ủy quyền.
- SEARCH_API_OK: endpoint tìm kiếm trả về dữ liệu.
- SEARCH_API_EMPTY: truy vấn hợp lệ nhưng không có kết quả; chưa chắc là lỗi.
- NOT_CONFIGURED: chưa thấy THREADS_ACCESS_TOKEN.
- THREADS_AUTH_FAILED: token sai/hết hạn/chưa được cấp quyền.
- THREADS_PERMISSION_DENIED: chưa có quyền tìm kiếm hoặc Meta chưa phê duyệt.

Ngay cả khi SEARCH_API_OK, **chưa chắc đã tìm được bài của người khác**. Với ứng dụng chưa qua Meta App Review cho quyền threads_keyword_search, kết quả tìm kiếm có thể chỉ gồm các bài của tài khoản đã ủy quyền.

## Bước 5 — Chạy tạo bản nháp từ dữ liệu Threads thật

1. Mở https://github.com/mvtruong2008-jpg/binance-square-ai-bot/actions/workflows/threads-trend-drafts.yml
2. Chọn Run workflow → source_mode = api.
3. Kết quả trong Artifacts / drafts.md / drafts.json, **KHÔNG ĐĂNG bài**.

Trong giai đoạn đầu chúng ta chỉ kiểm thử, không cấp quyền publishing.
Mọi bản nháp trên repository công khai có thể được người khác xem, nên không dùng cho nội dung riêng tư.

## Nếu cần tìm bài Threads công khai nhiều tài khoản

Meta có thể yêu cầu **App Review** cho threads_keyword_search trước khi mở truy vấn bài công khai của người khác. Phê duyệt do Meta quyết định; việc có token không đồng nghĩa đã được duyệt.

Không nên tự động lấy nội dung người khác để sao chép/đổi chữ. Bot lọc ý tưởng và yêu cầu Gemini viết góc nhìn độc lập.

## Chú ý bảo trì

Access Token có thời hạn. Đừng đăng token vào mạng xã hội hoặc ghi trong log; khi hết hạn cần làm mới token bằng cơ chế OAuth/refresh chính thức của Threads và cập nhật GitHub Secret.

Meta chính thức: https://developers.facebook.com/documentation/threads/get-started
Keyword Search: https://developers.facebook.com/documentation/threads/keyword-search
Meta Postman: https://www.postman.com/meta/threads/collection/dht3nzz/threads-api
