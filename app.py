import os, time, json, base64, uuid, hashlib, secrets, html, re
from functools import wraps
from flask import Flask, request, render_template, send_from_directory, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from config import SECRET_KEY, SQLALCHEMY_DATABASE_URI, UPLOADS_DIR, RATE_LIMIT, MAX_XP, UPLOAD_MAX_SIZE, ALLOWED_EXTENSIONS, ROLES, SITE_URL
from models import db, User, Friendship, Message, Reaction, Group, GroupMember, Achievement, Notification, ResetCode, InviteCode, hash_password, verify_password, generate_admin_secret
from modules.achievements import ACHIEVEMENTS, award_achievement

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = UPLOAD_MAX_SIZE

db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins=SITE_URL, async_mode='threading', manage_session=False)

user_sessions = {}
last_action = {}
consecutive_msgs = {}
auth_attempts = {}
reset_attempts = {}

def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        session_user = get_user_by_sid(request.sid)
        if not session_user:
            emit('error_msg', {'text': 'Ошибка авторизации'})
            return
        return f(*args, **kwargs)
    return wrapper

def get_session_user():
    return get_user_by_sid(request.sid)

with app.app_context():
    db.create_all()
    for un, role in ROLES.items():
        user = User.query.filter_by(username=un).first()
        if user:
            user.role = role
            if not user.admin_secret_hash:
                raw, user.admin_secret_hash, _ = generate_admin_secret()
            db.session.commit()
    # Generate secrets for existing admins who don't have one
    for admin in User.query.filter(User.role.in_(['owner', 'admin', 'moderator']), User.admin_secret_hash == '').all():
        _, admin.admin_secret_hash, _ = generate_admin_secret()
        db.session.commit()



# ========== HELPERS ==========

def get_user(username):
    return User.query.filter_by(username=username.lower().strip().replace('@', '')).first()


def get_user_by_sid(sid):
    for un, s in user_sessions.items():
        if s == sid:
            return get_user(un)
    return None


def notify_user(username, event, data):
    sid = user_sessions.get(username.lower())
    if sid:
        socketio.emit(event, data, room=sid)


def check_rate(username):
    now = time.time()
    last = last_action.get(username, 0)
    if now - last < RATE_LIMIT:
        return False
    last_action[username] = now
    return True


def get_role(username):
    user = get_user(username)
    if user:
        return user.role
    return ROLES.get(username.lower(), 'user')


def save_image(base64_data):
    try:
        parts = base64_data.split(',', 1)
        if len(parts) != 2:
            return None
        header = parts[0]
        raw_ext = header.split(';')[0].split('/')[-1] if '/' in header else ''
        ext = raw_ext.split('+')[0].split(';')[0]
        if ext not in ALLOWED_EXTENSIONS:
            ext = 'png'
        img_bytes = base64.b64decode(parts[1])
        if len(img_bytes) > UPLOAD_MAX_SIZE:
            return None
        filename = f"{uuid.uuid4()}.{ext}"
        path = os.path.join(UPLOADS_DIR, filename)
        with open(path, 'wb') as f:
            f.write(img_bytes)
        return f'/uploads/{filename}'
    except Exception:
        return None


def get_online_friends(username):
    user = get_user(username)
    if not user:
        return []
    friends = Friendship.query.filter(
        ((Friendship.user_id == user.id) | (Friendship.friend_id == user.id)),
        Friendship.status == 'accepted'
    ).all()
    result = []
    for f in friends:
        fid = f.friend_id if f.user_id == user.id else f.user_id
        friend = User.query.get(fid)
        if friend:
            result.append(friend.to_dict())
    return result


def get_unread_count(username, room):
    user = get_user(username)
    if not user:
        return 0
    return Message.query.filter(
        Message.room == room,
        Message.sender_id != user.id,
        Message.is_deleted == False
    ).count()


# ========== SOCKET.IO EVENTS ==========

@socketio.on('connect')
def handle_connect():
    pass


