import { api, categoryById, clear, el, fmtDate, fmtMoney, run } from './api.js';

const INTERVALS = { 7: 'weekly', 14: 'every 2 weeks', 30: 'monthly', 91: 'quarterly', 182: 'half-yearly', 365: 'yearly' };
const STATUS_LABEL = { detected: 'suggested', confirmed: '✓ kept', dismissed: 'dismissed' };
const KEEP_HINT = 'Keep this series in the list and forecast even if a payment is late, skipped or changes amount. '
    + 'Dismiss it when you cancel the subscription.';

/** Days a payment is overdue beyond a grace period (a quarter of its interval, at least 3 days). */
function daysLate(s) {
    const next = new Date(s.next_date + 'T00:00:00');
    const grace = Math.max(3, Math.round(s.interval_days / 4));
    const late = Math.floor((Date.now() - next.getTime()) / 86400000);
    return late > grace ? late : 0;
}

export async function render(root) {
    const box = el('div');
    const totals = el('div');
    root.append(el('div', { class: 'card' },
        el('div', { class: 'spread' }, el('h2', {}, 'Subscriptions & recurring payments'),
            el('button', { class: 'btn-light', onclick: e => run(e.currentTarget, async () => { await api('/recurring/scan', { method: 'POST' }); await load(); }) }, 'Scan again')),
        el('p', { class: 'muted small', style: { marginBottom: '16px' } },
            'Detected automatically after every import: payments to the same payee at a regular interval with a stable amount. ',
            'Suggested series count towards the totals and the month-end forecast right away.'),
        el('ul', { class: 'muted small', style: { margin: '0 0 16px 18px', lineHeight: 1.7 } },
            el('li', {}, el('strong', {}, 'Keep'), ': pins a series, so it stays even when a later scan no longer recognises it (a late, skipped or changed payment).'),
            el('li', {}, el('strong', {}, 'Dismiss'), ': hides a wrong suggestion or a cancelled subscription and leaves it out of totals and forecast.'),
            el('li', {}, el('strong', {}, 'Late'), ': the expected payment has not arrived. If you cancelled it, dismiss it.')),
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
                const late = s.status !== 'dismissed' ? daysLate(s) : 0;
                return el('tr', { style: s.status === 'dismissed' ? { opacity: 0.5 } : null },
                    el('td', {}, s.display_name, el('div', { class: 'muted small' }, `${s.occurrences} payments`)),
                    el('td', {}, cat ? cat.name : ''),
                    el('td', { class: `num ${s.typical_amount_cents < 0 ? 'neg' : 'pos'}` }, fmtMoney(s.typical_amount_cents)),
                    el('td', {}, INTERVALS[s.interval_days] || `${s.interval_days} days`),
                    el('td', { class: 'num' }, fmtMoney(s.monthly_cost_cents)),
                    el('td', {}, fmtDate(s.last_date)),
                    el('td', { class: late ? 'neg' : '' }, fmtDate(s.next_date),
                        late ? el('div', { class: 'small', title: 'No payment arrived around the expected date' }, `late by ${late} days`) : null),
                    el('td', {}, STATUS_LABEL[s.status] || s.status),
                    el('td', { class: 'num' },
                        s.status !== 'confirmed' ? el('button', { class: 'btn-light btn-sm', title: KEEP_HINT, onclick: setStatus('confirmed') }, 'Keep') : null, ' ',
                        s.status !== 'dismissed'
                            ? el('button', { class: 'btn-light btn-sm', onclick: setStatus('dismissed') }, 'Dismiss')
                            : el('button', { class: 'btn-light btn-sm', onclick: setStatus('detected') }, 'Restore'),
                        s.status === 'confirmed' ? [' ', el('button', { class: 'btn-light btn-sm', title: 'Turn back into a suggestion that follows the automatic detection', onclick: setStatus('detected') }, 'Unpin')] : null));
            })))));
    }
    await load();
}
