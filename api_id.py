import asyncio
import re
from flask import Flask, request, render_template_string
from telethon import TelegramClient
from telethon.tl.types import User
import pytz

# --- CẤU HÌNH (Điền thông tin của bạn vào đây) ---
api_id = 26594850  # THAY BẰNG API ID CỦA BẠN
api_hash = 'e441160135dafb81ff5770ebbf9aa141' # THAY BẰNG API HASH CỦA BẠN
session_name = 'my_web_telegram_session'

app = Flask(__name__)
VN_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

# --- GIAO DIỆN WEB (HTML TEMPLATE) ---
HTML_TEMPLATE = """
<!doctype html>
<html lang="vi">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
    <title>Telegram Price Finder Pro</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; background-color: #f4f7f9; margin: 20px; }
        .container { max-width: 800px; margin: auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        h1 { text-align: center; color: #333; }
        form { display: flex; flex-direction: column; gap: 15px; }
        input, button { padding: 10px; border-radius: 5px; border: 1px solid #ccc; font-size: 16px; }
        button { background-color: #007bff; color: white; cursor: pointer; border: none; }
        button:hover { background-color: #0056b3; }
        .results { margin-top: 20px; }
        .result-item { border: 1px solid #ddd; padding: 15px; margin-bottom: 15px; border-radius: 5px; background: #f9f9f9; }
        .content { white-space: pre-wrap; word-wrap: break-word; }
        .price-highlight { font-weight: bold; color: #d9534f; background-color: #fcf8e3; padding: 2px 5px; border-radius: 3px;}
        .meta { color: #555; font-size: 0.9em; margin-top: 10px; border-top: 1px solid #eee; padding-top: 10px;}
        .error { color: red; text-align: center; }
        .loader { text-align: center; display: none; margin-top: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔍 Telegram Price Finder Pro (Lọc trùng)</h1>
        <form action="/search" method="post" onsubmit="document.querySelector('.loader').style.display='block'">
            <input type="text" name="channel" placeholder="@username hoặc ID kênh" required value="{{ channel or '' }}">
            <input type="text" name="topic_id" placeholder="ID Topic (nếu có) - Bỏ trống nếu không có" value="{{ topic_id or '' }}">
            <input type="text" name="keywords" placeholder="netflix, spotify (chỉ tìm 1 từ khóa mỗi lần)" required value="{{ keywords_str or '' }}">
            <input type="number" name="limit" value="{{ limit or 2000 }}" placeholder="Số tin nhắn gần nhất để quét">
            <button type="submit">Tìm kiếm & Sắp xếp</button>
        </form>
        <div class="loader"><p><strong>Đang tìm kiếm, vui lòng chờ...</strong></p></div>

        {% if error %}<p class="error">{{ error }}</p>{% endif %}

        {% if results is not none %}
            <div class="results">
                <h2>Kết quả cho: "{{ search_keyword }}" (Đã sắp xếp & lọc trùng)</h2>
                {% for item in results %}
                    <div class="result-item">
                        <div class="content"><p>Giá tốt nhất: <span class="price-highlight">{{ item.primary_price_str }}</span></p><p>{{ item.content }}</p></div>
                        <div class="meta">
                            Đăng bởi: 
                            {% if item.sender_username %}
                                <a href="https://t.me/{{ item.sender_username }}" target="_blank">@{{ item.sender_username }}</a>
                            {% else %}
                                <strong>{{ item.sender_name }}</strong>
                            {% endif %}
                            <br>
                            Lúc: {{ item.date }}
                            <br>
                            <a href="{{ item.link }}" target="_blank">Xem tin nhắn gốc</a>
                        </div>
                    </div>
                {% else %}
                    <p>Không tìm thấy dòng nào chứa cả từ khóa và giá.</p>
                {% endfor %}
            </div>
        {% endif %}
    </div>
</body>
</html>
"""

# --- LOGIC XỬ LÝ GIÁ THÔNG MINH ---
def get_valid_prices(text_line):
    """Hàm này tìm tất cả các chuỗi có vẻ là giá và áp dụng các quy tắc để lọc bỏ sai sót."""
    price_pattern = re.compile(r'\b\d{1,3}(?:[.,]\d{3})*(?:k|tr|triệu|đ|vnd|ca|🐠)?|\b\d+(?:\.\d+)?\s*(?:k|tr|triệu)\b', re.IGNORECASE)
    candidates = price_pattern.findall(text_line)
    
    valid_prices = []
    for price_str in candidates:
        price_lower = price_str.lower()
        num_part = re.sub(r'[^0-9.,]', '', price_lower)
        if not num_part: continue

        # --- QUY TẮC LỌC MỚI ---
        # Một số chỉ được coi là giá nếu nó LỚN (>=10.000) hoặc có ĐƠN VỊ TIỀN TỆ đi kèm
        has_unit = any(unit in price_lower for unit in ['k', 'tr', 'đ', 'ca', '🐠', 'vnd', 'triệu'])
        try:
            is_large_number = float(num_part.replace(',', '.')) >= 10000
        except ValueError:
            is_large_number = False

        if not has_unit and not is_large_number:
            continue
            
        # Quy tắc loại bỏ "4k" nếu nó mang nghĩa độ phân giải
        if '4k' == price_lower and any(word in text_line.lower() for word in ['hdr', 'slot', 'profile', 'chất lượng']):
            continue

        valid_prices.append(price_str)
    return valid_prices

