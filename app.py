import eventlet
eventlet.monkey_patch()

import json, os, time, hashlib, secrets, base64, uuid
from flask import Flask, request, render_template, send_from_directory
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('CAT_SECRET_KEY', os.urandom(32).hex())
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

DATA_DIR = os.environ.get('CAT_DATA_DIR', '/tmp/cat_data')
UPLOADS_DIR = os.path.join(DATA_DIR, 'uploads')
os.makedirs(UPLOADS_DIR, exist_ok=True)

user_sessions = {}
last_action = {}
consecutive_msgs = {}

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

def load_groups():
    return load_db('groups')

def save_groups(groups):
    save_db('groups', groups)

def save_group(gid, data):
    groups = load_db('groups')
    groups[gid] = data
    save_db('groups', groups)

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return f"pbkdf2:sha256:100000${salt}${h.hex()}"

def verify_password(password: str, hashed: str) -> bool:
    if not hashed or not isinstance(hashed, str):
        return False
    if not hashed.startswith('pbkdf2:'):
        return password == hashed
    try:
        meta_part, salt, stored_hash = hashed.split('$', 2)
        _, _, iterations_str = meta_part.split(':')
        iterations = int(iterations_str)
        h = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), iterations)
        return h.hex() == stored_hash
    except Exception as e:
        return False

def notify_user(username, event, data):
    sid = user_sessions.get(username)
    if sid:
        try:
            socketio.emit(event, data, room=sid)
        except Exception as e:
            print(f"[notify_user] Ошибка для @{username}: {e}")

def notify_friends(username, event, data):
    users = load_users()
    if username in users:
        for friend in users[username].get('friends', []):
            notify_user(friend, event, data)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('templates/static', filename)

@app.route('/sw.js')
def service_worker():
    return send_from_directory('templates/static', 'sw.js')

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOADS_DIR, filename)

RATE_LIMIT = 0.5
MAX_XP = 99999

def check_rate_limit(username):
    now = time.time()
    last = last_action.get(username, 0)
    if now - last < RATE_LIMIT:
        return False
    last_action[username] = now
    return True

ROLES = {'krembovan': 'owner'}

def html_escape(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#x27;')

def sync_roles():
    users = load_users()
    for un in users:
        if un in ROLES:
            users[un]['role'] = ROLES[un]
        if 'role' not in users[un]:
            users[un]['role'] = 'user'
    save_db('users', users)

sync_roles()

def migrate_created_at():
    users = load_users()
    changed = False
    base_time = time.time() - (len(users) * 3600)
    for i, (un, u) in enumerate(users.items()):
        if 'created_at' not in u:
            u['created_at'] = base_time + (i * 3600)
            changed = True
        u.setdefault('achievements', [])
        u.setdefault('xp', 0)
        if u['xp'] > MAX_XP:
            u['xp'] = MAX_XP
            changed = True
        if not any(a['id'] == 'pioneer' for a in u['achievements']):
            u['achievements'].append({'id': 'pioneer', 'earned': time.time()})
            u['xp'] += 300
            if u['xp'] > MAX_XP:
                u['xp'] = MAX_XP
            changed = True
    if changed:
        save_db('users', users)

migrate_created_at()

def check_pioneer(username):
    users = load_users()
    if username not in users:
        return
    ordered = list(users.items())
    for i, (un, _) in enumerate(ordered):
        if un == username and i < 50:
            award_achievement(username, 'pioneer')
            return

def get_role(username):
    un = username.lower()
    users = load_users()
    if un in users and 'role' in users[un]:
        return users[un]['role']
    return ROLES.get(un, 'user')

@socketio.on('auth')
def handle_auth(data):
    action = data.get('action', 'login')
    un = data.get('username', '').strip().lower().replace('@', '')
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
            'username': un, 'display_name': dn or un, 'pass': hash_password(pwd),
            'avatar': f'https://api.dicebear.com/7.x/bottts-neutral/svg?seed={un}',
            'bio': 'Пользователь CAT', 'friends': [], 'requests': [], 'notifications': [], 'role': get_role(un),
            'xp': 0, 'achievements': [], 'telegram_verified': False, 'birthday': '', 'created_at': time.time(), 'legendary': False
        }
        new_user['achievements'].append({'id': 'pioneer', 'earned': time.time()})
        new_user['xp'] = min(new_user['xp'] + 300, MAX_XP)
        save_user(un, new_user)
        user_sessions[un] = request.sid
        emit('auth_result', {'success': True, 'user': new_user})
    else:
        if un not in users:
            emit('auth_result', {'success': False, 'error': 'Пользователь не найден'})
            return
        if not verify_password(pwd, users[un]['pass']):
            emit('auth_result', {'success': False, 'error': 'Неверный пароль'})
            return

        user_data = users[un]
        if not user_data['pass'].startswith('pbkdf2:'):
            user_data['pass'] = hash_password(pwd)
        user_data['role'] = get_role(un)
        user_data.setdefault('friends', [])
        user_data.setdefault('requests', [])
        user_data.setdefault('notifications', [])
        user_data.setdefault('xp', 0)
        user_data.setdefault('achievements', [])
        user_data.setdefault('telegram_verified', False)
        user_data.setdefault('birthday', '')
        user_data.setdefault('legendary', False)
        user_sessions[un] = request.sid
        user_data['online'] = True
        user_data['last_seen'] = time.time()
        save_user(un, user_data)
        check_daily_login(un)
        if get_role(un) in ['moderator', 'admin', 'owner']:
            award_achievement(un, 'dictator')
        check_pioneer(un)
        notify_friends(un, 'friend_online', {'username': un, 'online': True})
        groups = load_groups()
        for gid, g in groups.items():
            if un in g['members']:
                join_room(gid)
        emit('auth_result', {'success': True, 'user': user_data})

