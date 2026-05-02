import json
import os
import time
import threading
import requests
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'skam_secret_key_1337'
# Используем eventlet (убедись, что он есть в requirements.txt)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Пути к файлам
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILES = {
    'history': os.path.join(BASE_DIR, 'history.json'),
    'registry': os.path.join(BASE_DIR, 'chats_registry.json'),
    'users': os.path.join(BASE_DIR, 'users.json'),
    'hidden': os.path.join(BASE_DIR, 'hidden_chats.json')
}

def load_json(key):
    path = FILES[key]
    if not os.path.exists(path): return [] if key == 'history' else {}
    try:
        with open(path, 'r', encoding='utf-8') as f: return json.load(f)
    except: return [] if key == 'history' else {}

def save_json(key, data):
    with open(FILES[key], 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('delete_chat')
def handle_delete_chat(data):
    rid = data.get('chat_id')
    delete_for_all = data.get('delete_for_all')
    my_nick = data.get('my_nick', '').lower()

    if delete_for_all:
        # Удаляем сообщения
        msgs = [m for m in load_json('history') if m.get('room') != rid]
        save_json('history', msgs)
        # Удаляем из реестра
        reg = load_json('registry')
        if rid in reg: reg.pop(rid)
        save_json('registry', reg)
        emit('chat_deleted_globally', {'chat_id': rid}, broadcast=True)
    elif my_nick:
        hidden = load_json('hidden')
        if rid not in hidden: hidden[rid] = []
        if my_nick not in hidden[rid]: hidden[rid].append(my_nick)
        save_json('hidden', hidden)
        emit('chat_hidden_locally', {'chat_id': rid})

# Вставь сюда свои стандартные обработчики auth и message, если они были удалены

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host='0.0.0.0', port=port)