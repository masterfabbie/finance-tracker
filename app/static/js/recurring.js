import { api, categoryById, clear, el, fmtDate, fmtMoney, run } from './api.js';

const INTERVALS = { 7: 'weekly', 14: 'every 2 weeks', 30: 'monthly', 91: 'quarterly', 182: 'half-yearly', 365: 'yearly' };

export async function render(root) {
    const box = el('div');
    const totals = el('div');
    root.append(el('div', { class: 'card' },
        el('div', { class: 'spread' }, el('h2', {}, 'Subscriptions & recurring payments'),
            el('button', { class: 'btn-light', onclick: e => run(e.currentTarget, async () => { await api('/recurring/scan', { method: 'POST' }); await load(); }) }, 'Scan again')),
        el('p', { class: 'muted small', style: { marginBottom: '16px' } },
            'Detected automatically after every import: payments to the same payee at a regular interval with a stable amount. ',
            'Confirm the ones that are right; dismissed ones are hidden and left out of the forecast.'),
        totals, box));

    async function load() {
        const series = await api('/recurring');
        clear(box);
        clear(totals);
        const active = series.filter(s => s.status !== 'dismissed');
        const monthlyOut = active.filter(s => s.typical_amount_cents < 0).reduce((a, s) => a + s.monthly_cost_cents, 0);
        const monthlyIn = active.filter(s => s.typical_amount_cents > 0).reduce((a, s) => a + s.monthly_cost_cents, 0);
        totals.append(el('div', { class: 'summary-grid', style: { marginBottom: '20px' } },
            el('div', { class: 'summary-card expense' }, el('h3', {}, 'Fixed costs / month'), el('div', { class: 'amount' }, fmtMoney(-monthlyOut)),
                el('div', { class: 'sub' }, `${fmtMoney(-monthlyOut * 12)} per year`)),
            el('div', { class: 'summary-card income' }, el('h3', {}, 'Recurring income / month'), el('div', { class: 'amount' }, fmtMoney(monthlyIn))),
            el('div', { class: 'summary-card balance' }, el('h3', {}, 'Left after fixed costs'), el('div', { class: 'amount' }, fmtMoney(monthlyIn + monthlyOut)))));

        if (!series.length) { box.append(el('p', { class: 'empty' }, 'Nothing detected yet. Import a few months of transactions first.')); return; }
        const sorted = [...series].sort((a, b) => (a.status === 'dismissed') - (b.status === 'dismissed') || a.next_date.localeCompare(b.next_date));
        box.append(el('div', { class: 'table-wrap', style: { maxHeight: 'none' } }, el('table', { class: 'data' },
            el('thead', {}, el('tr', {}, ['Payee', 'Category', 'Amount', 'Interval', 'Per month', 'Last', 'Next', 'Status', ''].map(h => el('th', {}, h)))),
            el('tbody', {}, sorted.map(s => {
                const cat = categoryById(s.category_id);
                const setStatus = status => e => run(e.currentTarget, async () => {
                    await api(`/recurring/${s.id}`, { method: 'PATCH', body: { status } });
                    await load();
                });
                return el('tr', { style: s.status === 'dismissed' ? { opacity: 0.5 } : null },
                    el('td', {}, s.display_name, el('div', { class: 'muted small' }, `${s.occurrences} payments`)),
                    el('td', {}, cat ? cat.name : ''),
                    el('td', { class: `num ${s.typical_amount_cents < 0 ? 'neg' : 'pos'}` }, fmtMoney(s.typical_amount_cents)),
                    el('td', {}, INTERVALS[s.interval_days] || `${s.interval_days} days`),
                    el('td', { class: 'num' }, fmtMoney(s.monthly_cost_cents)),
                    el('td', {}, fmtDate(s.last_date)),
                    el('td', {}, fmtDate(s.next_date)),
                    el('td', {}, s.status === 'confirmed' ? '✓ confirmed' : s.status),
                    el('td', { class: 'num' },
                        s.status !== 'confirmed' ? el('button', { class: 'btn-light btn-sm', onclick: setStatus('confirmed') }, 'Confirm') : null, ' ',
                        s.status !== 'dismissed'
                            ? el('button', { class: 'btn-light btn-sm', onclick: setStatus('dismissed') }, 'Dismiss')
                            : el('button', { class: 'btn-light btn-sm', onclick: setStatus('detected') }, 'Restore')));
            })))));
    }
    await load();
}
