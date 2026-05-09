// ui.js — общие утилиты
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function escapeHtml(t) {
    const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
    return String(t).replace(/[&<>"']/g, (c) => map[c]);
}

let toastTimer = null;
function showToast(m, type = 'success') {
    const toast = $('#toast');
    if (!toast) return;
    if (toastTimer) clearTimeout(toastTimer);
    toast.textContent = m;
    toast.className = 'toast ' + type + ' show';
    toastTimer = setTimeout(() => toast.classList.remove('show'), 3000);
}

function openModal(id) {
    const el = typeof id === 'string' ? $(id) : id;
    if (el) el.classList.add('active');
}

function closeModal(id) {
    const el = typeof id === 'string' ? $(id) : id;
    if (el) el.classList.remove('active');
}

function timeAgo(d) {
    const s = Math.floor((new Date() - d) / 1000);
    if (s < 60) return 'только что';
    if (s < 3600) return Math.floor(s / 60) + ' мин назад';
    if (s < 86400) return Math.floor(s / 3600) + ' ч назад';
    return Math.floor(s / 86400) + ' дн назад';
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        $$('.modal-overlay.active').forEach(el => closeModal(el));
        const notif = $('#notifPanel');
        if (notif && notif.classList.contains('open')) notif.classList.remove('open');
    }
});

document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay')) {
        closeModal(e.target);
    }
});
