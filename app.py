import eventlet
eventlet.monkey_patch()

import json, os, time, shutil
from flask import Flask, request, render_template, send_from_directory
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'cat_secure_2024'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Хранилище данных
DATA_DIR = '/opt/cat_data' if os.path.exists('/opt') else '/tmp/cat_data'
os.makedirs(DATA_DIR, exist_ok=True)

BACKUP_DIR = os.path.join(DATA_DIR, 'backups')
os.makedirs(BACKUP_DIR, exist_ok=True)

user_sessions = {}
ROLES = {'krembovan': 'owner'}

# --- СИСТЕМНЫЕ ФУНКЦИИ (БАЗА ДАННЫХ) ---

def load_db(key):
    path = os.path.join(DATA_DIR, f'{key}.json')
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ Ошибка загрузки {key}: {e}")
    return [] if key == 'messages' else {}

def save_db(key, data):
    path = os.path.join(DATA_DIR, f'{key}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def backup_db():
    for key in ['users', 'messages']:
        path = os.path.join(DATA_DIR, f'{key}.json')
        if os.path.exists(path):
            shutil.copy2(path, os.path.join(BACKUP_DIR, f'{key}_{int(time.time())}.json'))

def load_users(): return load_db('users')
def save_user(username, data):
    users = load_users()
    users[username.lower()] = data
    save_db('users', users)

def load_messages(): return load_db('messages')
def save_message(msg):
    msgs = load_messages()
    msgs.append(msg)
    if len(msgs) > 500: msgs = msgs[-500:]
    save_db('messages', msgs)

def get_role(username):
    return ROLES.get(username.lower(), 'user')

# --- РОУТЫ ---

@app.route('/')
def index(): return render_template('index.html')

@app.route('/static/<path:filename>')
def static_files(filename): return send_from_directory('templates/static', filename)

@app.route('/admin')
def admin_panel():
    auth = request.authorization
    if not auth: return ('Доступ запрещён', 401, {'WWW-Authenticate': 'Basic realm="Admin"'})
    
    admin_un = auth.username.lower()
    users = load_users()
    if admin_un not in users or users[admin_un].get('pass') != auth.password:
        return ('Ошибка входа', 401)
    
    role = get_role(admin_un)
    if role not in ['owner', 'admin', 'moderator']: return ('Нет прав', 403)
    
    # Очень упрощенная выдача HTML для админки (как в твоем исходнике)
    return f"<h1>Админ-панель CAT</h1><p>Пользователей в базе: {len(users)}</p><p>Вы вошли как: {admin_un}</p>"

# --- SOCKET.IO ОБРАБОТЧИКИ ---

@socketio.on('auth')
def handle_auth(data):
    action = data.get('action', 'login')
    un = data.get('username', '').strip().lower().replace('@', '')
    pwd = data.get('password', '')
    
    users = load_users()
    
    if action == 'register':
        if un in users:
            emit('auth_result', {'success': False, 'error': 'Логин занят'})
            return
        new_user = {
            'username': un, 'display_name': un, 'pass': pwd,
            'avatar': f'https://api.dicebear.com/7.x/bottts-neutral/svg?seed={un}',
            'bio': 'Новый пользователь', 'friends': [], 'requests': [], 'role': get_role(un)
        }
        save_user(un, new_user)
        users = load_users() # Перезагружаем

    if un not in users or users[un]['pass'] != pwd:
        emit('auth_result', {'success': False, 'error': 'Ошибка авторизации'})
        return

    user_data = users[un]
    user_data['role'] = get_role(un)
    user_sessions[un] = request.sid
    emit('auth_result', {'success': True, 'user': user_data})

@socketio.on('update_profile')
def handle_profile_update(data):
    un = data.get('username', '').lower()
    users = load_users()
    if un not in users: return
    
    if data.get('display_name'): users[un]['display_name'] = data['display_name'].strip()
    if 'bio' in data: users[un]['bio'] = data['bio'].strip()
    if data.get('avatar'): users[un]['avatar'] = data['avatar'].strip()
    
    save_user(un, users[un])
    # Отправляем обновленные данные обратно клиенту
    emit('auth_result', {'success': True, 'user': users[un]})

@socketio.on('get_user_profile')
def handle_get_user_profile(data):
    target_un = data.get('username', '').lower().replace('@', '')
    users = load_users()
    if target_un in users:
        u = users[target_un]
        emit('user_profile', {
            'username': target_un,
            'user': {
                'display_name': u.get('display_name', target_un),
                'avatar': u.get('avatar', ''),
                'bio': u.get('bio', ''),
                'role': get_role(target_un),
                'online': target_un in user_sessions
            }
        })

import eventlet
eventlet.monkey_patch()
import json, os, time
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'cat_secure_2026'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

DATA_DIR = './cat_data'
os.makedirs(DATA_DIR, exist_ok=True)

def load_db(key):
    path = os.path.join(DATA_DIR, f'{key}.json')
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f: return json.load(f)
        except: pass
    return [] if key == 'messages' else {}

def save_db(key, data):
    path = os.path.join(DATA_DIR, f'{key}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/')
def index(): return render_template('index.html')

@socketio.on('auth')
def handle_auth(data):
    un = data.get('username', '').strip().lower().replace('@', '')
    pwd = data.get('password', '')
    users = load_db('users')
    if un not in users:
        users[un] = {
            'username': un, 'display_name': un, 'pass': pwd,
            'avatar': f'https://api.dicebear.com/7.x/bottts-neutral/svg?seed={un}', 
            'bio': 'Привет! Я использую CAT Messenger'
        }
        save_db('users', users)
    if users[un]['pass'] == pwd:
        emit('auth_result', {'success': True, 'user': users[un]})
    else:
        emit('auth_result', {'success': False, 'error': 'Неверный пароль'})

@socketio.on('message')
def handle_msg(data):
    un = data.get('username', '').lower()
    room = data.get('room', 'Общий')
    text = data.get('text', '').strip()
    if not text: return
    users = load_db('users')
    user_info = users.get(un, {})
    msg = {
        'username': un, 'user': user_info.get('display_name', un),
        'avatar': user_info.get('avatar', ''), 'text': text,
        'room': room, 'timestamp': time.time()
    }
    msgs = load_db('messages')
    msgs.append(msg)
    save_db('messages', msgs[-300:])
    emit('message', msg, to=room) # ИСПРАВЛЕНО: Отправка в конкретную комнату

@socketio.on('join')
def on_join(data):
    room = data.get('room', 'Общий')
    join_room(room)
    msgs = load_db('messages')
    hist = [m for m in msgs if m.get('room') == room]
    emit('history', hist)

@socketio.on('update_profile')
def handle_profile_update(data):
    un = data.get('username', '').lower()
    users = load_db('users')
    if un in users:
        users[un]['display_name'] = data.get('display_name', users[un]['display_name']).strip()
        users[un]['bio'] = data.get('bio', users[un]['bio']).strip()
        users[un]['avatar'] = data.get('avatar', users[un]['avatar']).strip()
        save_db('users', users)
        emit('auth_result', {'success': True, 'user': users[un]})

@socketio.on('get_user_profile')
def handle_get_user_profile(data):
    target_un = data.get('username', '').lower().replace('@', '')
    users = load_db('users')
    if target_un in users:
        emit('user_profile', {'username': target_un, 'user': users[target_un]})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
    un = data.get('username', '').lower()
    room = data.get('room', 'Общий')
    text = data.get('text', '').strip()
    if not text: return

    users = load_users()
    if un in users:
        # Прикрепляем и актуальную аватарку, И актуальное имя
        data['avatar'] = users[un].get('avatar', '')
        data['user'] = users[un].get('display_name', un) # Теперь имя тоже живое
    
    data['timestamp'] = time.time()
    save_message(data)
    emit('message', data, room=room)

@socketio.on('join')
def on_join(data):
    room = data.get('room', 'Общий')
    join_room(room)
    msgs = load_messages()
    hist = [m for m in msgs if m.get('room') == room][-50:]
    emit('history', hist)

@socketio.on('send_friend_request')
def handle_friend_request(data):
    my_un = data.get('my_username', '').lower()
    target_un = data.get('target_username', '').lower().replace('@', '')
    users = load_users()
    if target_un in users and target_un != my_un:
        target = users[target_un]
        if my_un not in target.get('requests', []) and my_un not in target.get('friends', []):
            target.setdefault('requests', []).append(my_un)
            save_user(target_un, target)
            # Если цель онлайн, уведомляем
            if target_un in user_sessions:
                emit('auth_result', {'success': True, 'user': target}, room=user_sessions[target_un])

@socketio.on('accept_friend')
def handle_accept(data):
    my_un = data.get('my_username', '').lower()
    target_un = data.get('target_username', '').lower()
    users = load_users()
    if my_un in users and target_un in users:
        u, t = users[my_un], users[target_un]
        if target_un in u.get('requests', []):
            u['requests'].remove(target_un)
            u.setdefault('friends', []).append(target_un)
            t.setdefault('friends', []).append(my_un)
            save_user(my_un, u)
            save_user(target_un, t)
            emit('auth_result', {'success': True, 'user': u})
            if target_un in user_sessions:
                emit('auth_result', {'success': True, 'user': t}, room=user_sessions[target_un])

@socketio.on('disconnect')
def handle_disconnect():
    for un, sid in list(user_sessions.items()):
        if sid == request.sid:
            del user_sessions[un]
            break

# Авто-бекап
def auto_backup():
    while True:
        eventlet.sleep(900)
        backup_db()

eventlet.spawn(auto_backup)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))