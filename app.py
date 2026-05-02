import eventlet
eventlet.monkey_patch()  # Должно быть самым первым!

import json, os, time
from flask import Flask, render_template, request, send_from_directory
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'skam_1337_prod'

# Настройка сокетов
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Пути к файлам базы данных
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILES = {
    'history': os.path.join(BASE_DIR, 'history.json'),
    'users': os.path.join(BASE_DIR, 'users.json'),
    'registry': os.path.join(BASE_DIR, 'chats_registry.json')
}

# Маршрут для иконки (чтобы убрать ошибку 404)
@app.route('/favicon.ico')
def favicon():
    # Если папки static нет, мы просто вернем пустой ответ, чтобы браузер отстал
    return '', 204

@app.route('/')
def index():
    return render_template('index.html')

# --- Далее идут твои функции базы данных и обработчики сокетов ---

def load_db(key):
    path = DB_FILES[key]
    if not os.path.exists(path): return [] if key == 'history' else {}
    try:
        with open(path, 'r', encoding='utf-8') as f: return json.load(f)
    except: return [] if key == 'history' else {}

def save_db(key, data):
    with open(DB_FILES[key], 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('join')
def on_join(data):
    room = data.get('room')
    if room:
        join_room(room)
        hist = [m for m in load_db('history') if m.get('room') == room]
        emit('history', hist)

@socketio.on('message')
def handle_msg(data):
    room = data.get('room')
    if not room: return
    data['timestamp'] = time.time()
    h = load_db('history')
    h.append(data)
    save_db('history', h[-1000:]) # Лимит 1000 сообщений
    emit('message', data, room=room)

@socketio.on('delete_chat')
def handle_delete(data):
    rid = data.get('chat_id')
    delete_all = data.get('delete_for_all')
    
    if delete_all:
        # 1. Стираем историю сообщений из файла
        msgs = [m for m in load_db('history') if m.get('room') != rid]
        save_db('history', msgs)
        # 2. Удаляем из реестра комнат
        reg = load_db('registry')
        if rid in reg: reg.pop(rid)
        save_db('registry', reg)
        # 3. Важное: сообщаем ВСЕМ, что чата больше нет
        emit('chat_deleted_globally', {'room': rid}, broadcast=True)
    else:
        # Локальное скрытие (по желанию можно дописать логику в hidden_chats.json)
        emit('chat_hidden_locally', {'room': rid})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host='0.0.0.0', port=port)