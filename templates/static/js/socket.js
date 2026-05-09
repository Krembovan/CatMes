// socket.js — подключение и глобальные переменные
const socket = io();

window.myData = null;
window.currentRoom = 'Общий';
window.notifications = [];
window.dmUser = null;
window.typingTimer = null;

// Глобальные события socket
socket.on('new_notification', (n) => {
    window.notifications.unshift(n);
    updateBadge();
    if (typeof showToast === 'function') showToast(n.text, 'info');
});

socket.on('friend_online', (d) => {
    const s = document.getElementById('status_' + d.username);
    if (s) {
        s.textContent = d.online ? '🟢 Онлайн' : '⚫ Оффлайн';
    }
});

socket.on('friend_avatar', (d) => {
    $$('.friend-avatar-' + d.username).forEach((i) => {
        i.src = d.avatar || 'https://api.dicebear.com/7.x/bottts-neutral/svg?seed=' + d.username;
    });
});