@socketio.on('update_profile')
def handle_profile_update(data):
    un = data.get('username', '').lower()
    users = load_users()
    if un not in users:
        emit('profile_updated', {'error': 'Пользователь не найден'})
        return
    if data.get('display_name', '').strip(): users[un]['display_name'] = data['display_name'].strip()
    if 'bio' in data: users[un]['bio'] = data['bio'].strip()
    if 'birthday' in data: users[un]['birthday'] = data['birthday'].strip()
    av = data.get('avatar', '').strip()
    if av:
        av_lower = av.lower()
        if av_lower.startswith('javascript:'):
            av = ''
        elif av_lower.startswith('data:') and not av_lower.startswith('data:image/'):
            av = ''
        elif not (av_lower.startswith('http://') or av_lower.startswith('https://') or av_lower.startswith('data:image/') or av_lower.startswith('/uploads/')):
            av = ''
        if av:
            users[un]['avatar'] = av
    save_user(un, users[un])
    if users[un].get('bio', '').strip():
        award_achievement(un, 'bio')
    if av and users[un].get('avatar', ''):
        award_achievement(un, 'avatar')
    emit('profile_updated', {'user': users[un]})

@socketio.on('send_friend_request')
def handle_friend_request(data):
    my_un = data.get('my_username', '').strip().lower()
    target_un = data.get('target_username', '').strip().lower().replace('@', '')
    if not target_un: 
        emit('friend_msg', {'text': 'Введите имя', 'type': 'error'}); 
        return
    if my_un and not check_rate_limit(my_un):
        emit('friend_msg', {'text': 'Слишком часто. Подождите.', 'type': 'error'})
        return
    users = load_users()
    if target_un not in users: 
        emit('friend_msg', {'text': 'Пользователь не найден', 'type': 'error'}); 
        return
    if target_un == my_un: 
        emit('friend_msg', {'text': 'Нельзя добавить себя', 'type': 'error'}); 
        return
    target = users[target_un]
    if my_un in target.get('friends', []): 
        emit('friend_msg', {'text': 'Вы уже друзья', 'type': 'info'}); 
        return
    if my_un in target.get('requests', []): 
        emit('friend_msg', {'text': 'Запрос уже отправлен', 'type': 'info'}); 
        return
    target.setdefault('requests', []).append(my_un)
    notif = {
        'id': str(int(time.time() * 1000)), 'type': 'friend_request', 'from': my_un,
        'from_name': users[my_un].get('display_name', my_un),
        'text': f'@{my_un} хочет добавить вас в друзья', 'timestamp': time.time(), 'read': False
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
    user['notifications'] = [n for n in user.get('notifications', []) if not (n.get('type')=='friend_request' and n.get('from','').lower()==target_un)]
    save_user(my_un, user)
    award_achievement(my_un, 'first_friend')
    if len(user.get('friends', [])) >= 5:
        award_achievement(my_un, 'soul_company')
    if len(user.get('friends', [])) >= 15:
        award_achievement(my_un, 'friend_specialist')
    award_achievement(target_un, 'first_friend')
    if target_un in users and len(users[target_un].get('friends', [])) >= 5:
        award_achievement(target_un, 'soul_company')
    if target_un in users and len(users[target_un].get('friends', [])) >= 15:
        award_achievement(target_un, 'friend_specialist')
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
    user['notifications'] = [n for n in user.get('notifications', []) if not (n.get('type')=='friend_request' and n.get('from','').lower()==target_un)]
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

    msgs = load_messages()
    target_msg = None
    for m in msgs:
        if str(m.get('id')) == msg_ts or str(m.get('timestamp')) == msg_ts:
            target_msg = m
            break

    can_delete = False
    if role in ['owner', 'admin']:
        can_delete = True
    elif role == 'moderator' and target_msg and target_msg.get('room') == 'Общий':
        can_delete = True
    elif target_msg and target_msg.get('username', '').lower() == username:
        if target_msg.get('room', '').startswith('dm_'):
            can_delete = True

    if not can_delete:
        emit('error_msg', {'text': 'Нет прав'})
        return

    msgs = [m for m in msgs if not (str(m.get('id')) == msg_ts or str(m.get('timestamp')) == msg_ts)]
    save_db('messages', msgs)
    emit('message_deleted', {'msg_id': msg_ts}, broadcast=True)

@socketio.on('message')
def handle_msg(data):
    room = data.get('room', 'Общий')
    text = data.get('text', '').strip()
    image = data.get('image', '').strip()
    reply_to = data.get('reply_to', '')
    username = data.get('username', '')

    if username and not check_rate_limit(username):
        emit('error_msg', {'text': 'Слишком часто. Подождите.'})
        return

    if room == 'Новости' and get_role(username) not in ['owner', 'admin']:
        return

    if not text and not image:
        return
    if text and len(text) > 5000:
        return
    if image:
        if len(image) > 5 * 1024 * 1024:
            return
        if not image.startswith('data:image/'):
            return
        try:
            img_data = base64.b64decode(image.split(',', 1)[1])
            ext = image.split(';')[0].split('/')[-1]
            if ext not in ('png', 'jpeg', 'jpg', 'gif', 'webp'):
                ext = 'png'
            img_filename = f"{uuid.uuid4()}.{ext}"
            img_path = os.path.join(UPLOADS_DIR, img_filename)
            with open(img_path, 'wb') as f:
                f.write(img_data)
            image = f'/uploads/{img_filename}'
        except Exception:
            return

    if room.startswith('dm_'):
        parts = room.split('_')
        if len(parts) >= 3:
            a, b = sorted([parts[1], parts[2]])
            room = f"dm_{a}_{b}"

    data['room'] = room
    data['timestamp'] = time.time()
    data['text'] = text
    data['image'] = image
    data['read'] = False

    data['id'] = data.get('id', str(uuid.uuid4()))

    if reply_to:
        data['reply_to'] = reply_to
        msgs = load_messages()
        for m in msgs:
            if str(m.get('timestamp')) == str(reply_to) or str(m.get('id')) == str(reply_to):
                data['reply_author'] = m.get('user') or m.get('username', '')
                data['reply_text'] = (m.get('text') or (m.get('image') and '[Изображение]') or '')[:100]
                break

    save_message(data)
    award_achievement(username, 'first_msg')
    if room == 'Общий':
        award_achievement(username, 'talkative')

    if username:
        user_consec = consecutive_msgs.setdefault(username, {'room': room, 'count': 0})
        if user_consec['room'] == room:
            user_consec['count'] += 1
        else:
            user_consec['room'] = room
            user_consec['count'] = 1
        if user_consec['count'] >= 10:
            award_achievement(username, 'first_spark')

        current_hour = int(time.strftime('%H', time.localtime(time.time())))
        if current_hour >= 0 and current_hour < 5:
            award_achievement(username, 'night_chatter')

        users = load_users()
        if username in users:
            today = time.strftime('%Y-%m-%d')
            u_data = users[username]
            if u_data.get('daily_date') != today:
                u_data['daily_msgs'] = 0
                u_data['daily_photos'] = 0
                u_data['daily_date'] = today
            u_data['daily_msgs'] = u_data.get('daily_msgs', 0) + 1
            if image:
                u_data['daily_photos'] = u_data.get('daily_photos', 0) + 1
            save_user(username, u_data)
            if u_data['daily_photos'] >= 10:
                award_achievement(username, 'media_master')
            if u_data['daily_msgs'] >= 100:
                award_achievement(username, 'sprinter')

    preview_text = text[:30] if text else ('[Изображение]' if image else '')

    if room.startswith('dm_'):
        parts = room.split('_')
        for p in parts[1:]:
            if p != data.get('username', ''):
                notify_user(p, 'new_dm', {
                    'from': data.get('username'),
                    'text': preview_text,
                    'room': room
                })

    emit('message', data, room=room)

@socketio.on('mark_read')
def handle_mark_read(data):
    room = data.get('room', '')
    username = data.get('username', '')
    if room:
        msgs = load_messages()
        changed = False
        for m in msgs:
            if m.get('room') == room and m.get('username') != username and not m.get('read'):
                m['read'] = True
                changed = True
        if changed:
            save_db('messages', msgs)
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
    msgs = load_messages()
    hist = [m for m in msgs if m.get('room') == room][-50:]
    emit('history', hist)

@socketio.on('get_rooms')
def get_rooms():
    emit('room_list', {
        'Общий': {"name": "Общий канал", "type": "public"},
        'Новости': {"name": "Новости", "type": "news"}
    })

@socketio.on('get_user_profile')
def handle_get_user_profile(data):
    target_un = data.get('username', '').strip().lower().replace('@', '')
    users = load_users()
    if target_un not in users:
        emit('user_profile', {'error': 'Пользователь не найден'})
        return
    user = users[target_un]
    emit('user_profile', {
        'username': target_un,
        'user': {
            'username': target_un,
            'display_name': user.get('display_name') or target_un,
            'avatar': user.get('avatar', ''),
            'bio': user.get('bio', ''),
            'friends': user.get('friends', []),
            'requests': user.get('requests', []),
            'role': get_role(target_un),
            'online': user.get('online', False),
            'last_seen': user.get('last_seen', 0),
            'xp': user.get('xp', 0),
            'achievements': user.get('achievements', []),
            'telegram_verified': user.get('telegram_verified', False),
            'birthday': user.get('birthday', ''),
            'legendary': user.get('legendary', False)
        }
    })

@socketio.on('check_status')
def handle_check_status(data):
    un = data.get('username', '').lower()
    emit('friend_online', {'username': un, 'online': un in user_sessions})

@socketio.on('get_avatar')
def handle_get_avatar(data):
    un = data.get('username', '').lower()
    users = load_users()
    if un in users:
        emit('friend_avatar', {'username': un, 'avatar': users[un].get('avatar', '')})

@socketio.on('disconnect')
def handle_disconnect():
    users = load_users()
    for un, sid in list(user_sessions.items()):
        if sid == request.sid:
            del user_sessions[un]
            if un in users:
                users[un]['online'] = False
                users[un]['last_seen'] = time.time()
                save_user(un, users[un])
                notify_friends(un, 'friend_online', {'username': un, 'online': False})
            break

@socketio.on('typing')
def handle_typing(data):
    room = data.get('room', '')
    if room.startswith('dm_'):
        emit('user_typing', {'username': data.get('username'), 'user': data.get('user')}, room=room, include_self=False)

@socketio.on('call_user')
def handle_call_user(data):
    notify_user(data.get('to'), 'incoming_call', {'from': data.get('from', ''), 'sdp': data.get('sdp')})

@socketio.on('call_accepted')
def handle_call_accepted(data):
    notify_user(data.get('to'), 'call_accepted', {'sdp': data.get('sdp')})

@socketio.on('call_signal')
def handle_call_signal(data):
    notify_user(data.get('to'), 'call_signal', {'ice': data.get('ice')})

# ========== GROUPS ==========

@socketio.on('create_group')
def handle_create_group(data):
    user = data.get('username', '').lower()
    if not user:
        return
    name = data.get('name', '').strip()
    if not name or len(name) > 50:
        emit('error_msg', {'text': 'Название группы: 1-50 символов'})
        return
    gid = 'group_' + str(uuid.uuid4())[:8]
    group = {
        'id': gid,
        'name': name,
        'creator': user,
        'members': [user],
        'created_at': time.time()
    }
    save_group(gid, group)
    join_room(gid)
    emit('group_created', group)

@socketio.on('get_groups')
def handle_get_groups(data=None):
    user = data.get('username', '').lower() if data else None
    if not user:
        return
    groups = load_groups()
    user_groups = {}
    for gid, g in groups.items():
        if user in g['members']:
            user_groups[gid] = g
            join_room(gid)
    emit('groups_list', user_groups)

@socketio.on('invite_to_group')
def handle_invite_to_group(data):
    user = data.get('username', '').lower()
    if not user:
        return
    gid = data.get('group_id', '')
    target = data.get('target', '').lower().replace('@', '')
    groups = load_groups()
    group = groups.get(gid)
    if not group or user != group['creator']:
        emit('error_msg', {'text': 'Только создатель может приглашать'})
        return
    if target in group['members']:
        emit('error_msg', {'text': 'Уже в группе'})
        return
    users = load_users()
    if target not in users:
        emit('error_msg', {'text': 'Пользователь не найден'})
        return
    group['members'].append(target)
    save_group(gid, group)
    notify_user(target, 'invited_to_group', {'group': group, 'invited_by': user})
    emit('group_updated', group)
    emit('group_updated', group, room=gid)

@socketio.on('leave_group')
def handle_leave_group(data):
    user = data.get('username', '').lower()
    if not user:
        return
    gid = data.get('group_id', '')
    groups = load_groups()
    group = groups.get(gid)
    if not group or user not in group['members']:
        return
    group['members'].remove(user)
    if not group['members']:
        del groups[gid]
        save_groups(groups)
    else:
        if user == group['creator'] and group['members']:
            group['creator'] = group['members'][0]
        save_group(gid, group)
    emit('group_left', {'group_id': gid})
    emit('group_updated', group, room=gid)

@socketio.on('get_group_members')
def handle_get_group_members(data):
    gid = data.get('group_id', '')
    groups = load_groups()
    group = groups.get(gid)
    if not group:
        return
    users = load_users()
    members = []
    for m in group['members']:
        u = users.get(m, {})
        members.append({
            'username': m,
            'display_name': u.get('display_name') or m,
            'avatar': u.get('avatar', ''),
            'online': m in user_sessions
        })
    emit('group_members', {'group_id': gid, 'members': members})

@app.route('/admin')
def admin_panel():
    auth = request.authorization
    if not auth:
        return ('Forbidden', 401, {'WWW-Authenticate': 'Basic realm="Admin"'})
    un = auth.username.lower()
    pw = auth.password
    users = load_users()
    if un not in users or not verify_password(pw, users[un].get('pass', '')):
        return ('Wrong', 401, {'WWW-Authenticate': 'Basic realm="Admin"'})
    if get_role(un) not in ['owner', 'admin', 'moderator']:
        return ('Forbidden', 403)
    msgs = load_messages()
    general = [m for m in msgs if m.get('room') == 'Общий'][-10:][::-1]
    users_list = []
    for uname, d in load_users().items():
        users_list.append({
            'username': uname,
            'display_name': d.get('display_name',''),
            'role': d.get('role','user'),
            'xp': d.get('xp', 0),
            'legendary': d.get('legendary', False),
            'friends': len(d.get('friends',[])),
            'requests': len(d.get('requests',[]))
        })
    is_owner = get_role(un) == 'owner'
    can_manage_roles = get_role(un) in ['owner', 'admin']
    can_manage_invites = get_role(un) in ['owner', 'admin']
    can_delete_user = get_role(un) == 'owner'
    html = '''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><title>CAT Admin</title><style>
    body{background:#0d1117;color:#e2e8f0;font-family:sans-serif;padding:30px}
    h1{background:linear-gradient(135deg,#7c5cfc,#38bdf8);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
    .stats{display:flex;gap:20px;margin:20px 0}
    .stat-card{background:#161b22;padding:20px;border-radius:16px;border:1px solid rgba(255,255,255,0.06);flex:1;text-align:center}
    .stat-value{font-size:2rem;font-weight:900;color:#7c5cfc}
    .stat-label{font-size:0.8rem;color:#94a3b8}
    table{width:100%;border-collapse:collapse;margin-top:20px;background:#161b22;border-radius:16px;overflow:hidden}
    th{background:#7c5cfc;padding:12px 16px;text-align:left;font-size:0.8rem;text-transform:uppercase}
    td{padding:10px 16px;border-bottom:1px solid rgba(255,255,255,0.04)}
    tr:hover{background:rgba(255,255,255,0.02)}
    .btn{padding:6px 14px;border-radius:8px;border:none;cursor:pointer;font-size:0.75rem;font-weight:600;margin:2px}
    .btn-danger{background:#ef4444;color:white}
    .btn-sm{background:#7c5cfc;color:white}
    .badge{padding:3px 10px;border-radius:20px;font-size:0.7rem;font-weight:700}
    .badge-owner{background:#f59e0b;color:#0d1117}
    .badge-admin{background:#ef4444;color:white}
    .badge-mod{background:#10b981;color:white}
    .badge-user{background:#94a3b8;color:#0d1117}
    .section{margin-top:30px}
    .section h2{font-size:1rem;color:#94a3b8;margin-bottom:10px}
    .msg-item{background:#161b22;padding:10px 16px;border-radius:8px;margin:5px 0;font-size:0.85rem}
    select{background:#161b22;color:white;border:1px solid rgba(255,255,255,0.1);padding:4px 8px;border-radius:6px}
    .user-info{color:#f59e0b;margin-bottom:20px}
    </style></head><body><h1>⚡ CAT Admin Panel</h1><div class="user-info">Вы вошли как: @''' + html_escape(un) + ''' (''' + {'owner':'Владелец','admin':'Админ','moderator':'Модер'}.get(get_role(un),'') + ''')</div>
    <div class="stats"><div class="stat-card"><div class="stat-value">''' + str(len(users_list)) + '''</div><div class="stat-label">Пользователей</div></div>
    <div class="stat-card"><div class="stat-value">''' + str(len(msgs)) + '''</div><div class="stat-label">Сообщений</div></div></div>
    <div class="section"><h2>👥 Пользователи</h2><table><tr><th>Username</th><th>Имя</th><th>Роль</th><th>XP</th><th>Друзья</th><th>Запросы</th>'''
    if can_manage_roles: 
        html += '<th>Действия</th>'
    html += '</tr>'
    for u in users_list:
        bc = 'badge-' + ('owner' if u['role']=='owner' else 'admin' if u['role']=='admin' else 'mod' if u['role']=='moderator' else 'user')
        rn = {'owner':'Владелец','admin':'Админ','moderator':'Модер','user':'Пользователь'}.get(u['role'],u['role'])
        html += f'<tr><td>@{html_escape(u["username"])}</td><td>{html_escape(u["display_name"])}</td><td><span class="badge {bc}">{html_escape(rn)}</span></td><td>{u["xp"]}</td><td>{u["friends"]}</td><td>{u["requests"]}</td>'
        if u['role'] == 'owner':
            html += '<td>'
            if can_manage_roles:
                html += f' <input type="number" id="xpInput-{html_escape(u["username"])}" min="1" value="1" style="width:50px;background:#0d1117;color:white;border:1px solid rgba(255,255,255,0.1);padding:4px;border-radius:6px;">'
                html += f' <button class="btn btn-sm" onclick="addXp(\'{html_escape(u["username"])}\')">➕XP</button>'
                if is_owner:
                    status = '★' if u.get('legendary') else '☆'
                    html += f' <button class="btn btn-sm" onclick="setLegendary(\'{html_escape(u["username"])}\')" style="background:#f59e0b;color:#0d1117;">{status}</button>'
            html += '</td>'
        elif can_manage_roles:
            html += '<td>'
            html += f'<select onchange="setRole(\'{html_escape(u["username"])}\',this.value)">'
            html += f'<option value="user" {"selected" if u["role"]=="user" else ""}>Пользователь</option>'
            html += f'<option value="moderator" {"selected" if u["role"]=="moderator" else ""}>Модератор</option>'
            if is_owner:
                html += f'<option value="admin" {"selected" if u["role"]=="admin" else ""}>Админ</option>'
            html += '</select>'
            html += f' <input type="number" id="xpInput-{html_escape(u["username"])}" min="1" value="1" style="width:50px;background:#0d1117;color:white;border:1px solid rgba(255,255,255,0.1);padding:4px;border-radius:6px;">'
            html += f' <button class="btn btn-sm" onclick="addXp(\'{html_escape(u["username"])}\')">➕XP</button>'
            if is_owner:
                status = '★' if u.get('legendary') else '☆'
                html += f' <button class="btn {"btn-sm"}" onclick="setLegendary(\'{html_escape(u["username"])}\')" style="background:#f59e0b;color:#0d1117;">{status}</button>'
            if can_delete_user:
                html += f' <button class="btn btn-danger" onclick="deleteUser(\'{html_escape(u["username"])}\')">Удалить</button>'
            html += '</td>'
        html += '</tr>'
    html += '</table></div><div class="section"><h2>📝 Сообщения (модерация)</h2>'
    for m in general:
        msg_user = m.get('username','')
        msg_text = m.get('text','')[:100]
        msg_ts = str(m.get('timestamp',''))
        html += f'<div class="msg-item"><b>@{html_escape(msg_user)}</b>: {html_escape(msg_text)} <button class="btn btn-sm" onclick="deleteMsg(\'{html_escape(msg_ts)}\')" style="float:right;">✕</button></div>'
    html += '</div>'
    if can_manage_invites:
        invites_data = load_invites()
        total_invites = len(invites_data)
        used_invites = sum(1 for v in invites_data.values() if v.get('used_by'))
        html += f'<div class="section"><h2>🔑 Инвайт-коды</h2><div class="stats"><div class="stat-card"><div class="stat-value">{total_invites}</div><div class="stat-label">Всего</div></div><div class="stat-card"><div class="stat-value">{total_invites - used_invites}</div><div class="stat-label">Активных</div></div></div>'
        html += '<button class="btn btn-sm" onclick="createInvite()" style="background:#7c5cfc;color:white;border:none;padding:10px 20px;border-radius:10px;cursor:pointer;font-weight:600;">➕ Создать код</button>'
        html += '<div id="newCodeDisplay" style="margin-top:15px;font-size:1.2rem;font-weight:900;color:#10b981;display:none;"></div>'
        html += '<table style="margin-top:15px;"><tr><th>Код</th><th>Создал</th><th>Статус</th></tr>'
        for c, v in sorted(invites_data.items(), key=lambda x: x[1].get('created_at', 0), reverse=True)[:50]:
            status = f'<span style="color:#ef4444;">Использован @{html_escape(v["used_by"])}</span>' if v.get('used_by') else '<span style="color:#10b981;">Активен</span>'
            html += f'<tr><td style="font-family:monospace;font-weight:700;">{html_escape(c)}</td><td>@{html_escape(v.get("created_by","?"))}</td><td>{status}</td></tr>'
        html += '</table></div>'
    html += '<script>'
    if can_manage_invites:
        html += 'function createInvite(){fetch("/api/invite/create",{method:"POST"}).then(r=>r.json()).then(d=>{if(d.ok){document.getElementById("newCodeDisplay").textContent="\\uD83C\\uDF89 "+d.code;document.getElementById("newCodeDisplay").style.display="block";setTimeout(()=>location.reload(),2000)}else{alert(d.error)}})}'
    html += 'function deleteUser(un){if(!confirm("\\u0423\\u0434\\u0430\\u043B\\u0438\\u0442\\u044C @"+un+"?"))return;fetch("/admin/delete/"+un,{method:"POST"}).then(r=>r.json()).then(d=>{alert(d.message);location.reload()})}'
    html += 'function setRole(un,r){fetch("/admin/setrole/"+un+"/"+r,{method:"POST"}).then(r=>r.json()).then(d=>{alert(d.message);location.reload()})}'
    html += 'function deleteMsg(ts){fetch("/admin/deletemsg/"+ts,{method:"POST"}).then(r=>r.json()).then(d=>{alert(d.message);location.reload()})}'
    html += 'function addXp(un){var am=document.getElementById("xpInput-"+un).value;fetch("/admin/addxp/"+un+"/"+am,{method:"POST"}).then(r=>r.json()).then(d=>{alert(d.message);location.reload()})}'
    html += 'function setLegendary(un){fetch("/admin/setlegendary/"+un,{method:"POST"}).then(r=>r.json()).then(d=>{alert(d.message);location.reload()})}'
    html += '</script></body></html>'
    return html

@app.route('/admin/delete/<username>', methods=['POST'])
def admin_delete_user(username):
    if get_role(request.authorization.username.lower() if request.authorization else '') not in ['owner','admin']: 
        return {'message':'Нет прав'}
    un = username.lower()
    users = load_users()
    users.pop(un, None)
    save_db('users', users)
    return {'message': f'Пользователь @{un} удалён'}

@app.route('/admin/addxp/<username>/<amount>', methods=['POST'])
def admin_add_xp(username, amount):
    requester_un = request.authorization.username.lower() if request.authorization else ''
    requester_role = get_role(requester_un)
    if requester_role not in ['owner', 'admin']:
        return {'message': 'Нет прав'}
    un = username.lower()
    try:
        xp_amount = int(amount)
        if xp_amount <= 0:
            return {'message': 'XP должно быть больше 0'}
    except ValueError:
        return {'message': 'Некорректное количество XP'}
    users = load_users()
    if un in users:
        users[un].setdefault('xp', 0)
        users[un]['xp'] = min(users[un]['xp'] + xp_amount, MAX_XP)
        save_db('users', users)
        notify_user(un, 'xp_awarded', {'amount': xp_amount, 'total': users[un]['xp']})
        return {'message': f'@{un} получил {xp_amount} XP (всего: {users[un]["xp"]})'}
    return {'message': 'Пользователь не найден'}

@app.route('/admin/setlegendary/<username>', methods=['POST'])
def admin_set_legendary(username):
    requester_un = request.authorization.username.lower() if request.authorization else ''
    requester_role = get_role(requester_un)
    if requester_role != 'owner':
        return {'message': 'Только Владелец может выдавать легендарный статус'}
    un = username.lower()
    users = load_users()
    if un in users:
        users[un]['legendary'] = not users[un].get('legendary', False)
        save_db('users', users)
        status = 'присвоен' if users[un]['legendary'] else 'снят'
        notify_user(un, 'legendary_update', {'legendary': users[un]['legendary']})
        return {'message': f'@{un} — легендарный статус {status}'}
    return {'message': 'Пользователь не найден'}

@app.route('/admin/setrole/<username>/<role>', methods=['POST'])
def admin_set_role(username, role):
    requester_un = request.authorization.username.lower() if request.authorization else ''
    requester_role = get_role(requester_un)
    if requester_role not in ['owner', 'admin']:
        return {'message': 'Нет прав'}
    un = username.lower()
    if requester_role == 'admin':
        if un == requester_un:
            return {'message': 'Админ не может изменить свою роль'}
        if get_role(un) in ['owner', 'admin']:
            return {'message': 'Админ не может изменить роль другого админа'}
        if role not in ['user', 'moderator']:
            return {'message': 'Админ может назначить только роль Модератора'}
    if role not in ['user', 'moderator', 'admin', 'owner']:
        return {'message': 'Некорректная роль'}
    users = load_users()
    if un in users:
        users[un]['role'] = role
        save_db('users', users)
        if role in ['moderator', 'admin', 'owner']:
            award_achievement(un, 'dictator')
        notify_user(un, 'role_changed', {'role': role})
    return {'message': f'Роль @{un} изменена на {role}'}

@app.route('/admin/deletemsg/<timestamp>', methods=['POST'])
def admin_delete_msg(timestamp):
    requester_un = request.authorization.username.lower() if request.authorization else ''
    requester_role = get_role(requester_un)
    if requester_role not in ['owner', 'admin', 'moderator']:
        return {'message': 'Нет прав'}
    msgs = load_messages()
    target_msg = None
    for m in msgs:
        if str(m.get('timestamp')) == str(timestamp) or str(m.get('id')) == str(timestamp):
            target_msg = m
            break
    if requester_role == 'moderator':
        if not target_msg or target_msg.get('room') != 'Общий':
            return {'message': 'Модератор может удалять только сообщения из Общего чата'}
    msgs = [m for m in msgs if str(m.get('timestamp')) != str(timestamp) and str(m.get('id')) != str(timestamp)]
    save_db('messages', msgs)
    return {'message': 'Сообщение удалено'}


# ========== ДОСТИЖЕНИЯ ==========
ACHIEVEMENTS = {
    'first_msg': {'icon': '🐱', 'name': 'Первый мяу', 'desc': 'Отправить первое сообщение в чат', 'xp': 25},
    'first_friend': {'icon': '🤝', 'name': 'Первый друг', 'desc': 'Добавить одного друга', 'xp': 25},
    'soul_company': {'icon': '🎉', 'name': 'Душа компании', 'desc': 'Иметь 5 друзей одновременно', 'xp': 50},
    'talkative': {'icon': '💬', 'name': 'Общительный', 'desc': 'Написать в общий канал сегодня', 'xp': 25},
    'daily_login': {'icon': '📅', 'name': 'Ежедневный вход', 'desc': 'Зайти в чат сегодня', 'xp': 25},
    'weekly_marathon': {'icon': '🔥', 'name': 'Недельный марафон', 'desc': 'Заходить 7 дней подряд', 'xp': 100},
    'bio': {'icon': '✏️', 'name': 'Биограф', 'desc': 'Заполнить описание профиля', 'xp': 25},
    'avatar': {'icon': '🖼️', 'name': 'Аватар', 'desc': 'Загрузить собственное фото', 'xp': 25},
    'first_spark': {'icon': '✨', 'name': 'Первый огонёк', 'desc': 'Отправить 10 сообщений подряд в одном чате', 'xp': 10},
    'night_chatter': {'icon': '🌙', 'name': 'Ночной чатер', 'desc': 'Написать сообщение с 00:00 до 5:00', 'xp': 25},
    'friend_specialist': {'icon': '🤝', 'name': 'Специалист по связям', 'desc': 'Добавить 15 друзей', 'xp': 30},
    'media_master': {'icon': '📸', 'name': 'Медиа-мастер', 'desc': 'Отправить 10 фото за 1 день', 'xp': 10},
    'sprinter': {'icon': '🏃', 'name': 'Спринтер', 'desc': 'Написать 100 сообщений за 24 часа', 'xp': 20},
    'dictator': {'icon': '👑', 'name': 'Диктатор', 'desc': 'Стать модератором', 'xp': 150},
    'pioneer': {'icon': '🏆', 'name': 'Первопроходец', 'desc': 'Стать одним из первых 50 пользователей', 'xp': 300},
}

def award_achievement(username, ach_id):
    users = load_users()
    if username not in users:
        return
    user = users[username]
    if not user.get('telegram_verified') and not user.get('verified_by'):
        return
    user.setdefault('achievements', [])
    user.setdefault('xp', 0)
    if any(a['id'] == ach_id for a in user['achievements']):
        return
    ach = ACHIEVEMENTS.get(ach_id)
    if not ach:
        return
    user['achievements'].append({'id': ach_id, 'earned': time.time()})
    user['xp'] = min(user['xp'] + ach['xp'], MAX_XP)
    save_user(username, user)
    notify_user(username, 'achievement_unlocked', {'id': ach_id, 'name': ach['name'], 'xp': ach['xp']})

def check_daily_login(username):
    users = load_users()
    if username not in users:
        return
    user = users[username]
    today = time.strftime('%Y-%m-%d')
    user.setdefault('login_dates', [])
    if today not in user['login_dates']:
        user['login_dates'].append(today)
        if len(user['login_dates']) > 30:
            user['login_dates'] = user['login_dates'][-30:]
        save_user(username, user)
    if len(user['login_dates']) >= 7:
        award_achievement(username, 'weekly_marathon')
    award_achievement(username, 'daily_login')

# ========== ИНВАЙТ-КОДЫ ==========
INVITE_FILE = os.path.join(DATA_DIR, "invite_codes.json")

def load_invites():
    if os.path.exists(INVITE_FILE):
        try:
            with open(INVITE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_invites(data):
    with open(INVITE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def generate_invite_code():
    return secrets.token_hex(4).upper()

@app.route('/api/invite/create', methods=['POST'])
def api_create_invite():
    auth = request.authorization
    if not auth:
        return {'ok': False, 'error': 'Требуется авторизация'}
    un = auth.username.lower()
    pw = auth.password
    users = load_users()
    if un not in users or not verify_password(pw, users[un].get('pass', '')):
        return {'ok': False, 'error': 'Неверные данные'}
    if get_role(un) not in ['owner', 'admin']:
        return {'ok': False, 'error': 'Только админы могут создавать коды'}
    invites = load_invites()
    code = generate_invite_code()
    while code in invites:
        code = generate_invite_code()
    invites[code] = {
        'created_by': un,
        'created_at': time.time(),
        'used_by': None
    }
    save_invites(invites)
    return {'ok': True, 'code': code}

@app.route('/api/invite/verify', methods=['POST'])
def api_verify_invite():
    try:
        data = request.get_json()
        un = data.get('username', '').lower()
        code = data.get('code', '').strip().upper()
        if not un or not code:
            return {'ok': False, 'error': 'Не указаны данные'}
        invites = load_invites()
        if code not in invites:
            return {'ok': False, 'error': 'Неверный код'}
        entry = invites[code]
        if entry.get('used_by'):
            return {'ok': False, 'error': 'Код уже использован'}
        users = load_users()
        if un not in users:
            return {'ok': False, 'error': 'Пользователь не найден'}
        users[un]['telegram_verified'] = True
        users[un]['verified_by'] = 'invite'
        save_db('users', users)
        entry['used_by'] = un
        save_invites(invites)
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host='0.0.0.0', port=port)
