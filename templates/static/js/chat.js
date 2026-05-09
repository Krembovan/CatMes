// chat.js — сообщения, комнаты

function switchRoom(r) {
    window.currentRoom = r;
    const mc = $('#messages');
    const ch = $('#chatHeader');
    if (mc) mc.innerHTML = '';
    if (ch) {
        if (r === 'Общий') { ch.textContent = '# Общий канал';
            window.dmUser = null; } else if (r.startsWith('dm_')) { ch.textContent = '💬 @' + window.dmUser; }
    }
    $$('.chat-item').forEach(el => el.classList.toggle('active', el.getAttribute('data-room') === r));
    socket.emit('join', { room: r });
    if (r.startsWith('dm_') && window.myData) {
        socket.emit('mark_read', { room: r, username: window.myData.username });
    }
    if (window.innerWidth <= 768) {
        const sb = $('#sidebar');
        if (sb) sb.classList.add('hidden');
    }
    if (r.startsWith('dm_') && window.dmUser) {
        window.notifications = window.notifications.filter(n => n.from !== window.dmUser);
        updateBadge();
    }
}

function goBack() {
    const sb = $('#sidebar');
    if (sb) sb.classList.remove('hidden');
}

function sendMsg() {
    const mi = $('#msgInput');
    if (!mi || !window.myData) return;
    const t = mi.value.trim();
    if (!t) return;
    socket.emit('message', {
        room: window.currentRoom,
        text: t,
        user: window.myData.display_name,
        username: window.myData.username,
        avatar: window.myData.avatar
    });
    mi.value = '';
    mi.focus();
}

function deleteMessage(id) {
    if (!confirm('Удалить сообщение?')) return;
    socket.emit('delete_message', { msg_id: id, username: window.myData.username });
}

function renderMessage(m) {
    const mc = $('#messages');
    if (!mc) return;
    if (mc.querySelector('.empty-chat')) mc.innerHTML = '';
    const isMy = m.username === (window.myData ? window.myData.username : '');
    const div = document.createElement('div');
    div.className = 'msg' + (isMy ? ' my' : '');
    const canDel = window.myData && ['owner', 'admin', 'moderator'].includes(window.myData.role);
    const delBtn = canDel ? `<span class="msg-delete-btn" data-delete="${m.timestamp}" title="Удалить">✕</span>` : '';
    const avUrl = 'https://ui-avatars.com/api/?name=' + m.username + '&background=7c5cfc&color=fff&size=40';
    const avHtml = `<img class="msg-avatar" src="${escapeHtml(m.avatar || avUrl)}" onerror="this.src='${avUrl}'" data-viewprofile="${escapeHtml(m.username)}" style="cursor:pointer;" title="Посмотреть профиль" alt="Аватар ${escapeHtml(m.username)}">`;
    const readMark = isMy ? (m.read ? '<span style="font-size:0.75rem;color:#38bdf8;font-weight:bold;">✓✓</span>' : '<span style="font-size:0.75rem;color:#7c5cfc;">✓</span>') : '';
    const authHtml = isMy ? '' : `<div class="msg-author" data-viewprofile="${escapeHtml(m.username)}" style="cursor:pointer;color:var(--accent);" title="Посмотреть профиль">${escapeHtml(m.user || m.username)}</div>`;
    div.innerHTML = avHtml + '<div class="msg-bubble">' + authHtml + escapeHtml(m.text) + ' ' + readMark + delBtn + '</div>';
    mc.appendChild(div);
    mc.scrollTop = mc.scrollHeight;
}

function startDM(u) {
    window.dmUser = u;
    const parts = [window.myData.username, u].sort();
    switchRoom('dm_' + parts[0] + '_' + parts[1]);
}

function viewProfile(u) {
    if (u === window.myData.username) {
        openModal('#profileOverlay');
        if (typeof loadProfile === 'function') loadProfile();
        return;
    }
    socket.emit('get_user_profile', { username: u, requester: window.myData.username });
}

function sendFriendReqTo(u) {
    socket.emit('send_friend_request', { my_username: window.myData.username, target_username: u });
    showToast('Запрос отправлен', 'success');
    closeModal('#userProfileOverlay');
}