@socketio.on('auth')
def handle_auth(data):
    ip = request.remote_addr or 'unknown'
    now = time.time()
    # Clean up old attempts every 100 requests
    if len(auth_attempts) > 1000:
        for ip_addr in list(auth_attempts.keys()):
            auth_attempts[ip_addr] = [t for t in auth_attempts[ip_addr] if now - t < 900]
            if not auth_attempts[ip_addr]:
                del auth_attempts[ip_addr]
    attempts = auth_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < 900]
    if len(attempts) >= 10:
        emit('auth_result', {'success': False, 'error': 'Слишком много попыток. Подождите 15 минут.'})
        return
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

    if action == 'register':
        if pwd != pwd2:
            emit('auth_result', {'success': False, 'error': 'Пароли не совпадают'})
            return
        if get_user(un):
            emit('auth_result', {'success': False, 'error': 'Пользователь уже существует'})
            return
        user = User(
            username=un,
            display_name=dn or un,
            password_hash=hash_password(pwd),
            avatar_url=f'https://api.dicebear.com/7.x/bottts-neutral/svg?seed={un}',
            bio='',
            role=ROLES.get(un, 'user'),
            xp=300,
            created_at=time.time(),
            last_seen=time.time(),
            online=True,
        )
        db.session.add(user)
        db.session.commit()

        ach = Achievement(user_id=user.id, ach_id='pioneer', earned_at=time.time())
        db.session.add(ach)
        db.session.commit()

        user_sessions[un] = request.sid
        emit('auth_result', {'success': True, 'user': user.to_dict(include_private=True)})
    else:
        user = get_user(un)
        if not user:
            auth_attempts.setdefault(ip, []).append(time.time())
            emit('auth_result', {'success': False, 'error': 'Неверный логин или пароль'})
            return
        if not verify_password(pwd, user.password_hash):
            auth_attempts.setdefault(ip, []).append(time.time())
            emit('auth_result', {'success': False, 'error': 'Неверный логин или пароль'})
            return

        user.online = True
        user.last_seen = time.time()
        db.session.commit()

        user_sessions[un] = request.sid
        emit('auth_result', {'success': True, 'user': user.to_dict(include_private=True)})

        # Notify friends
        friends = get_online_friends(un)
        for f in friends:
            notify_user(f['username'], 'friend_online', {'username': un, 'online': True})


@socketio.on('join_room')
@require_auth
def handle_join_room(data):
    room = data.get('room', 'Общий')
    join_room(room)
    messages = Message.query.filter_by(room=room, is_deleted=False).order_by(Message.created_at.desc()).limit(50).all()
    messages.reverse()
    emit('history', [m.to_dict() for m in messages])


@socketio.on('leave')
@require_auth
def handle_leave(data):
    room = data.get('room', '')
    leave_room(room)


@socketio.on('message')
@require_auth
def handle_message(data):
    room = data.get('room', 'Общий')
    text = data.get('text', '').strip()
    image_data = data.get('image', '').strip()
    voice_data = data.get('voice', '').strip()
    reply_to = data.get('reply_to', 0)
    user = get_session_user()
    if not user:
        return
    username = user.username
    if not check_rate(username):
        emit('error_msg', {'text': 'Слишком часто. Подождите.'})
        return
    if room == 'Новости' and user.role not in ['owner', 'admin']:
        return
    if not text and not image_data and not voice_data:
        return
    if text and len(text) > 5000:
        return
    text = re.sub(r'<[^>]*>', '', text)[:5000] if text else ''

    image_url = save_image(image_data) if image_data else ''
    voice_url = save_image(voice_data) if voice_data else ''

    reply_id = None
    if reply_to:
        reply_msg = Message.query.get(reply_to)
        if reply_msg and not reply_msg.is_deleted:
            reply_id = reply_to

    msg = Message(
        room=room,
        sender_id=user.id,
        text=text,
        image_url=image_url,
        voice_url=voice_url,
        reply_to=reply_id,
        created_at=time.time(),
    )
    db.session.add(msg)
    db.session.commit()

    award_achievement(db, Achievement, User, username, 'first_msg', socketio)
    if room == 'Общий':
        award_achievement(db, Achievement, User, username, 'talkative', socketio)

    # Consecutive messages
    now = time.time()
    cons = consecutive_msgs.setdefault(username, {'room': room, 'count': 0, 'last': 0})
    if cons['room'] == room and now - cons['last'] < 60:
        cons['count'] += 1
    else:
        cons['room'] = room
        cons['count'] = 1
    cons['last'] = now
    if cons['count'] >= 10:
        award_achievement(db, Achievement, User, username, 'first_spark', socketio)

    # Night chatter
    current_hour = int(time.strftime('%H', time.localtime()))
    if 0 <= current_hour < 5:
        award_achievement(db, Achievement, User, username, 'night_chatter', socketio)

    # Daily tracking
    today = time.strftime('%Y-%m-%d')
    if user.daily_date != today:
        user.daily_msgs = 0
        user.daily_date = today
    user.daily_msgs = (user.daily_msgs or 0) + 1
    db.session.commit()

    if (user.daily_msgs or 0) >= 100:
        award_achievement(db, Achievement, User, username, 'sprinter', socketio)

    socketio.emit('message', msg.to_dict(), room=room)


