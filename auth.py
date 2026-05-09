"""
auth.py — Модуль аутентификации и авторизации CAT.
Обрабатывает:
- Регистрацию / вход / выход
- Хеширование паролей (PBKDF2-SHA256)
- Роли и права доступа
- Защиту от brute-force (rate limiting)
- Сессии пользователей
"""

import time
import hashlib
import secrets
import sqlite3
from threading import Lock
from functools import wraps

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================
# Максимальное число неверных попыток входа за период
MAX_LOGIN_ATTEMPTS = 5
LOGIN_ATTEMPT_WINDOW = 300  # 5 минут
LOGIN_LOCKOUT_DURATION = 600  # 10 минут блокировки

# Роли по умолчанию для владельцев/админов (username -> role)
DEFAULT_ROLES = {
    'krembovan': 'owner'
}

# Иерархия ролей (кто кого может назначать/удалять)
ROLE_HIERARCHY = {
    'owner': 100,
    'admin': 80,
    'moderator': 50,
    'user': 0
}

# ============================================================
# ХЕШИРОВАНИЕ ПАРОЛЕЙ
# ============================================================
def hash_password(password: str) -> str:
    """
    PBKDF2-SHA256 с автоматической генерацией соли.
    Формат хеша: pbkdf2:sha256:100000$<hex-salt>$<hex-hash>
    """
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    return f"pbkdf2:sha256:100000${salt}${h.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """Проверить пароль против сохранённого хеша."""
    if not hashed or not hashed.startswith('pbkdf2:'):
        # Поддержка старых plaintext паролей (на время миграции)
        return password == hashed

    try:
        _, iterations_str, rest = hashed.split('$', 2)
        algo, _, iterations = iterations_str.split(':')
        salt, stored_hash = rest.split('$')

        h = hashlib.pbkdf2_hmac(
            algo,
            password.encode('utf-8'),
            salt.encode('utf-8'),
            int(iterations)
        )
        return h.hex() == stored_hash
    except (ValueError, AttributeError):
        return False


def needs_password_rehash(hashed: str) -> bool:
    """Проверить, нужно ли перехешировать пароль (для будущих апгрейдов)."""
    if not hashed or not hashed.startswith('pbkdf2:'):
        return True
    return False


# ============================================================
# ВАЛИДАЦИЯ
# ============================================================
def validate_username(username: str) -> tuple[bool, str]:
    """
    Проверить username на корректность.
    Возвращает (валиден?, сообщение_об_ошибке).
    """
    if not username:
        return False, 'Username обязателен'

    # Убираем @ в начале (на клиенте он добавляется)
    username = username.lstrip('@').strip().lower()

    if len(username) < 3:
        return False, 'Логин: минимум 3 символа'
    if len(username) > 20:
        return False, 'Логин: максимум 20 символов'
    if not username.replace('_', '').replace('.', '').isalnum():
        return False, 'Логин: только буквы, цифры, _ и .'

    return True, username


def validate_password(password: str) -> tuple[bool, str]:
    """
    Проверить пароль на минимальные требования.
    Возвращает (валиден?, сообщение_об_ошибке).
    """
    if not password:
        return False, 'Пароль обязателен'
    if len(password) < 4:
        return False, 'Пароль: минимум 4 символа'
    if len(password) > 128:
        return False, 'Пароль: максимум 128 символов'
    return True, password


def validate_display_name(name: str) -> tuple[bool, str]:
    """Проверить отображаемое имя."""
    if not name or not name.strip():
        return False, 'Имя обязательно'
    name = name.strip()
    if len(name) > 50:
        return False, 'Имя: максимум 50 символов'
    return True, name


# ============================================================
# УПРАВЛЕНИЕ РОЛЯМИ
# ============================================================
def get_role(username: str, saved_role: str = 'user') -> str:
    """
    Получить роль пользователя.
    Приоритет: DEFAULT_ROLES > сохранённая в БД роль.
    
    Args:
        username: имя пользователя в нижнем регистре
        saved_role: роль из базы данных
    
    Returns:
        'owner' | 'admin' | 'moderator' | 'user'
    """
    # Жёстко заданные роли имеют приоритет
    if username in DEFAULT_ROLES:
        return DEFAULT_ROLES[username]
    return saved_role if saved_role in ROLE_HIERARCHY else 'user'


def can_manage_role(actor_role: str, target_role: str) -> bool:
    """
    Может ли пользователь с ролью actor_role управлять target_role?
    Владелец может всё. Админ не может трогать владельца.
    """
    if actor_role == 'owner':
        return True
    if target_role == 'owner':
        return False
    return ROLE_HIERARCHY.get(actor_role, 0) > ROLE_HIERARCHY.get(target_role, 0)


def can_delete_message(role: str) -> bool:
    """Может ли роль удалять сообщения?"""
    return role in ['owner', 'admin', 'moderator']


def can_access_admin(role: str) -> bool:
    """Может ли роль заходить в админ-панель?"""
    return role in ['owner', 'admin', 'moderator']


def get_role_display(role: str) -> str:
    """Человекочитаемое название роли."""
    return {
        'owner': '👑 Владелец',
        'admin': '🛡️ Админ',
        'moderator': '🛡️ Модер',
        'user': '👤 Пользователь'
    }.get(role, '👤 Пользователь')


# ============================================================
# ЗАЩИТА ОТ BRUTE-FORCE
# ============================================================
# В памяти храним попытки входа: {username: [(timestamp, success), ...]}
_login_attempts = {}
_login_attempts_lock = Lock()


def check_login_rate_limit(username: str) -> tuple[bool, str]:
    """
    Проверить, не заблокирован ли вход для пользователя.
    Возвращает (разрешён?, сообщение).
    """
    with _login_attempts_lock:
        now = time.time()
        attempts = _login_attempts.get(username, [])

        # Очищаем старые попытки
        attempts = [a for a in attempts if a[0] > now - LOGIN_ATTEMPT_WINDOW]

        # Считаем недавние неудачные попытки
        recent_failures = [a for a in attempts if not a[1]]

        # Проверяем блокировку
        if len(recent_failures) >= MAX_LOGIN_ATTEMPTS:
            oldest_failure = recent_failures[0][0]
            lockout_remaining = LOGIN_LOCKOUT_DURATION - (now - oldest_failure)
            if lockout_remaining > 0:
                minutes = int(lockout_remaining / 60) + 1
                return False, f'Слишком много попыток. Попробуйте через {minutes} мин.'

            # Блокировка истекла — сбрасываем
            attempts = []
            recent_failures = []

        _login_attempts[username] = attempts
        return True, ''


def record_login_attempt(username: str, success: bool):
    """Записать попытку входа."""
    with _login_attempts_lock:
        now = time.time()
        if username not in _login_attempts:
            _login_attempts[username] = []
        _login_attempts[username].append((now, success))

        # Очистка старых записей (раз в 100 попыток)
        if len(_login_attempts) > 100:
            cutoff = now - max(LOGIN_ATTEMPT_WINDOW, LOGIN_LOCKOUT_DURATION)
            for uname in list(_login_attempts.keys()):
                _login_attempts[uname] = [
                    a for a in _login_attempts[uname] if a[0] > cutoff
                ]


# ============================================================
# ДЕКОРАТОР ДЛЯ ПРОВЕРКИ ПРАВ
# ============================================================
def require_role(min_role: str):
    """
    Декоратор для Socket.IO обработчиков.
    Проверяет, что у пользователя есть нужная роль.
    
    Использование:
        @socketio.on('admin_action')
        @require_role('admin')
        def handle_admin(data):
            ...
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Извлекаем username из первого аргумента (обычно data)
            data = args[0] if args else {}
            username = data.get('username', '').lower() if isinstance(data, dict) else ''

            # Для Flask-маршрутов проверяем request
            from flask import request as flask_request
            if hasattr(flask_request, 'authorization') and flask_request.authorization:
                username = flask_request.authorization.username.lower()

            user_data = None
            # Пытаемся получить роль из БД
            try:
                from app import get_user
                user_data = get_user(username)
            except:
                pass

            saved_role = user_data.get('role', 'user') if user_data else 'user'
            role = get_role(username, saved_role)

            if ROLE_HIERARCHY.get(role, 0) < ROLE_HIERARCHY.get(min_role, 0):
                from flask_socketio import emit
                emit('error_msg', {'text': 'Недостаточно прав'})
                return

            return func(*args, **kwargs)

        return wrapper

    return decorator


