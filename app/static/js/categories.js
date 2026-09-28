import {
    api, categoryById, categoryOptions, clear, confirmDialog, el, loadRefs, modal, options, run, state, toast,
} from './api.js';

const KINDS = [['expense', 'Expense'], ['income', 'Income'], ['transfer', 'Transfer (excluded from totals)']];
const FIELDS = [['payer', 'Payer / Payee'], ['description', 'Description'], ['iban', 'IBAN']];
const MATCHES = [['contains', 'contains'], ['equals', 'equals'], ['regex', 'matches regex']];
const SIGNS = [['any', 'Any amount'], ['expense', 'Expenses only'], ['income', 'Income only']];

export async function render(root) {
    const cats = el('div');
    const rules = el('div');
    root.append(el('div', { class: 'grid-2' },
        el('div', { class: 'card' },
            el('div', { class: 'spread' }, el('h2', {}, 'Categories'),
                el('button', { class: 'btn', onclick: () => editCategory(null).then(ok => ok && refresh()) }, '+ Add')),
            cats),
        el('div', { class: 'card' },
            el('div', { class: 'spread' }, el('h2', {}, 'Auto-categorization rules'),
                el('button', { class: 'btn', onclick: () => editRule(null).then(ok => ok && refresh()) }, '+ Add')),
            el('p', { class: 'muted small', style: { marginBottom: '12px' } },
                'Rules run on every import, top to bottom; the first match wins. Tip: change a category in the transaction list and ',
                'the app offers to create a rule for you.'),
            el('div', { class: 'row', style: { marginBottom: '14px' } },
                el('button', { class: 'btn-light btn-sm', onclick: e => rerun(e.currentTarget, false) }, 'Apply to uncategorized'),
                el('button', { class: 'btn-light btn-sm', onclick: e => rerun(e.currentTarget, true) }, 'Re-apply to all transactions')),
            rules)));

    async function refresh() {
        await loadRefs();
        renderCategories(cats, refresh);
        await renderRules(rules, refresh);
    }
    await refresh();
}

function rerun(btn, all) {
    run(btn, async () => {
        const r = await api('/rules/rerun', { method: 'POST', query: { all_transactions: all } });
        toast(`${r.updated} transactions updated`);
    });
}

function renderCategories(box, refresh) {
    clear(box).append(el('table', { class: 'data' }, el('tbody', {}, state.categories.map(c => el('tr', {},
        el('td', {}, el('span', { class: 'dot', style: { background: c.color, marginRight: '8px' } }), c.name),
        el('td', { class: 'muted small' }, c.kind),
        el('td', { class: 'num' },
            el('button', { class: 'btn-light btn-sm', onclick: () => editCategory(c).then(ok => ok && refresh()) }, 'Edit'), ' ',
            el('button', { class: 'btn-danger btn-sm', onclick: () => deleteCategory(c).then(ok => ok && refresh()) }, 'Delete')))))));
}

function editCategory(c) {
    return modal(c ? 'Edit category' : 'Add category', close => {
        const name = el('input', { required: true, value: c?.name || '' });
        const color = el('input', { type: 'color', value: c?.color || '#667eea' });
        const kind = el('select', {}, options(KINDS, c?.kind || 'expense'));
        const save = el('button', { class: 'btn', type: 'submit' }, 'Save');
        return el('form', { onsubmit: e => {
            e.preventDefault();
            run(save, async () => {
                const body = { name: name.value.trim(), color: color.value, kind: kind.value };
                await api(c ? `/categories/${c.id}` : '/categories', { method: c ? 'PUT' : 'POST', body });
                close(true);
            });
        } },
        el('div', { class: 'form-group' }, el('label', {}, 'Name'), name),
        el('div', { class: 'row form-group' }, el('div', {}, el('label', {}, 'Color'), color), el('div', { class: 'grow' }, el('label', {}, 'Kind'), kind)),
        el('div', { class: 'actions' }, el('button', { type: 'button', class: 'btn-light', onclick: () => close(false) }, 'Cancel'), save));
    });
}