@socketio.on('delete_message')
@require_auth
def handle_delete_message(data):
    msg_id = data.get('msg_id', 0)
    user = get_session_user()
    if not user:
        return
    msg = Message.query.get(msg_id)
    if not msg:
        return
    can_delete = False
    if user.role in ['owner', 'admin']:
        can_delete = True
    elif user.role == 'moderator' and msg.room == 'Общий':
        can_delete = True
    elif msg.sender_id == user.id:
        can_delete = True
    if not can_delete:
        emit('error_msg', {'text': 'Нет прав'})
        return
    msg.is_deleted = True
    db.session.commit()
    socketio.emit('message_deleted', {'msg_id': msg_id}, room=msg.room)


@socketio.on('add_reaction')
@require_auth
def handle_add_reaction(data):
    msg_id = data.get('msg_id', 0)
    emoji = data.get('emoji', '').strip()
    user = get_session_user()
    if not user or not emoji:
        return
    username = user.username
    msg = Message.query.get(msg_id)
    if not msg or msg.is_deleted:
        return
    existing = Reaction.query.filter_by(message_id=msg_id, user_id=user.id, emoji=emoji).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        socketio.emit('reaction_removed', {'msg_id': msg_id, 'reaction_id': existing.id}, room=msg.room)
        return
    reaction = Reaction(message_id=msg_id, user_id=user.id, emoji=emoji)
    db.session.add(reaction)
    db.session.commit()
    award_achievement(db, Achievement, User, username, 'reaction', socketio)
    socketio.emit('reaction_added', {'msg_id': msg_id, 'reaction': reaction.to_dict()}, room=msg.room)


@socketio.on('typing')
@require_auth
def handle_typing(data):
    room = data.get('room', '')
    user = get_session_user()
    if not user:
        return
    username = user.username
    if room and username:
        socketio.emit('user_typing', {'username': username, 'room': room}, room=room, include_self=False)


@socketio.on('get_users')
@require_auth
def handle_get_users():
    users = User.query.order_by(User.online.desc(), User.username).all()
    emit('users_list', [u.to_dict() for u in users])


@socketio.on('get_profile')
@require_auth
def handle_get_profile(data):
    target = data.get('username', '').lower()
    user = get_user(target)
    if not user:
        emit('user_profile', {'error': 'Пользователь не найден'})
        return
    emit('user_profile', {'user': user.to_dict(include_private=True)})


@socketio.on('update_profile')
@require_auth
def handle_update_profile(data):
    user = get_session_user()
    if not user:
        return
    username = user.username
    if data.get('display_name', '').strip():
        user.display_name = data['display_name'].strip()
    if 'bio' in data:
        user.bio = data['bio'].strip()
    if 'birthday' in data:
        user.birthday = data['birthday'].strip()
    if 'theme' in data:
        user.theme = data['theme'].strip()
    av = data.get('avatar', '').strip()
    if av:
        lower = av.lower()
        if lower.startswith('javascript:') or (lower.startswith('data:') and not lower.startswith('data:image/')):
            av = ''
        elif lower.startswith('data:image/'):
            saved = save_image(av)
            if saved:
                av = saved
            else:
                av = ''
        elif not (lower.startswith('http://') or lower.startswith('https://') or lower.startswith('/uploads/')):
            av = ''
        if av:
            user.avatar_url = av
            award_achievement(db, Achievement, User, username, 'avatar', socketio)
    db.session.commit()

    if user.bio.strip():
        award_achievement(db, Achievement, User, username, 'bio', socketio)
    if user.avatar_url:
        award_achievement(db, Achievement, User, username, 'avatar', socketio)

    emit('profile_updated', {'user': user.to_dict(include_private=True)})


@socketio.on('send_friend_request')
@require_auth
def handle_friend_request(data):
    me = get_session_user()
    if not me:
        return
    my_un = me.username
    target_un = data.get('target_username', '').strip().lower().replace('@', '')
    if not target_un:
        emit('friend_msg', {'text': 'Введите имя', 'type': 'error'})
        return
    if not check_rate(my_un):
        emit('friend_msg', {'text': 'Слишком часто', 'type': 'error'})
        return
    target = get_user(target_un)
    if not target:
        emit('friend_msg', {'text': 'Пользователь не найден', 'type': 'error'})
        return
    if target.id == me.id:
        emit('friend_msg', {'text': 'Нельзя добавить себя', 'type': 'error'})
        return
    existing = Friendship.query.filter(
        ((Friendship.user_id == me.id) & (Friendship.friend_id == target.id)) |
        ((Friendship.user_id == target.id) & (Friendship.friend_id == me.id))
    ).first()
    if existing:
        if existing.status == 'accepted':
            emit('friend_msg', {'text': 'Вы уже друзья', 'type': 'info'})
        else:
            emit('friend_msg', {'text': 'Запрос уже отправлен', 'type': 'info'})
        return
    friendship = Friendship(user_id=me.id, friend_id=target.id, status='pending')
    db.session.add(friendship)
    db.session.commit()
    notif = Notification(
        user_id=target.id,
        type='friend_request',
        data={'from': my_un, 'from_name': me.display_name or me.username},
    )
    db.session.add(notif)
    db.session.commit()
    emit('friend_msg', {'text': f'Запрос отправлен @{target_un}', 'type': 'success'})
    notify_user(target_un, 'friend_request', {'from': my_un, 'from_name': me.display_name or me.username})


