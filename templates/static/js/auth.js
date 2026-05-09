// auth.js — логин, регистрация, сброс пароля

function updateBadge() {
    const badge = $('#notifBadge');
    if (!badge || !window.myData) return;
    const total = (window.myData.requests ? window.myData.requests.length : 0) +
        window.notifications.filter((n) => !n.read).length;
    if (total > 0) {
        badge.textContent = total;
        badge.classList.add('show');
    } else {
        badge.classList.remove('show');
    }
}

function updateMyInfo() {
    if (!window.myData) return;
    const mn = $('#myName');
    const mu = $('#myUsername');
    const ma = $('#myAvatar');
    const mr = $('#myRole');
    if (mn) mn.textContent = window.myData.display_name || window.myData.username;
    if (mu) mu.textContent = '@' + window.myData.username;
    if (ma) ma.src = window.myData.avatar || '';
    const roleNames = { 'owner': '👑 Владелец', 'admin': '🛡️ Админ', 'moderator': '🛡️ Модер', 'user': '👤 Пользователь' };
    if (mr) mr.textContent = roleNames[window.myData.role] || '';
}

function switchAuthForm(mode) {
    const lf = $('#loginForm');
    const rf = $('#registerForm');
    const resf = $('#resetForm');
    const ae = $('#authError');
    const re = $('#regError');
    const rese = $('#resetError');

    if (lf) lf.style.display = mode === 'login' ? 'block' : 'none';
    if (rf) rf.style.display = mode === 'register' ? 'block' : 'none';
    if (resf) resf.style.display = mode === 'reset' ? 'block' : 'none';
    if (ae) ae.textContent = '';
    if (re) re.textContent = '';
    if (rese) rese.textContent = '';

    if (mode === 'register' && $('#regUser')) { $('#regUser').value = '@';
        $('#regUser').focus(); }
    if (mode === 'login' && $('#loginUser')) $('#loginUser').focus();
    if (mode === 'reset' && $('#resetUser')) $('#resetUser').focus();
}

function handleLogin() {
    const u = $('#loginUser').value.trim();
    const p = $('#loginPass').value;
    const ae = $('#authError');
    if (ae) ae.textContent = '';
    if (!u || !p) { if (ae) ae.textContent = 'Заполните все поля'; return; }
    socket.emit('auth', { action: 'login', username: u, password: p });
}

function handleRegister() {
    const u = $('#regUser').value.trim();
    const n = $('#regName').value.trim();
    const s = $('#regSecret').value.trim();
    const p = $('#regPass').value;
    const p2 = $('#regPass2').value;
    const re = $('#regError');
    if (re) re.textContent = '';
    if (!u || !n || !s || !p || !p2) { if (re) re.textContent = 'Заполните все поля'; return; }
    if (u.length < 3) { if (re) re.textContent = 'Логин: минимум 3 символа'; return; }
    if (p.length < 4) { if (re) re.textContent = 'Пароль: минимум 4 символа'; return; }
    if (p !== p2) { if (re) re.textContent = 'Пароли не совпадают'; return; }
    socket.emit('auth', { action: 'register', username: u, display_name: n, password: p, password2: p2, secret: s });
}

function handleReset() {
    const u = $('#resetUser').value.trim();
    const s = $('#resetSecret').value.trim();
    const rese = $('#resetError');
    if (rese) rese.textContent = '';
    if (!u || !s) { if (rese) rese.textContent = 'Заполните все поля'; return; }
    socket.emit('reset_password', { username: u, secret: s });
}

socket.on('auth_result', (d) => {
    if (d.success) {
        window.myData = d.user;
        localStorage.setItem('cat_user', window.myData.username);
        localStorage.setItem('cat_pass', $('#loginPass').value || localStorage.getItem('cat_pass') || '');
        window.notifications = window.myData.notifications || [];
        const ao = $('#authOverlay');
        const ma = $('#mainApp');
        if (ao) ao.classList.remove('active');
        if (ma) ma.style.display = 'flex';
        updateMyInfo();
        updateBadge();
        if (typeof updateFriendList === 'function') updateFriendList();
        if (typeof updateRoomList === 'function') updateRoomList();
        if (typeof switchRoom === 'function') switchRoom('Общий');
    } else {
        const rf = $('#registerForm');
        const ae = $('#authError');
        const re = $('#regError');
        if (rf && rf.style.display !== 'none') {
            if (re) re.textContent = d.error;
        } else {
            if (ae) ae.textContent = d.error;
        }
    }
});

socket.on('reset_result', (d) => {
    const rese = $('#resetError');
    if (d.success) {
        if (rese) rese.textContent = '';
        showToast(d.message, 'success');
        // Показать пароль в отдельном поле
        if (rese) rese.innerHTML = '<span style="color:#10b981;">Новый пароль: <b>' + d.new_password + '</b>. Обязательно смените его в профиле!</span>';
    } else {
        if (rese) rese.textContent = d.error;
    }
});

// Привязка обработчиков после загрузки DOM
document.addEventListener('DOMContentLoaded', () => {
    const lb = $('#loginBtn');
    const rb = $('#registerBtn');
    const resb = $('#resetBtn');
    const sr = $('#switchToRegister');
    const sl = $('#switchToLogin');
    const sres = $('#switchToReset');
    const slr = $('#switchToLoginFromReset');

    if (lb) lb.addEventListener('click', handleLogin);
    if (rb) rb.addEventListener('click', handleRegister);
    if (resb) resb.addEventListener('click', handleReset);
    if (sr) sr.addEventListener('click', () => switchAuthForm('register'));
    if (sl) sl.addEventListener('click', () => switchAuthForm('login'));
    if (sres) sres.addEventListener('click', () => switchAuthForm('reset'));
    if (slr) slr.addEventListener('click', () => switchAuthForm('login'));

    const lp = $('#loginPass');
    const rp2 = $('#regPass2');
    if (lp) lp.addEventListener('keypress', (e) => { if (e.key === 'Enter') handleLogin(); });
    if (rp2) rp2.addEventListener('keypress', (e) => { if (e.key === 'Enter') handleRegister(); });

    const ru = $('#regUser');
    if (ru) ru.addEventListener('input', function() { if (!this.value.startsWith('@')) this.value = '@' + this.value.replace(/@/g, ''); });

    // Авто-логин
    const savedUser = localStorage.getItem('cat_user');
    const savedPass = localStorage.getItem('cat_pass');
    if (savedUser && savedPass) {
        socket.emit('auth', { action: 'login', username: savedUser, password: savedPass });
    }
});

function logout() {
    localStorage.removeItem('cat_user');
    localStorage.removeItem('cat_pass');
    window.myData = null;
    window.dmUser = null;
    window.notifications = [];
    window.currentRoom = 'Общий';
    const ma = $('#mainApp');
    const ao = $('#authOverlay');
    const mc = $('#messages');
    if (ma) ma.style.display = 'none';
    if (ao) ao.classList.add('active');
    if (mc) mc.innerHTML = '<div class="empty-chat"><div class="empty-chat-icon">💬</div><div>Выберите чат</div></div>';
    closeModal('#profileOverlay');
    switchAuthForm('login');
}
