import { api, clear, confirmDialog, el, modal, run, state, toast } from './api.js';

export async function render(root) {
    if (!state.user.is_admin) {
        root.append(el('p', { class: 'empty' }, 'Admins only.'));
        return;
    }
    const list = el('div');
    root.append(el('div', { class: 'card' },
        el('div', { class: 'spread' }, el('h2', {}, 'Users'),
            el('button', { class: 'btn', onclick: () => createUser().then(ok => ok && load(list)) }, '+ Add user')),
        el('p', { class: 'muted small', style: { marginBottom: '12px' } }, 'Every user has their own private accounts, transactions and settings.'),
        list));
    await load(list);
}

async function load(list) {
    const users = await api('/admin/users');
    const patch = (u, body, msg) => e => run(e.currentTarget, async () => {
        await api(`/admin/users/${u.id}`, { method: 'PATCH', body });
        if (msg) toast(msg);
        load(list);
    });
    clear(list).append(el('table', { class: 'data' },
        el('thead', {}, el('tr', {}, ['User', 'Role', 'Status', 'Created', ''].map(h => el('th', {}, h)))),
        el('tbody', {}, users.map(u => {
            const self = u.id === state.user.id;
            return el('tr', {},
                el('td', {}, u.username, self ? el('span', { class: 'muted' }, ' (you)') : null),
                el('td', {}, u.is_admin ? 'Admin' : 'User'),
                el('td', { class: u.is_active ? '' : 'neg' }, u.is_active ? 'active' : 'deactivated'),
                el('td', {}, new Date(u.created_at).toLocaleDateString()),
                el('td', { class: 'num' }, self ? null : [
                    el('button', { class: 'btn-light btn-sm', onclick: patch(u, { is_admin: !u.is_admin }) }, u.is_admin ? 'Make user' : 'Make admin'), ' ',
                    el('button', { class: 'btn-light btn-sm', onclick: patch(u, { is_active: !u.is_active }) }, u.is_active ? 'Deactivate' : 'Activate'), ' ',
                    el('button', { class: 'btn-light btn-sm', onclick: () => resetPassword(u) }, 'Reset password'), ' ',
                    el('button', { class: 'btn-danger btn-sm', onclick: async e => {
                        const btn = e.currentTarget;
                        if (!await confirmDialog(`Delete user “${u.username}” and all of their data?`, { danger: true, confirmLabel: 'Delete', requireText: u.username })) return;
                        run(btn, async () => { await api(`/admin/users/${u.id}`, { method: 'DELETE' }); load(list); });
                    } }, 'Delete'),
                ]));
        }))));
}

function passwordForm(close, { withName }) {
    const username = withName ? el('input', { required: true, autocomplete: 'off' }) : null;
    const password = el('input', { type: 'text', required: true, minlength: 8, autocomplete: 'off' });
    const isAdmin = withName ? el('input', { type: 'checkbox' }) : null;
    const save = el('button', { class: 'btn', type: 'submit' }, 'Save');
    const form = el('form', {},
        withName ? el('div', { class: 'form-group' }, el('label', {}, 'Username'), username) : null,
        el('div', { class: 'form-group' }, el('label', {}, 'Password (min. 8 characters)'), password),
        withName ? el('div', { class: 'form-group' }, el('label', { class: 'inline-label' }, isAdmin, 'Administrator')) : null,
        el('div', { class: 'actions' }, el('button', { type: 'button', class: 'btn-light', onclick: () => close(false) }, 'Cancel'), save));
    return { form, username, password, isAdmin, save };
}

function createUser() {
    return modal('Add user', close => {
        const f = passwordForm(close, { withName: true });
        f.form.addEventListener('submit', e => {
            e.preventDefault();
            run(f.save, async () => {
                await api('/admin/users', { method: 'POST', body: { username: f.username.value.trim(), password: f.password.value, is_admin: f.isAdmin.checked } });
                close(true);
            });
        });
        return f.form;
    });
}

function resetPassword(u) {
    return modal(`New password for ${u.username}`, close => {
        const f = passwordForm(close, { withName: false });
        f.form.addEventListener('submit', e => {
            e.preventDefault();
            run(f.save, async () => {
                await api(`/admin/users/${u.id}`, { method: 'PATCH', body: { password: f.password.value } });
                toast('Password changed; the user has been logged out everywhere.');
                close(true);
            });
        });
        return f.form;
    });
}