@socketio.on('friend_response')
@require_auth
def handle_friend_response(data):
    me = get_session_user()
    if not me:
        return
    my_un = me.username
    target_un = data.get('target_username', '').strip().lower()
    accept = data.get('accept', True)
    target = get_user(target_un)
    if not target:
        return
    friendship = Friendship.query.filter(
        (Friendship.user_id == target.id) & (Friendship.friend_id == me.id) & (Friendship.status == 'pending')
    ).first()
    if not friendship:
        return
    if accept:
        friendship.status = 'accepted'
        db.session.commit()
        award_achievement(db, Achievement, User, my_un, 'first_friend', socketio)
        award_achievement(db, Achievement, User, target_un, 'first_friend', socketio)
        friend_count_me = Friendship.query.filter(
            ((Friendship.user_id == me.id) | (Friendship.friend_id == me.id)),
            Friendship.status == 'accepted'
        ).count()
        friend_count_target = Friendship.query.filter(
            ((Friendship.user_id == target.id) | (Friendship.friend_id == target.id)),
            Friendship.status == 'accepted'
        ).count()
        if friend_count_me >= 5:
            award_achievement(db, Achievement, User, my_un, 'soul_company', socketio)
        if friend_count_target >= 5:
            award_achievement(db, Achievement, User, target_un, 'soul_company', socketio)
        notify_user(target_un, 'friend_accepted', {'by': my_un, 'by_name': me.display_name or me.username})
    else:
        db.session.delete(friendship)
        db.session.commit()
    emit('friends_updated', get_online_friends(my_un))
    emit('friend_requests', get_friend_requests(my_un))


@socketio.on('remove_friend')
@require_auth
def handle_remove_friend(data):
    me = get_session_user()
    if not me:
        return
    my_un = me.username
    target_un = data.get('target_username', '').strip().lower()
    target = get_user(target_un)
    if not target:
        return
    friendship = Friendship.query.filter(
        ((Friendship.user_id == me.id) & (Friendship.friend_id == target.id)) |
        ((Friendship.user_id == target.id) & (Friendship.friend_id == me.id)),
        Friendship.status == 'accepted'
    ).first()
    if friendship:
        db.session.delete(friendship)
        db.session.commit()
    emit('friends_updated', get_online_friends(my_un))
    notify_user(target_un, 'friend_removed', {'by': my_un})


@socketio.on('get_friends')
@require_auth
def handle_get_friends(data):
    me = get_session_user()
    if not me:
        return
    my_un = me.username
    emit('friends_updated', get_online_friends(my_un))
    emit('friend_requests', get_friend_requests(my_un))


def get_friend_requests(username):
    user = get_user(username)
    if not user:
        return []
    requests = Friendship.query.filter_by(friend_id=user.id, status='pending').all()
    result = []
    for r in requests:
        req_user = User.query.get(r.user_id)
        if req_user:
            result.append(req_user.to_dict())
    return result


@socketio.on('get_rooms')
@require_auth
def handle_get_rooms():
    emit('room_list', {
        'Общий': {'name': 'Общий канал', 'type': 'public', 'icon': '🌍'},
        'Новости': {'name': 'Новости', 'type': 'news', 'icon': '📰'},
    })


# ========== GROUPS ==========

@socketio.on('create_group')
@require_auth
def handle_create_group(data):
    user = get_session_user()
    if not user:
        return
    username = user.username
    name = data.get('name', '').strip()
    if not name or len(name) > 50:
        emit('error_msg', {'text': 'Название: 1-50 символов'})
        return
    group = Group(name=name, creator_id=user.id)
    db.session.add(group)
    db.session.flush()
    member = GroupMember(group_id=group.id, user_id=user.id)
    db.session.add(member)
    db.session.commit()
    join_room(f"group_{group.id}")
    emit('group_created', group.to_dict())


@socketio.on('get_groups')
@require_auth
def handle_get_groups(data):
    user = get_session_user()
    if not user:
        return
    username = user.username
    memberships = GroupMember.query.filter_by(user_id=user.id).all()
    groups = {}
    for m in memberships:
        group = m.group
        if group:
            groups[group.id] = group.to_dict()
            join_room(f"group_{group.id}")
    emit('groups_list', groups)


