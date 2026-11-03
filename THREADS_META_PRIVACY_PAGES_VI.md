# Meta Threads: URL chính sách quyền riêng tư bằng GitHub Pages

Trang đã được xây dựng trong thư mục `docs/` của repository PUBLIC này.

## Một bước bật GitHub Pages trong giao diện GitHub

1. Đăng nhập GitHub bằng tài khoản chủ repository.
2. Mở **https://github.com/mvtruong2008-jpg/binance-square-ai-bot/settings/pages**
3. Tại **Build and deployment → Source** chọn **Deploy from a branch**.
4. Tại **Branch**, chọn **main** và thư mục **/docs**, sau đó nhấn **Save**.
5. Sau khi GitHub Pages báo trang đã xuất bản (hiển thị nút Visit site), mở website để kiểm tra nội dung.

Không cần mua tên miền, tạo server hoặc cài thêm workflow. GitHub Pages hỗ trợ xuất bản từ `main /docs`. GitHub Free dùng được Pages cho repository công khai.

## Các URL dự kiến (chỉ dùng khi đã truy cập được bình thường)

- Trang chủ: https://mvtruong2008-jpg.github.io/binance-square-ai-bot/
- **Privacy Policy** (dán vào Meta): https://mvtruong2008-jpg.github.io/binance-square-ai-bot/privacy-policy/
- Data Deletion: https://mvtruong2008-jpg.github.io/binance-square-ai-bot/data-deletion/

**Quan trọng:** Đường dẫn dự kiến không đồng nghĩa đã xuất bản. Đừng dán vào Meta khi còn lỗi 404 hoặc trang Pages chưa hoạt động.

## Điền trong Meta App Review

Trong ứng dụng `automation thread` → `Xét duyệt` → `Xét duyệt ứng dụng` → `Cài đặt ứng dụng`:
1. `URL chính sách quyền riêng tư`: dán đường dẫn Privacy Policy ở trên.
2. `Hạng mục ứng dụng`: chọn hạng mục đúng với công cụ nghiên cứu nội dung, ví dụ Productivity nếu Meta có hiển thị.
3. Tải biểu tượng ứng dụng hợp lệ, kiểm tra các trường bắt buộc khác rồi bấm Tiếp.
4. Nếu Meta yêu cầu `User Data Deletion URL` hoặc `Data deletion instructions`, dùng link Data Deletion.
5. Chỉ khai báo các quyền thực sự cần và thể hiện trong ứng dụng. Chưa có chức năng đăng Threads công khai.

## Chính sách hiện có mô tả

- Chỉ đọc hồ sơ người đã cấp quyền và dữ liệu công khai được Threads API cho phép.
- Sử dụng Gemini để tạo bản nháp; trích đoạn bài nguồn có thể được gửi đến Google.
- Token qua GitHub Actions Secrets; lịch sử xử lý trong GitHub Actions và các bản nháp trong Artifacts hiện có hạn giữ 3 ngày.
- Do repository công khai, các bản nháp/artifact có thể được người khác tiếp cận; không dùng workflow này với dữ liệu bí mật.
- Quy trình rút quyền và yêu cầu xóa dữ liệu.
- Liên hệ qua GitHub Issues (công khai; không gửi thông tin nhạy cảm).

**Vấn đề cần chú ý trước khi gửi Meta:** URL là bắt buộc nhưng **không đủ để Meta duyệt**. Meta có thể yêu cầu mô tả sử dụng, video demo thực, quyền truy cập người xét duyệt, thông tin liên hệ và xác minh tùy trường hợp. Chính sách phải luôn được cập nhật cho đúng hệ thống thực tế.

Không thêm token, App Secret, mật khẩu, private user data vào các tệp HTML hay repo công khai.

## Tài liệu GitHub chính thức

https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site