// Делегирование событий чата
document.addEventListener('click', (e) => {
    const t = e.target;

    if (t.matches('[data-room]') || t.closest('[data-room]')) {
        const el = t.matches('[data-room]') ? t : t.closest('[data-room]');
        switchRoom(el.getAttribute('data-room'));
        return;
    }

    if (t.matches('[data-dm]')) {
        startDM(t.getAttribute('data-dm'));
        const np = $('#notifPanel');
        if (np) np.classList.remove('open');
        closeModal('#userProfileOverlay');
        return;
    }

    if (t.matches('[data-viewprofile]')) {
        viewProfile(t.getAttribute('data-viewprofile'));
        return;
    }

    if (t.matches('[data-delete]')) {
        e.stopPropagation();
        deleteMessage(t.getAttribute('data-delete'));
        return;
    }

    if (t.matches('[data-sendreq]')) {
        sendFriendReqTo(t.getAttribute('data-sendreq'));
        return;
    }

    if (t.matches('[data-call]')) {
        const u = t.getAttribute('data-call');
        if (typeof startCall === 'function') startCall(u);
        closeModal('#userProfileOverlay');
        return;
    }

    if (t.matches('[data-close-profile]')) {
        closeModal('#userProfileOverlay');
        return;
    }
});

// Привязка кнопок
document.addEventListener('DOMContentLoaded', () => {
    const sb = $('#sendBtn');
    const bb = $('#backBtn');
    const mi = $('#msgInput');
    const tnb = $('#toggleNotifBtn');
    const cnb = $('#closeNotifBtn');

    if (sb) sb.addEventListener('click', sendMsg);
    if (bb) bb.addEventListener('click', goBack);
    if (mi) {
        mi.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendMsg(); });
        mi.addEventListener('input', () => {
            if (window.currentRoom.startsWith('dm_') && window.myData) {
                socket.emit('typing', { room: window.currentRoom, username: window.myData.username, user: window.myData.display_name });
            }
        });
    }
    if (tnb) tnb.addEventListener('click', () => {
        const np = $('#notifPanel');
        if (!np) return;
        if (np.classList.contains('open')) { np.classList.remove('open'); } else { if (typeof renderNotifications === 'function') renderNotifications();
            np.classList.add('open'); }
    });
    if (cnb) cnb.addEventListener('click', () => { const np = $('#notifPanel'); if (np) np.classList.remove('open'); });
});

// Socket events
socket.on('message', (m) => {
    let mr = m.room || '';
    let myR = window.currentRoom || '';
    if (mr.startsWith('dm_')) { const p = mr.split('_'); if (p.length >= 3) { const s = [p[1], p[2]].sort();
            mr = 'dm_' + s[0] + '_' + s[1]; } }
    if (myR.startsWith('dm_')) { const p = myR.split('_'); if (p.length >= 3) { const s = [p[1], p[2]].sort();
            myR = 'dm_' + s[0] + '_' + s[1]; } }
    if (mr === myR) renderMessage(m);
});

socket.on('history', (h) => {
    const mc = $('#messages');
    if (!mc) return;
    mc.innerHTML = '';
    if (!h || h.length === 0) {
        mc.innerHTML = '<div class="empty-chat"><div class="empty-chat-icon">💬</div><div>Нет сообщений</div></div>';
    } else {
        h.forEach(m => renderMessage(m));
    }
});

socket.on('message_deleted', () => { socket.emit('join', { room: window.currentRoom }); });

socket.on('messages_read', (data) => {
    socket.emit('join', { room: window.currentRoom });
    if (data.by !== window.myData.username) {
        $$('.msg.my .msg-bubble span').forEach(el => {
            if (el.textContent.trim() === '✓') {
                el.innerHTML = '✓✓';
                el.style.color = '#38bdf8';
                el.style.fontWeight = 'bold';
            }
        });
    }
});

socket.on('user_typing', (d) => {
    const ch = $('#chatHeader');
    if (ch) ch.textContent = '💬 @' + window.dmUser + ' (печатает...)';
    clearTimeout(window.typingTimer);
    window.typingTimer = setTimeout(() => { if (ch) ch.textContent = '💬 @' + window.dmUser; }, 1000);
});

socket.on('new_dm', (data) => {
    const notif = { type: 'new_message', from: data.from, text: data.text, timestamp: Date.now() / 1000, read: false };
    window.notifications.unshift(notif);
    updateBadge();
    showToast('💬 @' + data.from + ': ' + data.text, 'info');
});

