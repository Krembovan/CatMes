import eventlet
eventlet.monkey_patch()

import json, os, time
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'skam_forever'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILES = {
    'history': os.path.join(BASE_DIR, 'history.json'),
    'users': os.path.join(BASE_DIR, 'users.json'),
    'registry': os.path.join(BASE_DIR, 'chats_registry.json')
}

def load_db(key):
    path = DB_FILES[key]
    if not os.path.exists(path): return [] if key == 'history' else {}
    try:
        with open(path, 'r', encoding='utf-8') as f: return json.load(f)
    except: return [] if key == 'history' else {}

def save_db(key, data):
    with open(DB_FILES[key], 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('auth')
def handle_auth(data):
    username = data.get('username', '').strip().lower() # Уникальный ID
    display_name = data.get('display_name', '').strip() or username
    pwd = data.get('password', '')
    
    users = load_db('users')
    
    if username in users:
        if users[username]['pass'] == pwd:
            emit('auth_result', {'success': True, 'user': users[username]})
        else:
            emit('auth_result', {'success': False, 'error': 'Неверный пароль'})
    else:
        # Регистрация нового
        new_user = {
            'username': username,
            'display_name': display_name,
            'pass': pwd,
            'avatar': 'https://i.pravatar.cc/150?u=' + username,
            'bio': 'Новый пользователь SKAM',
            'friends': [],
            'requests': []
        }
        users[username] = new_user
        save_db('users', users)
        emit('auth_result', {'success': True, 'user': new_user})

@socketio.on('update_profile')
def update_profile(data):
    users = load_db('users')
    old_un = data.get('old_username').lower()
    new_un = data.get('new_username').lower().strip()
    
    if old_un in users:
        # Если меняется юзернейм, проверяем уникальность
        if old_un != new_un and new_un in users:
            emit('error', {'msg': 'Этот юзернейм уже занят!'})
            return
        
        user_data = users.pop(old_un)
        user_data['username'] = new_un
        user_data['display_name'] = data.get('display_name')
        user_data['avatar'] = data.get('avatar')
        user_data['bio'] = data.get('bio')
        
        users[new_un] = user_data
        save_db('users', users)
        emit('auth_result', {'success': True, 'user': user_data})

@socketio.on('message')
def handle_msg(data):
    room = data.get('room')
    if not room: return
    data['timestamp'] = time.time()
    h = load_db('history')
    h.append(data)
    save_db('history', h[-1000:])
    emit('message', data, room=room)

@socketio.on('join')
def on_join(data):
    room = data.get('room')
    if room:
        join_room(room)
        hist = [m for m in load_db('history') if m.get('room') == room]
        emit('history', hist)

@socketio.on('get_rooms')
def get_rooms():
    emit('room_list', load_db('registry'))

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))