@socketio.on('invite_to_group')
@require_auth
def handle_invite_to_group(data):
    user = get_session_user()
    if not user:
        return
    username = user.username
    group_id = data.get('group_id', 0)
    target = data.get('target', '').lower().replace('@', '')
    group = Group.query.get(group_id)
    target_user = get_user(target)
    if not group or not target_user:
        return
    if group.creator_id != user.id:
        emit('error_msg', {'text': 'Только создатель может добавлять'})
        return
    existing = GroupMember.query.filter_by(group_id=group.id, user_id=target_user.id).first()
    if existing:
        emit('error_msg', {'text': 'Уже в группе'})
        return
    member = GroupMember(group_id=group.id, user_id=target_user.id)
    db.session.add(member)
    db.session.commit()
    socketio.emit('group_updated', group.to_dict(), room=f"group_{group.id}")
    notify_user(target, 'group_invite', {'group': group.to_dict(), 'by': username})


@socketio.on('leave_group')
@require_auth
def handle_leave_group(data):
    user = get_session_user()
    if not user:
        return
    username = user.username
    group_id = data.get('group_id', 0)
    group = Group.query.get(group_id)
    if not group:
        return
    member = GroupMember.query.filter_by(group_id=group.id, user_id=user.id).first()
    if not member:
        return
    db.session.delete(member)
    if group.members.count() == 0:
        db.session.delete(group)
        db.session.commit()
        socketio.emit('group_deleted', {'group_id': group_id}, room=f"group_{group_id}")
    else:
        if group.creator_id == user.id:
            first = group.members.first()
            if first:
                group.creator_id = first.user_id
        db.session.commit()
        socketio.emit('group_updated', group.to_dict(), room=f"group_{group.id}")
    emit('group_left', {'group_id': group_id})


# ========== NOTIFICATIONS ==========

@socketio.on('get_notifications')
@require_auth
def handle_get_notifications(data):
    user = get_session_user()
    if not user:
        return
    notifs = Notification.query.filter_by(user_id=user.id).order_by(Notification.created_at.desc()).limit(30).all()
    emit('notifications', [n.to_dict() for n in notifs])


@socketio.on('mark_notification_read')
@require_auth
def handle_mark_notification_read(data):
    user = get_session_user()
    if not user:
        return
    notif_id = data.get('notif_id', 0)
    notif = Notification.query.get(notif_id)
    if notif and notif.user_id == user.id:
        notif.read = True
        db.session.commit()


# ========== INVITE CODES ==========

@socketio.on('verify_invite')
@require_auth
def handle_verify_invite(data):
    user = get_session_user()
    if not user:
        return
    username = user.username
    code = data.get('code', '').strip().upper()
    if user.verified:
        emit('invite_result', {'success': True, 'message': 'Уже верифицирован'})
        return
    invite = InviteCode.query.filter_by(code=code, used_by=None).first()
    if not invite:
        emit('invite_result', {'success': False, 'error': 'Неверный код'})
        return
    invite.used_by = username
    user.verified = True
    db.session.commit()
    emit('invite_result', {'success': True, 'message': 'Верификация пройдена!'})


# ========== PASSWORD RESET ==========

@socketio.on('verify_admin_access')
@require_auth
def handle_verify_admin_access(data):
    user = get_session_user()
    if not user:
        return
    secret = data.get('secret', '')
    if user.role not in ['owner', 'admin', 'moderator']:
        emit('admin_access_result', {'success': False, 'error': 'Нет прав'})
        return
    if not user.admin_secret_hash:
        emit('admin_access_result', {'success': False, 'error': 'Нет секрета админки. Попроси владельца выдать заново.'})
        return
    if not verify_password(secret, user.admin_secret_hash):
        emit('admin_access_result', {'success': False, 'error': 'Неверный секретный код'})
        return
    emit('admin_access_result', {'success': True})


@socketio.on('generate_reset_code')
@require_auth
def handle_generate_reset_code(data):
    user = get_session_user()
    if not user:
        return
    requester = user.username
    if user.role not in ['owner', 'admin', 'moderator']:
        emit('admin_msg', {'text': 'Нет прав', 'type': 'error'})
        return
    username = data.get('username', '').lower()
    target = get_user(username)
    if not target:
        emit('admin_msg', {'text': 'Пользователь не найден', 'type': 'error'})
        return
    code = secrets.token_hex(4).upper()[:8]
    rc = ResetCode(code=code, username=username)
    db.session.add(rc)
    db.session.commit()
    emit('admin_msg', {
        'text': f'Код для @{username}: {code} (действует 24ч)',
        'type': 'success'
    })


