// theme.js — тёмная/светлая тема
const THEME_KEY = 'cat_theme';

function applyTheme(theme) {
    const html = document.documentElement;
    if (theme === 'light') {
        html.classList.add('light-theme');
    } else {
        html.classList.remove('light-theme');
    }
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
        meta.content = theme === 'light' ? '#ffffff' : '#090c12';
    }
}

function toggleTheme() {
    const current = localStorage.getItem(THEME_KEY) || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
}

function loadTheme() {
    const saved = localStorage.getItem(THEME_KEY) || 'dark';
    applyTheme(saved);
}

loadTheme();
