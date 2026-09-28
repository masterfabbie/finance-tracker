import {
    accountOptions, api, clear, confirmDialog, el, fmtDate, fmtSigned, loadRefs, options, run, state, toast,
} from './api.js';

const FIELDS = [
    ['date', 'Date *'],
    ['description', 'Description'],
    ['amount', 'Amount *'],
    ['payer', 'Payer / Payee'],
    ['iban', 'Counterparty IBAN'],
    ['type', 'Type (empty = from sign)'],
    ['category', 'Category'],
    ['tags', 'Tags'],
    ['debit', 'Debit column (instead of amount)'],
    ['credit', 'Credit column (instead of amount)'],
];

let current = null; // preview response

export async function render(root) {
    current = null;
    const accountSel = el('select', {}, accountOptions(state.filters.account_id || state.accounts[0]?.id));
    const fileInput = el('input', { type: 'file', accept: '.csv,.txt,text/csv', class: 'hidden' });
    const work = el('div');
    const status = el('div', { class: 'status hidden' });
    const history = el('div');

    const setStatus = (msg, kind = 'info') => {
        status.className = `status ${kind}`;
        status.textContent = msg;
    };

    const upload = file => {
        if (!file) return;
        if (!/\.(csv|txt)$/i.test(file.name)) { setStatus('Please choose a .csv file', 'error'); return; }
        setStatus('Processing CSV file…');
        const form = new FormData();
        form.append('file', file);
        form.append('account_id', accountSel.value);
        run(null, async () => {
            try {
                current = await api('/imports/preview', { method: 'POST', form });
            } catch (e) {
                setStatus(`Error reading file: ${e.message}`, 'error');
                return;
            }
            status.className = 'status hidden';
            renderMapping(work, accountSel, setStatus, () => loadHistory(history));
        });
    };

    fileInput.addEventListener('change', () => upload(fileInput.files[0]));
    const drop = el('div', { class: 'dropzone', onclick: () => fileInput.click() },
        el('div', { class: 'icon' }, '📄'),
        el('p', {}, el('strong', {}, 'Click to upload'), ' or drag and drop your bank CSV file here'),
        el('p', { class: 'muted' }, 'Works with most German and international bank exports (Sparkasse, DKB, ING, Volksbank, comdirect, N26, …). ',
            'Encoding, delimiter and metadata lines are detected automatically.'));
    drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('dragover'); });
    drop.addEventListener('dragleave', e => { e.preventDefault(); drop.classList.remove('dragover'); });
    drop.addEventListener('drop', e => {
        e.preventDefault();
        drop.classList.remove('dragover');
        // Do not rely on the MIME type: Windows often reports CSV files as application/vnd.ms-excel.
        upload(e.dataTransfer.files[0]);
    });

    root.append(
        el('div', { class: 'card' },
            el('h2', {}, '📁 Import CSV File'),
            el('div', { class: 'form-group' }, el('label', {}, 'Import into account'), accountSel,
                el('p', { class: 'muted small', style: { marginTop: '4px' } },
                    'Column settings are remembered per account, so the next import of the same bank format is one click. ',
                    el('a', { href: '#/accounts' }, 'Manage accounts'))),
            drop, fileInput, status, work),
        el('div', { class: 'card' }, el('h2', {}, 'Import history'), history));
    await loadHistory(history);
}

