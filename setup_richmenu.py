"""
一次性執行：建立 LINE 圖文選單（Rich Menu）

執行前：
  1. 安裝 Pillow：pip install Pillow requests
  2. 在終端機設定環境變數：
     Windows PowerShell：
       $env:LINE_CHANNEL_ACCESS_TOKEN = "你的Token"
     或直接在下方 TOKEN 變數填入

執行：
  python setup_richmenu.py

完成後把輸出的兩個 ID 加到 Render 環境變數：
  EMPLOYEE_RICH_MENU_ID=xxxxx
  BOSS_RICH_MENU_ID=xxxxx
"""

import os
import io
import sys
import json
import requests
from PIL import Image, ImageDraw

TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '')
API_BASE = 'https://api.line.me/v2/bot'
DATA_BASE = 'https://api-data.line.me/v2/bot'

AUTH_HEADER = {'Authorization': f'Bearer {TOKEN}'}


# ──────────────────────────────────────────
#  字型載入
# ──────────────────────────────────────────

def load_font(size):
    from PIL import ImageFont
    candidates = [
        'C:/Windows/Fonts/msjhbd.ttc',
        'C:/Windows/Fonts/msjh.ttc',
        'C:/Windows/Fonts/msyhbd.ttc',
        'C:/Windows/Fonts/msyh.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def load_emoji_font(size):
    from PIL import ImageFont
    candidates = [
        'C:/Windows/Fonts/seguiemj.ttf',   # Segoe UI Emoji（Windows 彩色 emoji）
        'C:/Windows/Fonts/seguisym.ttf',
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return load_font(size)


# ──────────────────────────────────────────
#  圖片生成
# ──────────────────────────────────────────

BUTTON_COLORS = {
    'green':  '#27ae60',
    'red':    '#c0392b',
    'orange': '#e67e22',
    'blue':   '#2980b9',
    'purple': '#8e44ad',
    'teal':   '#16a085',
    'gray':   '#636e72',
    'dark':   '#2d3436',
}


def hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def darken(hex_color, factor=0.6):
    r, g, b = hex_to_rgb(hex_color)
    return (int(r * factor), int(g * factor), int(b * factor))


def draw_cell(draw, x, y, w, h, bg_hex, symbol, label, font_sym, font_lbl):
    """老闆選單用：簡單色塊按鈕"""
    draw.rectangle([x, y, x + w - 1, y + h - 1], fill=bg_hex)
    draw.rectangle([x, y, x + w - 1, y + 4], fill='#ffffff40')
    draw.rectangle([x, y + h - 5, x + w - 1, y + h - 1], fill='#00000040')
    cx = x + w // 2
    try:
        draw.text((cx, y + int(h * 0.32)), symbol, fill='white', anchor='mm', font=font_sym)
        draw.text((cx, y + int(h * 0.68)), label,  fill='white', anchor='mm', font=font_lbl)
    except TypeError:
        draw.text((cx - 60, y + int(h * 0.32) - 30), symbol, fill='white', font=font_sym)
        draw.text((cx - 80, y + int(h * 0.68) - 20), label,  fill='white', font=font_lbl)


def draw_veg_cell(img, draw, x, y, w, h, bg_hex, emoji_sym, label, font_emoji, font_lbl):
    """繪製蔬菜風格按鈕格"""
    bg = hex_to_rgb(bg_hex)
    dark = darken(bg_hex, 0.55)

    # 漸層背景（手動模擬：由深到亮）
    for row in range(h):
        ratio = row / h
        r = int(dark[0] + (bg[0] - dark[0]) * ratio)
        g = int(dark[1] + (bg[1] - dark[1]) * ratio)
        b = int(dark[2] + (bg[2] - dark[2]) * ratio)
        draw.line([(x, y + row), (x + w - 1, y + row)], fill=(r, g, b))

    # 裝飾圓形背景（讓 emoji 更突出）
    cx = x + w // 2
    circle_r = int(min(w, h) * 0.28)
    circle_y = y + int(h * 0.33)
    draw.ellipse(
        [cx - circle_r, circle_y - circle_r, cx + circle_r, circle_y + circle_r],
        fill=(255, 255, 255, 40) if hasattr(draw, '_image') else (255, 255, 255),
    )

    # Emoji 符號
    try:
        draw.text((cx, circle_y), emoji_sym, anchor='mm', font=font_emoji, embedded_color=True)
    except Exception:
        try:
            draw.text((cx, circle_y), emoji_sym, anchor='mm', font=font_emoji)
        except Exception:
            draw.text((cx - 80, circle_y - 80), emoji_sym, font=font_emoji)

    # 標籤文字
    lbl_y = y + int(h * 0.72)
    try:
        draw.text((cx, lbl_y), label, fill='white', anchor='mm', font=font_lbl)
    except Exception:
        lw = font_lbl.getlength(label) if hasattr(font_lbl, 'getlength') else len(label) * 50
        draw.text((cx - int(lw // 2), lbl_y - 35), label, fill='white', font=font_lbl)

    # 下方色條裝飾
    draw.rectangle([x, y + h - 12, x + w - 1, y + h - 1], fill=hex_to_rgb(bg_hex))


def draw_grid_lines(draw, W, H, rows, cols):
    cw = W // cols
    ch = H // rows
    for c in range(1, cols):
        draw.line([c * cw, 0, c * cw, H], fill=(255, 255, 255, 50), width=3)
    for r in range(1, rows):
        draw.line([0, r * ch, W, r * ch], fill=(255, 255, 255, 50), width=3)


def create_employee_image():
    """員工選單：6格 2×3，蔬菜主題"""
    W, H = 2500, 1686
    CW, CH = W // 2, H // 3

    img = Image.new('RGB', (W, H), '#111820')
    draw = ImageDraw.Draw(img)

    font_emoji = load_emoji_font(200)
    font_lbl = load_font(95)

    # 蔬菜主題：青花椰菜/南瓜/玉米筍/娃娃菜/櫻桃/香草
    cells = [
        ('#1a5c2a', '🥦', '上班打卡'),
        ('#7a3200', '🎃', '下班打卡'),
        ('#7a6200', '🌽', '查本月薪資'),
        ('#1a4a38', '🥬', '查打卡記錄'),
        ('#1a4d2e', '🥒', '登記'),
        ('#1c3d1a', '🫛', '說明'),
    ]

    for i, (color, emoji, lbl) in enumerate(cells):
        col = i % 2
        row = i // 2
        draw_veg_cell(img, draw, col * CW, row * CH, CW, CH, color, emoji, lbl, font_emoji, font_lbl)

    draw_grid_lines(draw, W, H, 3, 2)
    return img


def create_boss_image():
    """老闆選單：4格 2×2"""
    W, H = 2500, 1124
    CW, CH = W // 2, H // 2

    img = Image.new('RGB', (W, H), '#1a1a2e')
    draw = ImageDraw.Draw(img)

    font_sym = load_font(160)
    font_lbl = load_font(90)

    cells = [
        (BUTTON_COLORS['orange'], '#', '員工管理'),
        (BUTTON_COLORS['teal'],   '+', '補打卡'),
        (BUTTON_COLORS['purple'], '$', '薪資報表'),
        (BUTTON_COLORS['gray'],   '?', '說明'),
    ]

    for i, (color, sym, lbl) in enumerate(cells):
        col = i % 2
        row = i // 2
        draw_cell(draw, col * CW, row * CH, CW, CH, color, sym, lbl, font_sym, font_lbl)

    draw_grid_lines(draw, W, H, 2, 2)
    return img


def image_to_jpeg_bytes(img, quality=90):
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=quality)
    return buf.getvalue()


# ──────────────────────────────────────────
#  LINE API 操作
# ──────────────────────────────────────────

def delete_all_rich_menus():
    r = requests.get(f'{API_BASE}/richmenu/list', headers=AUTH_HEADER)
    r.raise_for_status()
    menus = r.json().get('richmenus', [])
    for m in menus:
        mid = m['richMenuId']
        requests.delete(f'{API_BASE}/richmenu/{mid}', headers=AUTH_HEADER)
        print(f'  刪除舊選單：{mid}')


def create_rich_menu(name, width, height, areas, chat_bar_text):
    payload = {
        'size': {'width': width, 'height': height},
        'selected': True,
        'name': name,
        'chatBarText': chat_bar_text,
        'areas': areas,
    }
    r = requests.post(
        f'{API_BASE}/richmenu',
        headers={**AUTH_HEADER, 'Content-Type': 'application/json'},
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8')
    )
    r.raise_for_status()
    return r.json()['richMenuId']


def upload_rich_menu_image(rich_menu_id, img_bytes):
    r = requests.post(
        f'{DATA_BASE}/richmenu/{rich_menu_id}/content',
        headers={**AUTH_HEADER, 'Content-Type': 'image/jpeg'},
        data=img_bytes
    )
    r.raise_for_status()


def set_default_rich_menu(rich_menu_id):
    r = requests.post(
        f'{API_BASE}/user/all/richmenu/{rich_menu_id}',
        headers=AUTH_HEADER
    )
    r.raise_for_status()


def make_message_area(x, y, w, h, text):
    return {
        'bounds': {'x': x, 'y': y, 'width': w, 'height': h},
        'action': {'type': 'message', 'text': text}
    }


# ──────────────────────────────────────────
#  主程式
# ──────────────────────────────────────────

def setup():
    if not TOKEN:
        print('❌ 請設定環境變數 LINE_CHANNEL_ACCESS_TOKEN')
        print('   PowerShell：$env:LINE_CHANNEL_ACCESS_TOKEN = "你的Token"')
        sys.exit(1)

    print('🗑  清除舊圖文選單...')
    delete_all_rich_menus()

    # 員工選單 區域定義（2×3 格，每格 1250×562）
    BW, EBH = 1250, 562
    emp_areas = [
        make_message_area(0,       0,       BW, EBH, '上班打卡'),
        make_message_area(BW,      0,       BW, EBH, '下班打卡'),
        make_message_area(0,       EBH,     BW, EBH, '查本月薪資'),
        make_message_area(BW,      EBH,     BW, EBH, '查打卡記錄'),
        make_message_area(0,       EBH * 2, BW, EBH, '登記'),
        make_message_area(BW,      EBH * 2, BW, EBH, '說明'),
    ]

    # 老闆選單 區域定義（2×2 格，每格 1250×562）
    BBH = 562
    boss_areas = [
        make_message_area(0,  0,   BW, BBH, '員工管理'),
        make_message_area(BW, 0,   BW, BBH, '補打卡'),
        make_message_area(0,  BBH, BW, BBH, '薪資報表'),
        make_message_area(BW, BBH, BW, BBH, '說明'),
    ]

    print('🖼  生成員工選單圖片...')
    emp_bytes = image_to_jpeg_bytes(create_employee_image())
    print(f'   圖片大小：{len(emp_bytes) // 1024} KB')

    print('🖼  生成老闆選單圖片...')
    boss_bytes = image_to_jpeg_bytes(create_boss_image())
    print(f'   圖片大小：{len(boss_bytes) // 1024} KB')

    print('📤 建立員工圖文選單...')
    emp_menu_id = create_rich_menu('員工打卡選單', 2500, 1686, emp_areas, '打卡選單')
    upload_rich_menu_image(emp_menu_id, emp_bytes)
    print(f'   員工選單 ID：{emp_menu_id}')

    print('📤 建立老闆圖文選單...')
    boss_menu_id = create_rich_menu('老闆管理選單', 2500, 1124, boss_areas, '管理選單')
    upload_rich_menu_image(boss_menu_id, boss_bytes)
    print(f'   老闆選單 ID：{boss_menu_id}')

    print('🔧 設定預設選單（員工）...')
    set_default_rich_menu(emp_menu_id)

    print('\n' + '=' * 50)
    print('✅ 圖文選單設定完成！')
    print('=' * 50)
    print('\n請將以下兩行加入 Render 環境變數：')
    print(f'\nEMPLOYEE_RICH_MENU_ID={emp_menu_id}')
    print(f'BOSS_RICH_MENU_ID={boss_menu_id}')
    print('\n之後老闆在 LINE 發送「設為老闆」，')
    print('系統會自動切換為老闆選單。')


if __name__ == '__main__':
    setup()
