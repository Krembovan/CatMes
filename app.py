import eventlet
eventlet.monkey_patch()

import json, os, time
from flask import Flask, render_template
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
    nick = data.get('nick', '').strip() or "Гость"
    pwd = data.get('password', '')
    users = load_db('users')
    search_nick = nick.lower()
    
    if search_nick in users:
        if users[search_nick]['pass'] == pwd:
            user_data = users[search_nick]
            # Гарантируем наличие полей
            user_data.setdefault('friends', [])
            user_data.setdefault('requests', [])
            emit('auth_result', {'success': True, 'user': user_data})
        else:
            emit('auth_result', {'success': False, 'error': 'Неверный пароль'})
    else:
        new_user = {
            'nick': nick, 'pass': pwd, 'avatar': '', 
            'bio': 'Пользователь Cyber Chat', 'friends': [], 'requests': []
        }
        users[search_nick] = new_user
        save_db('users', users)
        emit('auth_result', {'success': True, 'user': new_user})

@socketio.on('add_friend')
def add_friend(data):
    my_nick = data.get('my_nick').lower()
    target_nick = data.get('target_nick').lower()
    users = load_db('users')

    if target_nick in users and target_nick != my_nick:
        if my_nick not in users[target_nick]['requests'] and my_nick not in users[target_nick]['friends']:
            users[target_nick]['requests'].append(data.get('my_nick'))
            save_db('users', users)
            emit('friend_update', {'msg': 'Запрос отправлен!'}, room=request.sid)
    else:
        emit('friend_update', {'msg': 'Пользователь не найден'}, room=request.sid)

@socketio.on('accept_friend')
def accept_friend(data):
    my_nick = data.get('my_nick').lower()
    target_nick = data.get('target_nick').lower()
    users = load_db('users')

    if target_nick in users:
        # Убираем из заявок, добавляем в друзья обоим
        if data.get('target_nick') in users[my_nick]['requests']:
            users[my_nick]['requests'].remove(data.get('target_nick'))
        
        if data.get('target_nick') not in users[my_nick]['friends']:
            users[my_nick]['friends'].append(data.get('target_nick'))
        if data.get('my_nick') not in users[target_nick]['friends']:
            users[target_nick]['friends'].append(data.get('my_nick'))
        
        save_db('users', users)
        
        # Создаем приватный чат в реестре
        reg = load_db('registry')
        chat_id = f"priv_{min(my_nick, target_nick)}_{max(my_nick, target_nick)}"
        reg[chat_id] = {"name": f"🤝 {data.get('target_nick')}", "type": "private"}
        save_db('registry', reg)
        
        emit('auth_result', {'success': True, 'user': users[my_nick]})
        emit('room_list', reg, broadcast=True)

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