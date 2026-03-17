"""카카오톡 공유용 OG 이미지 생성 스크립트 (1200x630)"""
from PIL import Image, ImageDraw, ImageFont
import math
import random

WIDTH, HEIGHT = 1200, 630

img = Image.new("RGB", (WIDTH, HEIGHT), "#0d1117")
draw = ImageDraw.Draw(img)

# --- 배경 그라데이션 (하단으로 갈수록 약간 밝아짐) ---
for y in range(HEIGHT):
    r = int(13 + (25 - 13) * (y / HEIGHT))
    g = int(17 + (30 - 17) * (y / HEIGHT))
    b = int(23 + (40 - 23) * (y / HEIGHT))
    draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))

# --- 격자선 (은은하게) ---
grid_color = (30, 40, 55)
for x in range(0, WIDTH, 60):
    draw.line([(x, 0), (x, HEIGHT)], fill=grid_color, width=1)
for y in range(0, HEIGHT, 60):
    draw.line([(0, y), (WIDTH, y)], fill=grid_color, width=1)

# --- 캔들스틱 차트 ---
random.seed(42)
candle_x = 80
candle_width = 16
gap = 8
price = 150

candles = []
for i in range(45):
    change = random.uniform(-8, 9)
    open_p = price
    close_p = price + change
    high_p = max(open_p, close_p) + random.uniform(1, 5)
    low_p = min(open_p, close_p) - random.uniform(1, 5)
    candles.append((open_p, close_p, high_p, low_p))
    price = close_p

# 가격을 Y 좌표로 변환
all_prices = [p for c in candles for p in c]
min_price = min(all_prices)
max_price = max(all_prices)
chart_top = 80
chart_bottom = 480

def price_to_y(p):
    return chart_bottom - (p - min_price) / (max_price - min_price) * (chart_bottom - chart_top)

for i, (o, c, h, l) in enumerate(candles):
    x = 80 + i * (candle_width + gap)
    is_up = c >= o
    color = (0, 200, 120) if is_up else (255, 70, 70)

    # 꼬리
    mid_x = x + candle_width // 2
    draw.line([(mid_x, price_to_y(h)), (mid_x, price_to_y(l))], fill=color, width=2)

    # 몸통
    top_y = price_to_y(max(o, c))
    bot_y = price_to_y(min(o, c))
    if bot_y - top_y < 2:
        bot_y = top_y + 2
    draw.rectangle([(x, top_y), (x + candle_width, bot_y)], fill=color)

# --- 이동평균선 (부드러운 곡선) ---
def draw_smooth_line(points, color, width=2):
    for j in range(len(points) - 1):
        draw.line([points[j], points[j + 1]], fill=color, width=width)

# 5일 이동평균
ma5 = []
closes = [c[1] for c in candles]
for i in range(4, len(closes)):
    avg = sum(closes[i - 4:i + 1]) / 5
    x = 80 + i * (candle_width + gap) + candle_width // 2
    ma5.append((x, price_to_y(avg)))
draw_smooth_line(ma5, (255, 200, 50, 180), 3)

# 20일 이동평균
ma20 = []
for i in range(19, len(closes)):
    avg = sum(closes[i - 19:i + 1]) / 20
    x = 80 + i * (candle_width + gap) + candle_width // 2
    ma20.append((x, price_to_y(avg)))
draw_smooth_line(ma20, (100, 150, 255, 180), 3)

# --- 볼륨 바 (하단) ---
vol_top = 500
vol_bottom = 580
for i, (o, c, h, l) in enumerate(candles):
    x = 80 + i * (candle_width + gap)
    vol = random.uniform(0.3, 1.0)
    is_up = c >= o
    color = (0, 160, 100, 120) if is_up else (200, 50, 50, 120)
    bar_h = vol * (vol_bottom - vol_top)
    draw.rectangle(
        [(x, vol_bottom - bar_h), (x + candle_width, vol_bottom)],
        fill=color,
    )

# --- 글로우 효과 제거 (차트와 겹침 방지) ---

# --- 텍스트 ---
# macOS 시스템 폰트 사용
font_paths = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

title_font = None
for fp in font_paths:
    try:
        title_font = ImageFont.truetype(fp, 52)
        subtitle_font = ImageFont.truetype(fp, 24)
        break
    except (OSError, IOError):
        continue

if title_font is None:
    title_font = ImageFont.load_default()
    subtitle_font = ImageFont.load_default()

# 한글 폰트
kr_font_paths = [
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    "/Library/Fonts/NanumGothicBold.ttf",
]

kr_font = None
for fp in kr_font_paths:
    try:
        kr_font = ImageFont.truetype(fp, 22)
        kr_title_font = ImageFont.truetype(fp, 52)
        break
    except (OSError, IOError):
        continue

# 오른쪽 텍스트 영역
text_x = 750
# 반투명 배경 박스
draw.rounded_rectangle(
    [(text_x - 20, 160), (WIDTH - 40, 420)],
    radius=16,
    fill=(13, 17, 23, 200),
    outline=(0, 200, 120, 80),
    width=2,
)

# 돋보기 아이콘 대신 텍스트
icon_font = title_font
# 한글 타이틀 사용
if kr_title_font:
    draw.text((text_x, 195), "오크밸리", fill=(0, 200, 120), font=kr_title_font)
else:
    draw.text((text_x, 195), "OakValley", fill=(0, 200, 120), font=title_font)

# 구분선
draw.line([(text_x, 275), (text_x + 280, 275)], fill=(0, 200, 120), width=3)

# 부제
if kr_font:
    draw.text((text_x, 295), "주식 분석 & 포트폴리오", fill=(160, 170, 190), font=kr_font)
    draw.text((text_x, 330), "기술적 지표 · 전략 스코어 · AI 진단", fill=(120, 130, 150), font=ImageFont.truetype(kr_font_paths[0], 18))
else:
    draw.text((text_x, 295), "Stock Analysis & Portfolio", fill=(160, 170, 190), font=subtitle_font)

# --- 저장 ---
output_path = "/Users/donghapro/Documents/오크분석/static/og_image.png"
img.save(output_path, "PNG", quality=95)
print(f"OG image saved: {output_path}")
print(f"Size: {img.size}")
