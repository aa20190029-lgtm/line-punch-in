import os
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage,
    QuickReply, QuickReplyItem, MessageAction, LocationAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, LocationMessageContent
from handlers import handle_message, handle_location

app = Flask(__name__)
configuration = Configuration(access_token=os.environ['LINE_CHANNEL_ACCESS_TOKEN'])
handler = WebhookHandler(os.environ['LINE_CHANNEL_SECRET'])


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


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
