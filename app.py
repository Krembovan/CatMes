# САМАЯ ПЕРВАЯ СТРОКА
import eventlet
eventlet.monkey_patch()

import json
import os
import time
from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'skam_secure_2024'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILES = {
    'history': os.path.join(BASE_DIR, 'history.json'),
    'users': os.path.join(BASE_DIR, 'users.json'),
    'registry': os.path.join(BASE_DIR, 'chats_registry.json')
}

def load_db(key):
    path = DB_FILES[key]
    if not os.path.exists(path):
        default = [] if key == 'history' else {}
        save_db(key, default)
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return [] if key == 'history' else {}

def save_db(key, data):
    with open(DB_FILES[key], 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ============== HTML ПРЯМО В КОДЕ ==============
HTML_CONTENT = r'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SKAM Messenger</title>
    <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
    <style>
        :root {
            --bg: #0d1117; --surface: #161b22; --primary: #7c5cfc;
            --primary-dark: #6a48e0; --accent: #38bdf8; --text: #e2e8f0;
            --text-secondary: #94a3b8; --border: rgba(255,255,255,0.06);
            --danger: #ef4444; --success: #10b981; --radius: 16px;
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            background: #090c12; color: var(--text);
            font-family: 'Segoe UI', system-ui, sans-serif;
            height: 100vh; overflow: hidden;
        }
        .app-container { display: flex; height: 100vh; }
        
        .sidebar {
            width: 320px; background: var(--bg);
            border-right: 1px solid var(--border);
            display: flex; flex-direction: column;
        }
        .sidebar-header {
            padding: 20px; display: flex; justify-content: space-between;
            align-items: center; border-bottom: 1px solid var(--border);
        }
        .logo {
            font-size: 1.5rem; font-weight: 900;
            background: linear-gradient(135deg, var(--primary), var(--accent));
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        }
        .header-btns { display: flex; gap: 8px; }
        .icon-btn {
            width: 38px; height: 38px; border-radius: 12px;
            border: 1px solid var(--border); background: var(--surface);
            color: var(--text); cursor: pointer; font-size: 1.2rem;
            display: flex; align-items: center; justify-content: center;
            transition: 0.2s; position: relative;
        }
        .icon-btn:hover { background: var(--primary); border-color: var(--primary); }
        
        .badge-count {
            position: absolute; top: -6px; right: -6px;
            background: var(--danger); color: white;
            font-size: 0.6rem; width: 18px; height: 18px;
            border-radius: 50%; display: flex; align-items: center;
            justify-content: center; font-weight: bold; display: none;
        }
        .badge-count.show { display: flex; }
        
        .sidebar-nav { flex: 1; overflow-y: auto; padding: 15px; }
        .section-label {
            font-size: 0.65rem; font-weight: 700; text-transform: uppercase;
            letter-spacing: 2px; color: var(--text-secondary);
            padding: 15px 12px 8px;
        }
        .chat-item {
            display: flex; align-items: center; gap: 12px;
            padding: 10px 12px; border-radius: 12px;
            cursor: pointer; transition: 0.2s; color: var(--text-secondary);
            font-size: 0.9rem;
        }
        .chat-item:hover { background: var(--surface); color: var(--text); }
        .chat-item.active { background: rgba(124,92,252,0.15); color: var(--text); }
        .chat-avatar {
            width: 38px; height: 38px; border-radius: 12px;
            background: linear-gradient(135deg, var(--primary), var(--accent));
            display: flex; align-items: center; justify-content: center;
            font-weight: 700; flex-shrink: 0; font-size: 0.9rem;
        }
        .delete-chat-btn {
            margin-left: auto; cursor: pointer; opacity: 0;
            transition: 0.2s; font-size: 0.8rem;
        }
        .chat-item:hover .delete-chat-btn { opacity: 1; }
        .delete-chat-btn:hover { color: var(--danger); }
        
        .friend-item {
            display: flex; align-items: center; gap: 12px;
            padding: 10px 12px; border-radius: 12px;
            cursor: pointer; transition: 0.2s; color: var(--text-secondary);
            font-size: 0.9rem;
        }
        .friend-item:hover { background: var(--surface); color: var(--text); }
        .badge-accept {
            background: var(--primary); color: white; border: none;
            padding: 5px 12px; border-radius: 20px; font-size: 0.7rem;
            cursor: pointer; font-weight: 600; margin-left: auto;
        }
        .badge-accept:hover { background: var(--primary-dark); }
        
        .profile-mini {
            padding: 15px 20px; border-top: 1px solid var(--border);
            display: flex; align-items: center; gap: 12px; cursor: pointer;
        }
        .profile-mini:hover { background: var(--surface); }
        .avatar-mini {
            width: 38px; height: 38px; border-radius: 12px;
            object-fit: cover; background: var(--surface);
        }
        .profile-info { flex: 1; min-width: 0; }
        .profile-name { font-weight: 600; font-size: 0.9rem; }
        .profile-username { font-size: 0.75rem; color: var(--text-secondary); }
        
        .chat-area { flex: 1; display: flex; flex-direction: column; }
        .chat-header {
            padding: 18px 25px; border-bottom: 1px solid var(--border);
            font-weight: 600; background: rgba(13,17,23,0.8);
            backdrop-filter: blur(10px);
        }
        #messages {
            flex: 1; padding: 25px; overflow-y: auto;
            display: flex; flex-direction: column; gap: 8px;
        }
        .msg {
            display: flex; gap: 10px; max-width: 75%;
            animation: fadeIn 0.3s ease;
        }
        @keyframes fadeIn { from{opacity:0;transform:translateY(10px);} to{opacity:1;transform:translateY(0);} }
        .msg.my { align-self: flex-end; flex-direction: row-reverse; }
        .msg-avatar {
            width: 34px; height: 34px; border-radius: 10px;
            object-fit: cover; flex-shrink: 0;
        }
        .msg-bubble {
            padding: 12px 16px; border-radius: 18px;
            font-size: 0.9rem; line-height: 1.4; word-break: break-word;
        }
        .msg:not(.my) .msg-bubble {
            background: var(--surface); border: 1px solid var(--border);
            border-bottom-left-radius: 6px;
        }
        .msg.my .msg-bubble {
            background: linear-gradient(135deg, var(--primary), #9b7cfc);
            color: white; border-bottom-right-radius: 6px;
        }
        .msg-author { font-weight: 700; font-size: 0.8rem; margin-bottom: 2px; color: var(--accent); }
        .msg.my .msg-author { color: rgba(255,255,255,0.8); }
        
        .empty-chat {
            flex: 1; display: flex; flex-direction: column;
            align-items: center; justify-content: center;
            color: var(--text-secondary); gap: 15px;
        }
        .empty-chat-icon { font-size: 4rem; opacity: 0.3; }
        
        .input-box {
            padding: 20px 25px; display: flex; gap: 12px;
            background: var(--bg); border-top: 1px solid var(--border);
        }
        .input-msg {
            flex: 1; background: var(--surface); border: 1px solid var(--border);
            padding: 14px 20px; border-radius: 30px; color: var(--text);
            font-size: 0.95rem; outline: none; transition: 0.2s;
        }
        .input-msg:focus { border-color: var(--primary); }
        .btn-send {
            background: var(--primary); border: none; width: 48px; height: 48px;
            border-radius: 50%; cursor: pointer; font-size: 1.2rem;
            transition: 0.2s; display: flex; align-items: center;
            justify-content: center; flex-shrink: 0; color: white;
        }
        .btn-send:hover { background: var(--primary-dark); transform: scale(1.05); }
        
        /* УВЕДОМЛЕНИЯ */
        .notif-overlay {
            position: fixed; top: 60px; right: 20px; width: 360px;
            max-height: 500px; background: var(--surface);
            border: 1px solid var(--border); border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.6); z-index: 200;
            display: none; overflow-y: auto; flex-direction: column;
        }
        .notif-overlay.open { display: flex; }
        .notif-header {
            padding: 15px 20px; font-weight: 700; font-size: 0.9rem;
            border-bottom: 1px solid var(--border);
            display: flex; justify-content: space-between;
        }
        .notif-item {
            padding: 15px 20px; border-bottom: 1px solid rgba(255,255,255,0.03);
        }
        .notif-text { font-size: 0.85rem; margin-bottom: 5px; }
        .notif-time { font-size: 0.7rem; color: var(--text-secondary); }
        .notif-actions { display: flex; gap: 8px; margin-top: 10px; }
        .btn-sm {
            padding: 6px 16px; border-radius: 20px; border: none;
            cursor: pointer; font-size: 0.75rem; font-weight: 600;
        }
        .btn-sm.primary { background: var(--primary); color: white; }
        .btn-sm.danger { background: transparent; color: var(--danger); border: 1px solid var(--danger); }
        
        /* МОДАЛКИ */
        .modal-overlay {
            display: none; position: fixed; inset: 0;
            background: rgba(0,0,0,0.8); backdrop-filter: blur(12px);
            z-index: 1000; align-items: center; justify-content: center;
        }
        .modal-overlay.active { display: flex; }
        .modal {
            background: var(--bg); border: 1px solid var(--border);
            border-radius: 24px; padding: 35px; width: 420px;
            max-width: 90vw; box-shadow: 0 25px 50px rgba(0,0,0,0.5);
            max-height: 90vh; overflow-y: auto;
        }
        .modal h2 { text-align: center; margin-bottom: 25px; font-weight: 700; }
        .input-group { margin-bottom: 16px; }
        .input-group label {
            display: block; font-size: 0.75rem; font-weight: 600;
            color: var(--text-secondary); margin-bottom: 6px;
            text-transform: uppercase; letter-spacing: 1px;
        }
        .input-group input, .input-group textarea {
            width: 100%; padding: 12px 16px; border-radius: 12px;
            background: var(--surface); border: 1px solid var(--border);
            color: var(--text); font-size: 0.95rem; outline: none;
            resize: vertical;
        }
        .input-group input:focus, .input-group textarea:focus { border-color: var(--primary); }
        .input-group textarea { min-height: 70px; }
        .input-group input:disabled { opacity: 0.5; cursor: not-allowed; }
        
        .btn {
            width: 100%; padding: 14px; border-radius: 14px;
            border: none; font-weight: 600; font-size: 1rem;
            cursor: pointer; transition: 0.2s; margin-bottom: 8px;
        }
        .btn-primary { background: var(--primary); color: white; }
        .btn-primary:hover { background: var(--primary-dark); }
        .btn-secondary { background: transparent; color: var(--text); border: 1px solid var(--border); }
        .btn-danger { background: transparent; color: var(--danger); border: 1px solid var(--danger); }
        
        .modal-switch { text-align: center; margin-top: 20px; font-size: 0.85rem; color: var(--text-secondary); }
        .modal-switch a { color: var(--accent); cursor: pointer; font-weight: 600; }
        .error-text { color: var(--danger); font-size: 0.8rem; min-height: 20px; }
        .avatar-large {
            width: 90px; height: 90px; border-radius: 20px;
            object-fit: cover; display: block; margin: 0 auto 20px;
            border: 3px solid var(--primary);
        }
        
        .toast {
            position: fixed; top: 20px; left: 50%; transform: translateX(-50%) translateY(-120px);
            background: var(--surface); border: 1px solid var(--border);
            padding: 15px 25px; border-radius: 14px; z-index: 3000;
            font-weight: 500; transition: transform 0.3s ease;
        }
        .toast.show { transform: translateX(-50%) translateY(0); }
        .toast.success { border-left: 4px solid var(--success); }
        .toast.error { border-left: 4px solid var(--danger); }
        .toast.info { border-left: 4px solid var(--accent); }
    </style>
