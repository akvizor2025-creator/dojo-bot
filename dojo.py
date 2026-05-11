import os
import json
import urllib.request
from flask import Flask, request

app = Flask(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

def send_telegram(chat_id, msg):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    data = json.dumps({'chat_id': chat_id, 'text': msg, 'parse_mode': 'HTML'}).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    urllib.request.urlopen(req, timeout=10)

def supabase_get(table, params=''):
    url = f'{SUPABASE_URL}/rest/v1/{table}?{params}'
    req = urllib.request.Request(url, headers={
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}'
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def supabase_patch(table, data, condition):
    url = f'{SUPABASE_URL}/rest/v1/{table}?{condition}'
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method='PATCH', headers={
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json'
    })
    urllib.request.urlopen(req, timeout=10)

def supabase_post(table, data):
    url = f'{SUPABASE_URL}/rest/v1/{table}'
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def get_family_by_chat_id(chat_id):
    """Find which family this Telegram chat ID belongs to"""
    data = supabase_get('settings', f'telegram_chat_id=eq.{chat_id}&select=*&limit=1')
    return data[0] if data else None

def get_points(family_id):
    data = supabase_get('points', f'family_id=eq.{family_id}&select=*&order=created_at.desc&limit=1')
    return data[0] if data else None

def update_points(points_id, updates):
    supabase_patch('points', updates, f'id=eq.{points_id}')

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.json
    if not update or 'message' not in update:
        return 'ok'

    msg = update['message']
    chat_id = str(msg['chat']['id'])
    text = msg.get('text', '').strip().lower()

    # Handle /start command — register family
    if text == '/start':
        send_telegram(chat_id, 
            '👋 <b>Welcome to The Happy Family bot!</b>\n\n'
            'To connect this bot to your account:\n\n'
            '1. Open the Super Panel app\n'
            '2. Go to <b>Settings</b> tab\n'
            f'3. Enter your Telegram Chat ID: <b>{chat_id}</b>\n'
            '4. Click Save\n\n'
            'Then you\'ll receive notifications and can approve chores here!\n\n'
            '<i>Your Chat ID: <b>' + chat_id + '</b></i>'
        )
        return 'ok'

    # Find family by chat ID
    family = get_family_by_chat_id(chat_id)
    if not family:
        send_telegram(chat_id,
            '❌ <b>Not connected yet!</b>\n\n'
            f'Your Chat ID is: <b>{chat_id}</b>\n\n'
            'To connect:\n'
            '1. Open the Super Panel\n'
            '2. Go to Settings tab\n'
            '3. Enter your Chat ID and save\n\n'
            'Type /start for setup instructions.'
        )
        return 'ok'

    family_id = family['family_id']
    kid_name = family.get('kid_name', 'Your kid')

    if text in ('yes', 'y', '✓', 'approve', 'approved'):
        pending = supabase_get('chore_approvals', f'approved=is.null&family_id=eq.{family_id}&select=*&order=created_at&limit=1')
        if pending:
            chore = pending[0]
            supabase_patch('chore_approvals', {'approved': True}, f'id=eq.{chore["id"]}')
            # Get pay amount and update balance
            chore_data = supabase_get('chores', f'id=eq.{chore["chore_id"]}&select=pay')
            pay = float(chore_data[0]['pay']) if chore_data else 0.0
            new_owed = float(family.get('total_owed') or 0) + pay
            new_alltime = float(family.get('all_time_earned') or 0) + pay
            supabase_patch('settings', {'total_owed': round(new_owed, 2), 'all_time_earned': round(new_alltime, 2)}, f'family_id=eq.{family_id}')
            send_telegram(chat_id, f'✅ <b>{chore["chore_name"]}</b> approved!\n💰 +${pay:.2f} added\n💵 Total owed: <b>${new_owed:.2f}</b>')
        else:
            send_telegram(chat_id, '✅ No pending approvals!')

    elif text in ('no', 'n', '✗', 'reject', 'rejected', 'nope'):
        pending = supabase_get('chore_approvals', f'approved=is.null&family_id=eq.{family_id}&select=*&order=created_at&limit=1')
        if pending:
            chore = pending[0]
            supabase_patch('chore_approvals', {'approved': False}, f'id=eq.{chore["id"]}')
            points = get_points(family_id)
            if points:
                new_pts = int(points.get('total_points') or 0) + 50
                new_hrs = min(new_pts // 100, 6)
                update_points(points['id'], {'total_points': new_pts, 'screen_time_penalty_hours': new_hrs})
            send_telegram(chat_id, f'❌ <b>{chore["chore_name"]}</b> rejected.\n+50 points added.')
        else:
            send_telegram(chat_id, '✅ No pending approvals!')

    elif text in ('excused', 'excuse', 'yes excused'):
        pending = supabase_get('kungfu_approvals', f'excused=is.null&family_id=eq.{family_id}&select=*&order=created_at&limit=1')
        if pending:
            supabase_patch('kungfu_approvals', {'excused': True}, f'id=eq.{pending[0]["id"]}')
            send_telegram(chat_id, '✅ Kung fu absence marked as excused.')
        else:
            send_telegram(chat_id, '✅ No pending kung fu records!')

    elif text in ('not excused', 'unexcused', 'no excuse'):
        pending = supabase_get('kungfu_approvals', f'excused=is.null&family_id=eq.{family_id}&select=*&order=created_at&limit=1')
        if pending:
            supabase_patch('kungfu_approvals', {'excused': False}, f'id=eq.{pending[0]["id"]}')
            points = get_points(family_id)
            if points:
                new_pts = int(points.get('total_points') or 0) + 100
                new_hrs = min(new_pts // 100, 6)
                update_points(points['id'], {'total_points': new_pts, 'screen_time_penalty_hours': new_hrs})
            send_telegram(chat_id, '❌ Kung fu absence marked as NOT excused.\n+100 points added.')
        else:
            send_telegram(chat_id, '✅ No pending kung fu records!')

    elif text == 'pending':
        pending = supabase_get('chore_approvals', f'approved=is.null&family_id=eq.{family_id}&select=*&order=created_at')
        if pending:
            msg_text = f'📋 <b>Pending approvals for {kid_name}:</b>\n\n'
            for i, c in enumerate(pending, 1):
                msg_text += f'{i}. {c["chore_name"]} ({c["date"]})\n'
            msg_text += '\nReply <b>yes</b> or <b>no</b> to approve/reject one at a time.'
            send_telegram(chat_id, msg_text)
        else:
            send_telegram(chat_id, f'✅ No pending approvals for {kid_name}!')

    elif text == 'balance':
        owed = float(family.get('total_owed') or 0)
        alltime = float(family.get('all_time_earned') or 0)
        send_telegram(chat_id, f'💰 <b>Money Summary for {kid_name}</b>\n\nCurrently owed: <b>${owed:.2f}</b>\nAll-time earned: <b>${alltime:.2f}</b>')

    else:
        send_telegram(chat_id,
            f'📋 <b>Commands for {kid_name}:</b>\n\n'
            '<b>yes</b> — approve chore ✅\n'
            '<b>no</b> — reject chore ❌\n'
            '<b>excused</b> — excuse kung fu\n'
            '<b>not excused</b> — not excused\n'
            '<b>pending</b> — see all pending\n'
            '<b>balance</b> — check money owed'
        )

    return 'ok'

@app.route('/')
def home():
    return 'The Happy Family Bot is running! 🏠'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