function renderMapping(work, accountSel, setStatus, onImported) {
    clear(work);
    const p = current;
    const mapping = { ...p.mapping };
    const selects = {};

    const table = el('table', { class: 'data' },
        el('thead', {}, el('tr', {}, p.headers.map(h => el('th', {}, h)))),
        el('tbody', {}, p.rows.map(r => el('tr', {}, r.map(c => el('td', {}, c))))));

    const mapGrid = el('div', { class: 'mapping' }, FIELDS.map(([key, label]) => {
        selects[key] = el('select', { onchange: () => { mapping[key] = selects[key].value; } },
            options(p.headers, mapping[key] || '', key === 'type' ? 'Auto-detect from amount' : '— not used —'));
        return el('div', {}, el('label', {}, label), selects[key]);
    }));

    const dateOrder = el('select', {}, options([['auto', 'Auto (dd.mm.yyyy / yyyy-mm-dd)'], ['DMY', 'Day/Month/Year'], ['MDY', 'Month/Day/Year (US)'], ['YMD', 'Year-Month-Day']], mapping.date_order || 'auto'));
    const decimal = el('select', {}, options([['auto', 'Auto'], ['comma', '1.234,56 (comma decimal)'], ['dot', '1,234.56 (dot decimal)']], mapping.decimal_style || 'auto'));
    const invert = el('input', { type: 'checkbox', checked: !!mapping.invert_sign });
    const encoding = el('select', {}, options([['utf-8-sig', 'UTF-8'], ['cp1252', 'Windows-1252'], ['latin-1', 'ISO-8859-1 (Latin-1)']], p.encoding));
    const delimiter = el('select', {}, options([[';', 'Semicolon ;'], [',', 'Comma ,'], ['\t', 'Tab'], ['|', 'Pipe |']], p.delimiter));
    const reparse = () => run(null, async () => {
        const form = new FormData();
        form.append('token', p.token);
        form.append('encoding', encoding.value);
        form.append('delimiter', delimiter.value);
        current = await api('/imports/preview', { method: 'POST', form });
        renderMapping(work, accountSel, setStatus, onImported);
    });
    encoding.addEventListener('change', reparse);
    delimiter.addEventListener('change', reparse);

    const collect = () => ({
        ...Object.fromEntries(Object.keys(selects).map(k => [k, selects[k].value])),
        date_order: dateOrder.value,
        decimal_style: decimal.value,
        invert_sign: invert.checked,
        encoding: encoding.value,
        delimiter: delimiter.value,
    });
    const check = el('div');
    const body = () => ({ token: p.token, account_id: Number(accountSel.value), mapping: collect() });

    const checkBtn = el('button', { class: 'btn-light', onclick: e => run(e.currentTarget, async () => {
        const r = await api('/imports/commit', { method: 'POST', body: body(), query: { dry_run: true } });
        clear(check).append(el('div', {},
            el('h3', { style: { marginTop: '20px' } }, `Parsed result: ${r.valid} valid rows, ${r.failed} with errors`),
            el('div', { class: 'table-wrap' }, el('table', { class: 'data' },
                el('thead', {}, el('tr', {}, ['Line', 'Date', 'Description', 'Payer', 'Category', 'Tags', 'Amount'].map(h => el('th', {}, h)))),
                el('tbody', {}, r.rows.map(x => el('tr', {},
                    el('td', {}, x.line), el('td', {}, fmtDate(x.date)), el('td', {}, x.description), el('td', {}, x.payer),
                    el('td', {}, x.category), el('td', {}, x.tags.join(', ')),
                    el('td', { class: `num ${x.amount_cents < 0 ? 'neg' : 'pos'}` }, fmtSigned(x.amount_cents))))))),
            r.failed_rows.length ? el('p', { class: 'muted small', style: { marginTop: '8px' } },
                'Errors: ', r.failed_rows.slice(0, 10).map(f => `line ${f.line}: ${f.error}`).join('; ')) : null));
    }) }, 'Check parsing');

    const importBtn = el('button', { class: 'btn', onclick: e => run(e.currentTarget, async () => {
        const r = await api('/imports/commit', { method: 'POST', body: body() });
        let msg = `Successfully imported ${r.imported} transactions.`;
        if (r.duplicates) msg += ` ${r.duplicates} duplicates were skipped.`;
        if (r.failed) {
            const lines = r.failed_rows.map(f => f.line);
            msg += ` ${r.failed} rows had errors and were skipped. Failed lines: ${lines.slice(0, 10).join(', ')}${lines.length > 10 ? ` … and ${lines.length - 10} more` : ''}`;
        }
        clear(work);
        setStatus(msg, r.imported > 0 ? 'success' : 'error');
        await loadRefs();
        onImported();
    }) }, 'Import Data');

    work.append(
        el('p', { class: 'muted', style: { marginTop: '16px' } },
            `${p.filename}: ${p.total_rows} rows, header on line ${p.header_line}.`,
            p.profile_found ? ' Saved column settings for this account were applied.' : ''),
        el('div', { class: 'table-wrap' }, table),
        el('h3', { style: { marginTop: '20px' } }, 'Map CSV Columns'),
        mapGrid,
        el('div', { class: 'mapping' },
            el('div', {}, el('label', {}, 'Date format'), dateOrder),
            el('div', {}, el('label', {}, 'Number format'), decimal),
            el('div', {}, el('label', {}, 'File encoding'), encoding),
            el('div', {}, el('label', {}, 'Delimiter'), delimiter),
            el('div', {}, el('label', { class: 'inline-label' }, invert, 'Invert amounts (for exports where expenses are positive)'))),
        el('div', { class: 'row', style: { marginTop: '20px' } },
            importBtn, checkBtn,
            el('button', { class: 'btn-secondary', onclick: () => { current = null; clear(work); } }, 'Cancel')),
        check);
}

async function loadHistory(box) {
    const batches = await api('/imports');
    clear(box);
    if (!batches.length) { box.append(el('p', { class: 'muted' }, 'No imports yet.')); return; }
    box.append(el('div', { class: 'table-wrap', style: { maxHeight: 'none' } }, el('table', { class: 'data' },
        el('thead', {}, el('tr', {}, ['Date', 'File', 'Account', 'Imported', 'Duplicates', 'Errors', ''].map(h => el('th', {}, h)))),
        el('tbody', {}, batches.map(b => el('tr', {},
            el('td', {}, new Date(b.created_at).toLocaleString()),
            el('td', {}, b.filename), el('td', {}, b.account),
            el('td', { class: 'num' }, b.imported), el('td', { class: 'num' }, b.duplicates), el('td', { class: 'num' }, b.failed),
            el('td', {}, el('button', { class: 'btn-light btn-sm', onclick: async e => {
                const btn = e.currentTarget;
                if (!await confirmDialog(`Undo this import and delete its ${b.imported} transactions?`, { danger: true, confirmLabel: 'Undo import' })) return;
                run(btn, async () => {
                    const r = await api(`/imports/${b.id}`, { method: 'DELETE' });
                    toast(`Removed ${r.deleted} transactions`);
                    loadHistory(box);
                });
            } }, 'Undo'))))))));
}
