import os
import requests
from flask import Flask, request, abort, jsonify, render_template_string
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage,
    QuickReply, QuickReplyItem, MessageAction, LocationAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, LocationMessageContent
from handlers import handle_message, handle_location, punch_with_location
from line_config import configuration

app = Flask(__name__)
handler = WebhookHandler(os.environ['LINE_CHANNEL_SECRET'])

# LIFF / LINE Login 識別碼（非機密：LIFF ID 本就在網址中、Channel ID 為公開值）
# 以環境變數為優先，未設定時用下列預設值，免去在 Render 另外設定
LIFF_ID = os.environ.get('LIFF_ID', '2010369618-Zjvm8v62')
LINE_LOGIN_CHANNEL_ID = os.environ.get('LINE_LOGIN_CHANNEL_ID', '2010369618')


def build_text_message(reply):
    if isinstance(reply, str):
        return TextMessage(text=reply)
    text = reply.get('text', '')
    qr_labels = reply.get('quick_replies', [])
    if not qr_labels:
        return TextMessage(text=text)
    items = []
    for label in qr_labels:
        if label == '📍分享位置':
            items.append(QuickReplyItem(action=LocationAction(label='分享位置')))
        else:
            items.append(QuickReplyItem(action=MessageAction(label=label[:20], text=label)))
    return TextMessage(text=text, quick_reply=QuickReply(items=items[:13]))


def send_reply(reply_token, reply):
    if not reply:
        return
    msg = build_text_message(reply)
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=[msg])
        )


@app.route("/webhook", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    user_id = event.source.user_id
    text = event.message.text.strip()
    reply = handle_message(user_id, text)
    send_reply(event.reply_token, reply)


@handler.add(MessageEvent, message=LocationMessageContent)
def handle_location_message(event):
    user_id = event.source.user_id
    lat = event.message.latitude
    lng = event.message.longitude
    reply = handle_location(user_id, lat, lng)
    send_reply(event.reply_token, reply)


@app.route("/health")
def health():
    return 'OK'


@app.route("/")
def index():
    return '非晉餐廚東南店 LINE 打卡系統運作中'


# ──────────────────────────────────────────
#  LIFF 自動定位打卡（取代手動分享位置）
# ──────────────────────────────────────────

LIFF_HTML = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>打卡</title>
<script charset="utf-8" src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
<style>
  html,body{margin:0;height:100%;font-family:-apple-system,"Microsoft JhengHei",sans-serif;
    background:#111820;color:#fff;display:flex;align-items:center;justify-content:center;}
  .box{width:88%;max-width:420px;text-align:center;padding:32px 20px;}
  .shift{font-size:20px;color:#9fd3a8;margin-bottom:18px;font-weight:bold;}
  .spinner{width:54px;height:54px;border:6px solid #2c3a2f;border-top-color:#27ae60;
    border-radius:50%;animation:spin 1s linear infinite;margin:18px auto;}
  @keyframes spin{to{transform:rotate(360deg);}}
  .msg{font-size:19px;line-height:1.7;white-space:pre-wrap;margin:18px 0;}
  .ok{color:#7CFC9A;} .err{color:#ff8a80;}
  .hint{font-size:14px;color:#8b99a6;margin-top:8px;}
  button{margin-top:22px;padding:14px 30px;font-size:17px;border:none;border-radius:12px;
    background:#27ae60;color:#fff;font-weight:bold;}
  button.retry{background:#e67e22;}
</style>
</head>
<body>
<div class="box">
  <div class="shift" id="shift">打卡</div>
  <div id="spinner" class="spinner"></div>
  <div class="msg" id="msg">打卡中，請稍候…</div>
  <div class="hint" id="hint">請稍候，馬上完成</div>
  <button id="btn" style="display:none" onclick="closeWin()">關閉</button>
</div>
<script>
var LIFF_ID = "{{ liff_id }}";
var qs = new URLSearchParams(location.search);
var shift = qs.get("shift") || "1";
var shiftName = shift === "2" ? "晚班" : "早班";
document.getElementById("shift").textContent = shiftName + "打卡";

function show(text, ok, retry){
  document.getElementById("spinner").style.display = "none";
  var m = document.getElementById("msg");
  m.textContent = text;
  m.className = "msg " + (ok ? "ok" : "err");
  document.getElementById("hint").style.display = "none";
  var b = document.getElementById("btn");
  b.style.display = "inline-block";
  if(retry){ b.textContent = "重新打卡"; b.className = "retry"; b.onclick = function(){ location.reload(); }; }
}
function closeWin(){ if(window.liff && liff.closeWindow) liff.closeWindow(); else window.close(); }

function sendPunch(){
  document.getElementById("msg").textContent = "打卡中…";
  var idToken = (liff.getIDToken && liff.getIDToken()) || "";
  liff.getProfile().then(function(p){
    return fetch("/api/liff-punch", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ shift: shift, idToken: idToken, userId: p.userId })
    });
  }).then(function(r){ return r.json(); })
    .then(function(d){ show(d.message || "打卡完成", !!d.ok, !d.ok); })
    .catch(function(){ show("連線失敗，請檢查網路後重試。", false, true); });
}

liff.init({ liffId: LIFF_ID }).then(function(){
  if(!liff.isLoggedIn()){ liff.login(); return; }
  sendPunch();
}).catch(function(){
  show("初始化失敗，請關閉重開。\\n（老闆：請確認 LIFF_ID 設定正確）", false, true);
});
</script>
</body>
</html>"""


@app.route("/liff")
def liff_page():
    return render_template_string(LIFF_HTML, liff_id=LIFF_ID)


@app.route("/api/liff-punch", methods=['POST'])
def liff_punch():
    data = request.get_json(silent=True) or {}
    user_id = data.get('userId')
    id_token = data.get('idToken')

    # 若設定了 LINE Login 頻道 ID，用 id_token 驗證取得可信的 userId
    if LINE_LOGIN_CHANNEL_ID and id_token:
        try:
            vr = requests.post(
                'https://api.line.me/oauth2/v2.1/verify',
                data={'id_token': id_token, 'client_id': LINE_LOGIN_CHANNEL_ID},
                timeout=10,
            )
            if vr.status_code == 200:
                user_id = vr.json().get('sub') or user_id
            else:
                return jsonify({'ok': False, 'message': '身分驗證失敗，請關閉重新打卡。'})
        except Exception:
            pass  # 驗證服務異常時退回信任前端帶上的 userId

    if not user_id:
        return jsonify({'ok': False, 'message': '無法取得你的身分，請關閉重新打卡。'})

    try:
        shift_num = int(data.get('shift'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'message': '班別資料不完整，請重新打卡。'})

    text = punch_with_location(user_id, shift_num)
    return jsonify({'ok': text.startswith('✅'), 'message': text})


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
