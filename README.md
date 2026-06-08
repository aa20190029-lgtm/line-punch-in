# LINE 打卡系統

適合餐廳／小店的 LINE Bot 打卡管理系統，支援雙班制、GPS 驗證、薪資試算。

## 功能

- 員工上下班打卡（第一班 10:30-14:30、第二班 16:30-20:30）
- GPS 範圍驗證（可開關）
- 自動計算遲到、加班費（勞基法 1.34x / 1.67x）
- 月薪 / 時薪兩種模式
- 老闆：新增員工、補打卡、薪資報表
- LINE 圖文選單（員工 6 格 / 老闆 4 格）

---

## 新店部署 SOP

### 1. 從這個 Template 建新庫

GitHub → Use this template → 輸入新庫名稱（如 `line-punch-in-xxxx`）

### 2. 建立 LINE 官方帳號

1. LINE Developers → 建立新 Provider → 建立 Messaging API Channel
2. 複製 `Channel Secret` 和 `Channel Access Token`
3. LINE OA Manager → 回應設定 → **關閉自動回覆**

### 3. 建立 Render 服務

1. Render Dashboard → New Web Service → 連結新 GitHub 庫
2. Environment 加入以下環境變數：

| 變數名 | 說明 |
|--------|------|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Token |
| `LINE_CHANNEL_SECRET` | LINE Secret |
| `DATABASE_URL` | PostgreSQL 連線字串（Render 自動提供） |
| `EMPLOYEE_RICH_MENU_ID` | 執行 setup_richmenu.py 後取得 |
| `BOSS_RICH_MENU_ID` | 執行 setup_richmenu.py 後取得 |

3. 建立 Render PostgreSQL 資料庫（Free 方案），將 Internal Database URL 填入 `DATABASE_URL`

### 4. 建立圖文選單

```powershell
$env:LINE_CHANNEL_ACCESS_TOKEN = "貼上Token"
python -X utf8 setup_richmenu.py
```

輸出的兩個 ID 填回 Render 環境變數。

### 5. 設定 Webhook

LINE Developers → Messaging API → Webhook URL：
```
https://你的服務名稱.onrender.com/webhook
```

勾選「Use webhook」。

### 6. 啟用老闆帳號

老闆在 LINE 對話中傳：`設為老闆`

### 7. 設定 GPS（可選）

老闆傳：`GPS設定` → 分享位置 → 輸入公尺數 → `GPS開啟`

### 8. 防止 Render 冷啟動（建議）

到 [UptimeRobot](https://uptimerobot.com/) 新增監控，每 5 分鐘 ping：
```
https://你的服務名稱.onrender.com/health
```

---

## 調整班次時間

修改 `handlers.py` 頂端的 `SHIFTS`：

```python
SHIFTS = {
    1: {'start': '10:30', 'end': '14:30', 'window_start': 600,  'window_end': 900},
    2: {'start': '16:30', 'end': '20:30', 'window_start': 960,  'window_end': 1260},
}
```

`window_start` / `window_end` 是打卡有效時間（分鐘，從 0:00 起算）。
