import { api, centsToInput, clear, el, MONTHS, options, parseMoney, run, state, toast } from './api.js';
import { budgetBars } from './dashboard.js';

const now = new Date();
const sel = { year: now.getFullYear(), month: now.getMonth() + 1 };

export async function render(root) {
    const bars = el('div');
    const table = el('div');
    const yearSel = el('select', { onchange: () => { sel.year = Number(yearSel.value); load(); } },
        options(Array.from({ length: 6 }, (_, i) => now.getFullYear() - i), sel.year));
    const monthSel = el('select', { onchange: () => { sel.month = Number(monthSel.value); load(); } },
        options(MONTHS.map((m, i) => [i + 1, m]), sel.month));

    const category = el('select', {}, options(state.categories.filter(c => c.kind === 'expense').map(c => [c.id, c.name]), '', 'Choose category'));
    const limit = el('input', { inputmode: 'decimal', placeholder: 'Monthly limit in €' });
    const save = el('button', { class: 'btn', type: 'submit' }, 'Save budget');
    const form = el('form', { class: 'row', onsubmit: e => {
        e.preventDefault();
        const cents = parseMoney(limit.value);
        if (!category.value || Number.isNaN(cents) || cents <= 0) { toast('Choose a category and a positive limit', { error: true }); return; }
        run(save, async () => {
            await api('/budgets', { method: 'PUT', body: { category_id: Number(category.value), monthly_limit_cents: cents } });
            limit.value = '';
            load();
        });
    } }, el('div', { class: 'grow' }, category), el('div', { class: 'grow' }, limit), save);

    root.append(
        el('div', { class: 'card' },
            el('div', { class: 'spread' }, el('h2', {}, 'Budgets'), el('div', { class: 'row filters' }, monthSel, yearSel)),
            bars),
        el('div', { class: 'card' },
            el('h3', {}, 'Set a monthly budget'),
            el('p', { class: 'muted small', style: { marginBottom: '12px' } }, 'Saving a budget for a category that already has one updates its limit.'),
            form, table));

    async function load() {
        const budgets = await api('/budgets', { query: sel });
        clear(bars).append(...(budgets.length ? budgetBars(budgets) : [el('p', { class: 'muted' }, 'No budgets yet.')]));
        clear(table);
        if (budgets.length) {
            table.append(el('table', { class: 'data', style: { marginTop: '16px' } }, el('tbody', {}, budgets.map(b => el('tr', {},
                el('td', {}, el('span', { class: 'dot', style: { background: b.color, marginRight: '8px' } }), b.category),
                el('td', { class: 'num' }, centsToInput(b.limit) + ' €'),
                el('td', { class: 'num' },
                    el('button', { class: 'btn-light btn-sm', onclick: () => { category.value = String(b.category_id); limit.value = centsToInput(b.limit); limit.focus(); } }, 'Edit'), ' ',
                    el('button', { class: 'btn-danger btn-sm', onclick: e => run(e.currentTarget, async () => {
                        await api(`/budgets/${b.id}`, { method: 'DELETE' });
                        load();
                    }) }, '✕')))))));
        }
    }
    await load();
}
