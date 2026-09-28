import { api, clear, cssVar, el, fmtDate, fmtMoney, state } from './api.js';
import { filterBar, filterQuery } from './filters.js';

let charts = [];
let chartView = 'line';
let activeCategories = []; // empty = all

function destroyCharts() {
    charts.forEach(c => c.destroy());
    charts = [];
}

const euroTick = v => '€' + Number(v).toLocaleString();

export async function render(root) {
    destroyCharts();
    const body = el('div');
    root.append(await filterBar(() => refresh(body)), body);
    await refresh(body);
}

async function refresh(body) {
    destroyCharts();
    const q = filterQuery();
    const [summary, balances, forecast, budgets] = await Promise.all([
        api('/stats/summary', { query: q }),
        api('/stats/balances'),
        api('/recurring/forecast', { query: { account_id: q.account_id } }),
        api('/budgets'),
    ]);
    clear(body);

    const balanceCls = summary.balance >= 0 ? 'pos' : 'neg';
    body.append(el('div', { class: 'card' },
        el('div', { class: 'summary-grid' },
            el('div', { class: 'summary-card income' }, el('h3', {}, 'Total Income'), el('div', { class: 'amount' }, fmtMoney(summary.income))),
            el('div', { class: 'summary-card expense' }, el('h3', {}, 'Total Expenses'), el('div', { class: 'amount' }, fmtMoney(summary.expenses))),
            el('div', { class: 'summary-card balance' }, el('h3', {}, 'Net Balance'), el('div', { class: `amount ${balanceCls}` }, fmtMoney(summary.balance))),
        )));

    // Accounts + forecast
    const shown = balances.filter(b => !q.account_id || String(b.account_id) === String(q.account_id));
    body.append(el('div', { class: 'grid-2', style: { marginBottom: '30px' } },
        el('div', { class: 'card' },
            el('h3', {}, 'Account balances'),
            el('div', { class: 'summary-grid' }, shown.map(b =>
                el('div', { class: 'summary-card balance' }, el('h3', {}, b.name),
                    el('div', { class: `amount ${b.balance >= 0 ? '' : 'neg'}` }, fmtMoney(b.balance)))))),
        forecastCard(forecast)));

    body.append(budgetCard(budgets));
    body.append(await chartCard());
}

function forecastCard(fc) {
    const list = fc.upcoming.length
        ? el('table', { class: 'data' }, el('tbody', {}, fc.upcoming.slice(0, 8).map(u =>
            el('tr', {}, el('td', {}, fmtDate(u.date)), el('td', {}, u.name),
                el('td', { class: `num ${u.amount < 0 ? 'neg' : 'pos'}` }, fmtMoney(u.amount))))))
        : el('p', { class: 'muted' }, 'No more recurring payments expected this month.');
    return el('div', { class: 'card' },
        el('h3', {}, 'Rest of this month'),
        el('div', { class: 'summary-grid', style: { marginBottom: '12px' } },
            el('div', { class: 'summary-card' }, el('h3', {}, 'Still expected'),
                el('div', { class: `amount ${fc.expected_change < 0 ? 'neg' : 'pos'}` }, fmtMoney(fc.expected_change))),
            el('div', { class: 'summary-card balance' }, el('h3', {}, 'Month-end balance'),
                el('div', { class: 'amount' }, fmtMoney(fc.expected_month_end_balance)))),
        list,
        el('p', { class: 'muted small', style: { marginTop: '8px' } },
            el('a', { href: '#/recurring' }, 'Manage subscriptions →')));
}

export function budgetBars(budgets) {
    return budgets.map(b => {
        const cls = b.percent > 100 ? 'over' : b.percent > 80 ? 'warn' : '';
        return el('div', { class: 'budget-item' },
            el('div', { class: 'spread', style: { marginBottom: '0' } },
                el('span', {}, el('span', { class: 'dot', style: { background: b.color, marginRight: '6px' } }), b.category),
                el('span', { class: `small ${b.percent > 100 ? 'neg' : ''}` },
                    `${fmtMoney(b.spent)} / ${fmtMoney(b.limit)} (${b.percent}%)`)),
            el('div', { class: 'progress' }, el('div', { class: cls, style: { width: `${Math.min(100, b.percent)}%` } })));
    });
}

function budgetCard(budgets) {
    const over = budgets.filter(b => b.percent > 100);
    return el('div', { class: 'card' },
        el('div', { class: 'spread' }, el('h3', {}, 'Budgets this month'), el('a', { href: '#/budgets', class: 'small' }, 'Edit budgets →')),
        over.length ? el('div', { class: 'status error', style: { marginBottom: '14px', marginTop: 0 } },
            `Over budget: ${over.map(b => b.category).join(', ')}`) : null,
        budgets.length ? budgetBars(budgets) : el('p', { class: 'muted' }, 'No budgets yet. Set monthly limits per category on the Budgets tab.'));
}

