// profile.js — профиль, смена username, DND

function loadProfile() {
    if (!window.myData) return;
    const pn = $('#profileName');
    const pu = $('#profileUser');
    const pb = $('#profileBio');
    const pa = $('#profileAvatarUrl');
    const pav = $('#profileAvatar');
    const pnu = $('#profileNewUser');
    const ppc = $('#profilePassForChange');
    const uce = $('#usernameChangeError');

    if (pn) pn.value = window.myData.display_name || '';
    if (pu) pu.value = '@' + window.myData.username;
    if (pb) pb.value = window.myData.bio || '';
    if (pa) pa.value = window.myData.avatar || '';
    if (pav) pav.src = window.myData.avatar || '';
    if (pnu) pnu.value = '';
    if (ppc) ppc.value = '';
    if (uce) uce.textContent = '';
    updateDndButton();
}

function updateDndButton() {
    const dnd = window.myData && window.myData.dnd;
    const btn = $('#toggleDndBtn');
    const badge = $('#myDndBadge');
    if (btn) btn.textContent = dnd ? '🔕 Выключить' : '🔔 Включить';
    if (badge) badge.style.display = dnd ? 'block' : 'none';
}

function saveProfile() {
    const n = $('#profileName').value.trim();
    const b = $('#profileBio').value.trim();
    const a = $('#profileAvatarUrl').value.trim();
    const newUsername = $('#profileNewUser').value.trim();
    const passForChange = $('#profilePassForChange').value;
    const uce = $('#usernameChangeError');

    if (!n) { showToast('Имя обязательно', 'error'); return; }

    if (newUsername && newUsername !== window.myData.username) {
        if (!passForChange) {
            if (uce) uce.textContent = 'Введите пароль для смены username';
            return;
        }
        socket.emit('change_username', {
            old_username: window.myData.username,
            new_username: newUsername,
            password: passForChange
        });
        return;
    }

    socket.emit('update_profile', { username: window.myData.username, display_name: n, bio: b, avatar: a });
}

// Привязка событий
document.addEventListener('DOMContentLoaded', () => {
    const opb = $('#openProfileBtn');
    const pmb = $('#profileMiniBtn');
    const spb = $('#saveProfileBtn');
    const cpb = $('#cancelProfileBtn');
    const lob = $('#logoutBtn');
    const tdb = $('#toggleDndBtn');
    const ttb = $('#toggleThemeBtn');

    if (opb) opb.addEventListener('click', () => { openModal('#profileOverlay');
        loadProfile(); });
    if (pmb) pmb.addEventListener('click', () => { openModal('#profileOverlay');
        loadProfile(); });
    if (spb) spb.addEventListener('click', saveProfile);
    if (cpb) cpb.addEventListener('click', () => closeModal('#profileOverlay'));
    if (lob) lob.addEventListener('click', logout);
    if (tdb) tdb.addEventListener('click', () => socket.emit('toggle_dnd', { username: window.myData && window.myData
            .username }));
    if (ttb) ttb.addEventListener('click', toggleTheme);
});

socket.on('dnd_updated', (d) => {
    if (window.myData) {
        window.myData.dnd = d.dnd;
        updateDndButton();
        showToast(d.dnd ? '🔕 Не беспокоить включён' : '🔔 Уведомления включены', 'info');
    }
});

socket.on('username_change_result', (d) => {
    if (d.success) {
        localStorage.setItem('cat_user', d.new_username);
        if (window.myData) window.myData.username = d.new_username;
        updateMyInfo();
        const pu = $('#profileUser');
        const pnu = $('#profileNewUser');
        const ppc = $('#profilePassForChange');
        if (pu) pu.value = '@' + d.new_username;
        if (pnu) pnu.value = '';
        if (ppc) ppc.value = '';
        showToast('Username изменён на @' + d.new_username, 'success');
    } else {
        const uce = $('#usernameChangeError');
        if (uce) uce.textContent = d.error;
    }
});

socket.on('friend_username_changed', (d) => {
    if (typeof updateFriendList === 'function') updateFriendList();
    showToast('@' + d.old + ' сменил username на @' + d.new, 'info');
});

socket.on('profile_updated', (d) => {
    window.myData = d.user;
    updateMyInfo();
    showToast('Профиль обновлён!', 'success');
    closeModal('#profileOverlay');
});
