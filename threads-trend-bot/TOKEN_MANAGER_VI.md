# Threads Token Manager — sử dụng lâu dài trên GitHub Actions

**Đã cài mã, chưa thể tự đưa khóa từ chat vào GitHub Secrets.** Kết nối GitHub của trợ lý chỉ cho phép sửa file và xem Actions, không cho phép ghi endpoint Actions Secrets. Đừng đưa token vào commit, README, issue hay log.

## Khóa cần thiết (GitHub Secrets)

Mở https://github.com/mvtruong2008-jpg/binance-square-ai-bot/settings/secrets/actions

| Tên | Nội dung | Dùng khi nào |
| --- | --- | --- |
| THREADS_ACCESS_TOKEN | **User Access Token** Threads còn hiệu lực, được cấp qua Meta Threads Login/OAuth | Bắt buộc để kiểm tra và tạo nháp từ bài thật |
| THREADS_APP_SECRET | App Secret của Meta Threads App (KHÔNG phải user token) | Chỉ bắt buộc khi đổi token ngắn hạn sang dài hạn |
| GH_SECRETS_PAT | GitHub fine-grained Personal Access Token có quyền **Secrets: Read and write** trên DUY NHẤT repository binance-square-ai-bot | Bắt buộc nếu muốn bot tự thay giá trị THREADS_ACCESS_TOKEN sau khi đổi hoặc gia hạn |

KHÔNG đưa khóa vào "Variables", vì Variables không được bảo mật như Actions Secrets.

### Cách tạo GH_SECRETS_PAT với quyền tối thiểu

1. GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token.
2. Resource owner: tài khoản GitHub của bạn.
3. Repository access: **Only select repositories** → binance-square-ai-bot.
4. Repository permissions: **Secrets → Read and write**. Để các quyền khác ở mức không cần thiết (Metadata: Read là quyền nền).
5. Chọn thời hạn phù hợp và lưu PAT vào GitHub Actions Secret GH_SECRETS_PAT. Nếu PAT hết hạn, gia hạn sẽ dừng; chọn thời hạn phù hợp và quản lý hạn sử dụng.

Cảnh báo: PAT có quyền viết Secrets là thông tin đặc biệt nhạy cảm. Bảo vệ nhánh main, hạn chế người có quyền sửa workflow và không chạy workflow lạ từ nguồn chưa tin cậy.

## Đổi token từ 1 giờ → 60 ngày (một lần)

1. Trong Meta App Dashboard, tạo User Access Token mới (mã token bạn từng dán vào chat có thể đã hết hạn; hãy tạo mã mới để dùng).
2. Lưu token này vào THREADS_ACCESS_TOKEN.
3. Lưu Meta App Secret đúng ứng dụng vào THREADS_APP_SECRET.
4. Lưu GitHub PAT vào GH_SECRETS_PAT.
5. Mở https://github.com/mvtruong2008-jpg/binance-square-ai-bot/actions/workflows/threads-token-manager.yml
6. Nhấn Run workflow, chọn mode = **exchange**.
7. Khi log báo TOKEN_EXCHANGE_OK, token dài hạn đã được lưu *thay thế* vào THREADS_ACCESS_TOKEN bằng GitHub REST API với LibSodium sealed-box encryption. Không cần tự sao chép token dài hạn.

Nếu token ban đầu đã là dài hạn, **không chạy exchange**: dùng inspect, rồi thử refresh khi token đã đủ 24 giờ tuổi.

## Kiểm tra và tự gia hạn

- mode = inspect: kiểm tra profile, KHÔNG chỉnh sửa token. Không thể xác định tuổi thọ chỉ bằng endpoint profile.
- mode = refresh: gia hạn long-lived token còn hạn, sau đó tự ghi token mới vào GitHub Secret. Không cần Meta App Secret.
- Scheduled: workflow có lịch hàng tuần vào **03:14 sáng thứ Hai (giờ Việt Nam)**. Để BẬT, vào https://github.com/mvtruong2008-jpg/binance-square-ai-bot/settings/variables/actions, thêm repository variable THREADS_AUTORENEW_ENABLED = true.
- Không bật lịch trước khi hoàn tất exchange và đã xác thực refresh hoạt động. Nếu Meta trả lỗi, workflow sẽ thất bại và KHÔNG âm thầm làm giả thành công.

Meta quy định refresh long-lived token sau khi token đã có tuổi ít nhất 24 giờ, trước khi hết hạn; một token hết hạn phải xác thực lại. Gia hạn không đảm bảo token tồn tại vô thời hạn.

## Tự tìm bài và tạo bản nháp 4 lần/ngày (chưa đăng công khai)

Khi có THREADS_ACCESS_TOKEN hợp lệ với threads_keyword_search, mở:
https://github.com/mvtruong2008-jpg/binance-square-ai-bot/settings/variables/actions

Thêm repository variable THREADS_DRAFT_SCHEDULE_ENABLED = true.

Khi đó workflow Threads Trend Bot - Drafts Only sẽ tự chạy 4 lần/ngày (giờ VN khoảng 02:19, 08:19, 14:19, 20:19; GitHub cron có thể trễ), sử dụng SOURCE_MODE=api. Chỉ tải dữ liệu qua Threads GET keyword_search, tạo bản nháp Gemini và lưu Artifact. **KHÔNG ĐĂNG THREADS**.

Workflow sẽ báo lỗi nếu quyền Threads keyword_search không đủ, thay vì tráo nội dung demo và gọi đó là bài viral.

## Vì sao có 2 bước chủ tài khoản phải làm?

Kết nối GitHub App của trợ lý **KHÔNG có quyền tạo hoặc cập nhật GitHub Actions Secrets**, và **KHÔNG đăng nhập tài khoản Meta**. Vì thế bạn phải tự dán token vào GitHub Secrets thông qua giao diện được bảo vệ một lần; bot sẽ tự gia hạn và cập nhật về sau nếu đã có GH_SECRETS_PAT.

Lưu ý repository hiện PUBLIC: GitHub Actions artifacts có thể công khai, không lưu nội dung riêng tư trong bản nháp. API token không được lưu vào mã nguồn hoặc artifact.

## Tham khảo

- Meta official API and token management: https://developers.facebook.com/documentation/threads/get-started
- Official Meta Threads Postman: https://www.postman.com/meta/threads/collection/dht3nzz/threads-api
- GitHub encrypted secrets: https://docs.github.com/en/rest/actions/secrets
