import json, os, time
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'skam_1337_key'
# Обязательно используем eventlet для стабильности на Render
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Пути к файлам в корне проекта
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = {
    'history': os.path.join(BASE_DIR, 'history.json'),
    'users': os.path.join(BASE_DIR, 'users.json'),
    'registry': os.path.join(BASE_DIR, 'chats_registry.json')
}

def load_db(key):
    if not os.path.exists(DB[key]): return [] if key == 'history' else {}
    with open(DB[key], 'r', encoding='utf-8') as f:
        try: return json.load(f)
        except: return [] if key == 'history' else {}

def save_db(key, data):
    with open(DB[key], 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('auth')
def on_auth(data):
    nick = data.get('nick', '').strip()
    users = load_db('users')
    if nick.lower() not in users:
        users[nick.lower()] = {'display': nick, 'pass': data.get('password'), 'avatar': ''}
        save_db('users', users)
    emit('auth_result', {'success': True, 'user_data': users[nick.lower()]})

@socketio.on('delete_chat')
def handle_delete(data):
    rid = data.get('chat_id')
    if data.get('delete_for_all'):
        msgs = [m for m in load_db('history') if m.get('room') != rid]
        save_db('history', msgs)
        emit('chat_deleted_globally', {'chat_id': rid}, broadcast=True)
    else:
        emit('chat_hidden_locally', {'chat_id': rid})

@socketio.on('message')
def handle_msg(data):
    h = load_db('history')
    data['timestamp'] = time.time()
    h.append(data)
    save_db('history', h[-500:])
    emit('message', data, room=data.get('room'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host='0.0.0.0', port=port)