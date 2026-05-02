import eventlet
eventlet.monkey_patch()

import json, os, time
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'skam_forever_friends'
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
    un = data.get('username', '').strip().lower()
    dn = data.get('display_name', '').strip() or un
    pwd = data.get('password', '')
    users = load_db('users')
    
    if un in users:
        if users[un]['pass'] == pwd:
            user_data = users[un]
            user_data.setdefault('friends', [])
            user_data.setdefault('requests', [])
            emit('auth_result', {'success': True, 'user': user_data})
        else:
            emit('auth_result', {'success': False, 'error': 'Неверный пароль'})
    else:
        new_user = {'username': un, 'display_name': dn, 'pass': pwd, 
                    'avatar': f'https://i.pravatar.cc/150?u={un}', 
                    'bio': 'Пользователь SKAM', 'friends': [], 'requests': []}
        users[un] = new_user
        save_db('users', users)
        emit('auth_result', {'success': True, 'user': new_user})

@socketio.on('send_friend_request')
def handle_friend_request(data):
    my_un = data.get('my_username').lower()
    target_un = data.get('target_username').lower().replace('@', '')
    users = load_db('users')

    if target_un in users and target_un != my_un:
        if my_un not in users[target_un]['friends'] and my_un not in users[target_un]['requests']:
            users[target_un]['requests'].append(my_un)
            save_db('users', users)
            emit('friend_msg', {'text': 'Запрос отправлен!'}, room=request.sid)
    else:
        emit('friend_msg', {'text': 'Пользователь не найден'}, room=request.sid)

@socketio.on('accept_friend')
def handle_accept(data):
    my_un = data.get('my_username').lower()
    target_un = data.get('target_username').lower()
    users = load_db('users')

    if target_un in users[my_un]['requests']:
        users[my_un]['requests'].remove(target_un)
        if target_un not in users[my_un]['friends']: users[my_un]['friends'].append(target_un)
        if my_un not in users[target_un]['friends']: users[target_un]['friends'].append(my_un)
        save_db('users', users)
        
        # Создаем запись о привате
        reg = load_db('registry')
        chat_id = f"priv_{min(my_un, target_un)}_{max(my_un, target_un)}"
        reg[chat_id] = {"name": f"🤝 {target_un}", "type": "private"}
        save_db('registry', reg)
        
        emit('auth_result', {'success': True, 'user': users[my_un]})
        emit('room_list', reg, broadcast=True)

@socketio.on('message')
def handle_msg(data):
    room = data.get('room')
    data['timestamp'] = time.time()
    h = load_db('history')
    h.append(data)
    save_db('history', h[-1000:])
    emit('message', data, room=room)

@socketio.on('join')
def on_join(data):
    room = data.get('room')
    join_room(room)
    hist = [m for m in load_db('history') if m.get('room') == room]
    emit('history', hist)

@socketio.on('get_rooms')
def get_rooms():
    emit('room_list', load_db('registry'))

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))