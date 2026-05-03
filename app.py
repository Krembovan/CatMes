import eventlet
eventlet.monkey_patch()

import json, os, time
from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'skam_secure_2024'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = {}
DB_FILES = {
    'history': os.path.join(BASE_DIR, 'history.json'),
    'users': os.path.join(BASE_DIR, 'users.json'),
    'registry': os.path.join(BASE_DIR, 'chats_registry.json')
}
user_sessions = {}

def load_db(key):
    path = DB_FILES[key]
    if key not in DB:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    DB[key] = json.load(f)
            except:
                DB[key] = [] if key == 'history' else {}
        else:
            DB[key] = [] if key == 'history' else {}
    return DB[key]

def save_db(key, data):
    DB[key] = data
    path = DB_FILES[key]
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving {key}: {e}", flush=True)

def notify_user(username, event, data):
    sid = user_sessions.get(username)
    if sid:
        try:
            socketio.emit(event, data, room=sid)
        except:
            pass

@app.route('/')
def index():
    from flask import render_template
    return render_template('index.html')

@socketio.on('auth')
def handle_auth(data):
    action = data.get('action', 'login')
    un = data.get('username', '').strip().lower()
    dn = data.get('display_name', '').strip()
    pwd = data.get('password', '')
    pwd2 = data.get('password2', '')
    
    if not un or len(un) < 3 or len(un) > 20:
        emit('auth_result', {'success': False, 'error': 'Логин: 3-20 символов'})
        return
    if not pwd or len(pwd) < 4:
        emit('auth_result', {'success': False, 'error': 'Пароль: минимум 4 символа'})
        return
    
    users = load_db('users')
    
    if action == 'register':
        if pwd != pwd2:
            emit('auth_result', {'success': False, 'error': 'Пароли не совпадают'})
            return
        if un in users:
            emit('auth_result', {'success': False, 'error': 'Пользователь уже существует'})
            return
        
        users[un] = {
            'username': un, 'display_name': dn or un, 'pass': pwd,
            'avatar': f'https://api.dicebear.com/7.x/bottts-neutral/svg?seed={un}',
            'bio': 'Пользователь SKAM', 'friends': [], 'requests': [], 'notifications': []
        }
        save_db('users', users)
        user_sessions[un] = request.sid
        emit('auth_result', {'success': True, 'user': users[un]})
    else:
        if un not in users:
            emit('auth_result', {'success': False, 'error': 'Пользователь не найден'})
            return
        if users[un]['pass'] != pwd:
            emit('auth_result', {'success': False, 'error': 'Неверный пароль'})
            return
        
        user_data = users[un]
        user_data.setdefault('friends', [])
        user_data.setdefault('requests', [])
        user_data.setdefault('notifications', [])
        user_sessions[un] = request.sid
        emit('auth_result', {'success': True, 'user': user_data})

@socketio.on('update_profile')
def handle_profile_update(data):
    un = data.get('username', '').lower()
    users = load_db('users')
    if un not in users: return
    if data.get('display_name', '').strip():
        users[un]['display_name'] = data['display_name'].strip()
    if 'bio' in data:
        users[un]['bio'] = data['bio'].strip()
    if data.get('avatar', '').strip():
        users[un]['avatar'] = data['avatar'].strip()
    save_db('users', users)
    emit('profile_updated', {'user': users[un]})

@socketio.on('send_friend_request')
def handle_friend_request(data):
    my_un = data.get('my_username', '').strip().lower()
    target_un = data.get('target_username', '').strip().lower().replace('@', '')
    
    if not target_un:
        emit('friend_msg', {'text': 'Введите имя', 'type': 'error'})
        return
    
    users = load_db('users')
    
    if target_un not in users:
        emit('friend_msg', {'text': 'Пользователь не найден', 'type': 'error'})
        return
    if target_un == my_un:
        emit('friend_msg', {'text': 'Нельзя добавить себя', 'type': 'error'})
        return
    
    target = users[target_un]
    
    if my_un in target.get('friends', []):
        emit('friend_msg', {'text': 'Вы уже друзья', 'type': 'info'})
        return
    if my_un in target.get('requests', []):
        emit('friend_msg', {'text': 'Запрос уже отправлен', 'type': 'info'})
        return
    
    target.setdefault('requests', []).append(my_un)
    
    notif = {
        'id': str(int(time.time() * 1000)),
        'type': 'friend_request',
        'from': my_un,
        'from_name': users[my_un].get('display_name', my_un),
        'text': f'@{my_un} хочет добавить вас в друзья',
        'timestamp': time.time(),
        'read': False
    }
    target.setdefault('notifications', []).insert(0, notif)
    
    save_db('users', users)
    emit('friend_msg', {'text': f'Запрос отправлен @{target_un}', 'type': 'success'})
    notify_user(target_un, 'incoming_friend_request', {'user': target, 'from': my_un})

