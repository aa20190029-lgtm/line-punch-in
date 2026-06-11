import os
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi

configuration = Configuration(access_token=os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', ''))


def link_user_menu(line_user_id, menu_id):
    """將使用者綁定到指定的圖文選單"""
    if not menu_id or not line_user_id:
        return
    try:
        with ApiClient(configuration) as api_client:
            api = MessagingApi(api_client)
            api.link_rich_menu_id_to_user(line_user_id, menu_id)
    except Exception:
        pass


def link_user_to_boss_menu(line_user_id):
    menu_id = os.environ.get('BOSS_RICH_MENU_ID', '')
    link_user_menu(line_user_id, menu_id)


def link_user_to_employee_menu(line_user_id):
    # 未設環境變數時用目前的員工選單（含 LIFF 定位打卡鈕）為預設
    menu_id = os.environ.get('EMPLOYEE_RICH_MENU_ID', 'richmenu-964514c7e10612f2efb22488c15ed16f')
    link_user_menu(line_user_id, menu_id)