// User profile modal
socket.on('user_profile', (d) => {
    if (d.error) { showToast(d.error, 'error'); return; }
    const u = d.user;
    const isF = window.myData.friends && window.myData.friends.includes(d.username);
    const isR = window.myData.requests && window.myData.requests.includes(d.username);
    const isBy = u.requests && u.requests.includes(window.myData.username);
    const rn = { 'owner': '👑 Владелец', 'admin': '🛡️ Админ', 'moderator': '🛡️ Модер', 'user': '👤 Пользователь' };
    const rc = u.role === 'owner' ? 'color:#f59e0b;' : u.role === 'admin' ? 'color:#ef4444;' : u.role === 'moderator' ? 'color:#10b981;' : 'color:#94a3b8;';
    const ls = u.last_seen ? new Date(u.last_seen * 1000) : null;
    const st = u.online ? '🟢 Онлайн' : (ls ? 'Был(а) ' + timeAgo(ls) : '');
    let h = '<h2>👤 Профиль</h2>';
    h += '<img src="' + escapeHtml(u.avatar || '') + '" class="avatar-large" alt="Аватар">';
    h += '<div style="text-align:center;font-size:1.2rem;font-weight:700;">' + escapeHtml(u.display_name) + '</div>';
    h += '<div style="text-align:center;color:var(--text-secondary);">@' + escapeHtml(d.username) + '</div>';
    h += '<div style="text-align:center;font-weight:600;' + rc + '">' + (rn[u.role] || '👤 Пользователь') + '</div>';
    h += '<div style="text-align:center;font-size:0.75rem;color:var(--text-secondary);margin-top:4px;">' + st + '</div>';
    if (u.dnd) h += '<div style="text-align:center;color:#f59e0b;margin-top:2px;">🔕 Не беспокоить</div>';
    h += '<div style="text-align:center;margin:10px 0;padding:8px;background:var(--surface);border-radius:8px;">' + escapeHtml(u.bio || '') + '</div>';
    h += '<div style="display:flex;gap:20px;justify-content:center;margin:10px 0;color:var(--text-secondary);font-size:0.85rem;"><span>Друзей: ' + (u.friends ? u.friends.length : 0) + '</span></div>';
    if (!isF && !isBy && !isR) h += '<button class="btn btn-primary" data-sendreq="' + d.username + '">📨 Добавить в друзья</button>';
    else if (isR) h += '<button class="btn btn-primary" data-accept="' + d.username + '">✓ Принять запрос</button>';
    else if (isBy) h += '<button class="btn btn-secondary" disabled>⏳ Запрос отправлен</button>';
    else if (isF) h += '<button class="btn btn-primary" data-dm="' + d.username + '">💬 Написать</button>';
    h += '<button class="btn btn-primary" data-call="' + d.username + '">📞 Позвонить</button>';
    h += '<button class="btn btn-secondary" data-close-profile>Закрыть</button>';
    const ucc = $('#userProfileContent');
    if (ucc) ucc.innerHTML = h;
    openModal('#userProfileOverlay');
});

// Notifications
function renderNotifications() {
    const nl = $('#notifList');
    if (!nl) return;
    const reqs = (window.myData && window.myData.requests || []).map(u => ({ type: 'friend_request', from: u, text: '@' + u + ' хочет добавить вас в друзья', timestamp: Date.now() / 1000 }));
    const all = reqs.concat(window.notifications);
    if (all.length === 0) { nl.innerHTML = '<div style="padding:30px;text-align:center;color:var(--text-secondary);">Нет уведомлений</div>'; return; }
    nl.innerHTML = all.map(n => {
        let btns = '';
        if (n.type === 'friend_request') btns = '<div class="notif-actions"><button class="btn-sm primary" data-accept="' + escapeHtml(n.from) + '">✓ Принять</button><button class="btn-sm danger" data-decline="' + escapeHtml(n.from) + '">✕ Отклонить</button></div>';
        const notifText = n.type === 'new_message' ? '💬 @' + n.from + ': ' + n.text : n.text;
        const onClick = n.type === 'new_message' ? ' data-dm="' + escapeHtml(n.from) + '" style="cursor:pointer;"' : '';
        return '<div class="notif-item"' + onClick + '><div class="notif-text">' + escapeHtml(notifText) + '</div><div class="notif-time">' + new Date(n.timestamp * 1000).toLocaleString() + '</div>' + btns + '</div>';
    }).join('');
}

document.addEventListener('click', (e) => {
    if (e.target.matches('[data-decline]')) {
        e.stopPropagation();
        const u = e.target.getAttribute('data-decline');
        socket.emit('decline_friend', { my_username: window.myData.username, target_username: u });
        const np = $('#notifPanel');
        if (np) np.classList.remove('open');
    }
});