</head>
<body>

    <!-- АВТОРИЗАЦИЯ -->
    <div id="authOverlay" class="modal-overlay active">
        <div class="modal">
            <h2>⚡ <span style="background:linear-gradient(135deg,#7c5cfc,#38bdf8);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">SKAM</span></h2>
            <div id="authError" class="error-text" style="text-align:center;margin-bottom:15px;"></div>
            
            <div id="loginForm">
                <div class="input-group"><label>Username</label><input type="text" id="loginUser" placeholder="@username"></div>
                <div class="input-group"><label>Пароль</label><input type="password" id="loginPass" placeholder="••••"></div>
                <button class="btn btn-primary" onclick="handleLogin()">Войти</button>
                <div class="modal-switch">Нет аккаунта? <a onclick="switchAuth('register')">Создать</a></div>
            </div>

            <div id="registerForm" style="display:none;">
                <div class="input-group"><label>Username</label><input type="text" id="regUser" placeholder="уникальный логин"></div>
                <div class="input-group"><label>Имя</label><input type="text" id="regName" placeholder="Ваше имя"></div>
                <div class="input-group"><label>Пароль</label><input type="password" id="regPass" placeholder="минимум 4 символа"></div>
                <div class="input-group"><label>Повторите пароль</label><input type="password" id="regPass2" placeholder="повторите пароль"></div>
                <div id="regError" class="error-text"></div>
                <button class="btn btn-primary" onclick="handleRegister()">Зарегистрироваться</button>
                <div class="modal-switch">Уже есть аккаунт? <a onclick="switchAuth('login')">Войти</a></div>
            </div>
        </div>
    </div>

    <!-- ПРОФИЛЬ -->
    <div id="profileOverlay" class="modal-overlay">
        <div class="modal">
            <h2>👤 Профиль</h2>
            <img id="profileAvatar" class="avatar-large" src="" alt="Аватар">
            <div class="input-group"><label>Имя</label><input type="text" id="profileName"></div>
            <div class="input-group"><label>Username</label><input type="text" id="profileUser" disabled></div>
            <div class="input-group"><label>Описание</label><textarea id="profileBio"></textarea></div>
            <div class="input-group"><label>URL Аватара</label><input type="text" id="profileAvatarUrl"></div>
            <button class="btn btn-primary" onclick="saveProfile()">💾 Сохранить</button>
            <button class="btn btn-secondary" onclick="closeModal('profileOverlay')">Отмена</button>
            <button class="btn btn-danger" onclick="logout()">🚪 Выйти</button>
        </div>
    </div>

    <!-- ДОБАВЛЕНИЕ ДРУГА -->
    <div id="friendOverlay" class="modal-overlay">
        <div class="modal">
            <h2>🔍 Найти друга</h2>
            <div class="input-group"><label>Username</label><input type="text" id="searchUser" placeholder="@username"></div>
            <div id="friendError" class="error-text"></div>
            <button class="btn btn-primary" onclick="sendFriendReq()">📨 Отправить запрос</button>
            <button class="btn btn-secondary" onclick="closeModal('friendOverlay')">Отмена</button>
        </div>
    </div>

    <!-- УВЕДОМЛЕНИЯ -->
    <div class="notif-overlay" id="notifPanel">
        <div class="notif-header">
            <span>🔔 Уведомления</span>
            <span style="cursor:pointer;color:var(--text-secondary);" onclick="document.getElementById('notifPanel').classList.remove('open')">✕</span>
        </div>
        <div id="notifList"></div>
    </div>

    <div id="toast" class="toast"></div>

    <!-- ОСНОВНОЙ ИНТЕРФЕЙС -->
    <div class="app-container" id="mainApp" style="display:none;">
        <div class="sidebar">
            <div class="sidebar-header">
                <span class="logo">SKAM</span>
                <div class="header-btns">
                    <div class="icon-btn" onclick="toggleNotifPanel()" title="Уведомления">
                        🔔<span class="badge-count" id="notifBadge"></span>
                    </div>
                    <div class="icon-btn" onclick="openModal('friendOverlay')" title="Добавить друга">+</div>
                    <div class="icon-btn" onclick="openModal('profileOverlay');loadProfile();" title="Профиль">👤</div>
                </div>
            </div>
            <div class="sidebar-nav">
                <div class="section-label">💬 Каналы</div>
                <div id="roomList"></div>
                <div class="section-label">👥 Друзья</div>
                <div id="friendList"></div>
            </div>
            <div class="profile-mini" onclick="openModal('profileOverlay');loadProfile();">
                <img id="myAvatar" class="avatar-mini" src="" alt="Аватар">
                <div class="profile-info">
                    <div class="profile-name" id="myName">—</div>
                    <div class="profile-username" id="myUsername">@—</div>
                </div>
            </div>
        </div>

        <div class="chat-area">
            <div class="chat-header" id="chatHeader"># Общий канал</div>
            <div id="messages">
                <div class="empty-chat">
                    <div class="empty-chat-icon">💬</div>
                    <div>Выберите чат и начните общение</div>
                </div>
            </div>
            <div class="input-box">
                <input type="text" class="input-msg" id="msgInput" placeholder="Написать сообщение..." onkeypress="if(event.key==='Enter')sendMsg()">
                <button class="btn-send" onclick="sendMsg()">➤</button>
            </div>
        </div>
    </div>

    <script>
        const socket = io();
        let myData = null;
        let currentRoom = 'Общий';
        let notifications = [];

        function escapeHtml(text) {
            const map = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'};
            return String(text).replace(/[&<>"']/g, m => map[m]);
        }

        function showToast(msg, type='success') {
            const t = document.getElementById('toast');
            t.textContent = msg;
            t.className = `toast ${type} show`;
            clearTimeout(t._t);
            t._t = setTimeout(() => t.classList.remove('show'), 3000);
        }

        function openModal(id) { document.getElementById(id).classList.add('active'); }
        function closeModal(id) { document.getElementById(id).classList.remove('active'); }

        document.addEventListener('keydown', e => {
            if (e.key === 'Escape') document.querySelectorAll('.modal-overlay').forEach(m => m.classList.remove('active'));
        });

        function switchAuth(mode) {
            document.getElementById('loginForm').style.display = mode === 'login' ? 'block' : 'none';
            document.getElementById('registerForm').style.display = mode === 'register' ? 'block' : 'none';
            document.getElementById('authError').textContent = '';
            document.getElementById('regError').textContent = '';
        }

        function handleLogin() {
            const un = document.getElementById('loginUser').value.trim();
            const pwd = document.getElementById('loginPass').value;
            document.getElementById('authError').textContent = '';
            if (!un || !pwd) { document.getElementById('authError').textContent = 'Заполните все поля'; return; }
            socket.emit('auth', { action: 'login', username: un, password: pwd });
        }

        function handleRegister() {
            const un = document.getElementById('regUser').value.trim();
            const name = document.getElementById('regName').value.trim();
            const pwd = document.getElementById('regPass').value;
            const pwd2 = document.getElementById('regPass2').value;
            const errEl = document.getElementById('regError');
            errEl.textContent = '';
            if (!un || !name || !pwd || !pwd2) { errEl.textContent = 'Заполните все поля'; return; }
            if (un.length < 3) { errEl.textContent = 'Логин: минимум 3 символа'; return; }
            if (pwd.length < 4) { errEl.textContent = 'Пароль: минимум 4 символа'; return; }
            if (pwd !== pwd2) { errEl.textContent = 'Пароли не совпадают'; return; }
            socket.emit('auth', { action: 'register', username: un, display_name: name, password: pwd, password2: pwd2 });
        }

        socket.on('auth_result', data => {
            if (data.success) {
                myData = data.user;
                notifications = myData.notifications || [];
                document.getElementById('authOverlay').classList.remove('active');
                document.getElementById('mainApp').style.display = 'flex';
                updateMyInfo();
                updateBadge();
                updateFriendList();
                socket.emit('get_rooms');
                switchRoom('Общий');
            } else {
                if (document.getElementById('registerForm').style.display === 'block') {
                    document.getElementById('regError').textContent = data.error;
                } else {
                    document.getElementById('authError').textContent = data.error;
                }
            }
        });

        function updateMyInfo() {
            if (!myData) return;
            document.getElementById('myName').textContent = myData.display_name;
            document.getElementById('myUsername').textContent = '@' + myData.username;
            document.getElementById('myAvatar').src = myData.avatar;
        }

        function loadProfile() {
            if (!myData) return;
            document.getElementById('profileName').value = myData.display_name;
            document.getElementById('profileUser').value = '@' + myData.username;
            document.getElementById('profileBio').value = myData.bio || '';
            document.getElementById('profileAvatarUrl').value = myData.avatar || '';
            document.getElementById('profileAvatar').src = myData.avatar;
        }

        function saveProfile() {
            const name = document.getElementById('profileName').value.trim();
            const bio = document.getElementById('profileBio').value.trim();
            const avatarUrl = document.getElementById('profileAvatarUrl').value.trim();
            if (!name) { showToast('Имя обязательно', 'error'); return; }
            socket.emit('update_profile', { username: myData.username, display_name: name, bio: bio, avatar: avatarUrl });
        }

        socket.on('profile_updated', data => {
            myData = data.user;
            updateMyInfo();
            showToast('Профиль обновлён!', 'success');
            closeModal('profileOverlay');
        });

        function logout() {
            myData = null;
            document.getElementById('mainApp').style.display = 'none';
            document.getElementById('authOverlay').classList.add('active');
            document.getElementById('messages').innerHTML = '<div class="empty-chat"><div class="empty-chat-icon">💬</div><div>Выберите чат</div></div>';
            closeModal('profileOverlay');
        }

        // ========== УВЕДОМЛЕНИЯ ==========
        function toggleNotifPanel() {
            const panel = document.getElementById('notifPanel');
            panel.classList.toggle('open');
            if (panel.classList.contains('open')) renderNotifications();
        }

        function updateBadge() {
            const unread = notifications.filter(n => !n.read).length;
            const badge = document.getElementById('notifBadge');
            badge.textContent = unread;
            badge.classList.toggle('show', unread > 0);
        }

        function renderNotifications() {
            const list = document.getElementById('notifList');
            const all = [...(myData?.requests || []).map(un => ({
                type: 'friend_request',
                from: un,
                text: `@${un} хочет добавить вас в друзья`,
                timestamp: Date.now() / 1000
            })), ...notifications];
            
            if (all.length === 0) {
                list.innerHTML = '<div style="padding:30px;text-align:center;color:var(--text-secondary);">Нет уведомлений</div>';
                return;
            }
            
            list.innerHTML = all.map(n => `
                <div class="notif-item">
                    <div class="notif-text">${escapeHtml(n.text)}</div>
                    <div class="notif-time">${new Date(n.timestamp * 1000).toLocaleString()}</div>
                    ${n.type === 'friend_request' ? `
                        <div class="notif-actions">
                            <button class="btn-sm primary" onclick="acceptFriend('${n.from}');toggleNotifPanel();">✓ Принять</button>
                            <button class="btn-sm danger" onclick="declineFriend('${n.from}');toggleNotifPanel();">✕ Отклонить</button>
                        </div>
                    ` : ''}
                </div>
            `).join('');
        }

        socket.on('new_notification', notif => {
            notifications.unshift(notif);
            updateBadge();
            showToast(notif.text, 'info');
        });

        // ========== ДРУЗЬЯ ==========
        function updateFriendList() {
            if (!myData) return;
            updateBadge();
            const list = document.getElementById('friendList');
            let html = '';
            (myData.requests || []).forEach(un => {
                html += `<div class="friend-item" style="border:1px dashed var(--primary);">
                    <div class="chat-avatar">👤</div>
                    <span style="flex:1;">@${escapeHtml(un)}</span>
                    <button class="badge-accept" onclick="event.stopPropagation();acceptFriend('${escapeHtml(un)}')">✓ Принять</button>
                </div>`;
            });
            (myData.friends || []).forEach(un => {
                html += `<div class="friend-item" onclick="startPrivate('${escapeHtml(un)}')">
                    <div class="chat-avatar">🔵</div><span>@${escapeHtml(un)}</span>
                </div>`;
            });
            if (!html) html = '<div style="padding:10px;color:var(--text-secondary);font-size:0.8rem;">Нет друзей</div>';
            list.innerHTML = html;
        }

        function sendFriendReq() {
            const target = document.getElementById('searchUser').value.trim();
            if (!target) { document.getElementById('friendError').textContent = 'Введите username'; return; }
            socket.emit('send_friend_request', { my_username: myData.username, target_username: target });
            closeModal('friendOverlay');
        }

        function acceptFriend(un) {
            socket.emit('accept_friend', { my_username: myData.username, target_username: un });
        }

        function declineFriend(un) {
            socket.emit('decline_friend', { my_username: myData.username, target_username: un });
        }

        socket.on('friend_msg', data => showToast(data.text, data.type || 'info'));

        // ========== КОМНАТЫ ==========
        socket.on('room_list', rooms => {
            const list = document.getElementById('roomList');
            let html = `<div class="chat-item active" onclick="switchRoom('Общий')" data-room="Общий"><div class="chat-avatar">🌍</div><span>Общий канал</span></div>`;
            Object.keys(rooms).forEach(id => {
                if (id === 'Общий') return;
                if (rooms[id].type === 'private') {
                    if (myData && id.includes(myData.username)) {
                        html += `<div class="chat-item" onclick="switchRoom('${id}')" data-room="${id}">
                            <div class="chat-avatar">💬</div><span>${escapeHtml(rooms[id].name)}</span>
                            <span class="delete-chat-btn" onclick="event.stopPropagation();deleteChat('${id}')" title="Удалить чат">🗑️</span>
                        </div>`;
                    }
                } else {
                    html += `<div class="chat-item" onclick="switchRoom('${id}')" data-room="${id}"><div class="chat-avatar">#</div><span>${escapeHtml(rooms[id].name)}</span></div>`;
                }
            });
            list.innerHTML = html;
        });

        function switchRoom(roomId) {
            currentRoom = roomId;
            document.getElementById('messages').innerHTML = '';
            document.getElementById('chatHeader').textContent = roomId === 'Общий' ? '# Общий канал' : `💬 Чат`;
            document.querySelectorAll('.chat-item').forEach(el => el.classList.toggle('active', el.dataset.room === roomId));
            socket.emit('join', { room: roomId });
        }

        function startPrivate(un) {
            const ids = [myData.username, un].sort();
            switchRoom(`priv_${ids[0]}_${ids[1]}`);
        }

        function deleteChat(chatId) {
            if (!confirm('Удалить переписку навсегда? История будет потеряна у обоих.')) return;
            socket.emit('delete_chat', { chat_id: chatId, username: myData.username });
        }

        socket.on('chat_deleted', data => {
            if (data.success) {
                showToast('Чат удалён', 'success');
                if (currentRoom === data.chat_id) switchRoom('Общий');
                socket.emit('get_rooms');
            }
        });

        // ========== СООБЩЕНИЯ ==========
        function sendMsg() {
            const input = document.getElementById('msgInput');
            const text = input.value.trim();
            if (!text || !myData) return;
            socket.emit('message', { room: currentRoom, text, user: myData.display_name, username: myData.username, avatar: myData.avatar });
            input.value = '';
        }

        function renderMessage(msg) {
            const box = document.getElementById('messages');
            if (box.querySelector('.empty-chat')) box.innerHTML = '';
            const isMy = msg.username === myData?.username;
            const div = document.createElement('div');
            div.className = `msg ${isMy ? 'my' : ''}`;
            div.innerHTML = `
                <img class="msg-avatar" src="${escapeHtml(msg.avatar||'')}" onerror="this.style.display='none'">
                <div class="msg-bubble">
                    ${isMy ? '' : `<div class="msg-author">${escapeHtml(msg.user)}</div>`}
                    ${escapeHtml(msg.text)}
                </div>`;
            box.appendChild(div);
            box.scrollTop = box.scrollHeight;
        }

        socket.on('message', msg => { if (msg.room === currentRoom) renderMessage(msg); });
        socket.on('history', hist => {
            document.getElementById('messages').innerHTML = '';
            if (!hist.length) {
                document.getElementById('messages').innerHTML = '<div class="empty-chat"><div class="empty-chat-icon">💬</div><div>Нет сообщений</div></div>';
            } else hist.forEach(renderMessage);
        });

        document.getElementById('loginPass').addEventListener('keypress', e => { if (e.key === 'Enter') handleLogin(); });
        document.getElementById('regPass2').addEventListener('keypress', e => { if (e.key === 'Enter') handleRegister(); });
    </script>
</body>
</html>'''

@app.route('/')
def index():
    return HTML_CONTENT

# ============== АВТОРИЗАЦИЯ ==============
@socketio.on('auth')
def handle_auth(data):
    action = data.get('action', 'login')
    un = data.get('username', '').strip().lower()
    dn = data.get('display_name', '').strip()
    pwd = data.get('password', '')
    pwd2 = data.get('password2', '')
    
    if not un or len(un) < 3 or len(un) > 20:
        emit('auth_result', {'success': False, 'error': 'Логин: 3-20 символов'})
        return
    if not pwd or len(pwd) < 4:
        emit('auth_result', {'success': False, 'error': 'Пароль: минимум 4 символа'})
        return
    
    users = load_db('users')
    
    if action == 'register':
        if pwd != pwd2:
            emit('auth_result', {'success': False, 'error': 'Пароли не совпадают'})
            return
        if un in users:
            emit('auth_result', {'success': False, 'error': 'Пользователь уже существует'})
            return
        
        users[un] = {
            'username': un, 'display_name': dn or un, 'pass': pwd,
            'avatar': f'https://api.dicebear.com/7.x/bottts-neutral/svg?seed={un}',
            'bio': 'Пользователь SKAM', 'friends': [], 'requests': [],
            'notifications': []
        }
        save_db('users', users)
        emit('auth_result', {'success': True, 'user': users[un]})
    else:
        if un not in users:
            emit('auth_result', {'success': False, 'error': 'Пользователь не найден'})
            return
        if users[un]['pass'] != pwd:
            emit('auth_result', {'success': False, 'error': 'Неверный пароль'})
            return
        
        user_data = users[un]
        user_data.setdefault('friends', [])
        user_data.setdefault('requests', [])
        user_data.setdefault('notifications', [])
        emit('auth_result', {'success': True, 'user': user_data})

@socketio.on('update_profile')
def handle_profile_update(data):
    un = data.get('username', '').lower()
    users = load_db('users')
    if un not in users: return
    if 'display_name' in data and data['display_name'].strip():
        users[un]['display_name'] = data['display_name'].strip()
    if 'bio' in data: users[un]['bio'] = data['bio'].strip()
    if 'avatar' in data and data['avatar'].strip():
        users[un]['avatar'] = data['avatar'].strip()
    save_db('users', users)
    emit('profile_updated', {'user': users[un]})

@socketio.on('send_friend_request')
def handle_friend_request(data):
    my_un = data.get('my_username', '').lower()
    target_un = data.get('target_username', '').lower().replace('@', '').strip()
    users = load_db('users')
    if not target_un: emit('friend_msg', {'text':'Введите имя','type':'error'}, room=request.sid); return
    if target_un not in users: emit('friend_msg', {'text':'Не найден','type':'error'}, room=request.sid); return
    if target_un == my_un: emit('friend_msg', {'text':'Нельзя добавить себя','type':'error'}, room=request.sid); return
    user = users[target_un]
    if my_un in user.get('friends', []): emit('friend_msg', {'text':'Уже друзья','type':'info'}, room=request.sid); return
    if my_un in user.get('requests', []): emit('friend_msg', {'text':'Запрос уже отправлен','type':'info'}, room=request.sid); return
    user.setdefault('requests', []).append(my_un)
    notif = {'id':str(int(time.time()*1000)),'type':'friend_request','from':my_un,'from_name':users[my_un]['display_name'],'text':f'@{my_un} хочет добавить вас в друзья','timestamp':time.time(),'read':False}
    user.setdefault('notifications', []).insert(0, notif)
    save_db('users', users)
    emit('friend_msg', {'text':f'Запрос отправлен @{target_un}','type':'success'}, room=request.sid)

@socketio.on('accept_friend')
def handle_accept(data):
    my_un = data.get('my_username', '').lower()
    target_un = data.get('target_username', '').lower()
    users = load_db('users')
    if my_un not in users: return
    user = users[my_un]
    if target_un not in user.get('requests', []): return
    user['requests'].remove(target_un)
    user.setdefault('friends', []).append(target_un)
    if target_un in users:
        users[target_un].setdefault('friends', []).append(my_un)
        notif = {'id':str(int(time.time()*1000)),'type':'friend_accepted','from':my_un,'from_name':users[my_un]['display_name'],'text':f'@{my_un} принял запрос','timestamp':time.time(),'read':False}
        users[target_un].setdefault('notifications', []).insert(0, notif)
    reg = load_db('registry')
    chat_id = f"priv_{min(my_un, target_un)}_{max(my_un, target_un)}"
    if chat_id not in reg:
        reg[chat_id] = {"name":f"Чат @{target_un}","type":"private","users":[my_un,target_un]}
        save_db('registry', reg)
    user.setdefault('notifications', [])
    user['notifications'] = [n for n in user['notifications'] if not (n['type']=='friend_request' and n['from']==target_un)]
    save_db('users', users)
    emit('auth_result', {'success':True,'user':users[my_un]})
    emit('room_list', reg, broadcast=True)

@socketio.on('decline_friend')
def handle_decline(data):
    my_un = data.get('my_username', '').lower()
    target_un = data.get('target_username', '').lower()
    users = load_db('users')
    if my_un not in users: return
    user = users[my_un]
    if target_un in user.get('requests', []): user['requests'].remove(target_un)
    user.setdefault('notifications', [])
    user['notifications'] = [n for n in user['notifications'] if not (n['type']=='friend_request' and n['from']==target_un)]
    save_db('users', users)
    emit('auth_result', {'success':True,'user':users[my_un]})

@socketio.on('delete_chat')
def handle_delete_chat(data):
    chat_id = data.get('chat_id', '')
    if not chat_id or not chat_id.startswith('priv_'): return
    reg = load_db('registry')
    if chat_id in reg:
        del reg[chat_id]
        save_db('registry', reg)
        hist = load_db('history')
        hist = [m for m in hist if m.get('room') != chat_id]
        save_db('history', hist)
        emit('chat_deleted', {'success':True,'chat_id':chat_id}, broadcast=True)
        emit('room_list', reg, broadcast=True)

@socketio.on('message')
def handle_msg(data):
    room = data.get('room', 'Общий')
    text = data.get('text', '').strip()
    if not text or len(text) > 1000: return
    data['timestamp'] = time.time()
    data['text'] = text
    h = load_db('history')
    h.append(data)
    if len(h) > 1000: h = h[-1000:]
    save_db('history', h)
    emit('message', data, room=room)

@socketio.on('join')
def on_join(data):
    room = data.get('room', 'Общий')
    join_room(room)
    hist = [m for m in load_db('history') if m.get('room') == room][-50:]
    emit('history', hist)

@socketio.on('get_rooms')
def get_rooms():
    reg = load_db('registry')
    if 'Общий' not in reg:
        reg['Общий'] = {"name":"Общий канал","type":"public","users":[]}
        save_db('registry', reg)
    emit('room_list', reg)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host='0.0.0.0', port=port)