# ============================================================
# СЕССИИ ПОЛЬЗОВАТЕЛЕЙ
# ============================================================
user_sessions = {}  # username -> socket.sid
sessions_lock = Lock()


def set_session(username: str, sid: str):
    """Привязать Socket.IO сессию к пользователю."""
    with sessions_lock:
        user_sessions[username] = sid


def remove_session(sid: str) -> str | None:
    """
    Удалить сессию по socket.sid.
    Возвращает username, если сессия была.
    """
    with sessions_lock:
        for username, existing_sid in list(user_sessions.items()):
            if existing_sid == sid:
                del user_sessions[username]
                return username
    return None


def get_session_sid(username: str) -> str | None:
    """Получить sid пользователя, если он онлайн."""
    with sessions_lock:
        return user_sessions.get(username)


def is_online(username: str) -> bool:
    """Проверить, онлайн ли пользователь."""
    with sessions_lock:
        return username in user_sessions


def get_online_users() -> list:
    """Получить список пользователей онлайн."""
    with sessions_lock:
        return list(user_sessions.keys())


# ============================================================
# ЭКСПОРТ
# ============================================================
__all__ = [
    # Хеширование
    'hash_password',
    'verify_password',
    'needs_password_rehash',

    # Валидация
    'validate_username',
    'validate_password',
    'validate_display_name',

    # Роли
    'get_role',
    'can_manage_role',
    'can_delete_message',
    'can_access_admin',
    'get_role_display',
    'DEFAULT_ROLES',
    'ROLE_HIERARCHY',

    # Rate limiting
    'check_login_rate_limit',
    'record_login_attempt',

    # Сессии
    'set_session',
    'remove_session',
    'get_session_sid',
    'is_online',
    'get_online_users',
    'user_sessions',

    # Декоратор
    'require_role',
]