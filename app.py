import eventlet
eventlet.monkey_patch()

import json, os, time
from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'skam_secure_2024'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

DATA_DIR = '/tmp/skam_data'
os.makedirs(DATA_DIR, exist_ok=True)

user_sessions = {}

def load_db(key):
    path = os.path.join(DATA_DIR, f'{key}.json')
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return [] if key == 'messages' else {}

def save_db(key, data):
    path = os.path.join(DATA_DIR, f'{key}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_users():
    return load_db('users')

def save_user(username, data):
    users = load_db('users')
    users[username] = data
    save_db('users', users)

def load_messages():
    return load_db('messages')

def save_message(msg):
    msgs = load_db('messages')
    msgs.append(msg)
    if len(msgs) > 500:
        msgs = msgs[-500:]
    save_db('messages', msgs)

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

ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'krembovan@181818'

ROLES = {'krembovan': 'owner'}

ROLE_PERMS = {
    'owner': ['admin_panel', 'manage_roles', 'delete_users', 'delete_messages', 'view_stats'],
    'admin': ['admin_panel', 'delete_users', 'delete_messages', 'view_stats'],
    'moderator': ['admin_panel', 'delete_messages'],
    'user': []
}

def get_role(username):
    role = ROLES.get(username.lower(), 'user')
    users = load_users()
    if username.lower() in users and users[username.lower()].get('role') != role:
        users[username.lower()]['role'] = role
        save_db('users', users)
    return role

@app.route('/admin')
def admin_panel():
    auth = request.authorization
    if not auth or auth.username != ADMIN_USERNAME or auth.password != ADMIN_PASSWORD:
        return ('Доступ запрещён', 401, {'WWW-Authenticate': 'Basic realm="Admin"'})
    
    users = load_users()
    msgs = load_messages()
    msg_count = len(msgs)
    last_msgs = msgs[-10:] if msgs else []
    last_msgs.reverse()
    
    users_list = []
    for username, d in users.items():
        users_list.append({
            'username': username,
            'display_name': d.get('display_name', ''),
            'role': d.get('role', 'user'),
            'friends': len(d.get('friends', [])),
            'requests': len(d.get('requests', []))
        })
    
    html = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>SKAM Admin Panel</title>
    <style>
        body { background: #0d1117; color: #e2e8f0; font-family: 'Segoe UI', sans-serif; padding: 30px; }
        h1 { background: linear-gradient(135deg, #7c5cfc, #38bdf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .stats { display: flex; gap: 20px; margin: 20px 0; }
        .stat-card { background: #161b22; padding: 20px; border-radius: 16px; border: 1px solid rgba(255,255,255,0.06); flex: 1; text-align: center; }
        .stat-value { font-size: 2rem; font-weight: 900; color: #7c5cfc; }
        .stat-label { font-size: 0.8rem; color: #94a3b8; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; background: #161b22; border-radius: 16px; overflow: hidden; }
        th { background: #7c5cfc; padding: 12px 16px; text-align: left; font-size: 0.8rem; text-transform: uppercase; }
        td { padding: 10px 16px; border-bottom: 1px solid rgba(255,255,255,0.04); }
        tr:hover { background: rgba(255,255,255,0.02); }
        .btn { padding: 6px 14px; border-radius: 8px; border: none; cursor: pointer; font-size: 0.75rem; font-weight: 600; margin: 2px; }
        .btn-danger { background: #ef4444; color: white; }
        .btn-sm { background: #7c5cfc; color: white; }
        .badge { padding: 3px 10px; border-radius: 20px; font-size: 0.7rem; font-weight: 700; }
        .badge-owner { background: #f59e0b; color: #0d1117; }
        .badge-admin { background: #ef4444; color: white; }
        .badge-mod { background: #10b981; color: white; }
        .badge-user { background: #94a3b8; color: #0d1117; }
        .section { margin-top: 30px; }
        .section h2 { font-size: 1rem; color: #94a3b8; margin-bottom: 10px; }
        .msg-item { background: #161b22; padding: 10px 16px; border-radius: 8px; margin: 5px 0; font-size: 0.85rem; }
        select { background: #161b22; color: white; border: 1px solid rgba(255,255,255,0.1); padding: 4px 8px; border-radius: 6px; }
    </style>
</head>
<body>
    <h1>⚡ SKAM Admin Panel</h1>
    <div class="stats">
        <div class="stat-card"><div class="stat-value">''' + str(len(users_list)) + '''</div><div class="stat-label">Пользователей</div></div>
        <div class="stat-card"><div class="stat-value">''' + str(msg_count) + '''</div><div class="stat-label">Сообщений</div></div>
    </div>
    <div class="section"><h2>👥 Пользователи</h2><table>
        <tr><th>Username</th><th>Имя</th><th>Роль</th><th>Друзья</th><th>Запросы</th><th>Действия</th></tr>'''
    
    for u in users_list:
        bc = 'badge-' + ('owner' if u['role'] == 'owner' else 'admin' if u['role'] == 'admin' else 'mod' if u['role'] == 'moderator' else 'user')
        rn = {'owner': 'Владелец', 'admin': 'Админ', 'moderator': 'Модер', 'user': 'Пользователь'}.get(u['role'], u['role'])
        html += f'''<tr><td>@{u['username']}</td><td>{u['display_name']}</td><td><span class="badge {bc}">{rn}</span></td><td>{u['friends']}</td><td>{u['requests']}</td>
            <td><select onchange="setRole('{u['username']}',this.value)"><option value="user" {"selected" if u['role']=='user' else ""}>Пользователь</option>
            <option value="moderator" {"selected" if u['role']=='moderator' else ""}>Модератор</option>
            <option value="admin" {"selected" if u['role']=='admin' else ""}>Админ</option></select>
            <button class="btn btn-danger" onclick="deleteUser('{u['username']}')">Удалить</button></td></tr>'''
    
    html += '''</table></div><div class="section"><h2>📝 Последние сообщения (модерация)</h2>'''
    
    for m in last_msgs:
        html += f'''<div class="msg-item"><b>@{m.get("username","")}</b>: {m.get("text","")[:100]}
            <span style="color:#94a3b8;font-size:0.7rem;">({m.get("room","")})</span>
            <button class="btn btn-sm" onclick="deleteMsg('{m.get('timestamp','')}')" style="float:right;">✕</button></div>'''
    
    html += '''</div><script>
        function deleteUser(un){if(!confirm("Удалить @"+un+"?"))return;fetch('/admin/delete/'+un,{method:'POST'}).then(r=>r.json()).then(d=>{alert(d.message);location.reload()});}
        function setRole(un,r){fetch('/admin/setrole/'+un+'/'+r,{method:'POST'}).then(r=>r.json()).then(d=>{alert(d.message);location.reload()});}
        function deleteMsg(ts){fetch('/admin/deletemsg/'+ts,{method:'POST'}).then(r=>r.json()).then(d=>{alert(d.message);location.reload()});}
    </script></body></html>'''
    return html

@app.route('/admin/delete/<username>', methods=['POST'])
def admin_delete_user(username):
    auth = request.authorization
    if not auth or auth.username != ADMIN_USERNAME or auth.password != ADMIN_PASSWORD:
        return json.dumps({'message':'Доступ запрещён'}),401
    un = username.lower()
    users = load_users()
    if un in users:
        del users[un]
        save_db('users', users)
    return json.dumps({'message':f'Пользователь @{un} удалён'})

@app.route('/admin/setrole/<username>/<role>', methods=['POST'])
def admin_set_role(username, role):
    auth = request.authorization
    if not auth or auth.username != ADMIN_USERNAME or auth.password != ADMIN_PASSWORD:
        return json.dumps({'message':'Доступ запрещён'}),401
    if role not in ['user','moderator','admin']:
        return json.dumps({'message':'Неверная роль'}),400
    un = username.lower()
    if get_role(un) == 'owner':
        return json.dumps({'message':'Нельзя изменить роль владельца'}),403
    ROLES[un] = role
    users = load_users()
    if un in users:
        users[un]['role'] = role
        save_db('users', users)
    return json.dumps({'message':f'Роль @{un} изменена на {role}'})

@app.route('/admin/deletemsg/<timestamp>', methods=['POST'])
def admin_delete_msg(timestamp):
    auth = request.authorization
    if not auth or auth.username != ADMIN_USERNAME or auth.password != ADMIN_PASSWORD:
        return json.dumps({'message':'Доступ запрещён'}),401
    msgs = load_messages()
    msgs = [m for m in msgs if str(m.get('timestamp')) != timestamp]
    save_db('messages', msgs)
    return json.dumps({'message':'Сообщение удалено'})

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
            'bio': 'Пользователь SKAM', 'friends': [], 'requests': [], 'notifications': [], 'role': get_role(un)
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
        user_data['role'] = get_role(un)
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
    if 'bio' in data: users[un]['bio'] = data['bio'].strip()
    if data.get('avatar', '').strip(): users[un]['avatar'] = data['avatar'].strip()
    save_user(un, users[un])
    emit('profile_updated', {'user': users[un]})

@socketio.on('send_friend_request')
def handle_friend_request(data):
    my_un = data.get('my_username', '').strip().lower()
    target_un = data.get('target_username', '').strip().lower().replace('@', '')
    if not target_un: emit('friend_msg', {'text': 'Введите имя', 'type': 'error'}); return
    users = load_users()
    if target_un not in users: emit('friend_msg', {'text': 'Пользователь не найден', 'type': 'error'}); return
    if target_un == my_un: emit('friend_msg', {'text': 'Нельзя добавить себя', 'type': 'error'}); return
    target = users[target_un]
    if my_un in target.get('friends', []): emit('friend_msg', {'text': 'Вы уже друзья', 'type': 'info'}); return
    if my_un in target.get('requests', []): emit('friend_msg', {'text': 'Запрос уже отправлен', 'type': 'info'}); return
    target.setdefault('requests', []).append(my_un)
    notif = {'id': str(int(time.time() * 1000)), 'type': 'friend_request', 'from': my_un, 'from_name': users[my_un].get('display_name', my_un), 'text': f'@{my_un} хочет добавить вас в друзья', 'timestamp': time.time(), 'read': False}
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
        if req.lower() == target_un: found = req; break
    if not found: return
    user['requests'].remove(found)
    if target_un not in user.get('friends', []): user.setdefault('friends', []).append(target_un)
    if target_un in users:
        if my_un not in users[target_un].get('friends', []):
            users[target_un].setdefault('friends', []).append(my_un)
            save_user(target_un, users[target_un])
    user.setdefault('notifications', [])
    user['notifications'] = [n for n in user['notifications'] if not (n.get('type')=='friend_request' and n.get('from','').lower()==target_un)]
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
        if req.lower() == target_un: found = req; break
    if found: user['requests'].remove(found)
    user.setdefault('notifications', [])
    user['notifications'] = [n for n in user['notifications'] if not (n.get('type')=='friend_request' and n.get('from','').lower()==target_un)]
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

@socketio.on('delete_message')
def handle_delete_message(data):
    msg_ts = str(data.get('msg_id', ''))
    username = data.get('username', '').lower()
    role = get_role(username)
    if role not in ['owner', 'admin', 'moderator']:
        emit('error_msg', {'text': 'Нет прав'})
        return
    msgs = load_messages()
    msgs = [m for m in msgs if str(m.get('timestamp')) != msg_ts]
    save_db('messages', msgs)
    emit('message_deleted', {'msg_id': msg_ts}, broadcast=True)

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
    save_message(data)
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
    msgs = load_messages()
    hist = [m for m in msgs if m.get('room') == room][-50:]
    emit('history', hist)

@socketio.on('get_rooms')
def get_rooms():
    emit('room_list', {'Общий': {"name": "Общий канал", "type": "public"}})

@socketio.on('get_user_profile')
def handle_get_user_profile(data):
    target_un = data.get('username', '').strip().lower()
    users = load_users()
    if target_un not in users:
        emit('user_profile', {'error': 'Пользователь не найден'})
        return
    user = users[target_un]
    role = get_role(target_un)
    role_names = {'owner': '👑 Владелец', 'admin': '🛡️ Админ', 'moderator': '🛡️ Модер', 'user': '👤 Пользователь'}
    emit('user_profile', {
        'username': target_un,
        'user': {
            'display_name': user.get('display_name', target_un),
            'avatar': user.get('avatar', ''),
            'bio': user.get('bio', ''),
            'friends': user.get('friends', []),
            'requests': user.get('requests', []),
            'role': role,
            'role_name': role_names.get(role, 'Пользователь')
        }
    })

@socketio.on('disconnect')
def handle_disconnect():
    for un, sid in list(user_sessions.items()):
        if sid == request.sid:
            del user_sessions[un]
            break

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host='0.0.0.0', port=port)