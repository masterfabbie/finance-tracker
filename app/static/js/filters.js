import { accountOptions, api, el, MONTHS, options, state } from './api.js';

/** Account / year / month filter bar shared by dashboard and transactions. */
export async function filterBar(onChange, extra = []) {
    const years = await api('/transactions/years');
    const f = state.filters;
    const account = el('select', { onchange: () => { f.account_id = account.value; onChange(); } },
        accountOptions(f.account_id, 'All accounts'));
    const year = el('select', { onchange: () => { f.year = year.value; onChange(); } },
        options(years, f.year, 'All years'));
    const month = el('select', { onchange: () => { f.month = month.value; onChange(); } },
        options(MONTHS.map((m, i) => [i + 1, m]), f.month, 'All months'));
    return el('div', { class: 'row filters', style: { marginBottom: '20px' } }, account, year, month, extra);
}

export const filterQuery = () => ({ ...state.filters });
