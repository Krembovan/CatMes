import json, os, time
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'skam_secure_1337'
# Обязательно используем eventlet для стабильности на Render
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Пути к базам данных
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = {
    'history': os.path.join(BASE_DIR, 'history.json'),
    'registry': os.path.join(BASE_DIR, 'chats_registry.json'),
    'users': os.path.join(BASE_DIR, 'users.json'),
    'hidden': os.path.join(BASE_DIR, 'hidden_chats.json')
}

def load_db(key):
    path = DB[key]
    if not os.path.exists(path): return [] if key == 'history' else {}
    try:
        with open(path, 'r', encoding='utf-8') as f: return json.load(f)
    except: return [] if key == 'history' else {}

def save_db(key, data):
    with open(DB[key], 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/')
def index():
    return render_template('index.html')

# --- УДАЛЕНИЕ ЧАТА (FIXED) ---
@socketio.on('delete_chat')
def handle_delete(data):
    rid = data.get('chat_id')
    delete_all = data.get('delete_for_all')
    my_nick = data.get('my_nick', '').lower()

    if not rid: return

    if delete_all:
        # 1. Удаляем историю сообщений
        all_msgs = load_db('history')
        filtered = [m for m in all_msgs if m.get('room') != rid]
        save_db('history', filtered)
        # 2. Удаляем комнату из реестра
        registry = load_db('registry')
        if rid in registry:
            registry.pop(rid)
            save_db('registry', registry)
        # 3. Сообщаем ВСЕМ клиентам в этой комнате
        emit('chat_deleted_globally', {'chat_id': rid}, broadcast=True)
    elif my_nick:
        # Скрываем только для себя
        hidden = load_db('hidden')
        if rid not in hidden: hidden[rid] = []
        if my_nick not in hidden[rid]: hidden[rid].append(my_nick)
        save_db('hidden', hidden)
        emit('chat_hidden_locally', {'chat_id': rid})

# (Остальные обработчики message, join, auth оставь как были)

if __name__ == '__main__':
    # Render автоматически передает PORT. Если нет — берем 10000
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host='0.0.0.0', port=port)