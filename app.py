import eventlet
eventlet.monkey_patch()

import os
import time
import uuid
import json
import html as html_module
from flask import Flask, request, render_template, send_from_directory, g
from flask_socketio import SocketIO, emit, join_room

# Импорт модуля авторизации
import auth

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', auth.hash_password(os.urandom(16).hex()))
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

DATA_DIR = os.environ.get('DATA_DIR', '/tmp/cat_data')
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, 'cat.db')

# ============================================================
# БАЗА ДАННЫХ SQLite
# ============================================================
def get_db():
    """Получить соединение с БД (thread-safe через g)."""
    if 'db' not in g:
        g.db = __import__('sqlite3').connect(DB_PATH)
        g.db.row_factory = __import__('sqlite3').Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

def close_db(error=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

app.teardown_appcontext(close_db)

def init_db():
    """Создать таблицы, если их нет."""
    import sqlite3 as sql
    conn = sql.connect(DB_PATH)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            avatar TEXT DEFAULT '',
            bio TEXT DEFAULT '',
            role TEXT DEFAULT 'user',
            friends TEXT DEFAULT '[]',
            requests TEXT DEFAULT '[]',
            notifications TEXT DEFAULT '[]',
            last_seen REAL DEFAULT 0,
            online INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            room TEXT NOT NULL,
            username TEXT NOT NULL,
            user TEXT NOT NULL,
            avatar TEXT DEFAULT '',
            text TEXT NOT NULL,
            timestamp REAL NOT NULL,
            read INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_messages_room ON messages(room);
        CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
    ''')
    conn.commit()
    conn.close()

init_db()

# ============================================================
# УТИЛИТЫ РАБОТЫ С БД
# ============================================================
def load_users() -> dict:
    """Загрузить всех пользователей как словарь {username: {...}}."""
    db = get_db()
    rows = db.execute("SELECT * FROM users").fetchall()
    result = {}
    for row in rows:
        d = dict(row)
        for field in ['friends', 'requests', 'notifications']:
            try:
                d[field] = json.loads(d[field])
            except:
                d[field] = []
        result[d['username']] = d
    return result

def save_user(username: str, data: dict):
    """Сохранить одного пользователя."""
    db = get_db()
    friends_json = json.dumps(data.get('friends', []), ensure_ascii=False)
    requests_json = json.dumps(data.get('requests', []), ensure_ascii=False)
    notifications_json = json.dumps(data.get('notifications', []), ensure_ascii=False)

    db.execute('''
        INSERT OR REPLACE INTO users (username, display_name, password_hash, avatar, bio, role, friends, requests, notifications, last_seen, online)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        username,
        data.get('display_name', username),
        data.get('password_hash', ''),
        data.get('avatar', ''),
        data.get('bio', ''),
        data.get('role', 'user'),
        friends_json,
        requests_json,
        notifications_json,
        data.get('last_seen', 0),
        int(data.get('online', False))
    ))
    db.commit()

def load_messages() -> list:
    """Загрузить все сообщения."""
    db = get_db()
    rows = db.execute("SELECT * FROM messages ORDER BY timestamp").fetchall()
    return [dict(r) for r in rows]

