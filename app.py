import eventlet
eventlet.monkey_patch()

import json, os, time
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'cyber_vibe_secret'
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
    nick = data.get('nick', '').strip() or "Guest"
    pwd = data.get('password', '')
    users = load_db('users')
    search_nick = nick.lower()
    
    if search_nick in users:
        if users[search_nick]['pass'] == pwd:
            emit('auth_result', {'success': True, 'user': users[search_nick]})
        else:
            emit('auth_result', {'success': False, 'error': 'Неверный пароль'})
    else:
        new_user = {'nick': nick, 'pass': pwd, 'avatar': 'https://i.imgur.com/6VBx3io.png', 'bio': 'Cyber Traveler', 'rank': 'User'}
        users[search_nick] = new_user
        save_db('users', users)
        emit('auth_result', {'success': True, 'user': new_user})

@socketio.on('update_profile')
def update_profile(data):
    users = load_db('users')
    nick_key = data.get('nick', '').lower()
    if nick_key in users:
        users[nick_key]['avatar'] = data.get('avatar')
        users[nick_key]['bio'] = data.get('bio')
        save_db('users', users)
        emit('auth_result', {'success': True, 'user': users[nick_key]})

@socketio.on('get_rooms')
def get_rooms():
    emit('room_list', load_db('registry'))

@socketio.on('join')
def on_join(data):
    room = data.get('room')
    if room:
        join_room(room)
        hist = [m for m in load_db('history') if m.get('room') == room]
        emit('history', hist)

@socketio.on('message')
def handle_msg(data):
    room = data.get('room')
    if not room: return
    data['timestamp'] = time.time()
    h = load_db('history')
    h.append(data)
    save_db('history', h[-1000:])
    emit('message', data, room=room)

@socketio.on('delete_chat')
def handle_delete(data):
    rid = data.get('chat_id')
    if data.get('delete_for_all'):
        msgs = [m for m in load_db('history') if m.get('room') != rid]
        save_db('history', msgs)
        emit('chat_deleted_globally', {'room': rid}, broadcast=True)
    else:
        emit('chat_hidden_locally', {'room': rid})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host='0.0.0.0', port=port)