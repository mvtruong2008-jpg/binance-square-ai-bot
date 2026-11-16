"""Self-contained read-only operations report, safe to open from Actions artifacts."""
from __future__ import annotations

import html
import json
from pathlib import Path


def render(report, output):
    def esc(value):
        return html.escape(str(value))
    def table(headers, rows):
        return '<div class="scroll"><table><thead><tr>' + ''.join('<th>'+esc(h)+'</th>' for h in headers) + '</tr></thead><tbody>' + ''.join(
            '<tr>' + ''.join('<td>'+esc(v)+'</td>' for v in row) + '</tr>' for row in rows) + '</tbody></table></div>'
    sections = []
    sections.append('<h2>Coin đang xu hướng</h2>'+table(["Coin", "Giá USDT", "24h", "Volume giờ / TB", "Search rank", "Danh tính"], [
        [r["symbol"], format(r["price"], ".8g"), f'{r["change"]:+.2f}%', f'{r["volume_ratio"]:.2f}x', r.get("rank") or "—", r["id"]]
        for r in report.get("markets", [])]))
    sections.append('<h2>Tin vừa phát hiện</h2>'+table(["Thời gian UTC", "Nguồn", "Chủ đề", "Tiêu đề", "Đường dẫn gốc"], [
        [r["published"], r["publisher"], r["category"], r["title"], r["url"]] for r in report.get("news", [])]))
    sections.append('<h2>Hàng đợi và điểm chất lượng</h2>'+table(["Loại", "Điểm / 100", "Thành phần điểm", "Chủ đề", "Trạng thái"], [
        [t["kind"], t["score"], json.dumps(t["breakdown"]), t["title"], "trùng" if t["duplicate"] else "đủ ngưỡng" if t["score"] >= report["threshold"] else "dưới ngưỡng"]
        for t in report.get("topics", [])]))
    for draft in report.get("drafts", []):
        media = draft["media"]
        sections.append('<article><h3>'+esc(draft["kind"])+'</h3><p>'+esc(draft["text"])+'</p><img alt="Ảnh minh họa bài viết" src="'+esc(media["path"])+'"><p class="muted">'+esc(media.get("license"))+' / '+esc(media.get("creator"))+'</p></article>')
    sections.append('<h2>Lịch sử và đối soát</h2>'+table(["Thời gian", "Trạng thái", "Coin", "Loại", "ID bài", "Nội dung"], [
        [r["reserved_at"], r["status"], r["symbol"], r["kind"], r.get("post_id", "—"), r["text"]] for r in reversed(report.get("posts", [])[-100:])]))
    sections.append('<h2>Nguồn xã hội</h2>'+table(["Nguồn", "Trạng thái"], report.get("social_status", {}).items()))
    sections.append(table(["Bài xã hội", "Net score", "Comments", "Score/giờ", "Từ khóa"], [
        [r["title"], r["net_score"], r["comments"], r.get("score_per_hour"), ", ".join(r.get("keywords", []))] for r in report.get("social", [])]))
    sections.append('<h2>API và hạn mức</h2><p>Số request thực tế trong lượt chạy; không suy đoán hạn mức còn lại hoặc hóa đơn.</p>'+table(
        ["Host", "Requests"], report.get("requests", {}).items()))
    sections.append('<p>AI: '+esc(report.get("ai_calls", 0))+' calls / '+esc(report.get("ai_limit", 0))+'; '+esc(report.get("ai_tokens", 0))+' tokens. Chi phí: dùng cấu hình miễn phí đã xác nhận; hóa đơn thực tế không có API truy cập.</p>')
    sections.append('<h2>Hiệu suất nội dung</h2><p>Chưa có API thống kê Binance Square được xác nhận. Views/likes/comments/shares/clicks: không có dữ liệu. Chiến lược giữ mặc định, chỉ điều chỉnh từ số liệu thật được nhập và kiểm tra.</p>')
    if report.get("performance"):
        sections.append(table(["Phân tích theo", "Nhóm", "Số bài", "Views", "Likes", "Like/view"], [
            [r["dimension"], r["value"], r["posts"], r["views"], r["likes"], f'{r["like_rate"]:.2%}'] for r in report["performance"]]))
    sections.append('<h2>Lỗi / nội dung bị loại</h2>'+table(["Nguồn", "Lỗi", "Thời gian UTC"], [[r.get("source"), r.get("error"), r.get("time", "")] for r in report.get("errors", [])]))
    page = '''<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'">
<title>X LEI 3.0 · Newsroom</title><style>
*{box-sizing:border-box}body{margin:0;background:#09101f;color:#e8eef7;font:16px/1.6 system-ui,sans-serif}main{max-width:1280px;margin:auto;padding:40px 24px}h1{font-size:44px;margin:0;color:#61e2ba}h2{margin-top:40px}p,.muted{color:#adbbcf}.status{padding:18px;border:1px solid #30526a;border-radius:12px;background:#13243a}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid #27364b;overflow-wrap:anywhere;min-width:90px}th{color:#7be6c4}article{margin-top:28px;padding:24px;border-radius:14px;background:#162238}img{width:100%;max-width:840px;border-radius:8px}a{color:#7be6c4}</style><main><h1>X LEI 3.0</h1><p>AUTONOMOUS CRYPTO NEWSROOM</p>'''
    page += '<div class="status"><strong>'+esc(report["mode"])+' · '+esc(report["status"])+'</strong><br>'+esc(report["time"])+ ' UTC<br>Giới hạn: tối đa 20 bài / 24 giờ; ngưỡng '+esc(report["threshold"])+'. Dừng khẩn cấp: đặt newsroom/control.json → stop=true trên main.</div>'
    page += ''.join(sections) + '</main></html>'
    Path(output).mkdir(parents=True, exist_ok=True)
    Path(output, "index.html").write_text(page, encoding="utf-8")
