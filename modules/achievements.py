ACHIEVEMENTS = {
    'first_msg': {'icon': '🐱', 'name': 'Первый мяу', 'desc': 'Отправить первое сообщение', 'xp': 25},
    'first_friend': {'icon': '🤝', 'name': 'Первый друг', 'desc': 'Добавить одного друга', 'xp': 25},
    'soul_company': {'icon': '🎉', 'name': 'Душа компании', 'desc': 'Иметь 5 друзей одновременно', 'xp': 50},
    'talkative': {'icon': '💬', 'name': 'Общительный', 'desc': 'Написать в общий канал', 'xp': 25},
    'daily_login': {'icon': '📅', 'name': 'Ежедневный вход', 'desc': 'Зайти в чат сегодня', 'xp': 25},
    'weekly_marathon': {'icon': '🔥', 'name': 'Недельный марафон', 'desc': 'Заходить 7 дней подряд', 'xp': 100},
    'bio': {'icon': '✏️', 'name': 'Биограф', 'desc': 'Заполнить описание профиля', 'xp': 25},
    'avatar': {'icon': '🖼️', 'name': 'Аватар', 'desc': 'Загрузить фото профиля', 'xp': 25},
    'first_spark': {'icon': '✨', 'name': 'Первый огонёк', 'desc': 'Отправить 10 сообщений подряд', 'xp': 10},
    'night_chatter': {'icon': '🌙', 'name': 'Ночной чатер', 'desc': 'Написать с 00:00 до 5:00', 'xp': 25},
    'friend_specialist': {'icon': '🤝', 'name': 'Специалист по связям', 'desc': 'Добавить 15 друзей', 'xp': 30},
    'media_master': {'icon': '📸', 'name': 'Медиа-мастер', 'desc': 'Отправить 10 фото за день', 'xp': 10},
    'sprinter': {'icon': '🏃', 'name': 'Спринтер', 'desc': 'Написать 100 сообщений за 24ч', 'xp': 20},
    'dictator': {'icon': '👑', 'name': 'Диктатор', 'desc': 'Получить роль модератора', 'xp': 150},
    'pioneer': {'icon': '🏆', 'name': 'Первопроходец', 'desc': 'Войти в первые 50 пользователей', 'xp': 300},
    'reaction': {'icon': '❤️', 'name': 'Сердцеед', 'desc': 'Поставить первую реакцию', 'xp': 10},
    'voice': {'icon': '🎤', 'name': 'Голос', 'desc': 'Отправить голосовое сообщение', 'xp': 25},
}


def award_achievement(db, Achievement, User, username, ach_id, socketio=None):
    user = User.query.filter_by(username=username).first()
    if not user or not user.verified:
        return
    existing = Achievement.query.filter_by(user_id=user.id, ach_id=ach_id).first()
    if existing:
        return
    ach_data = ACHIEVEMENTS.get(ach_id)
    if not ach_data:
        return
    achievement = Achievement(user_id=user.id, ach_id=ach_id)
    db.session.add(achievement)
    user.xp = min(user.xp + ach_data['xp'], 99999)
    db.session.commit()
    if socketio:
        socketio.emit('achievement_unlocked', {
            'ach_id': ach_id,
            'name': ach_data['name'],
            'xp': ach_data['xp'],
        }, room=f"user_{username}")
