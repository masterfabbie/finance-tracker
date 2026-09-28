import { api, clear, el, loadRefs, run, showError, state } from './api.js';
import * as dashboard from './dashboard.js';
import * as transactions from './transactions.js';
import * as importer from './import.js';
import * as accounts from './accounts.js';
import * as categories from './categories.js';
import * as budgets from './budgets.js';
import * as recurring from './recurring.js';
import * as settings from './settings.js';
import * as admin from './admin.js';

const routes = { dashboard, transactions, import: importer, accounts, categories, budgets, recurring, settings, admin };
const view = document.getElementById('view');

async function render() {
    const name = (location.hash.replace(/^#\/?/, '').split('?')[0]) || 'dashboard';
    const page = routes[name] || dashboard;
    document.querySelectorAll('nav.tabs a').forEach(a => a.classList.toggle('active', a.dataset.route === name));
    clear(view);
    try {
        await page.render(view);
    } catch (e) {
        showError(e);
    }
}

function showLogin(allowRegistration) {
    document.getElementById('nav').classList.add('hidden');
    document.getElementById('userBox').classList.add('hidden');
    clear(view);
    let registering = false;
    const username = el('input', { id: 'username', autocomplete: 'username', required: true });
    const password = el('input', { id: 'password', type: 'password', autocomplete: 'current-password', required: true });
    const status = el('div', { class: 'status error hidden' });
    const submit = el('button', { class: 'btn', type: 'submit', style: { width: '100%' } }, 'Log in');
    const toggle = allowRegistration
        ? el('p', { class: 'muted', style: { textAlign: 'center', marginTop: '14px' } },
            el('a', { href: '#', onclick: e => {
                e.preventDefault();
                registering = !registering;
                submit.textContent = registering ? 'Create account' : 'Log in';
                e.target.textContent = registering ? 'I already have an account' : 'Create an account';
            } }, 'Create an account'))
        : null;
    const form = el('form', {
        onsubmit: e => {
            e.preventDefault();
            status.classList.add('hidden');
            run(submit, async () => {
                try {
                    await api(registering ? '/auth/register' : '/auth/login', {
                        method: 'POST', body: { username: username.value.trim(), password: password.value },
                    });
                } catch (err) {
                    status.textContent = err.message;
                    status.classList.remove('hidden');
                    return;
                }
                await start();
            });
        },
    },
    el('div', { class: 'form-group' }, el('label', { for: 'username' }, 'Username'), username),
    el('div', { class: 'form-group' }, el('label', { for: 'password' }, 'Password'), password),
    submit, status, toggle);
    view.append(el('div', { class: 'card login-box' }, el('h1', {}, 'Welcome back'), form));
    username.focus();
}

async function start() {
    try {
        state.user = await api('/auth/me');
    } catch {
        const cfg = await api('/auth/config').catch(() => ({ allow_registration: false }));
        showLogin(cfg.allow_registration);
        return;
    }
    await loadRefs();
    document.getElementById('nav').classList.remove('hidden');
    document.getElementById('userBox').classList.remove('hidden');
    document.getElementById('userName').textContent = `👤 ${state.user.username}`;
    document.getElementById('adminTab').classList.toggle('hidden', !state.user.is_admin);
    await render();
}

window.addEventListener('hashchange', () => { if (state.user) render(); });
window.addEventListener('ft:unauthorized', () => { state.user = null; start(); });
document.getElementById('logoutLink').addEventListener('click', async e => {
    e.preventDefault();
    await api('/auth/logout', { method: 'POST' }).catch(() => {});
    state.user = null;
    location.hash = '';
    start();
});

start();
