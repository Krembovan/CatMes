import eventlet
eventlet.monkey_patch()

import sqlite3, json, os, time
from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'skam_secure_2024'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'skam.db')
user_sessions = {}

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    db = get_db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            data TEXT
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room TEXT,
            username TEXT,
            user TEXT,
            avatar TEXT,
            text TEXT,
            timestamp REAL
        );
    ''')
    db.commit()
    db.close()

init_db()

def load_users():
    db = get_db()
    rows = db.execute("SELECT username, data FROM users").fetchall()
    db.close()
    return {row['username']: json.loads(row['data']) for row in rows}

def save_user(username, data):
    db = get_db()
    db.execute("INSERT OR REPLACE INTO users (username, data) VALUES (?, ?)",
               (username, json.dumps(data, ensure_ascii=False)))
    db.commit()
    db.close()

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

@app.route('/db')
def view_db():
    db = get_db()
    users = db.execute("SELECT username, data FROM users").fetchall()
    msgs = db.execute("SELECT COUNT(*) as c FROM messages").fetchone()
    db.close()
    html = '<h2>Пользователи:</h2><ul>'
    for u in users:
        d = json.loads(u['data'])
        html += f'<li>@{u["username"]} — {d.get("display_name")} | Друзей: {len(d.get("friends",[]))}</li>'
    html += f'</ul><h2>Сообщений: {msgs["c"]}</h2>'
    return html

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
    
    users = load_users()
    
    if action == 'register':
        if pwd != pwd2:
            emit('auth_result', {'success': False, 'error': 'Пароли не совпадают'})
            return
        if un in users:
            emit('auth_result', {'success': False, 'error': 'Пользователь уже существует'})
            return
        
        new_user = {
            'username': un, 'display_name': dn or un, 'pass': pwd,
            'avatar': f'https://api.dicebear.com/7.x/bottts-neutral/svg?seed={un}',
            'bio': 'Пользователь SKAM', 'friends': [], 'requests': [], 'notifications': []
        }
        save_user(un, new_user)
        user_sessions[un] = request.sid
        emit('auth_result', {'success': True, 'user': new_user})
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
    users = load_users()
    if un not in users: return
    if data.get('display_name', '').strip():
        users[un]['display_name'] = data['display_name'].strip()
    if 'bio' in data:
        users[un]['bio'] = data['bio'].strip()
    if data.get('avatar', '').strip():
        users[un]['avatar'] = data['avatar'].strip()
    save_user(un, users[un])
    emit('profile_updated', {'user': users[un]})

@socketio.on('send_friend_request')
def handle_friend_request(data):
    my_un = data.get('my_username', '').strip().lower()
    target_un = data.get('target_username', '').strip().lower().replace('@', '')
    
    if not target_un:
        emit('friend_msg', {'text': 'Введите имя', 'type': 'error'})
        return
    
    users = load_users()
    
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
    
    save_user(target_un, target)
    emit('friend_msg', {'text': f'Запрос отправлен @{target_un}', 'type': 'success'})
    notify_user(target_un, 'incoming_friend_request', {'user': target, 'from': my_un})

@socketio.on('accept_friend')
def handle_accept(data):
    my_un = data.get('my_username', '').strip().lower()
    target_un = data.get('target_username', '').strip().lower()
    
    users = load_users()
    if my_un not in users: return
    
    user = users[my_un]
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
            save_user(target_un, users[target_un])
    
    user.setdefault('notifications', [])
    user['notifications'] = [n for n in user['notifications'] if not (n.get('type') == 'friend_request' and n.get('from', '').lower() == target_un)]
    
    save_user(my_un, user)
    emit('auth_result', {'success': True, 'user': user})
    notify_user(target_un, 'friend_accepted_notify', {'user': users.get(target_un), 'by': my_un})

@socketio.on('decline_friend')
def handle_decline(data):
    my_un = data.get('my_username', '').strip().lower()
    target_un = data.get('target_username', '').strip().lower()
    users = load_users()
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
    save_user(my_un, user)
    emit('auth_result', {'success': True, 'user': user})

@socketio.on('remove_friend')
def handle_remove_friend(data):
    my_un = data.get('my_username', '').strip().lower()
    target_un = data.get('target_username', '').strip().lower()
    users = load_users()
    if my_un not in users: return
    
    if target_un in users[my_un].get('friends', []):
        users[my_un]['friends'].remove(target_un)
        save_user(my_un, users[my_un])
    if target_un in users and my_un in users[target_un].get('friends', []):
        users[target_un]['friends'].remove(my_un)
        save_user(target_un, users[target_un])
    
    emit('auth_result', {'success': True, 'user': users[my_un]})
    notify_user(target_un, 'friend_removed_notify', {'user': users.get(target_un), 'by': my_un})

@socketio.on('message')
def handle_msg(data):
    room = data.get('room', 'Общий')
    text = data.get('text', '').strip()
    if not text or len(text) > 1000: return
    
    if room.startswith('dm_'):
        parts = room.split('_')
        if len(parts) >= 3:
            a, b = sorted([parts[1], parts[2]])
            room = f"dm_{a}_{b}"
    
    data['room'] = room
    data['timestamp'] = time.time()
    data['text'] = text
    
    db = get_db()
    db.execute("INSERT INTO messages (room, username, user, avatar, text, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
               (room, data.get('username', ''), data.get('user', ''), data.get('avatar', ''), text, data['timestamp']))
    # Чистим старые
    db.execute("DELETE FROM messages WHERE id NOT IN (SELECT id FROM messages ORDER BY id DESC LIMIT 500)")
    db.commit()
    db.close()
    
    emit('message', data, room=room)

@socketio.on('join')
def on_join(data):
    room = data.get('room', 'Общий')
    
    if room.startswith('dm_'):
        parts = room.split('_')
        if len(parts) >= 3:
            a, b = sorted([parts[1], parts[2]])
            room = f"dm_{a}_{b}"
    
    join_room(room)
    db = get_db()
    rows = db.execute("SELECT * FROM messages WHERE room = ? ORDER BY id DESC LIMIT 50", (room,)).fetchall()
    db.close()
    hist = [dict(r) for r in reversed(rows)]
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