function deleteCategory(c) {
    return modal(`Delete “${c.name}”`, close => {
        const moveTo = el('select', {}, options(state.categories.filter(x => x.id !== c.id).map(x => [x.id, x.name]), '', 'Leave uncategorized'));
        const del = el('button', { class: 'btn-danger' }, 'Delete');
        del.addEventListener('click', () => run(del, async () => {
            await api(`/categories/${c.id}`, { method: 'DELETE', query: { move_to: moveTo.value } });
            close(true);
        }));
        return el('div', {},
            el('div', { class: 'form-group' }, el('label', {}, 'Move its transactions to'), moveTo),
            el('p', { class: 'muted small' }, 'Rules and budgets for this category are deleted too.'),
            el('div', { class: 'actions' }, el('button', { class: 'btn-light', onclick: () => close(false) }, 'Cancel'), del));
    });
}

async function renderRules(box, refresh) {
    const rules = await api('/rules');
    clear(box);
    if (!rules.length) { box.append(el('p', { class: 'muted' }, 'No rules yet.')); return; }
    const label = (list, v) => (list.find(x => x[0] === v) || [v, v])[1];
    box.append(el('table', { class: 'data' }, el('tbody', {}, rules.map(r => {
        const cat = categoryById(r.category_id);
        return el('tr', {},
            el('td', { class: 'small' },
                `${label(FIELDS, r.field)} ${label(MATCHES, r.match)} `, el('strong', {}, `“${r.pattern}”`),
                r.amount_sign !== 'any' ? el('span', { class: 'muted' }, ` (${label(SIGNS, r.amount_sign).toLowerCase()})`) : null,
                ' → ', cat ? el('span', {}, el('span', { class: 'dot', style: { background: cat.color, margin: '0 4px' } }), cat.name) : '?',
                r.add_tags.length ? el('span', { class: 'muted' }, ` + tags: ${r.add_tags.join(', ')}`) : null),
            el('td', { class: 'num' },
                el('button', { class: 'btn-light btn-sm', onclick: () => editRule(r).then(ok => ok && refresh()) }, 'Edit'), ' ',
                el('button', { class: 'btn-danger btn-sm', onclick: async e => {
                    const btn = e.currentTarget;
                    if (await confirmDialog('Delete this rule?', { danger: true, confirmLabel: 'Delete' })) {
                        run(btn, async () => { await api(`/rules/${r.id}`, { method: 'DELETE' }); refresh(); });
                    }
                } }, '✕')));
    }))));
}

function editRule(r) {
    return modal(r ? 'Edit rule' : 'Add rule', close => {
        const field = el('select', {}, options(FIELDS, r?.field || 'payer'));
        const match = el('select', {}, options(MATCHES, r?.match || 'contains'));
        const pattern = el('input', { required: true, value: r?.pattern || '', placeholder: 'e.g. REWE' });
        const sign = el('select', {}, options(SIGNS, r?.amount_sign || 'any'));
        const category = el('select', { required: true }, categoryOptions(r?.category_id));
        const tags = el('input', { value: (r?.add_tags || []).join(', '), placeholder: 'optional, comma separated' });
        const priority = el('input', { type: 'number', value: r?.priority ?? 100 });
        const save = el('button', { class: 'btn', type: 'submit' }, 'Save');
        const g = (l, i) => el('div', { class: 'form-group' }, el('label', {}, l), i);
        return el('form', { onsubmit: e => {
            e.preventDefault();
            const body = {
                field: field.value, match: match.value, pattern: pattern.value.trim(), amount_sign: sign.value,
                category_id: Number(category.value), priority: Number(priority.value) || 100,
                add_tags: tags.value.split(',').map(t => t.trim().toLowerCase()).filter(Boolean),
            };
            run(save, async () => {
                await api(r ? `/rules/${r.id}` : '/rules', { method: r ? 'PUT' : 'POST', body });
                close(true);
            });
        } },
        el('div', { class: 'grid-2', style: { gap: '0 16px' } }, g('Field', field), g('Match', match)),
        g('Pattern (case-insensitive)', pattern),
        el('div', { class: 'grid-2', style: { gap: '0 16px' } }, g('Applies to', sign), g('Priority (lower runs first)', priority)),
        g('Set category', category),
        g('Add tags', tags),
        el('div', { class: 'actions' }, el('button', { type: 'button', class: 'btn-light', onclick: () => close(false) }, 'Cancel'), save));
    });
}
