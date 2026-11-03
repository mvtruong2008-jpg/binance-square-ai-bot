# Binance Square – 5 bài liên tiếp mỗi đợt

## Lịch và giới hạn

- Mỗi lần chạy: tối đa 5 bài cho 5 đồng coin khác nhau, Gemini tạo nội dung, ảnh giá thị trường thật.
- Giãn cách tối thiểu 60 giây giữa các bài thành công, không bắn đồng loạt cùng giây.
- Lịch GitHub: 07:37, 13:37, 19:37, 01:37 theo giờ Việt Nam, tức 4 đợt/ngày và tối đa 20 bài/ngày trong điều kiện bình thường.
- Giới hạn phụ: 30 bài trong 24 giờ qua theo lịch sử bot; mỗi coin nghỉ 12 giờ, các đợt đăng nghỉ ít nhất 5 giờ.
- Tín hiệu cron của GitHub có thể trễ hoặc bị bỏ lỡ, nên đây là lịch dự kiến chứ không được bảo đảm.

## Ba cơ chế chạy

1. GitHub Actions schedule: PUBLISH=true, tối đa 5 bài công khai mỗi đợt.
2. Run workflow thủ công: mặc định publish=false, tạo ảnh bản nháp; tích publish mới đăng.
3. External heartbeat: thay nội dung tệp automation/binance-five-batch-trigger.txt:
   - GitHub commit message chính xác "trigger:binance-5post-preview" chạy bản nháp.
   - GitHub commit message chính xác "trigger:binance-5post-publish" đăng thật.
   - Các commit khác KHÔNG đăng, chỉ chạy kiểm thử offline.

Có thể dùng ChatGPT Automations để cập nhật trigger bên ngoài đồng hồ GitHub. Điều này chỉ hoạt động khi nhiệm vụ ChatGPT thực sự được tạo và có quyền GitHub trong lần chạy.

## Chống trùng và báo cáo

- Khôi phục lịch sử từ Actions cache (nếu có) để tránh dùng cùng coin trong 12 giờ và tránh lặp một tin đã đăng.
- Lưu cache mới sau khi đăng, ngay cả khi đợt gặp lỗi.
- Nếu không tìm thấy tin mới, dùng Market Snapshot với giá Binance/CoinGecko thật; không bịa tin tức.
- Nếu API lỗi, thông báo số bài đăng thực tế trong log.
- Không thể đếm các bài được đăng bằng tay hoặc nền tảng khác trong giới hạn lịch sử của bot.
- Cache có thể không sẵn sàng hoặc mất trạng thái; vì vậy chưa thể bảo đảm tuyệt đối không trùng.

## Nguồn

- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- https://www.binance.com/en/skills/detail/binance/square-post