@socketio.on('reset_password')
def handle_reset_password(data):
    ip = request.remote_addr or 'unknown'
    now = time.time()
    # Clean up old reset attempts
    if len(reset_attempts) > 1000:
        for rip in list(reset_attempts.keys()):
            reset_attempts[rip] = [t for t in reset_attempts[rip] if now - t < 900]
            if not reset_attempts[rip]:
                del reset_attempts[rip]
    r_attempts = reset_attempts.get(ip, [])
    r_attempts = [t for t in r_attempts if now - t < 900]
    if len(r_attempts) >= 10:
        emit('reset_result', {'success': False, 'error': 'Слишком много попыток. Подождите 15 минут.'})
        return
    username = data.get('username', '').lower().replace('@', '')
    code = data.get('code', '').strip().upper()
    new_pw = data.get('password', '')

    if not username or not code or not new_pw:
        emit('reset_result', {'success': False, 'error': 'Заполни все поля'})
        return
    if len(new_pw) < 4:
        emit('reset_result', {'success': False, 'error': 'Пароль: минимум 4 символа'})
        return

    user = get_user(username)
    if not user:
        reset_attempts.setdefault(ip, []).append(time.time())
        emit('reset_result', {'success': False, 'error': 'Неверный код или пользователь'})
        return

    rc = ResetCode.query.filter_by(
        code=code, username=username, used=False
    ).filter(ResetCode.expires_at > time.time()).first()
    if not rc:
        reset_attempts.setdefault(ip, []).append(time.time())
        emit('reset_result', {'success': False, 'error': 'Неверный код или пользователь'})
        return

    rc.used = True
    user.password_hash = hash_password(new_pw)
    db.session.commit()

    emit('reset_result', {'success': True, 'message': 'Пароль изменён! Можешь войти.'})


# ========== ADMIN ==========

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # CSRF check: reject cross-origin requests
        origin = request.headers.get('Origin', '')
        if origin and origin.rstrip('/') != SITE_URL.rstrip('/'):
            return ('CSRF check failed', 403)
        auth = request.authorization
        if not auth:
            return ('Forbidden', 401, {'WWW-Authenticate': 'Basic realm="Admin"'})
        user = get_user(auth.username)
        if not user or not verify_password(auth.password, user.password_hash) or user.role not in ['owner', 'admin', 'moderator']:
            return ('Wrong', 401, {'WWW-Authenticate': 'Basic realm="Admin"'})
        return f(*args, **kwargs)
    return decorated


# ========== ADMIN API ==========

@app.route('/api/generate_reset_code', methods=['POST'])
@admin_required
def api_generate_reset_code():
    data = request.json or {}
    username = data.get('username', '').lower().strip().replace('@', '')
    target = get_user(username)
    if not target:
        return jsonify({'success': False, 'error': 'Пользователь не найден'})
    code = secrets.token_hex(4).upper()[:8]
    rc = ResetCode(code=code, username=username)
    db.session.add(rc)
    db.session.commit()
    return jsonify({'success': True, 'code': code})


@app.route('/api/stats', methods=['POST'])
@admin_required
def api_stats():
    now = time.time()
    today = time.strftime('%Y-%m-%d')
    users = User.query.count()
    online = User.query.filter_by(online=True).count()
    total_msgs = Message.query.count()
    today_msgs = Message.query.filter(Message.created_at >= now - 86400).count()
    pending_requests = Friendship.query.filter_by(status='pending').count()

    # Activity by day (last 7 days)
    days = []
    for i in range(6, -1, -1):
        day_start = now - (i * 86400 + now % 86400)
        day_end = day_start + 86400
        count = Message.query.filter(
            Message.created_at >= day_start,
            Message.created_at < day_end
        ).count()
        days.append({
            'date': time.strftime('%d.%m', time.localtime(day_start)),
            'count': count
        })

    # Last registered
    last_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    # Last messages
    last_msgs = Message.query.filter_by(is_deleted=False).order_by(Message.created_at.desc()).limit(5).all()

    return jsonify({
        'users': users,
        'online': online,
        'total_msgs': total_msgs,
        'today_msgs': today_msgs,
        'pending_requests': pending_requests,
        'activity_days': days,
        'last_users': [{'username': u.username, 'display_name': u.display_name, 'created_at': u.created_at} for u in last_users],
        'last_messages': [m.to_dict() for m in last_msgs],
    })


@app.route('/api/users', methods=['POST'])
@admin_required
def api_users():
    users = User.query.order_by(User.online.desc(), User.username).all()
    return jsonify({
        'users': [{
            'id': u.id,
            'username': u.username,
            'display_name': u.display_name,
            'role': u.role,
            'xp': u.xp,
            'verified': u.verified,
            'online': u.online,
            'achievement_count': u.achievements.count(),
            'friend_count': Friendship.query.filter(
                ((Friendship.user_id == u.id) | (Friendship.friend_id == u.id)),
                Friendship.status == 'accepted'
            ).count() // 2,
            'last_seen': u.last_seen,
            'created_at': u.created_at,
        } for u in users]
    })


