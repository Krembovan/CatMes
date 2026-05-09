// friends.js — друзья и избранное

function updateFriendList() {
    if (!window.myData) return;
    updateBadge();

    const pinned = window.myData.pinned || [];
    const friends = window.myData.friends || [];
    const requests = window.myData.requests || [];

    // Избранные
    let ph = '';
    pinned.forEach(u => { ph += renderFriendItem(u, true); });
    if (!ph) ph = '<div style="padding:10px;color:var(--text-secondary);font-size:0.7rem;">Нет избранных. Нажмите ⭐ у друга.</div>';
    const pl = $('#pinnedList');
    if (pl) pl.innerHTML = ph;

    // Запросы
    let rh = '';
    requests.forEach(u => {
        rh += `<div class="friend-item" style="border:1px dashed var(--primary);"><div class="chat-avatar">👤</div><span style="flex:1;">@${escapeHtml(u)}</span><button class="badge-accept" data-accept="${escapeHtml(u)}">✓ Принять</button></div>`;
    });

    // Друзья
    let fh = rh;
    friends.forEach(u => {
        if (!pinned.includes(u)) fh += renderFriendItem(u, false);
    });
    if (!fh) fh = '<div style="padding:10px;color:var(--text-secondary);font-size:0.8rem;">Нет друзей</div>';
    const fl = $('#friendList');
    if (fl) fl.innerHTML = fh;

    friends.forEach(u => {
        socket.emit('check_status', { username: u });
        socket.emit('get_avatar', { username: u });
    });
}

function renderFriendItem(u, isPinned) {
    const star = isPinned ? '⭐' : '☆';
    return `<div class="friend-item">
        <img class="chat-avatar friend-avatar-${u}" data-viewprofile="${escapeHtml(u)}" src="https://api.dicebear.com/7.x/bottts-neutral/svg?seed=${u}" style="object-fit:cover;border-radius:12px;width:38px;height:38px;" alt="Аватар ${escapeHtml(u)}">
        <span style="flex:1;" data-dm="${escapeHtml(u)}">
            <span style="font-weight:600;">@${escapeHtml(u)}</span>
            <span id="status_${u}" style="display:block;font-size:0.65rem;color:var(--text-secondary);"></span>
        </span>
        <span class="friend-remove-btn" data-pin="${escapeHtml(u)}" title="В избранное">${star}</span>
        <span class="friend-remove-btn" data-remove="${escapeHtml(u)}" title="Удалить">✕</span>
    </div>`;
}

function updateRoomList() {
    const rl = $('#roomList');
    if (rl) rl.innerHTML = '<div class="chat-item active" data-room="Общий"><div class="chat-avatar">🌍</div><span>Общий канал</span></div>';
}

// Делегирование событий
document.addEventListener('click', (e) => {
    const t = e.target;

    if (t.matches('[data-pin]')) {
        e.stopPropagation();
        const friend = t.getAttribute('data-pin');
        if (window.myData) socket.emit('toggle_pin_friend', { username: window.myData.username, friend });
        return;
    }

    if (t.matches('[data-accept]')) {
        e.stopPropagation();
        const u = t.getAttribute('data-accept');
        socket.emit('accept_friend', { my_username: window.myData.username, target_username: u });
        return;
    }

    if (t.matches('[data-remove]')) {
        e.stopPropagation();
        const u = t.getAttribute('data-remove');
        if (confirm('Удалить @' + u + ' из друзей?')) {
            socket.emit('remove_friend', { my_username: window.myData.username, target_username: u });
        }
        return;
    }
});

socket.on('pinned_updated', (d) => {
    if (window.myData) {
        window.myData.pinned = d.pinned;
        updateFriendList();
    }
});

socket.on('incoming_friend_request', (d) => {
    if (window.myData && d.user && d.user.username === window.myData.username) {
        window.myData = d.user;
        updateFriendList();
        updateBadge();
        showToast('@' + d.from + ' хочет добавить вас в друзья', 'info');
    }
});

socket.on('friend_accepted_notify', (d) => {
    if (window.myData && d.user && d.user.username === window.myData.username) {
        window.myData = d.user;
        updateFriendList();
        showToast('@' + d.by + ' принял ваш запрос', 'success');
    }
});

socket.on('friend_removed_notify', (d) => {
    if (window.myData && d.user && d.user.username === window.myData.username) {
        window.myData = d.user;
        updateFriendList();
        showToast('@' + d.by + ' удалил вас из друзей', 'info');
    }
});

// Friend search modal
document.addEventListener('DOMContentLoaded', () => {
    const ofb = $('#openFriendModalBtn');
    const sfb = $('#sendFriendReqBtn');
    const cfb = $('#cancelFriendBtn');
    const su = $('#searchUser');

    if (ofb) ofb.addEventListener('click', () => { if (su) su.value = '@'; const fe = $('#friendError'); if (fe) fe
            .textContent = '';
        openModal('#friendOverlay'); });
    if (sfb) sfb.addEventListener('click', () => {
        const t = su ? su.value.trim() : '';
        if (!t || t === '@') { const fe = $('#friendError'); if (fe) fe.textContent = 'Введите username'; return; }
        socket.emit('send_friend_request', { my_username: window.myData.username, target_username: t });
        closeModal('#friendOverlay');
    });
    if (cfb) cfb.addEventListener('click', () => closeModal('#friendOverlay'));
    if (su) {
        su.addEventListener('focus', function() { if (this.value === '') this.value = '@'; });
        su.addEventListener('input', function() { if (!this.value.startsWith('@')) this.value = '@' + this.value
                .replace(/@/g, ''); });
    }
});

socket.on('friend_msg', (d) => { showToast(d.text, d.type || 'info'); });
