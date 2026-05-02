import json
import os
import time
import threading
import requests
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'skam_secret_key_1337'
# Используем eventlet для стабильности на Render
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Пути
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, 'history.json')
CHATS_FILE = os.path.join(BASE_DIR, 'chats_registry.json')
USERS_FILE = os.path.join(BASE_DIR, 'users.json')
HIDDEN_FILE = os.path.join(BASE_DIR, 'hidden_chats.json')

def load_json(filename, default):
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return default
    return default

def save_json(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/')
def index():
    return render_template('index.html')

# --- LOGIC: DELETE ---
@socketio.on('delete_chat')
def handle_delete_chat(data):
    rid = data.get('chat_id')
    delete_for_all = data.get('delete_for_all')
    my_nick = data.get('my_nick', '').lower()

    if not rid: return

    if delete_for_all:
        # Удаляем историю полностью
        all_msgs = load_json(HISTORY_FILE, [])
        filtered_msgs = [m for m in all_msgs if m.get('room') != rid]
        save_json(HISTORY_FILE, filtered_msgs)
        
        # Удаляем комнату из реестра
        registry = load_json(CHATS_FILE, {})
        if rid in registry:
            registry.pop(rid)
            save_json(CHATS_FILE, registry)
            
        # Оповещаем всех в этой комнате
        emit('chat_deleted_globally', {'chat_id': rid}, room=rid)
    else:
        # Скрываем только у себя
        if my_nick:
            hidden = load_json(HIDDEN_FILE, {})
            if rid not in hidden: hidden[rid] = []
            if my_nick not in hidden[rid]: hidden[rid].append(my_nick)
            save_json(HIDDEN_FILE, hidden)
            emit('chat_hidden_locally', {'chat_id': rid})

# --- ОСТАЛЬНЫЕ СОБЫТИЯ (AUTH, MSG, JOIN) ---
# ... (используй те, что работали раньше, главное не дублируй импорты) ...

if __name__ == '__main__':
    # Render передает PORT автоматически. Если его нет — берем 10000
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host='0.0.0.0', port=port)