async function chartCard() {
    const box = el('div', { class: 'chart-box' });
    const chips = el('div', { class: 'chips' });
    const btn = (id, label) => el('button', {
        class: `chip ${chartView === id ? 'active' : ''}`,
        onclick: () => { chartView = id; card.replaceWith(rebuild()); },
    }, label);
    let card;
    const rebuild = () => {
        destroyCharts();
        clear(box); clear(chips);
        card = el('div', { class: 'card' },
            el('div', { class: 'spread' }, el('h2', {}, 'Overview'),
                el('div', { class: 'row' }, btn('line', 'Monthly'), btn('pie', 'By category'), btn('balance', 'Balance'))),
            chartView === 'line' ? chips : null,
            box);
        drawChart(box, chips).catch(e => console.error(e));
        return card;
    };
    return rebuild();
}

async function drawChart(box, chips) {
    if (typeof Chart === 'undefined') {
        box.append(el('p', { class: 'muted' }, 'Chart library not loaded.'));
        return;
    }
    const q = filterQuery();
    Chart.defaults.color = cssVar('--chart-text') || '#666';
    Chart.defaults.borderColor = cssVar('--chart-grid') || 'rgba(0,0,0,0.1)';
    const inc = cssVar('--income') || '#28a745';
    const exp = cssVar('--expense') || '#dc3545';
    const acc = cssVar('--primary') || '#667eea';
    const canvas = el('canvas');
    box.append(canvas);

    if (chartView === 'line') {
        renderCategoryChips(chips, box);
        // The monthly chart shows the whole timeline, so the month filter is ignored here.
        const data = await api('/stats/monthly', { query: { account_id: q.account_id, year: q.year, category_id: activeCategories } });
        charts.push(new Chart(canvas, {
            type: 'line',
            data: {
                labels: data.map(d => {
                    const [y, m] = d.month.split('-');
                    return new Date(y, m - 1, 1).toLocaleDateString('en', { month: 'short', year: 'numeric' });
                }),
                datasets: [
                    { label: 'Income', data: data.map(d => d.income / 100), borderColor: inc, backgroundColor: inc + '1a', tension: 0.4, fill: true },
                    { label: 'Expenses', data: data.map(d => d.expenses / 100), borderColor: exp, backgroundColor: exp + '1a', tension: 0.4, fill: true },
                ],
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'top' } }, scales: { y: { beginAtZero: true, ticks: { callback: euroTick } } } },
        }));
    } else if (chartView === 'pie') {
        const data = await api('/stats/by-category', { query: q });
        if (!data.length) { box.replaceChildren(el('p', { class: 'empty' }, 'No expenses in this period.')); return; }
        charts.push(new Chart(canvas, {
            type: 'pie',
            data: { labels: data.map(d => d.name), datasets: [{ data: data.map(d => d.amount / 100), backgroundColor: data.map(d => d.color) }] },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'right' },
                    tooltip: { callbacks: { label: ctx => {
                        const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                        return `${ctx.label}: ${fmtMoney(Math.round(ctx.parsed * 100))} (${((ctx.parsed / total) * 100).toFixed(1)}%)`;
                    } } },
                },
            },
        }));
    } else {
        const data = await api('/stats/balance-history', { query: { account_id: q.account_id } });
        charts.push(new Chart(canvas, {
            type: 'line',
            data: { labels: data.map(d => fmtDate(d.date)), datasets: [{ label: 'Balance', data: data.map(d => d.balance / 100), borderColor: acc, backgroundColor: acc + '1a', fill: true, pointRadius: 0, tension: 0.2 }] },
            options: { responsive: true, maintainAspectRatio: false, scales: { y: { ticks: { callback: euroTick } }, x: { ticks: { maxTicksLimit: 12 } } } },
        }));
    }
}

function renderCategoryChips(chips, box) {
    clear(chips);
    const redraw = () => { destroyCharts(); clear(box); drawChart(box, chips); };
    chips.append(el('button', {
        class: `chip ${activeCategories.length === 0 ? 'active' : ''}`,
        onclick: () => { activeCategories = []; redraw(); },
    }, 'All Categories'));
    for (const c of state.categories) {
        const on = activeCategories.includes(c.id);
        chips.append(el('button', {
            class: `chip ${on ? 'active' : ''}`,
            onclick: () => {
                activeCategories = on ? activeCategories.filter(x => x !== c.id) : [...activeCategories, c.id];
                redraw();
            },
        }, el('span', { class: 'dot', style: { background: c.color } }), c.name));
    }
}