def normalize_price(price_str):
    """Chuyển đổi chuỗi giá hợp lệ thành số để so sánh."""
    price_lower = price_str.lower()
    num_str = re.sub(r'[^0-9.,]', '', price_lower)
    num_str = num_str.replace(',', '.')

    multiplier = 1
    if any(unit in price_lower for unit in ['tr', 'triệu']):
        multiplier = 1000000
    elif any(unit in price_lower for unit in ['k', 'ca', '🐠']):
        multiplier = 1000

    try:
        if not num_str: return float('inf')
        value = float(num_str)
        # Đối với các số không có đơn vị (ví dụ 150), không nhân thêm
        if multiplier == 1 and value < 10000 and not any(unit in price_lower for unit in ['đ', 'vnd']):
             return int(value)
        return int(value * multiplier)
    except (ValueError, TypeError):
        return float('inf')

# --- LOGIC TELEGRAM ---
async def search_telegram_pro(channel, keyword, limit, topic_id):
    results = []
    async with TelegramClient(session_name, api_id, api_hash) as client:
        try:
            target_channel = await client.get_entity(channel)
        except Exception:
            return None, "channel_error"

        async for message in client.iter_messages(target_channel, limit=limit, search=keyword, reply_to=topic_id):
            if message and message.text:
                matching_lines = []
                for line in message.text.splitlines():
                    if keyword.lower() in line.lower() and get_valid_prices(line):
                        matching_lines.append(line)
                
                if matching_lines:
                    content = '\n'.join(matching_lines)
                    line_prices_str = get_valid_prices(content)
                    if not line_prices_str: continue

                    normalized_prices = [normalize_price(p) for p in line_prices_str]
                    min_price_value = min(normalized_prices)

                    primary_price_str = ""
                    for p_str in line_prices_str:
                        if normalize_price(p_str) == min_price_value:
                            primary_price_str = p_str
                            break
                    
                    sender_name = "Không xác định"
                    sender_username = None
                    sender_id = message.sender_id # Dùng sender_id để định danh duy nhất
                    if message.sender:
                        if isinstance(message.sender, User):
                            sender_name = message.sender.first_name or "User"
                            if message.sender.last_name: sender_name += f" {message.sender.last_name}"
                            sender_username = message.sender.username
                        else:
                            sender_name = message.sender.title
                    
                    vn_time = message.date.astimezone(VN_TZ)
                    formatted_date = vn_time.strftime('%H:%M ngày %d-%m-%Y')

                    results.append({
                        'link': f"https://t.me/c/{target_channel.id}/{message.id}",
                        'content': content,
                        'sender_id': sender_id,
                        'sender_name': sender_name,
                        'sender_username': sender_username,
                        'date': formatted_date,
                        'price_value': min_price_value,
                        'primary_price_str': primary_price_str
                    })
    return results, "success"

# --- ROUTE VÀ CÁC HÀM CÒN LẠI ---
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/search', methods=['POST'])
def search():
    channel = request.form.get('channel')
    keywords_str = request.form.get('keywords', '')
    limit = int(request.form.get('limit', 2000))
    topic_id_str = request.form.get('topic_id')
    topic_id = int(topic_id_str) if topic_id_str and topic_id_str.isdigit() else None
    
    search_keyword = keywords_str.split(',')[0].strip()

    if not channel or not search_keyword:
        return render_template_string(HTML_TEMPLATE, error="Vui lòng nhập đủ thông tin kênh và từ khóa.")

    results, status = asyncio.run(search_telegram_pro(channel, search_keyword, limit, topic_id))

    if status == "channel_error":
        return render_template_string(HTML_TEMPLATE, error=f"Không thể tìm thấy hoặc truy cập kênh '{channel}'.")

    final_results = []
    if results:
        # 1. Sắp xếp tất cả kết quả theo giá tăng dần
        results.sort(key=lambda x: x.get('price_value', float('inf')))

        # 2. Lọc để mỗi người chỉ xuất hiện 1 lần với giá tốt nhất của họ
        seen_senders = set()
        for item in results:
            sender_id = item.get('sender_id')
            if sender_id not in seen_senders:
                final_results.append(item)
                seen_senders.add(sender_id)

    return render_template_string(HTML_TEMPLATE, results=final_results, search_keyword=search_keyword, channel=channel, topic_id=topic_id, keywords_str=keywords_str, limit=limit)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)