# app.py — Полный код с фиксами
import eventlet
eventlet.monkey_patch()

import json, os, time
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'skam_secret_2024')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILES = {
    'history': os.path.join(BASE_DIR, 'history.json'),
    'users': os.path.join(BASE_DIR, 'users.json'),
    'registry': os.path.join(BASE_DIR, 'chats_registry.json')
}

def load_db(key):
    path = DB_FILES[key]
    if not os.path.exists(path):
        default = [] if key == 'history' else {}
        save_db(key, default)
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return [] if key == 'history' else {}

def save_db(key, data):
    with open(DB_FILES[key], 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('auth')
def handle_auth(data):
    action = data.get('action', 'login')
    un = data.get('username', '').strip().lower()
    dn = data.get('display_name', '').strip()
    pwd = data.get('password', '')
    pwd2 = data.get('password2', '')
    
    # Валидация
    if not un or len(un) < 3 or len(un) > 20:
        emit('auth_result', {'success': False, 'error': 'Username от 3 до 20 символов'})
        return
    if not pwd or len(pwd) < 4:
        emit('auth_result', {'success': False, 'error': 'Пароль минимум 4 символа'})
        return
    
    users = load_db('users')
    
    if action == 'register':
        if pwd != pwd2:
            emit('auth_result', {'success': False, 'error': 'Пароли не совпадают'})
            return
        if un in users:
            emit('auth_result', {'success': False, 'error': 'Пользователь уже существует'})
            return
        
        new_user = {
            'username': un,
            'display_name': dn or un,
            'pass': pwd,
            'avatar': f'https://api.dicebear.com/7.x/bottts-neutral/svg?seed={un}',
            'bio': 'Новый пользователь SKAM',
            'friends': [],
            'requests': []
        }
        users[un] = new_user
        save_db('users', users)
        emit('auth_result', {'success': True, 'user': new_user})
    
    else:  # login
        if un not in users:
            emit('auth_result', {'success': False, 'error': 'Пользователь не найден'})
            return
        if users[un]['pass'] != pwd:
            emit('auth_result', {'success': False, 'error': 'Неверный пароль'})
            return
        
        user_data = users[un]
        user_data.setdefault('friends', [])
        user_data.setdefault('requests', [])
        emit('auth_result', {'success': True, 'user': user_data})

@socketio.on('update_profile')
def handle_profile_update(data):
    un = data.get('username', '').lower()
    users = load_db('users')
    
    if un not in users:
        return
    
    # Обновляем только разрешённые поля
    if 'display_name' in data and data['display_name'].strip():
        users[un]['display_name'] = data['display_name'].strip()
    if 'bio' in data:
        users[un]['bio'] = data['bio'].strip()
    if 'avatar' in data and data['avatar'].strip():
        users[un]['avatar'] = data['avatar'].strip()
    
    save_db('users', users)
    emit('profile_updated', {'user': users[un]})

@socketio.on('send_friend_request')
def handle_friend_request(data):
    my_un = data.get('my_username', '').lower()
    target_un = data.get('target_username', '').lower().replace('@', '').strip()
    users = load_db('users')
    
    if not target_un:
        emit('friend_msg', {'text': 'Введите username', 'type': 'error'}, room=request.sid)
        return
    
    if target_un not in users:
        emit('friend_msg', {'text': 'Пользователь не найден', 'type': 'error'}, room=request.sid)
        return
    
    if target_un == my_un:
        emit('friend_msg', {'text': 'Нельзя добавить себя', 'type': 'error'}, room=request.sid)
        return
    
    user = users[target_un]
    if my_un in user.get('friends', []):
        emit('friend_msg', {'text': 'Вы уже друзья', 'type': 'info'}, room=request.sid)
        return
    
    if my_un in user.get('requests', []):
        emit('friend_msg', {'text': 'Запрос уже отправлен', 'type': 'info'}, room=request.sid)
        return
    
    user.setdefault('requests', []).append(my_un)
    save_db('users', users)
    emit('friend_msg', {'text': f'Запрос отправлен @{target_un}', 'type': 'success'}, room=request.sid)

@socketio.on('accept_friend')
def handle_accept(data):
    my_un = data.get('my_username', '').lower()
    target_un = data.get('target_username', '').lower()
    users = load_db('users')
    
    if not my_un in users:
        return
    
    user = users[my_un]
    if target_un not in user.get('requests', []):
        return
    
    user['requests'].remove(target_un)
    user.setdefault('friends', []).append(target_un)
    
    if target_un in users:
        users[target_un].setdefault('friends', []).append(my_un)
    
    # Создаём приватный чат
    reg = load_db('registry')
    chat_id = f"priv_{min(my_un, target_un)}_{max(my_un, target_un)}"
    if chat_id not in reg:
        reg[chat_id] = {"name": f"Чат с @{target_un}", "type": "private"}
        save_db('registry', reg)
    
    save_db('users', users)
    emit('auth_result', {'success': True, 'user': users[my_un]})
    emit('room_list', reg, broadcast=True)

@socketio.on('message')
def handle_msg(data):
    room = data.get('room', 'Общий')
    text = data.get('text', '').strip()
    
    if not text or len(text) > 1000:
        return
    
    data['timestamp'] = time.time()
    data['text'] = text
    
    h = load_db('history')
    h.append(data)
    if len(h) > 1000:
        h = h[-1000:]
    save_db('history', h)
    
    emit('message', data, room=room)

@socketio.on('join')
def on_join(data):
    room = data.get('room', 'Общий')
    join_room(room)
    hist = [m for m in load_db('history') if m.get('room') == room][-50:]
    emit('history', hist)

@socketio.on('get_rooms')
def get_rooms():
    reg = load_db('registry')
    # Добавляем общую комнату всегда
    if 'Общий' not in reg:
        reg['Общий'] = {"name": "Общий канал", "type": "public"}
    emit('room_list', reg)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))