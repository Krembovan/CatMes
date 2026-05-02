import json
import os
import time
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room
import threading
import time
import requests
import os

def keep_alive():
    # Даем серверу 30 секунд, чтобы просто запуститься перед первым пингом
    time.sleep(30)
    while True:
        try:
            # Render сам подставит URL в переменную окружения, либо впиши свою ссылку
            url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}"
            requests.get(url)
            print("Пинг выполнен: сервер не спит!")
        except Exception as e:
            print(f"Ошибка пинга: {e}")
        
        # Спим 10 минут (600 секунд)
        time.sleep(600)

# Запуск фонового потока
threading.Thread(target=keep_alive, daemon=True).start()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'skam_secret_key_1337'
socketio = SocketIO(app, cors_allowed_origins="*")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, 'history.json')
CHATS_FILE = os.path.join(BASE_DIR, 'chats_registry.json')
USERS_FILE = os.path.join(BASE_DIR, 'users.json')
HIDDEN_FILE = os.path.join(BASE_DIR, 'hidden_chats.json')

def load_json(filename, default):
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return default
    return default

def save_json(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('auth')
def on_auth(data):
    display_nick = data['nick'].strip()
    search_nick = display_nick.lower()
    password = data['password']
    users = load_json(USERS_FILE, {})
    if search_nick in users:
        if users[search_nick]['pass'] == password:
            users[search_nick]['last_seen'] = time.time()
            save_json(USERS_FILE, users)
            emit('auth_result', {'success': True, 'user_data': users[search_nick]})
        else:
            emit('auth_result', {'success': False, 'error': 'Неверный пароль!'})
    else:
        new_user = {'pass': password, 'display': display_nick, 'last_seen': time.time(), 'avatar': '', 'bio': 'Новичок в СКAM', 'username': search_nick}
        users[search_nick] = new_user
        save_json(USERS_FILE, users)
        emit('auth_result', {'success': True, 'user_data': new_user})

@socketio.on('update_profile')
def on_update_profile(data):
    old_lower = data['my_nick'].lower()
    users = load_json(USERS_FILE, {})
    if old_lower in users:
        users[old_lower].update({'display': data['new_display'], 'avatar': data['new_avatar'], 'bio': data['new_bio'], 'username': data['new_username'].replace('@', '').lower()})
        save_json(USERS_FILE, users)
        emit('profile_updated', users[old_lower], broadcast=True)
        emit('refresh_chat_list', broadcast=True)

@socketio.on('get_user_info')
def on_get_user(data):
    target_nick = data['nick'].lower()
    users = load_json(USERS_FILE, {})
    if target_nick in users:
        u = users[target_nick]
        emit('user_info_res', {'display': u.get('display'), 'avatar': u.get('avatar'), 'bio': u.get('bio', 'Нет описания'), 'username': u.get('username', '—'), 'online': (time.time() - u.get('last_seen', 0)) < 60})

@socketio.on('user_online')
def on_online(data):
    my_nick_lower = data['nick'].lower()
    join_room(f"user_{my_nick_lower}")
    users_db = load_json(USERS_FILE, {})
    if my_nick_lower in users_db:
        users_db[my_nick_lower]['last_seen'] = time.time()
        save_json(USERS_FILE, users_db)
    registry = load_json(CHATS_FILE, {})
    hidden = load_json(HIDDEN_FILE, {})
    my_chats = []
    for rid, u_list in registry.items():
        if my_nick_lower in u_list:
            if rid not in hidden or my_nick_lower not in hidden[rid]:
                other_lower = u_list[0] if u_list[1] == my_nick_lower else u_list[1]
                other_data = users_db.get(other_lower, {})
                my_chats.append({'display': other_data.get('display', other_lower), 'lower': other_lower, 'online': (time.time() - other_data.get('last_seen', 0)) < 60, 'avatar': other_data.get('avatar', '')})
    emit('init_chats', my_chats)

@socketio.on('hide_chat')
def on_hide_chat(data):
    my_nick = data['my_nick'].lower()
    rid = data['room_id']
    hidden = load_json(HIDDEN_FILE, {})
    if rid not in hidden: hidden[rid] = []
    if my_nick not in hidden[rid]: hidden[rid].append(my_nick)
    save_json(HIDDEN_FILE, hidden)
    emit('refresh_chat_list')

@socketio.on('delete_chat_history')
def on_delete_chat(data):
    rid = data['room_id']
    all_msgs = load_json(HISTORY_FILE, [])
    filtered_msgs = [m for m in all_msgs if m.get('room') != rid]
    save_json(HISTORY_FILE, filtered_msgs)
    emit('chat_deleted', {'room_id': rid}, broadcast=True)

@socketio.on('message')
def handle_message(data):
    room = data.get('room', 'Общий')
    data['timestamp'] = time.time()
    users = load_json(USERS_FILE, {})
    sender_data = users.get(data['n'].lower(), {})
    data['avatar'] = sender_data.get('avatar', '')
    all_msgs = load_json(HISTORY_FILE, [])
    all_msgs.append(data)
    save_json(HISTORY_FILE, [m for m in all_msgs if time.time() - m.get('timestamp', 0) < 86400])
    if room.startswith('direct_'):
        registry = load_json(CHATS_FILE, {})
        nicks = room.replace('direct_', '').split('_')
        if room not in registry: registry[room] = nicks
        save_json(CHATS_FILE, registry)
        hidden = load_json(HIDDEN_FILE, {})
        if room in hidden:
            hidden.pop(room)
            save_json(HIDDEN_FILE, hidden)
            emit('refresh_chat_list', broadcast=True)
    emit('message', data, room=room)

@socketio.on('typing')
def on_typing(data): emit('user_typing', data, room=data['room'], include_self=False)
@socketio.on('stop_typing')
def on_stop_typing(data): emit('user_stop_typing', data, room=data['room'], include_self=False)
@socketio.on('join')
def on_join(data):
    join_room(data['room'])
    history = [m for m in load_json(HISTORY_FILE, []) if m.get('room') == data['room']]
    emit('history', history)

if __name__ == '__main__':
    # Считываем порт, который даст Render (по умолчанию 10000 там)
    port = int(os.environ.get('PORT', 5000))
    # Запуск через socketio
    socketio.run(app, host='0.0.0.0', port=port)