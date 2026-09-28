import { api, applyTheme, el, getTheme, run, state, THEMES, toast } from './api.js';

export async function render(root) {
    const current = el('input', { type: 'password', autocomplete: 'current-password', required: true });
    const next = el('input', { type: 'password', autocomplete: 'new-password', required: true, minlength: 8 });
    const repeat = el('input', { type: 'password', autocomplete: 'new-password', required: true });
    const save = el('button', { class: 'btn', type: 'submit' }, 'Change password');
    const form = el('form', { onsubmit: e => {
        e.preventDefault();
        if (next.value !== repeat.value) { toast('The new passwords do not match', { error: true }); return; }
        run(save, async () => {
            await api('/auth/password', { method: 'POST', body: { current_password: current.value, new_password: next.value } });
            form.reset();
            toast('Password changed');
        });
    } },
    el('div', { class: 'form-group' }, el('label', {}, 'Current password'), current),
    el('div', { class: 'form-group' }, el('label', {}, 'New password (min. 8 characters)'), next),
    el('div', { class: 'form-group' }, el('label', {}, 'Repeat new password'), repeat),
    save);

    const themeBox = el('div', { class: 'row' });
    const renderThemes = () => {
        themeBox.replaceChildren(...THEMES.map(([id, name, desc]) => el('button', {
            class: `chip ${getTheme() === id ? 'active' : ''}`,
            title: desc,
            onclick: () => { applyTheme(id); renderThemes(); },
        }, name)));
    };
    renderThemes();

    root.append(el('div', { class: 'card' },
        el('h2', {}, 'Appearance'),
        el('p', { class: 'muted', style: { marginBottom: '12px' } }, 'Pick a style. It is saved in this browser.'),
        themeBox));
    root.append(el('div', { class: 'grid-2' },
        el('div', { class: 'card' }, el('h2', {}, `Account: ${state.user.username}`), form),
        el('div', { class: 'card' },
            el('h2', {}, 'Your data'),
            el('p', { class: 'muted', style: { marginBottom: '16px' } },
                'Download a full backup of your accounts, categories, rules, budgets and transactions as JSON, ',
                'or export transactions for a spreadsheet.'),
            el('div', { class: 'row' },
                el('a', { class: 'btn', href: '/api/export/json' }, 'Download JSON backup'),
                el('a', { class: 'btn-light', href: '/api/export/xlsx' }, 'All transactions (Excel)'),
                el('a', { class: 'btn-light', href: '/api/export/csv' }, 'All transactions (CSV)')))));
}
