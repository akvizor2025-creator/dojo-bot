import os
import json
import urllib.request
from flask import Flask, request

app = Flask(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
MOM_CHAT_ID = os.environ.get('MOM_CHAT_ID')

def send_telegram(chat_id, msg):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    data = json.dumps({'chat_id': chat_id, 'text': msg, 'parse_mode': 'HTML'}).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    urllib.request.urlopen(req, timeout=10)

def supabase_patch(table, data, condition):
    url = f'{SUPABASE_URL}/rest/v1/{table}?{condition}'
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method='PATCH', headers={
        'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json'
    })
    urllib.request.urlopen(req, timeout=10)

def supabase_get(table, params=''):
    url = f'{SUPABASE_URL}/rest/v1/{table}?{params}'
    req = urllib.request.Request(url, headers={
        'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}'
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.json
    if not update or 'message' not in update:
        return 'ok'
    
    msg = update['message']
    chat_id = str(msg['chat']['id'])
    text = msg.get('text', '').strip().lower()
    
    # Only respond to mom
    if chat_id != str(MOM_CHAT_ID):
        return 'ok'
    
    if text in ('yes', 'y', '✓', 'approve', 'approved'):
        # Approve the oldest pending chore
        pending = supabase_get('chore_approvals', 'approved=is.null&select=*&order=created_at&limit=1')
        if pending:
            chore = pending[0]
            supabase_patch('chore_approvals', {'approved': True}, f'id=eq.{chore["id"]}')
            send_telegram(chat_id, f'✅ <b>{chore["chore_name"]}</b> approved!')
        else:
            send_telegram(chat_id, 'No pending approvals!')
    
    elif text in ('no', 'n', '✗', 'reject', 'rejected', 'nope'):
        # Reject the oldest pending chore
        pending = supabase_get('chore_approvals', 'approved=is.null&select=*&order=created_at&limit=1')
        if pending:
            chore = pending[0]
            supabase_patch('chore_approvals', {'approved': False}, f'id=eq.{chore["id"]}')
            # Add 50 points
            points = supabase_get('points', 'select=*&order=created_at&limit=1')
            if points:
                new_pts = (points[0].get('total_points') or 0) + 50
                new_hrs = min(new_pts // 100, 6)
                supabase_patch('points', {'total_points': new_pts, 'screen_time_penalty_hours': new_hrs}, f'id=eq.{points[0]["id"]}')
            send_telegram(chat_id, f'❌ <b>{chore["chore_name"]}</b> rejected. +50 points added.')
        else:
            send_telegram(chat_id, 'No pending approvals!')
    
    elif text in ('excused', 'excuse', 'yes excused'):
        pending = supabase_get('kungfu_approvals', 'excused=is.null&select=*&order=created_at&limit=1')
        if pending:
            supabase_patch('kungfu_approvals', {'excused': True}, f'id=eq.{pending[0]["id"]}')
            send_telegram(chat_id, '✅ Kung fu absence marked as excused.')
        else:
            send_telegram(chat_id, 'No pending kung fu records!')
    
    elif text in ('not excused', 'unexcused', 'no excuse'):
        pending = supabase_get('kungfu_approvals', 'excused=is.null&select=*&order=created_at&limit=1')
        if pending:
            supabase_patch('kungfu_approvals', {'excused': False}, f'id=eq.{pending[0]["id"]}')
            points = supabase_get('points', 'select=*&order=created_at&limit=1')
            if points:
                new_pts = (points[0].get('total_points') or 0) + 100
                new_hrs = min(new_pts // 100, 6)
                supabase_patch('points', {'total_points': new_pts, 'screen_time_penalty_hours': new_hrs}, f'id=eq.{points[0]["id"]}')
            send_telegram(chat_id, '❌ Kung fu absence marked as NOT excused. +100 points added.')
        else:
            send_telegram(chat_id, 'No pending kung fu records!')
    
    elif text == 'pending':
        pending = supabase_get('chore_approvals', 'approved=is.null&select=*&order=created_at')
        if pending:
            msg_text = '📋 <b>Pending approvals:</b>\n\n'
            for i, c in enumerate(pending, 1):
                msg_text += f'{i}. {c["chore_name"]} ({c["date"]})\n'
            msg_text += '\nReply <b>yes</b> or <b>no</b> to approve/reject one at a time.'
            send_telegram(chat_id, msg_text)
        else:
            send_telegram(chat_id, '✅ No pending approvals!')
    
    else:
        send_telegram(chat_id, '📋 <b>Commands:</b>\n\n<b>yes</b> — approve chore\n<b>no</b> — reject chore\n<b>excused</b> — excuse kung fu\n<b>not excused</b> — not excused\n<b>pending</b> — see all pending')
    
    return 'ok'

@app.route('/')
def home():
    return 'Dojo Bot is running!'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