def save_message(msg: dict):
    """Сохранить одно сообщение + обрезать историю до 500 последних."""
    db = get_db()
    msg['id'] = msg.get('id', str(uuid.uuid4()))
    db.execute('''
        INSERT OR IGNORE INTO messages (id, room, username, user, avatar, text, timestamp, read)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        msg['id'],
        msg.get('room', 'Общий'),
        msg.get('username', ''),
        msg.get('user', ''),
        msg.get('avatar', ''),
        msg.get('text', ''),
        msg.get('timestamp', time.time()),
        int(msg.get('read', False))
    ))

    # Обрезаем старые сообщения (оставляем последние 500)
    count = db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    if count > 500:
        db.execute('''
            DELETE FROM messages WHERE id IN (
                SELECT id FROM messages ORDER BY timestamp ASC LIMIT ?
            )
        ''', (count - 500,))

    db.commit()

def get_user(username: str) -> dict | None:
    """Получить одного пользователя по username."""
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    for field in ['friends', 'requests', 'notifications']:
        try:
            d[field] = json.loads(d[field])
        except:
            d[field] = []
    return d

# ============================================================
# КОРРЕКТНАЯ РОЛЬ (через auth.py)
# ============================================================
def get_role(username: str) -> str:
    """Получить роль пользователя (синхронизирует с auth.DEFAULT_ROLES)."""
    user = get_user(username.lower())
    saved_role = user.get('role', 'user') if user else 'user'
    role = auth.get_role(username.lower(), saved_role)

    # Если роль изменилась (например, владелец в DEFAULT_ROLES), обновляем БД
    if user and user.get('role') != role:
        user['role'] = role
        save_user(username.lower(), user)

    return role

# ============================================================
# УВЕДОМЛЕНИЯ
# ============================================================
def notify_user(username: str, event: str, data: dict):
    """Отправить SocketIO событие конкретному пользователю."""
    sid = auth.get_session_sid(username)
    if sid:
        try:
            socketio.emit(event, data, room=sid)
        except:
            pass

def notify_friends(username: str, event: str, data: dict):
    """Отправить событие всем друзьям пользователя."""
    user = get_user(username)
    if user and 'friends' in user:
        for friend in user['friends']:
            notify_user(friend, event, data)

# ============================================================
# МИГРАЦИЯ С JSON НА SQLite (одноразовая)
# ============================================================
def migrate_json_to_sqlite():
    """Перенести данные из старых JSON-файлов в SQLite (если нужно)."""
    # Проверяем, есть ли уже пользователи в БД
    db = get_db()
    count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count > 0:
        return  # Уже мигрировали

    users_path = os.path.join(DATA_DIR, 'users.json')
    messages_path = os.path.join(DATA_DIR, 'messages.json')

    if os.path.exists(users_path):
        with open(users_path, 'r', encoding='utf-8') as f:
            users = json.load(f)
        for username, data in users.items():
            if 'pass' in data and not data.get('password_hash'):
                # Мигрируем старый пароль в хеш через auth.py
                data['password_hash'] = auth.hash_password(data.pop('pass', ''))
            elif 'pass' in data:
                del data['pass']
            save_user(username, data)
        os.rename(users_path, users_path + '.bak')

    if os.path.exists(messages_path):
        with open(messages_path, 'r', encoding='utf-8') as f:
            messages = json.load(f)
        for msg in messages[:500]:
            msg['id'] = msg.get('id', str(uuid.uuid4()))
            save_message(msg)
        os.rename(messages_path, messages_path + '.bak')

migrate_json_to_sqlite()

# ============================================================
# ФИЛЬТР ДЛЯ КЛИЕНТА (убираем password_hash)
# ============================================================
def safe_user_for_client(user: dict) -> dict:
    """Вернуть копию пользователя без конфиденциальных полей."""
    return {k: v for k, v in user.items() if k != 'password_hash'}

# ============================================================
# МАРШРУТЫ FLASK
# ============================================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('templates/static', filename)

@app.route('/sw.js')
def service_worker():
    return send_from_directory('templates/static', 'sw.js')

# ============================================================
# АДМИН-ПАНЕЛЬ (ИСПРАВЛЕН XSS + ИСПОЛЬЗУЕТ auth.py)
# ============================================================
@app.route('/admin')
def admin_panel():
    auth_header = request.authorization
    if not auth_header:
        return ('Доступ запрещён', 401, {'WWW-Authenticate': 'Basic realm="Admin"'})

    username = auth_header.username.lower()
    password = auth_header.password
    user = get_user(username)

    if not user or not auth.verify_password(password, user.get('password_hash', '')):
        return ('Неверный логин или пароль', 401, {'WWW-Authenticate': 'Basic realm="Admin"'})

    role = get_role(username)
    if not auth.can_access_admin(role):
        return ('Доступ запрещён', 403)

    msgs = load_messages()
    msg_count = len(msgs)
    general_msgs = [m for m in msgs if m.get('room') == 'Общий']
    last_msgs = general_msgs[-10:] if general_msgs else []
    last_msgs.reverse()

    users_list = []
    all_users = load_users()
    for uname, d in all_users.items():
        users_list.append({
            'username': html_module.escape(uname),
            'display_name': html_module.escape(d.get('display_name', '')),
            'role': html_module.escape(d.get('role', 'user')),
            'friends': len(d.get('friends', [])),
            'requests': len(d.get('requests', []))
        })

    can_manage = role in ['owner', 'admin']
    role_display = auth.get_role_display(role)

    html = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>CAT Admin Panel</title>
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
        .user-info { color: #f59e0b; margin-bottom: 20px; }
    </style>
</head>
<body>
    <h1>⚡ CAT Admin Panel</h1>
    <div class="user-info">Вы вошли как: @''' + html_module.escape(username) + ''' (''' + html_module.escape(role_display) + ''')</div>
    <div class="stats">
        <div class="stat-card"><div class="stat-value">''' + str(len(users_list)) + '''</div><div class="stat-label">Пользователей</div></div>
        <div class="stat-card"><div class="stat-value">''' + str(msg_count) + '''</div><div class="stat-label">Сообщений</div></div>
    </div>
    <div class="section"><h2>👥 Пользователи</h2><table>
        <tr><th>Username</th><th>Имя</th><th>Роль</th><th>Друзья</th><th>Запросы</th>'''

    if can_manage:
        html += '<th>Действия</th>'
    html += '</tr>'

    for u in users_list:
        bc = 'badge-' + ('owner' if u['role'] == 'owner' else 'admin' if u['role'] == 'admin' else 'mod' if u['role'] == 'moderator' else 'user')
        rn = {
            'owner': 'Владелец', 'admin': 'Админ', 'moderator': 'Модер', 'user': 'Пользователь'
        }.get(u['role'], u['role'])
        html += f'''<tr><td>@{u['username']}</td><td>{u['display_name']}</td><td><span class="badge {bc}">{rn}</span></td><td>{u['friends']}</td><td>{u['requests']}</td>'''

        if can_manage and u['role'] != 'owner':
            admin_role = get_role(username)
            target_role = get_role(u['username'].lower())
            if auth.can_manage_role(admin_role, target_role):
                html += f'''<td><select onchange="setRole('{u['username']}',this.value)">
                    <option value="user" {"selected" if u['role']=='user' else ""}>Пользователь</option>
                    <option value="moderator" {"selected" if u['role']=='moderator' else ""}>Модератор</option>
                    <option value="admin" {"selected" if u['role']=='admin' else ""}>Админ</option></select>
                    <button class="btn btn-danger" onclick="deleteUser('{u['username']}')">Удалить</button></td>'''
            else:
                html += '<td>—</td>'
        elif u['role'] == 'owner':
            html += '<td><span style="color:#f59e0b;">Владелец</span></td>'
        html += '</tr>'

    html += '''</table></div><div class="section"><h2>📝 Сообщения (модерация)</h2>'''
    for m in last_msgs:
        msg_user = html_module.escape(m.get('username', ''))
        msg_text = html_module.escape(m.get('text', '')[:100])
        msg_id = html_module.escape(str(m.get('id', '')))
        html += f'''<div class="msg-item"><b>@{msg_user}</b>: {msg_text}
            <button class="btn btn-sm" onclick="deleteMsg('{msg_id}')" style="float:right;">✕</button></div>'''

    html += '''</div><script>
        function deleteUser(un){if(!confirm("Удалить @"+un+"?"))return;
            fetch('/admin/delete/'+un,{method:'POST'}).then(r=>r.json()).then(d=>{alert(d.message);location.reload()});}
        function setRole(un,r){fetch('/admin/setrole/'+un+'/'+r,{method:'POST'}).then(r=>r.json()).then(d=>{alert(d.message);location.reload()});}
        function deleteMsg(id){fetch('/admin/deletemsg/'+id,{method:'POST'}).then(r=>r.json()).then(d=>{alert(d.message);location.reload()});}
    </script></body></html>'''
    return html


@app.route('/admin/delete/<username>', methods=['POST'])
def admin_delete_user(username):
    auth_header = request.authorization
    if not auth_header:
        return ({'message': 'Доступ запрещён'}, 401)

    admin_un = auth_header.username.lower()
    if get_role(admin_un) not in ['owner', 'admin']:
        return ({'message': 'Нет прав'}, 403)

    un = username.lower()
    target_role = get_role(un)

    if not auth.can_manage_role(get_role(admin_un), target_role):
        return ({'message': 'Недостаточно прав для удаления этого пользователя'}, 403)

    db = get_db()
    db.execute("DELETE FROM users WHERE username = ?", (un,))
    db.commit()
    return {'message': f'Пользователь @{un} удалён'}


@app.route('/admin/setrole/<username>/<role>', methods=['POST'])
def admin_set_role(username, role):
    auth_header = request.authorization
    if not auth_header:
        return ({'message': 'Доступ запрещён'}, 401)

    admin_un = auth_header.username.lower()
    admin_role = get_role(admin_un)

    if admin_role not in ['owner', 'admin']:
        return ({'message': 'Нет прав'}, 403)

    if role not in ['user', 'moderator', 'admin']:
        return ({'message': 'Неверная роль'}, 400)

    un = username.lower()
    target_role = get_role(un)

    if not auth.can_manage_role(admin_role, target_role):
        return ({'message': 'Недостаточно прав для изменения роли этого пользователя'}, 403)

    user = get_user(un)
    if user:
        user['role'] = role
        save_user(un, user)

    return {'message': f'Роль @{un} изменена на {role}'}


@app.route('/admin/deletemsg/<msg_id>', methods=['POST'])
def admin_delete_msg(msg_id):
    auth_header = request.authorization
    if not auth_header:
        return ({'message': 'Доступ запрещён'}, 401)

    role = get_role(auth_header.username.lower())
    if not auth.can_delete_message(role):
        return ({'message': 'Нет прав'}, 403)

    db = get_db()
    db.execute("DELETE FROM messages WHERE id = ?", (msg_id,))
    db.commit()
    return {'message': 'Сообщение удалено'}


# ============================================================
# SOCKET.IO ОБРАБОТЧИКИ
# ============================================================
@socketio.on('auth')
def handle_auth(data):
    action = data.get('action', 'login')
    un = data.get('username', '').strip().lower().replace('@', '')
    dn = data.get('display_name', '').strip()
    pwd = data.get('password', '')
    pwd2 = data.get('password2', '')

    # Валидация через auth.py
    valid_un, un = auth.validate_username(un)
    if not valid_un:
        emit('auth_result', {'success': False, 'error': un})
        return

    valid_pwd, pwd = auth.validate_password(pwd)
    if not valid_pwd:
        emit('auth_result', {'success': False, 'error': pwd})
        return

    if action == 'register':
        valid_dn, dn = auth.validate_display_name(dn)
        if not valid_dn:
            emit('auth_result', {'success': False, 'error': dn})
            return

        if pwd != pwd2:
            emit('auth_result', {'success': False, 'error': 'Пароли не совпадают'})
            return

        existing = get_user(un)
        if existing:
            emit('auth_result', {'success': False, 'error': 'Пользователь уже существует'})
            return

        new_user = {
            'username': un,
            'display_name': dn,
            'password_hash': auth.hash_password(pwd),
            'avatar': f'https://api.dicebear.com/7.x/bottts-neutral/svg?seed={un}',
            'bio': 'Пользователь CAT',
            'friends': [],
            'requests': [],
            'notifications': [],
            'role': get_role(un),
            'last_seen': time.time(),
            'online': True
        }
        save_user(un, new_user)
        auth.set_session(un, request.sid)
        auth.record_login_attempt(un, True)

        emit('auth_result', {'success': True, 'user': safe_user_for_client(new_user)})

    else:  # login
        # Проверка rate limit
        allowed, error = auth.check_login_rate_limit(un)
        if not allowed:
            emit('auth_result', {'success': False, 'error': error})
            return

        user = get_user(un)
        if not user:
            auth.record_login_attempt(un, False)
            emit('auth_result', {'success': False, 'error': 'Пользователь не найден'})
            return

        if not auth.verify_password(pwd, user.get('password_hash', '')):
            auth.record_login_attempt(un, False)
            emit('auth_result', {'success': False, 'error': 'Неверный пароль'})
            return

        # Проверить, не нужно ли обновить хеш (для будущих апгрейдов)
        if auth.needs_password_rehash(user.get('password_hash', '')):
            user['password_hash'] = auth.hash_password(pwd)
            save_user(un, user)

        auth.record_login_attempt(un, True)
        user['role'] = get_role(un)
        user['friends'] = user.get('friends', [])
        user['requests'] = user.get('requests', [])
        user['notifications'] = user.get('notifications', [])
        user['online'] = True
        user['last_seen'] = time.time()
        auth.set_session(un, request.sid)

        save_user(un, user)
        notify_friends(un, 'friend_online', {'username': un, 'online': True})

        emit('auth_result', {'success': True, 'user': safe_user_for_client(user)})


@socketio.on('update_profile')
def handle_profile_update(data):
    un = data.get('username', '').lower()
    user = get_user(un)
    if not user:
        return

    if data.get('display_name', '').strip():
        valid_dn, dn = auth.validate_display_name(data['display_name'])
        if valid_dn:
            user['display_name'] = dn

    if 'bio' in data:
        user['bio'] = data['bio'].strip()[:200]  # Ограничение длины

    if data.get('avatar', '').strip():
        avatar = data['avatar'].strip()
        # Базовая проверка URL
        if avatar.startswith('http://') or avatar.startswith('https://'):
            user['avatar'] = avatar[:500]  # Ограничение длины

    save_user(un, user)
    emit('profile_updated', {'user': safe_user_for_client(user)})


@socketio.on('send_friend_request')
def handle_friend_request(data):
    my_un = data.get('my_username', '').strip().lower()
    target_un = data.get('target_username', '').strip().lower().replace('@', '')

    if not target_un:
        emit('friend_msg', {'text': 'Введите имя', 'type': 'error'})
        return

    target = get_user(target_un)
    if not target:
        emit('friend_msg', {'text': 'Пользователь не найден', 'type': 'error'})
        return
    if target_un == my_un:
        emit('friend_msg', {'text': 'Нельзя добавить себя', 'type': 'error'})
        return
    if my_un in target.get('friends', []):
        emit('friend_msg', {'text': 'Вы уже друзья', 'type': 'info'})
        return
    if my_un in target.get('requests', []):
        emit('friend_msg', {'text': 'Запрос уже отправлен', 'type': 'info'})
        return

    target['requests'] = target.get('requests', [])
    target['requests'].append(my_un)

    notif = {
        'id': str(uuid.uuid4()),
        'type': 'friend_request',
        'from': my_un,
        'from_name': get_user(my_un).get('display_name', my_un) if get_user(my_un) else my_un,
        'text': f'@{my_un} хочет добавить вас в друзья',
        'timestamp': time.time(),
        'read': False
    }
    target['notifications'] = target.get('notifications', [])
    target['notifications'].insert(0, notif)

    save_user(target_un, target)
    emit('friend_msg', {'text': f'Запрос отправлен @{target_un}', 'type': 'success'})
    notify_user(target_un, 'incoming_friend_request', {'user': safe_user_for_client(target), 'from': my_un})


@socketio.on('accept_friend')
def handle_accept(data):
    my_un = data.get('my_username', '').strip().lower()
    target_un = data.get('target_username', '').strip().lower()

    user = get_user(my_un)
    if not user:
        return

    found = None
    for req in user.get('requests', []):
        if req.lower() == target_un:
            found = req
            break

    if not found:
        return

    user['requests'].remove(found)
    user['friends'] = user.get('friends', [])
    if target_un not in user['friends']:
        user['friends'].append(target_un)

    target = get_user(target_un)
    if target:
        target['friends'] = target.get('friends', [])
        if my_un not in target['friends']:
            target['friends'].append(my_un)
        save_user(target_un, target)

    user['notifications'] = [
        n for n in user.get('notifications', [])
        if not (n.get('type') == 'friend_request' and n.get('from', '').lower() == target_un)
    ]

    save_user(my_un, user)
    emit('auth_result', {'success': True, 'user': safe_user_for_client(user)})
    notify_user(target_un, 'friend_accepted_notify', {'user': safe_user_for_client(target) if target else None, 'by': my_un})


@socketio.on('decline_friend')
def handle_decline(data):
    my_un = data.get('my_username', '').strip().lower()
    target_un = data.get('target_username', '').strip().lower()

    user = get_user(my_un)
    if not user:
        return

    found = None
    for req in user.get('requests', []):
        if req.lower() == target_un:
            found = req
            break

    if found:
        user['requests'].remove(found)

    user['notifications'] = [
        n for n in user.get('notifications', [])
        if not (n.get('type') == 'friend_request' and n.get('from', '').lower() == target_un)
    ]

    save_user(my_un, user)
    emit('auth_result', {'success': True, 'user': safe_user_for_client(user)})


@socketio.on('remove_friend')
def handle_remove_friend(data):
    my_un = data.get('my_username', '').strip().lower()
    target_un = data.get('target_username', '').strip().lower()

    user = get_user(my_un)
    if not user:
        return

    if target_un in user.get('friends', []):
        user['friends'].remove(target_un)
        save_user(my_un, user)

    target = get_user(target_un)
    if target and my_un in target.get('friends', []):
        target['friends'].remove(my_un)
        save_user(target_un, target)

    emit('auth_result', {'success': True, 'user': safe_user_for_client(user)})
    notify_user(target_un, 'friend_removed_notify', {'user': safe_user_for_client(target) if target else None, 'by': my_un})


@socketio.on('delete_message')
def handle_delete_message(data):
    msg_id = str(data.get('msg_id', ''))
    username = data.get('username', '').lower()
    role = get_role(username)

    if not auth.can_delete_message(role):
        emit('error_msg', {'text': 'Нет прав'})
        return

    db = get_db()
    db.execute("DELETE FROM messages WHERE id = ?", (msg_id,))
    db.commit()

    emit('message_deleted', {'msg_id': msg_id}, broadcast=True)


@socketio.on('message')
def handle_msg(data):
    room = data.get('room', 'Общий')
    text = data.get('text', '').strip()

    if not text or len(text) > 1000:
        return

    # Нормализация DM-комнаты
    if room.startswith('dm_'):
        parts = room.split('_')
        if len(parts) >= 3:
            a, b = sorted([parts[1], parts[2]])
            room = f"dm_{a}_{b}"

    data['room'] = room
    data['timestamp'] = time.time()
    data['text'] = text
    data['read'] = False

    save_message(data)

    # Уведомление для DM
    if room.startswith('dm_'):
        parts = room.split('_')
        for p in parts[1:]:
            if p != data.get('username', ''):
                notify_user(p, 'new_dm', {
                    'from': data.get('username'),
                    'text': text[:30],
                    'room': room
                })

    emit('message', data, room=room)


@socketio.on('mark_read')
def handle_mark_read(data):
    room = data.get('room', '')
    username = data.get('username', '')

    if room:
        db = get_db()
        db.execute(
            "UPDATE messages SET read = 1 WHERE room = ? AND username != ?",
            (room, username)
        )
        db.commit()
        emit('messages_read', {'room': room, 'by': username}, room=room)


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
    msgs = db.execute(
        "SELECT * FROM messages WHERE room = ? ORDER BY timestamp DESC LIMIT 50",
        (room,)
    ).fetchall()

    hist = [dict(m) for m in reversed(msgs)]
    emit('history', hist)


@socketio.on('get_rooms')
def get_rooms():
    emit('room_list', {'Общий': {"name": "Общий канал", "type": "public"}})


@socketio.on('get_user_profile')
def handle_get_user_profile(data):
    target_un = data.get('username', '').strip().lower().replace('@', '')
    user = get_user(target_un)

    if not user:
        emit('user_profile', {'error': 'Пользователь не найден'})
        return

    role = get_role(target_un)

    emit('user_profile', {
        'username': target_un,
        'user': {
            'display_name': user.get('display_name', target_un),
            'avatar': user.get('avatar', ''),
            'bio': user.get('bio', ''),
            'friends': user.get('friends', []),
            'requests': user.get('requests', []),
            'role': role,
            'role_name': auth.get_role_display(role),
            'online': auth.is_online(target_un),
            'last_seen': user.get('last_seen', 0)
        }
    })


@socketio.on('check_status')
def handle_check_status(data):
    un = data.get('username', '').lower()
    emit('friend_online', {'username': un, 'online': auth.is_online(un)})


@socketio.on('disconnect')
def handle_disconnect():
    username = auth.remove_session(request.sid)
    if username:
        user = get_user(username)
        if user:
            user['online'] = False
            user['last_seen'] = time.time()
            save_user(username, user)
            notify_friends(username, 'friend_online', {'username': username, 'online': False})


@socketio.on('typing')
def handle_typing(data):
    room = data.get('room', '')
    if room.startswith('dm_'):
        emit('user_typing', {
            'username': data.get('username'),
            'user': data.get('user')
        }, room=room, include_self=False)


@socketio.on('get_avatar')
def handle_get_avatar(data):
    un = data.get('username', '').lower()
    user = get_user(un)
    if user:
        emit('friend_avatar', {'username': un, 'avatar': user.get('avatar', '')})


# WebRTC сигналинг
@socketio.on('call_user')
def handle_call_user(data):
    target = data.get('to')
    notify_user(target, 'incoming_call', {
        'from': data.get('from', ''),
        'sdp': data.get('sdp')
    })


@socketio.on('call_accepted')
def handle_call_accepted(data):
    notify_user(data.get('to'), 'call_accepted', {'sdp': data.get('sdp')})


@socketio.on('call_signal')
def handle_call_signal(data):
    notify_user(data.get('to'), 'call_signal', {'ice': data.get('ice')})


# ============================================================
# ЗАПУСК
# ============================================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host='0.0.0.0', port=port)