@app.route('/api/user/<username>', methods=['POST'])
@admin_required
def api_user_detail(username):
    user = get_user(username)
    if not user:
        return jsonify({'error': 'Не найден'})
    return jsonify({
        'user': {
            'username': user.username,
            'display_name': user.display_name,
            'bio': user.bio,
            'role': user.role,
            'xp': user.xp,
            'legendary': user.legendary,
            'verified': user.verified,
            'online': user.online,
            'last_seen': user.last_seen,
            'created_at': user.created_at,
            'achievements': [a.to_dict() for a in user.achievements.all()],
            'friends': list(set(
                f.receiver.username if f.user_id == user.id else f.sender.username
                for f in Friendship.query.filter(
                    ((Friendship.user_id == user.id) | (Friendship.friend_id == user.id)),
                    Friendship.status == 'accepted'
                ).all()
            )),
        }
    })


@app.route('/api/user/<username>/role', methods=['POST'])
@admin_required
def api_user_role(username):
    auth = request.authorization
    requester = get_user(auth.username)
    data = request.json or {}
    new_role = data.get('role', '')
    if new_role not in ['user', 'moderator', 'admin', 'owner']:
        return jsonify({'success': False, 'error': 'Некорректная роль'})
    user = get_user(username)
    if not user:
        return jsonify({'success': False, 'error': 'Не найден'})
    # Only owner can assign owner or admin roles
    if new_role in ['owner', 'admin'] and requester.role != 'owner':
        return jsonify({'success': False, 'error': 'Только владелец может выдавать owner/admin'})
    # Only owner can demote owner
    if user.role == 'owner' and requester.role != 'owner':
        return jsonify({'success': False, 'error': 'Только владелец может менять роль владельца'})
    # System owner (krembovan) cannot be demoted
    if username == 'krembovan' and new_role != 'owner':
        return jsonify({'success': False, 'error': 'Нельзя понизить системного владельца'})
    old_role = user.role
    user.role = new_role
    secret_plain = None
    if new_role in ['owner', 'admin', 'moderator'] and not user.admin_secret_hash:
        secret_plain, user.admin_secret_hash, _ = generate_admin_secret()
    if old_role in ['owner', 'admin', 'moderator'] and new_role == 'user':
        user.admin_secret_hash = ''
    db.session.commit()
    if new_role in ['moderator', 'admin'] and old_role == 'user':
        from modules.achievements import award_achievement
        award_achievement(db, Achievement, User, username, 'dictator', None)
    return jsonify({'success': True, 'role': new_role, 'admin_secret': secret_plain})


@app.route('/api/user/<username>/verify', methods=['POST'])
@admin_required
def api_user_verify(username):
    user = get_user(username)
    if not user:
        return jsonify({'success': False, 'error': 'Не найден'})
    user.verified = not user.verified
    db.session.commit()
    return jsonify({'success': True, 'verified': user.verified})


@app.route('/api/user/<username>/award', methods=['POST'])
@admin_required
def api_user_award(username):
    data = request.json or {}
    ach_id = data.get('ach_id', '')
    if ach_id not in ACHIEVEMENTS:
        return jsonify({'success': False, 'error': 'Неизвестная ачивка'})
    user = get_user(username)
    if not user:
        return jsonify({'success': False, 'error': 'Не найден'})
    existing = Achievement.query.filter_by(user_id=user.id, ach_id=ach_id).first()
    if existing:
        return jsonify({'success': False, 'error': 'Уже есть'})
    ach = Achievement(user_id=user.id, ach_id=ach_id)
    db.session.add(ach)
    user.xp = min((user.xp or 0) + ACHIEVEMENTS[ach_id]['xp'], 99999)
    db.session.commit()
    return jsonify({'success': True, 'xp': user.xp})


@app.route('/api/user/<username>/legendary', methods=['POST'])
@admin_required
def api_user_legendary(username):
    user = get_user(username)
    if not user:
        return jsonify({'success': False, 'error': 'Не найден'})
    user.legendary = not user.legendary
    db.session.commit()
    return jsonify({'success': True, 'legendary': user.legendary})


@app.route('/api/admin_secrets', methods=['POST'])
@admin_required
def api_admin_secrets():
    auth = request.authorization
    requester = get_user(auth.username)
    if not requester or requester.role != 'owner':
        return jsonify({'success': False, 'error': 'Только владелец'})
    admins = User.query.filter(User.role.in_(['owner', 'admin', 'moderator'])).all()
    return jsonify({
        'secrets': [{
            'username': u.username,
            'display_name': u.display_name,
            'role': u.role,
            'secret': '•••••••• (нажмите "Сбросить" для нового)',
        } for u in admins]
    })


