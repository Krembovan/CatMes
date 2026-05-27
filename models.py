import time
import secrets
import hashlib
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return f"pbkdf2:sha256:100000${salt}${h.hex()}"


def generate_admin_secret() -> tuple:
    raw = secrets.token_hex(4).upper()[:8]
    return raw, hash_password(raw), raw


def verify_password(password: str, hashed: str) -> bool:
    if not hashed or not isinstance(hashed, str):
        return False
    if not hashed.startswith('pbkdf2:'):
        return password == hashed
    try:
        meta_part, salt, stored_hash = hashed.split('$', 2)
        _, _, iterations_str = meta_part.split(':')
        h = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), int(iterations_str))
        return h.hex() == stored_hash
    except Exception:
        return False


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(50), default='')
    password_hash = db.Column(db.String(200), nullable=False)
    avatar_url = db.Column(db.String(500), default='')
    bio = db.Column(db.String(500), default='')
    birthday = db.Column(db.String(20), default='')
    role = db.Column(db.String(20), default='user')
    xp = db.Column(db.Integer, default=0)
    legendary = db.Column(db.Boolean, default=False)
    verified = db.Column(db.Boolean, default=False)
    theme = db.Column(db.String(20), default='dark')
    status = db.Column(db.String(50), default='online')
    created_at = db.Column(db.Float, default=time.time)
    last_seen = db.Column(db.Float, default=time.time)
    online = db.Column(db.Boolean, default=False)
    daily_date = db.Column(db.String(20), default='')
    daily_msgs = db.Column(db.Integer, default=0)
    login_dates = db.Column(db.JSON, default=list)
    admin_secret_hash = db.Column(db.String(200), default='')
    admin_secret_plain = db.Column(db.String(20), default='')

    achievements = db.relationship('Achievement', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    sent_friend_requests = db.relationship('Friendship', foreign_keys='Friendship.user_id', backref='sender', lazy='dynamic', cascade='all, delete-orphan')
    received_friend_requests = db.relationship('Friendship', foreign_keys='Friendship.friend_id', backref='receiver', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self, include_private=False):
        d = {
            'id': self.id,
            'username': self.username,
            'display_name': self.display_name or self.username,
            'avatar_url': self.avatar_url,
            'bio': self.bio,
            'birthday': self.birthday,
            'role': self.role,
            'xp': self.xp,
            'legendary': self.legendary,
            'verified': self.verified,
            'theme': self.theme,
            'status': self.status,
            'online': self.online,
            'last_seen': self.last_seen,
            'created_at': self.created_at,
        }
        if include_private:
            d['achievements'] = [a.to_dict() for a in self.achievements.all()]
        return d


class Friendship(db.Model):
    __tablename__ = 'friendships'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    friend_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.Float, default=time.time)


class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    room = db.Column(db.String(100), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    text = db.Column(db.Text, default='')
    image_url = db.Column(db.String(500), default='')
    voice_url = db.Column(db.String(500), default='')
    reply_to = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=True)
    is_deleted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.Float, default=time.time)
    edited_at = db.Column(db.Float, nullable=True)

    sender = db.relationship('User', backref='messages')
    reply = db.relationship('Message', remote_side=[id], backref='replies')
    reactions = db.relationship('Reaction', backref='message', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'room': self.room,
            'sender_id': self.sender_id,
            'sender_name': self.sender.display_name or self.sender.username,
            'sender_username': self.sender.username,
            'sender_avatar': self.sender.avatar_url,
            'text': self.text,
            'image_url': self.image_url,
            'voice_url': self.voice_url,
            'reply_to': self.reply_to,
            'reply_data': self.reply.to_dict() if self.reply and not self.reply.is_deleted else None,
            'is_deleted': self.is_deleted,
            'created_at': self.created_at,
            'edited_at': self.edited_at,
            'reactions': [r.to_dict() for r in self.reactions.all()],
        }


class Reaction(db.Model):
    __tablename__ = 'reactions'
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    emoji = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.Float, default=time.time)
    user = db.relationship('User', backref='reactions')

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'username': self.user.username,
            'emoji': self.emoji,
        }


class Group(db.Model):
    __tablename__ = 'groups'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    creator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.Float, default=time.time)
    creator = db.relationship('User', backref='created_groups')
    members = db.relationship('GroupMember', backref='group', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'creator_id': self.creator_id,
            'created_at': self.created_at,
            'member_count': self.members.count(),
        }


class GroupMember(db.Model):
    __tablename__ = 'group_members'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    joined_at = db.Column(db.Float, default=time.time)
    user = db.relationship('User', backref='group_memberships')


class Achievement(db.Model):
    __tablename__ = 'achievements'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    ach_id = db.Column(db.String(50), nullable=False)
    earned_at = db.Column(db.Float, default=time.time)

    def to_dict(self):
        return {'ach_id': self.ach_id, 'earned_at': self.earned_at}


class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    data = db.Column(db.JSON, default=dict)
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.Float, default=time.time)

    def to_dict(self):
        return {
            'id': self.id,
            'type': self.type,
            'data': self.data,
            'read': self.read,
            'created_at': self.created_at,
        }


class ResetCode(db.Model):
    __tablename__ = 'reset_codes'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    username = db.Column(db.String(20), nullable=False)
    used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.Float, default=time.time)
    expires_at = db.Column(db.Float, default=lambda: time.time() + 86400)


class InviteCode(db.Model):
    __tablename__ = 'invite_codes'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    created_by = db.Column(db.String(20), nullable=False)
    used_by = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.Float, default=time.time)
