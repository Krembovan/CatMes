import eventlet
eventlet.monkey_patch()

import json, os, time, shutil
from flask import Flask, request, render_template, send_from_directory
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'cat_secure_2026'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Хранилище данных
DATA_DIR = './cat_data'
os.makedirs(DATA_DIR, exist_ok=True)

BACKUP_DIR = os.path.join(DATA_DIR, 'backups')
os.makedirs(BACKUP_DIR, exist_ok=True)

user_sessions = {} # username: sid
ROLES = {'krembovan': 'owner'}

# --- БАЗА ДАННЫХ ---

def load_db(key):
    path = os.path.join(DATA_DIR, f'{key}.json')
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return [] if key == 'messages' else {}

def save_db(key, data):
    path = os.path.join(DATA_DIR, f'{key}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# --- РОУТЫ ---

@app.route('/')
def index(): 
    return render_template('index.html')

@app.route('/admin')
def admin_panel():
    auth = request.authorization
    if not auth: return ('Доступ запрещён', 401, {'WWW-Authenticate': 'Basic realm="Admin"'})
    users = load_db('users')
    un = auth.username.lower()
    if un in users and users[un].get('pass') == auth.password:
        if ROLES.get(un) in ['owner', 'admin']:
            return f"<h1>Админка CAT</h1><p>Юзеров: {len(users)}</p>"
    return ('Отказ', 403)

# --- SOCKET.IO ---

@socketio.on('auth')
def handle_auth(data):
    un = data.get('username', '').strip().lower().replace('@', '')
    pwd = data.get('password', '')
    users = load_db('users')

    if un not in users:
        users[un] = {
            'username': un, 'display_name': un, 'pass': pwd,
            'avatar': f'https://api.dicebear.com/7.x/bottts-neutral/svg?seed={un}',
            'bio': 'Новый пользователь', 'friends': [], 'requests': []
        }
        save_db('users', users)

    if users[un]['pass'] == pwd:
        user_sessions[un] = request.sid
        users[un]['role'] = ROLES.get(un, 'user')
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
        'username': un,
        'user': user_info.get('display_name', un),
        'avatar': user_info.get('avatar', f'https://api.dicebear.com/7.x/bottts-neutral/svg?seed={un}'),
        'text': text,
        'room': room,
        'timestamp': time.time()
    }

    msgs = load_db('messages')
    msgs.append(msg)
    save_db('messages', msgs[-300:])
    emit('message', msg, to=room)

@socketio.on('join')
def on_join(data):
    room = data.get('room', 'Общий')
    join_room(room)
    msgs = load_db('messages')
    hist = [m for m in msgs if m.get('room') == room]
    emit('history', hist)

@socketio.on('update_profile')
def handle_update(data):
    un = data.get('username', '').lower()
    users = load_db('users')
    if un in users:
        for field in ['display_name', 'bio', 'avatar']:
            if field in data: users[un][field] = data[field].strip()
        save_db('users', users)
        emit('auth_result', {'success': True, 'user': users[un]})

@socketio.on('get_user_profile')
def handle_get_profile(data):
    target = data.get('username', '').lower().replace('@', '')
    users = load_db('users')
    if target in users:
        u = users[target]
        emit('user_profile', {
            'username': target,
            'user': {
                'display_name': u.get('display_name', target),
                'avatar': u.get('avatar', ''),
                'bio': u.get('bio', ''),
                'online': target in user_sessions
            }
        })

@socketio.on('disconnect')
def handle_disconnect():
    for un, sid in list(user_sessions.items()):
        if sid == request.sid:
            del user_sessions[un]
            break

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)