@socketio.on('accept_friend')
def handle_accept(data):
    my_un = data.get('my_username', '').strip().lower()
    target_un = data.get('target_username', '').strip().lower()
    
    users = load_db('users')
    if my_un not in users: return
    
    user = users[my_un]
    
    # Ищем запрос
    found = None
    for req in user.get('requests', []):
        if req.lower() == target_un:
            found = req
            break
    if not found: return
    
    user['requests'].remove(found)
    if target_un not in user.get('friends', []):
        user.setdefault('friends', []).append(target_un)
    
    if target_un in users:
        if my_un not in users[target_un].get('friends', []):
            users[target_un].setdefault('friends', []).append(my_un)
    
    user.setdefault('notifications', [])
    user['notifications'] = [n for n in user['notifications'] if not (n.get('type') == 'friend_request' and n.get('from', '').lower() == target_un)]
    
    save_db('users', users)
    emit('auth_result', {'success': True, 'user': users[my_un]})
    notify_user(target_un, 'friend_accepted_notify', {'user': users[target_un], 'by': my_un})

@socketio.on('decline_friend')
def handle_decline(data):
    my_un = data.get('my_username', '').strip().lower()
    target_un = data.get('target_username', '').strip().lower()
    users = load_db('users')
    if my_un not in users: return
    
    user = users[my_un]
    found = None
    for req in user.get('requests', []):
        if req.lower() == target_un:
            found = req
            break
    if found:
        user['requests'].remove(found)
    
    user.setdefault('notifications', [])
    user['notifications'] = [n for n in user['notifications'] if not (n.get('type') == 'friend_request' and n.get('from', '').lower() == target_un)]
    save_db('users', users)
    emit('auth_result', {'success': True, 'user': users[my_un]})

@socketio.on('remove_friend')
def handle_remove_friend(data):
    my_un = data.get('my_username', '').strip().lower()
    target_un = data.get('target_username', '').strip().lower()
    users = load_db('users')
    if my_un not in users: return
    
    if target_un in users[my_un].get('friends', []):
        users[my_un]['friends'].remove(target_un)
    if target_un in users and my_un in users[target_un].get('friends', []):
        users[target_un]['friends'].remove(my_un)
    
    save_db('users', users)
    emit('auth_result', {'success': True, 'user': users[my_un]})
    notify_user(target_un, 'friend_removed_notify', {'user': users[target_un], 'by': my_un})

@socketio.on('message')
def handle_msg(data):
    room = data.get('room', 'Общий')
    text = data.get('text', '').strip()
    if not text or len(text) > 1000: return
    
    # Нормализуем DM комнаты
    if room.startswith('dm_'):
        parts = room.split('_')
        if len(parts) >= 3:
            a, b = sorted([parts[1], parts[2]])
            room = f"dm_{a}_{b}"
    
    data['room'] = room
    data['timestamp'] = time.time()
    data['text'] = text
    
    h = load_db('history')
    h.append(data)
    if len(h) > 1000: h = h[-1000:]
    save_db('history', h)
    emit('message', data, room=room)

@socketio.on('join')
def on_join(data):
    room = data.get('room', 'Общий')
    
    # Нормализуем DM комнаты
    if room.startswith('dm_'):
        parts = room.split('_')
        if len(parts) >= 3:
            a, b = sorted([parts[1], parts[2]])
            room = f"dm_{a}_{b}"
    
    join_room(room)
    hist = [m for m in load_db('history') if m.get('room') == room][-50:]
    emit('history', hist)

@socketio.on('get_rooms')
def get_rooms():
    emit('room_list', {'Общий': {"name": "Общий канал", "type": "public"}})

@socketio.on('disconnect')
def handle_disconnect():
    for un, sid in list(user_sessions.items()):
        if sid == request.sid:
            del user_sessions[un]
            break

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host='0.0.0.0', port=port)