@app.route('/api/admin_secrets/regenerate', methods=['POST'])
@admin_required
def api_admin_secret_regenerate():
    auth = request.authorization
    requester = get_user(auth.username)
    if not requester or requester.role != 'owner':
        return jsonify({'success': False, 'error': 'Только владелец'})
    data = request.json or {}
    username = data.get('username', '').lower().strip().replace('@', '')
    user = get_user(username)
    if not user or user.role not in ['owner', 'admin', 'moderator']:
        return jsonify({'success': False, 'error': 'Не найден или не админ'})
    secret_plain, user.admin_secret_hash, _ = generate_admin_secret()
    db.session.commit()
    return jsonify({'success': True, 'secret': secret_plain})


@app.route('/api/whoami', methods=['POST'])
@admin_required
def api_whoami():
    auth = request.authorization
    user = get_user(auth.username)
    if not user:
        return jsonify({'error': 'Not found'})
    return jsonify({'username': user.username, 'role': user.role})


@app.route('/api/invite_codes', methods=['POST'])
@admin_required
def api_invite_codes():
    codes = InviteCode.query.order_by(InviteCode.created_at.desc()).limit(50).all()
    return jsonify({
        'codes': [{
            'code': c.code,
            'created_by': c.created_by,
            'used_by': c.used_by,
            'created_at': c.created_at,
        } for c in codes]
    })


@app.route('/api/invite_codes/generate', methods=['POST'])
@admin_required
def api_invite_generate():
    auth = request.authorization
    data = request.json or {}
    try:
        count = min(int(data.get('count', 1)), 20)
    except (ValueError, TypeError):
        count = 1
    codes = []
    for _ in range(count):
        code = secrets.token_hex(4).upper()[:8]
        ic = InviteCode(code=code, created_by=auth.username)
        db.session.add(ic)
        codes.append(code)
    db.session.commit()
    return jsonify({'success': True, 'codes': codes})


@app.route('/api/news', methods=['POST'])
@admin_required
def api_news():
    data = request.json or {}
    text = data.get('text', '').strip()
    if not text:
        return jsonify({'success': False, 'error': 'Пустой текст'})
    if len(text) > 5000:
        return jsonify({'success': False, 'error': 'Максимум 5000 символов'})
    auth = request.authorization
    user = get_user(auth.username)
    if not user:
        return jsonify({'success': False, 'error': 'Админ не найден'})
    if user.role not in ['owner', 'admin']:
        return jsonify({'success': False, 'error': 'Только админ может публиковать новости'})
    msg = Message(
        room='Новости',
        sender_id=user.id,
        text=text,
        created_at=time.time(),
    )
    db.session.add(msg)
    db.session.commit()
    socketio.emit('message', msg.to_dict(), room='Новости')
    return jsonify({'success': True})


@app.route('/api/messages/search', methods=['POST'])
@admin_required
def api_messages_search():
    data = request.json or {}
    query = data.get('query', '').strip().lower()
    author = data.get('author', '').strip().lower()
    room = data.get('room', '')

    msgs = Message.query.filter_by(is_deleted=False)
    if room:
        msgs = msgs.filter(Message.room == room)
    if author:
        user = get_user(author)
        if user:
            msgs = msgs.filter(Message.sender_id == user.id)
        else:
            return jsonify({'messages': []})
    if query:
        msgs = msgs.filter(Message.text.ilike(f'%{query}%'))

    msgs = msgs.order_by(Message.created_at.desc()).limit(50).all()
    return jsonify({'messages': [m.to_dict() for m in msgs]})


@app.route('/api/messages/delete', methods=['POST'])
@admin_required
def api_messages_delete():
    data = request.json or {}
    msg_id = data.get('msg_id', 0)
    msg = Message.query.get(msg_id)
    if not msg:
        return jsonify({'success': False, 'error': 'Не найдено'})
    msg.is_deleted = True
    db.session.commit()
    socketio.emit('message_deleted', {'msg_id': msg_id}, room=msg.room)
    return jsonify({'success': True})


@app.route('/admin')
@admin_required
def admin_panel():
    return render_template('admin.html')


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOADS_DIR, filename)


@socketio.on('disconnect')
def handle_disconnect():
    for un, sid in list(user_sessions.items()):
        if sid == request.sid:
            del user_sessions[un]
            user = get_user(un)
            if user:
                user.online = False
                user.last_seen = time.time()
                db.session.commit()
                friends = get_online_friends(un)
                for f in friends:
                    notify_user(f['username'], 'friend_online', {'username': un, 'online': False})
            break


# ========== MAIN ==========

@app.route('/')
def index():
    return render_template('index.html')


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=3000, debug=False, allow_unsafe_werkzeug=True)
