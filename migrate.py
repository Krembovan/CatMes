"""Migrate old JSON data to CATMES_NEO SQLite database."""
import json, os, sys, time, hashlib, secrets
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['CAT_DATA_DIR'] = '/opt/skam/data'

from app import app, db
from models import User, Friendship, Message, Achievement, hash_password

DATA_SOURCES = [
    '/opt/cat_data',
    '/opt/skam-backup-20260525_000614/cat_data',
]

def load_json(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None

def migrate():
    with app.app_context():
        db.create_all()

        # Find latest users.json
        users_data = None
        msgs_data = None
        for src in DATA_SOURCES:
            u = load_json(os.path.join(src, 'users.json'))
            m = load_json(os.path.join(src, 'messages.json'))
            if u and not users_data:
                users_data = u
                print(f"Users from: {src} ({len(u)} users)")
            if m and not msgs_data:
                msgs_data = m
                print(f"Messages from: {src} ({len(m)} msgs)")

        if not users_data:
            print("No users.json found!")
            return

        # Import users
        for un, data in users_data.items():
            existing = User.query.filter_by(username=un).first()
            if existing:
                print(f"  User @{un} already exists, skipping")
                continue

            pw_hash = data.get('pass')
            if pw_hash and not pw_hash.startswith('pbkdf2:'):
                pw_hash = hash_password(pw_hash)

            user = User(
                username=un,
                display_name=data.get('display_name', un),
                password_hash=pw_hash or hash_password('migrated'),
                avatar_url=data.get('avatar', ''),
                bio=data.get('bio', ''),
                birthday=data.get('birthday', ''),
                role=data.get('role', 'user'),
                xp=min(data.get('xp', 0), 99999),
                legendary=data.get('legendary', False),
                verified=data.get('telegram_verified', False) or bool(data.get('verified_by')),
                online=False,
                last_seen=data.get('last_seen', time.time()),
                created_at=data.get('created_at', time.time()),
                login_dates=data.get('login_dates', []),
            )
            db.session.add(user)
            db.session.flush()

            # Import achievements
            for ach in data.get('achievements', []):
                a = Achievement(user_id=user.id, ach_id=ach['id'], earned_at=ach['earned'])
                db.session.add(a)

            print(f"  + @{un} — {user.display_name} ({user.role}, {user.xp} XP)")

        db.session.commit()

        # Import messages
        if msgs_data:
            msg_count = 0
            for m in msgs_data:
                room = m.get('room', 'Общий')
                sender_name = m.get('username', '') or m.get('user', '')
                sender = User.query.filter_by(username=sender_name.lower()).first()
                if not sender:
                    continue

                existing_msg = Message.query.filter_by(
                    room=room,
                    sender_id=sender.id,
                    created_at=m.get('timestamp', 0)
                ).first()
                if existing_msg:
                    continue

                msg = Message(
                    room=room,
                    sender_id=sender.id,
                    text=m.get('text', ''),
                    image_url=m.get('image', ''),
                    created_at=m.get('timestamp', time.time()),
                )
                db.session.add(msg)
                msg_count += 1

            db.session.commit()
            print(f"  {msg_count} messages imported")

        print("Migration complete!")

if __name__ == '__main__':
    migrate()
