const $ = (id) => document.getElementById(id);
const fmtMoney = new Intl.NumberFormat('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const fmtInt = (n) => Number(n || 0).toLocaleString('es-AR');
const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
                set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };
function el(tag, text, cls) { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; }
function row(cells) { const tr = document.createElement('tr'); cells.forEach(c => tr.append(c)); return tr; }

const STATUS_LABEL = {
  OPEN: 'Abierta', IN_REVIEW: 'En análisis', ESCALATED_COMPLIANCE: 'Escalada a Cumplimiento',
  CLOSED_FALSE_POSITIVE: 'Cerrada – falso positivo', CLOSED_CONFIRMED_FRAUD: 'Cerrada – fraude confirmado',
  ROS_FILED: 'ROS presentado', CLOSED_NO_ROS: 'Cerrada sin ROS',
};
const NEXT = {
  OPEN: [['IN_REVIEW', 'Tomar alerta', 'primary']],
  IN_REVIEW: [['CLOSED_FALSE_POSITIVE', 'Cerrar: falso positivo', ''], ['CLOSED_CONFIRMED_FRAUD', 'Cerrar: fraude confirmado', 'danger'],
              ['ESCALATED_COMPLIANCE', 'Escalar a Cumplimiento', 'primary']],
  ESCALATED_COMPLIANCE: [['ROS_FILED', 'ROS presentado a la UIF', 'danger'], ['CLOSED_NO_ROS', 'Cerrar sin ROS', '']],
};

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    let d = body.detail;
    if (Array.isArray(d)) d = d.map(x => (x.loc ? x.loc.filter(p => p !== 'body').join('.') + ': ' : '') + x.msg.replace(/^Value error, /, '')).join(' · ');
    throw new Error(d || ('Error ' + r.status));
  }
  return body;
}

// ------------------------------------------------------------------ tabs
let current = store.get('tab') || 'live';
function show(tab) {
  current = tab; store.set('tab', tab);
  document.querySelectorAll('nav button').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('section.tab').forEach(s => s.classList.toggle('active', s.id === 'tab-' + tab));
  if (tab === 'alerts') loadAlerts();
  if (tab === 'rules') loadRules();
  if (tab === 'metrics') loadMetrics();
  if (tab === 'params') loadParams();
  if (tab === 'history') loadHistory();
}
document.querySelectorAll('nav button').forEach(b => b.addEventListener('click', () => show(b.dataset.tab)));

// ------------------------------------------------------------ live feed
const counts = {total:0, APPROVE:0, REVIEW:0, DECLINE:0}; let latSum = 0;
const onlyRisk = $('only-risk');
onlyRisk.checked = store.get('onlyRisk') === '1';
document.body.classList.toggle('only-risk', onlyRisk.checked);
onlyRisk.addEventListener('change', () => { document.body.classList.toggle('only-risk', onlyRisk.checked); store.set('onlyRisk', onlyRisk.checked ? '1' : '0'); });

const es = new EventSource('/v1/stream/decisions');
es.onopen = () => $('status').textContent = '● En vivo';
es.onerror = () => $('status').textContent = 'Reconectando…';
es.onmessage = (ev) => {
  const d = JSON.parse(ev.data);
  $('live-empty').hidden = true;
  counts.total++; counts[d.action]++; latSum += d.latency_ms;
  for (const k of ['total','APPROVE','REVIEW','DECLINE']) $('k-'+k).textContent = fmtInt(counts[k]);
  $('k-lat').textContent = (latSum / counts.total).toFixed(2) + ' ms';
  const tr = row([el('td', new Date(d.evaluated_at).toLocaleTimeString('es-AR')), el('td', d.transaction_id, 'id'), el('td', d.channel),
    el('td', d.amount_ars != null ? fmtMoney.format(d.amount_ars) : '—', 'num'), el('td', d.risk_score, 'num'), el('td', d.action, d.action),
    el('td', (d.reason_codes.length ? d.reason_codes.join(', ') + ' — ' : '') + d.reasons.join(' · '), 'reasons')]);
  tr.className = 'risk-' + d.action;
  if (d.alert_id) { tr.classList.add('clickable'); tr.title = 'Ver alerta ' + d.alert_id; tr.onclick = () => { show('alerts'); openAlert(d.alert_id); }; }
  const rows = $('live-rows'); rows.prepend(tr);
  while (rows.children.length > 300) rows.lastChild.remove();
};

// --------------------------------------------------------------- alerts
$('user').value = store.get('user') || '';
$('user').addEventListener('change', () => store.set('user', $('user').value.trim()));
$('a-filter').addEventListener('change', loadAlerts);
let selectedAlert = null;

async function loadAlerts() {
  try {
    const [stats, list] = await Promise.all([api('/v1/alerts/stats'),
      api('/v1/alerts?limit=500' + ($('a-filter').value ? '&status=' + $('a-filter').value : ''))]);
    const bs = stats.by_status || {};
    $('a-open').textContent = fmtInt(bs.OPEN); $('a-review').textContent = fmtInt(bs.IN_REVIEW);
    $('a-esc').textContent = fmtInt(bs.ESCALATED_COMPLIANCE); $('a-overdue').textContent = fmtInt(stats.overdue);
    $('a-total').textContent = fmtInt(stats.total);
    const open = (bs.OPEN || 0);
    $('badge-open').hidden = !open; $('badge-open').textContent = open;
    const tbody = $('alert-rows'); tbody.replaceChildren();
    $('alerts-empty').hidden = list.length > 0;
    const now = Date.now();
    for (const a of list) {
      const due = new Date(a.due_at);
      const isOpen = ['OPEN','IN_REVIEW','ESCALATED_COMPLIANCE'].includes(a.status);
      const dueCell = el('td', isOpen ? due.toLocaleString('es-AR', {dateStyle:'short', timeStyle:'short'}) : '—', 'nowrap' + (isOpen && due < now ? ' overdue' : ''));
      const tr = row([el('td', a.alert_id, 'id'), el('td', a.severity, 'sev-' + a.severity), el('td', a.channel), el('td', a.customer_id || '—', 'id'),
        el('td', a.risk_score, 'num'), el('td', a.action, a.action), el('td', STATUS_LABEL[a.status] || a.status), dueCell]);
      tr.className = 'clickable' + (a.alert_id === selectedAlert ? ' selected' : '');
      tr.onclick = () => openAlert(a.alert_id);
      tbody.append(tr);
    }
  } catch (e) { $('alerts-empty').hidden = false; $('alerts-empty').textContent = 'No se pudieron cargar las alertas: ' + e.message; }
}

async function openAlert(id, message) {
  selectedAlert = id;
  document.querySelectorAll('#alert-rows tr').forEach(tr => tr.classList.toggle('selected', tr.firstChild.textContent === id));
  const panel = $('alert-detail');
  let a;
  try { a = await api('/v1/alerts/' + encodeURIComponent(id)); }
  catch (e) { panel.replaceChildren(el('div', e.message, 'msg err')); return; }
  panel.replaceChildren();
  panel.append(el('h2', 'Alerta ' + a.alert_id));
  const dl = el('dl');
  const add = (k, v, cls) => { dl.append(el('dt', k), el('dd', v, cls)); };
  add('Estado', STATUS_LABEL[a.status] || a.status); add('Severidad', a.severity, 'sev-' + a.severity);
  add('Categorías', a.categories.join(', ')); add('Transacción', a.transaction_id, 'id'); add('Canal', a.channel);
  add('Cliente', a.customer_id || '—', 'id'); add('Decisión del motor', a.action, a.action); add('Score', a.risk_score);
  add('Creada', new Date(a.created_at).toLocaleString('es-AR')); add('Vence (SLA)', new Date(a.due_at).toLocaleString('es-AR'));
  add('Asignada a', a.assignee || '—');
  panel.append(dl);
  panel.append(el('strong', 'Motivos'));
  const ul = el('ul'); a.reasons.forEach((r, i) => ul.append(el('li', (a.rule_ids[i] ? a.rule_ids[i] + ': ' : '') + r))); panel.append(ul);

  const next = NEXT[a.status] || [];
  if (next.length) {
    const box = el('div', null, 'actions');
    box.append(el('strong', 'Gestión'));
    const ta = el('textarea'); ta.placeholder = 'Fundamento del análisis (obligatorio para cerrar o escalar)'; box.append(ta);
    const btns = el('div', null, 'row');
    for (const [to, label, cls] of next) {
      const b = el('button', label, 'btn ' + cls);
      b.onclick = async () => {
        const user = $('user').value.trim();
        if (!user) { showMsg('Completá "Tu usuario" arriba antes de gestionar la alerta.', true); $('user').focus(); return; }
        try {
          await api('/v1/alerts/' + encodeURIComponent(a.alert_id) + '/transition', {
            method: 'POST', headers: {'Content-Type': 'application/json', 'X-User': user},
            body: JSON.stringify({to_status: to, comment: ta.value}) });
          await loadAlerts(); await openAlert(a.alert_id, ['Estado actualizado: ' + (STATUS_LABEL[to] || to), false]);
        } catch (e) { showMsg(e.message, true); }
      };
      btns.append(b);
    }
    box.append(btns);
    const msg = el('div', null, 'msg'); box.append(msg);
    function showMsg(t, err) { msg.textContent = t; msg.className = 'msg ' + (err ? 'err' : 'ok'); }
    if (message) showMsg(message[0], message[1]);
    if (a.status === 'ESCALATED_COMPLIANCE') box.append(el('div', 'Principio de 4 ojos: debe resolverla un usuario distinto de quien la escaló.', 'muted'));
    panel.append(box);
  } else if (message) { panel.append(el('div', message[0], 'msg ok')); }

  panel.append(el('strong', 'Historial'));
  const h = el('div', null, 'history');
  for (const ev of a.history) {
    h.append(el('div', new Date(ev.at).toLocaleString('es-AR') + ' · ' + ev.user + ' → ' + (STATUS_LABEL[ev.to_status] || ev.to_status) + (ev.comment ? ' — "' + ev.comment + '"' : '')));
  }
  panel.append(h);
}

// ---------------------------------------------------------------- rules
const STATE_LABEL = {active: 'Activa', shadow: 'Sombra', disabled: 'Desactivada'};
const CH_LABEL = {ACQUIRING: 'Adquirencia', CASH_IN: 'Cash-in', CASH_OUT: 'Cash-out'};
const ACTION_LABEL = {APPROVE: 'Aprobar', REVIEW: 'Revisar / retener', DECLINE: 'Rechazar'};
let rulesCache = null, ruleHits = {}, catalogCache = null, selectedRule = null;
const ruleState = (r) => !r.enabled ? 'disabled' : r.mode;

function user() { return $('user').value.trim(); }
function requireUser(msgFn) {
  if (user()) return true;
  msgFn('Completá "Tu usuario" (arriba a la derecha) para registrar quién hace el cambio.', true);
  $('user').focus();
  return false;
}
async function send(path, method, body) {
  return api(path, {method, headers: {'Content-Type': 'application/json', 'X-User': user() || 'consola'},
                    body: body === undefined ? undefined : JSON.stringify(body)});
}

async function loadRules(force) {
  try {
    const [rs, m, cat] = await Promise.all([
      rulesCache && !force ? Promise.resolve(rulesCache) : api('/v1/rules'), api('/v1/metrics'),
      catalogCache && !force ? Promise.resolve(catalogCache) : api('/v1/rules/catalog')]);
    rulesCache = rs; catalogCache = cat; ruleHits = parseRuleHits(m.counters);
    $('rs-version').textContent = rs.version;
    renderRules();
  } catch (e) { $('r-count').textContent = 'Error: ' + e.message; }
}
function renderRules() {
  const q = $('r-search').value.toLowerCase(), ch = $('r-channel').value, cat = $('r-category').value, st = $('r-state').value;
  const list = rulesCache.rules.filter(r => (!ch || r.channels.includes(ch)) && (!cat || r.category === cat) &&
    (!st || ruleState(r) === st) && (!q || (r.id + ' ' + r.name + ' ' + r.condition + ' ' + r.description).toLowerCase().includes(q)));
  $('r-count').textContent = list.length + ' de ' + rulesCache.rules.length + ' reglas';
  const tbody = $('rule-rows'); tbody.replaceChildren();
  for (const r of list) {
    const state = ruleState(r);
    const name = el('td'); name.append(el('div', r.name));
    if (r.deletable) name.append(el('span', 'creada en consola', 'pill custom'));
    const stateCell = el('td'); stateCell.append(el('span', STATE_LABEL[state], 'pill ' + state));
    const tr = row([el('td', r.id, 'id'), name, el('td', r.channels.map(c => CH_LABEL[c]).join(', ')),
      el('td', r.action, r.action), el('td', r.score, 'num'), stateCell, el('td', fmtInt(ruleHits[r.id]), 'num')]);
    tr.className = 'clickable' + (r.id === selectedRule ? ' selected' : '');
    tr.title = r.explanation || r.description;
    tr.onclick = () => openRule(r.id);
    tbody.append(tr);
  }
}
['r-search','r-channel','r-category','r-state'].forEach(id => $(id).addEventListener('input', () => rulesCache && renderRules()));
$('r-new').addEventListener('click', () => newRule());

function parseRuleHits(counters) {
  const out = {};
  for (const [k, v] of Object.entries(counters)) {
    const m = k.match(/^(?:shadow_)?rule_hits_total\|rule="([^"]+)"/); if (m) out[m[1]] = (out[m[1]] || 0) + v;
  }
  return out;
}

function nextRuleId() {
  let n = 0;
  for (const r of rulesCache.rules) { const m = r.id.match(/^USR-(\d+)$/); if (m) n = Math.max(n, +m[1]); }
  return 'USR-' + String(n + 1).padStart(3, '0');
}

async function openRule(id) {
  if (!rulesCache || !catalogCache) await loadRules();
  const r = rulesCache.rules.find(x => x.id === id);
  if (!r) return;
  selectedRule = id; renderRules();
  renderEditor(structuredClone(r), false);
}
function newRule(base) {
  selectedRule = null; renderRules();
  const tpl = base || {name: '', description: '', channels: ['CASH_OUT'], category: 'FRAUD', severity: 'MEDIUM',
    action: 'REVIEW', score: 40, mode: 'shadow', enabled: true, condition: '', reason: '', regulatory_refs: [],
    owner: 'Prevención de Fraude'};
  renderEditor({...tpl, id: nextRuleId(), mode: 'shadow', enabled: true, deletable: true, source: ''}, true);
}

function field(label, input, cls, hint) {
  const l = el('label', null, 'f' + (cls ? ' ' + cls : '')); l.append(el('span', label)); l.append(input);
  if (hint) l.append(el('span', hint, 'hint'));
  return l;
}
function select(options, value) {
  const s = el('select');
  for (const [v, t] of options) { const o = el('option', t); o.value = v; if (v === value) o.selected = true; s.append(o); }
  return s;
}
function fmtVal(v) {
  if (typeof v === 'number') return v.toLocaleString('es-AR');
  if (Array.isArray(v)) return v.join(', ');
  return v == null ? '—' : String(v);
}

function renderEditor(r, isNew) {
  const panel = $('rule-editor'); panel.replaceChildren();
  const originalMode = r.mode;
  const head = el('div', null, 'toolbar');
  head.append(el('h2', isNew ? 'Nueva regla' : r.id + ' · ' + r.name));
  if (!isNew) { head.append(el('span', STATE_LABEL[ruleState(r)], 'pill ' + ruleState(r)));
                head.append(el('span', r.deletable ? 'creada en consola' : 'catálogo base (' + r.source + ')', 'pill' + (r.deletable ? ' custom' : ''))); }
  panel.append(head);
  if (!isNew) panel.append(el('div', 'Disparos desde que arrancó el sistema: ' + fmtInt(ruleHits[r.id]), 'muted'));

  // --- Qué hace (explicación en lenguaje natural)
  const explain = el('div', null, 'explain'); panel.append(explain);

  // --- Formulario
  const form = el('div', null, 'form'); panel.append(form);
  const fId = el('input'); fId.value = r.id; fId.className = 'code'; fId.disabled = !isNew;
  const fName = el('input'); fName.value = r.name; fName.placeholder = 'Ej.: Egreso alto a beneficiario nuevo de noche';
  const fDesc = el('textarea'); fDesc.value = r.description || ''; fDesc.placeholder = 'Qué tipología detecta y por qué es riesgosa';
  const chBox = el('div', null, 'checks'); const chInputs = {};
  for (const c of catalogCache.channels) {
    const lab = el('label'); const cb = el('input'); cb.type = 'checkbox'; cb.checked = r.channels.includes(c);
    chInputs[c] = cb; lab.append(cb, ' ' + CH_LABEL[c]); chBox.append(lab);
  }
  const fCat = select(catalogCache.categories.map(c => [c, {FRAUD: 'Fraude', AML: 'Lavado de activos (PLA)', CFT: 'Financiamiento del terrorismo', OPERATIONAL: 'Operativa'}[c]]), r.category);
  const fSev = select(catalogCache.severities.map(c => [c, {LOW: 'Baja', MEDIUM: 'Media', HIGH: 'Alta', CRITICAL: 'Crítica'}[c]]), r.severity);
  const fAct = select(catalogCache.actions.map(a => [a, ACTION_LABEL[a]]), r.action);
  const fScore = el('input'); fScore.type = 'number'; fScore.min = 0; fScore.max = 100; fScore.value = r.score;
  const fState = select([['shadow', 'Sombra (se evalúa, no afecta la decisión)'], ['active', 'Activa (afecta la decisión)'], ['disabled', 'Desactivada']], ruleState(r));
  const fCond = el('textarea'); fCond.className = 'code'; fCond.value = r.condition; fCond.spellcheck = false;
  fCond.placeholder = "Ej.: feat.is_new_beneficiary and txn.amount_ars >= p.new_beneficiary_high_ars";
  const fReason = el('input'); fReason.value = r.reason || ''; fReason.placeholder = 'Ej.: Transferencia de ARS {txn.amount_ars} a beneficiario nuevo';
  const refBox = el('div', null, 'checks refs'); const refInputs = {};
  for (const [code, desc] of Object.entries(catalogCache.regulatory_refs)) {
    const lab = el('label'); lab.title = desc; const cb = el('input'); cb.type = 'checkbox'; cb.checked = (r.regulatory_refs || []).includes(code);
    refInputs[code] = cb; lab.append(cb, ' ' + code); refBox.append(lab);
  }
  const fOwner = el('input'); fOwner.value = r.owner || '';

  form.append(field('ID', fId, '', isNew ? 'Formato PREFIJO-NÚMERO, ej. USR-001' : 'El ID no se puede cambiar'),
    field('Nombre', fName), field('Descripción', fDesc, 'full'), field('Canales', chBox, 'full'),
    field('Categoría', fCat), field('Severidad', fSev),
    field('Acción al dispararse', fAct, '', 'Revisar = retener y generar alerta'),
    field('Score de riesgo (0-100)', fScore, '', 'Se combina con el de otras reglas; ver umbrales en Parámetros'),
    field('Estado', fState, 'full'),
    field('Condición', fCond, 'full', 'txn.* = datos de la operación · feat.* = variables calculadas · p.* = parámetros'),
  );
  const helper = buildHelper(fCond, () => Object.keys(chInputs).filter(c => chInputs[c].checked));
  form.append(helper);
  form.append(field('Motivo que verá el analista', fReason, 'full', 'Podés incluir valores entre llaves, ej. {feat.card_count_1h}'),
    field('Referencias normativas (al menos una)', refBox, 'full'), field('Área responsable', fOwner, 'full'));

  const draft = () => {
    const state = fState.value;
    return {
      id: fId.value.trim().toUpperCase(), name: fName.value.trim(), description: fDesc.value.trim(),
      channels: Object.keys(chInputs).filter(c => chInputs[c].checked), category: fCat.value, severity: fSev.value,
      action: fAct.value, score: parseInt(fScore.value || '0', 10),
      mode: state === 'disabled' ? (originalMode || 'shadow') : state, enabled: state !== 'disabled',
      condition: fCond.value.trim(), reason: fReason.value.trim(),
      regulatory_refs: Object.keys(refInputs).filter(c => refInputs[c].checked), owner: fOwner.value.trim() || 'Prevención de Fraude',
    };
  };

  // --- explicación en vivo
  let timer = null;
  async function refreshExplain() {
    explain.replaceChildren(el('strong', '¿Qué hace esta regla?'));
    const cond = fCond.value.trim();
    if (!cond) { explain.append(el('div', 'Escribí una condición para ver su explicación.', 'muted')); return; }
    try {
      const ex = await send('/v1/rules/explain', 'POST', {condition: cond});
      const ul = el('ul'); ex.clauses.forEach(c => ul.append(el('li', c)));
      explain.append(el('div', 'Se dispara cuando se cumple' + (ex.clauses.length > 1 ? 'n todas estas condiciones:' : ':')), ul);
      const d = draft();
      explain.append(el('div', 'Entonces: ' + ACTION_LABEL[d.action] + ' con score ' + d.score + ' en ' +
        (d.channels.map(c => CH_LABEL[c]).join(', ') || '— (elegí al menos un canal)') + '.', 'muted'));
      if (ex.params.length) {
        const pr = el('div', 'Parámetros que usa: ', 'hint');
        ex.params.forEach(pp => { const b = el('button', pp.name + ' = ' + fmtVal(pp.value), 'chip'); b.title = 'Ver/editar en Parámetros';
          b.onclick = () => { show('params'); $('p-search').value = pp.name; renderParams(); }; pr.append(b); });
        explain.append(pr);
      }
    } catch (e) { explain.append(el('div', e.message, 'err')); }
  }
  fCond.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(refreshExplain, 400); });
  [fAct, fScore].forEach(x => x.addEventListener('change', refreshExplain));
  Object.values(chInputs).forEach(x => x.addEventListener('change', refreshExplain));
  refreshExplain();

  // --- botones
  const btns = el('div', null, 'btnrow');
  const bTest = el('button', 'Probar con tráfico reciente', 'btn');
  const bTx = el('button', 'Probar con una transacción', 'btn');
  const bSave = el('button', isNew ? 'Crear regla' : 'Guardar cambios', 'btn primary');
  btns.append(bTest, bTx, bSave);
  if (!isNew) {
    const bDup = el('button', 'Duplicar', 'btn');
    bDup.onclick = () => newRule({...draft(), name: draft().name + ' (copia)'});
    btns.append(bDup);
    if (r.deletable) {
      const bDel = el('button', 'Eliminar', 'btn danger');
      bDel.onclick = async () => {
        if (!requireUser(showMsg)) return;
        if (!confirm('¿Eliminar la regla ' + r.id + '? Queda registrado en el historial.')) return;
        try { await send('/v1/rules/' + encodeURIComponent(r.id), 'DELETE'); await loadRules(true);
              $('rule-editor').replaceChildren(el('div', 'Regla ' + r.id + ' eliminada.', 'msg ok')); }
        catch (e) { showMsg(e.message, true); }
      };
      btns.append(bDel);
    }
  }
  panel.append(btns);
  const msg = el('div', null, 'msg'); panel.append(msg);
  function showMsg(t, err) { msg.textContent = t; msg.className = 'msg ' + (err ? 'err' : 'ok'); }
  const txBox = el('div', null, 'result'); txBox.hidden = true; panel.append(txBox);
  const result = el('div', null, 'result'); result.hidden = true; panel.append(result);

  bTest.onclick = async () => {
    showMsg('Probando…'); result.hidden = false; result.replaceChildren(el('div', 'Evaluando la regla sobre las operaciones recientes…', 'muted'));
    try {
      const bt = await send('/v1/rules/backtest', 'POST', {rule: draft(), existing_id: isNew ? null : r.id});
      showMsg(''); renderBacktest(result, bt); result.scrollIntoView({behavior: 'smooth', block: 'start'});
    } catch (e) { result.hidden = true; showMsg(e.message, true); }
  };
  bTx.onclick = () => {
    txBox.hidden = !txBox.hidden; if (txBox.hidden) return;
    txBox.replaceChildren(el('strong', 'Transacción de prueba'),
      el('div', 'Editá los datos y presioná Evaluar. Se usa la historia real del cliente/tarjeta, pero la operación NO se registra ni genera alertas.', 'hint'));
    const ch = draft().channels[0] || 'CASH_OUT';
    const ta = el('textarea'); ta.className = 'code'; ta.style.minHeight = '220px'; ta.value = JSON.stringify(sampleTxn(ch), null, 2);
    const go = el('button', 'Evaluar', 'btn primary'); const out = el('div');
    go.onclick = async () => {
      let txn; try { txn = JSON.parse(ta.value); } catch (e) { out.replaceChildren(el('div', 'El JSON no es válido: ' + e.message, 'msg err')); return; }
      try {
        const t = await send('/v1/rules/test', 'POST', {rule: draft(), transaction: txn});
        out.replaceChildren(
          el('div', !t.applies_to_channel ? 'La regla no aplica a este canal.' : t.matched ? '✔ La regla SE DISPARA: ' + t.reason : '✘ La regla NO se dispara con esta operación.', 'msg ' + (t.matched ? 'ok' : '')),
          el('div', 'Decisión sin esta regla: ' + t.decision_without_rule.action + ' (score ' + t.decision_without_rule.score + (t.decision_without_rule.rules.length ? ', reglas: ' + t.decision_without_rule.rules.join(', ') : '') + ')'),
          el('div', 'Decisión con esta regla activa: ' + t.decision_with_rule.action + ' (score ' + t.decision_with_rule.score + ')'));
        const det = el('details'); det.append(el('summary', 'Ver variables calculadas para esta operación'));
        const pre = el('pre', JSON.stringify(t.features, null, 2), 'code'); pre.style.fontSize = '12px'; det.append(pre); out.append(det);
      } catch (e) { out.replaceChildren(el('div', e.message, 'msg err')); }
    };
    txBox.append(ta, go, out); txBox.scrollIntoView({behavior: 'smooth', block: 'start'});
  };
  bSave.onclick = async () => {
    if (!requireUser(showMsg)) return;
    const d = draft();
    if (d.mode === 'active' && d.enabled && isNew && !confirm('La regla se va a crear ACTIVA y afectará decisiones reales de inmediato. ¿Continuar? (Recomendado: crearla en Sombra)')) return;
    try {
      const res = isNew ? await send('/v1/rules', 'POST', d) : await send('/v1/rules/' + encodeURIComponent(r.id), 'PUT', d);
      await loadRules(true);
      await openRule(d.id);
      $('rule-editor').querySelector('.msg').textContent = (isNew ? 'Regla creada' : 'Cambios guardados') + '. Nueva versión del conjunto de reglas: ' + res.ruleset_version;
      $('rule-editor').querySelector('.msg').className = 'msg ok';
    } catch (e) { showMsg(e.message, true); }
  };
}

function renderBacktest(box, bt) {
  box.replaceChildren(el('strong', 'Resultado sobre las últimas ' + fmtInt(bt.evaluated) + ' operaciones de los canales elegidos'));
  if (!bt.evaluated) { box.append(el('div', 'Todavía no hay operaciones recientes para probar. Generá tráfico con el simulador y volvé a intentar.', 'muted')); return; }
  const stats = el('div', null, 'stats');
  const stat = (label, value) => { const d = el('div'); d.append(el('span', label, 'muted'), el('b', value)); stats.append(d); };
  stat('Se habría disparado', fmtInt(bt.matched) + ' veces'); stat('Tasa de disparo', bt.match_rate.toLocaleString('es-AR') + ' %');
  stat('Decisiones que cambiarían', fmtInt(bt.changed));
  box.append(stats);
  const t = el('table'); t.className = 'compact';
  t.append(row([el('th', 'Decisión'), el('th', 'Sin la regla', 'num'), el('th', 'Con la regla activa', 'num')]));
  for (const a of ['APPROVE', 'REVIEW', 'DECLINE'])
    t.append(row([el('td', a, a), el('td', fmtInt(bt.decisions_before[a]), 'num'), el('td', fmtInt(bt.decisions_after[a]), 'num')]));
  box.append(t);
  if (bt.samples.length) {
    box.append(el('div', 'Ejemplos de operaciones donde se dispara:', 'hint'));
    const s = el('table'); s.className = 'compact';
    s.append(row([el('th', 'Transacción'), el('th', 'Monto', 'num'), el('th', 'Antes'), el('th', 'Después'), el('th', 'Motivo')]));
    for (const x of bt.samples)
      s.append(row([el('td', x.transaction_id, 'id'), el('td', fmtMoney.format(x.amount_ars || 0), 'num'), el('td', x.before, x.before),
                    el('td', x.after, x.after), el('td', x.reason, 'reasons')]));
    const w = el('div', null, 'wrap'); w.append(s); box.append(w);
  }
  if (bt.match_rate > 5) box.append(el('div', 'Atención: la regla se dispara en más del 5% de las operaciones; podría generar demasiadas alertas.', 'warnbox'));
}

function buildHelper(target, channels) {
  const det = el('details', null, 'helper full');
  det.append(el('summary', 'Ayuda: insertar variables, parámetros, listas y funciones'));
  const body = el('div', null, 'body'); det.append(body);
  const bar = el('div', null, 'toolbar');
  const q = el('input'); q.placeholder = 'Buscar…'; q.size = 24;
  const kind = select([['feat', 'Variables calculadas'], ['txn', 'Datos de la transacción'], ['p', 'Parámetros'], ['lists', 'Listas de control'], ['fn', 'Funciones y operadores']], 'feat');
  bar.append(kind, q); body.append(bar);
  const items = el('div', null, 'items'); body.append(items);
  body.append(el('div', 'Clic en un elemento para insertarlo en la condición, donde está el cursor.', 'hint'));
  const insert = (text) => {
    const s = target.selectionStart ?? target.value.length, e = target.selectionEnd ?? target.value.length;
    const pre = target.value.slice(0, s), post = target.value.slice(e);
    const sep = pre && !/\s$/.test(pre) ? ' ' : '';
    target.value = pre + sep + text + post; target.focus();
    const pos = (pre + sep + text).length; target.setSelectionRange(pos, pos);
    target.dispatchEvent(new Event('input'));
  };
  const render = () => {
    items.replaceChildren();
    const term = q.value.toLowerCase(); const chs = channels();
    let list = [];
    if (kind.value === 'feat') list = catalogCache.features.filter(f => !chs.length || f.channels.some(c => chs.includes(c)))
      .map(f => [f.name, f.label + (f.unit ? ' (' + f.unit + ')' : ''), f.description]);
    if (kind.value === 'txn') list = catalogCache.transaction_fields.map(f => [f.name, f.label, f.description]);
    if (kind.value === 'p') list = Object.entries(catalogCache.params).map(([k, v]) => ['p.' + k, 'Valor actual: ' + fmtVal(v), '']);
    if (kind.value === 'lists') list = Object.entries(catalogCache.lists).map(([k, n]) => ["in_list('" + k + "', )", 'Lista «' + k + '»', n + ' elementos. Completá el valor a verificar, ej. txn.counterparty.cuit']);
    if (kind.value === 'fn') list = catalogCache.functions.map(f => [f.syntax, f.description, ''])
      .concat(catalogCache.operators.map(o => [o.syntax.split(' ')[0], o.syntax, o.description]));
    for (const [code, label, desc] of list) {
      if (term && !(code + label + desc).toLowerCase().includes(term)) continue;
      const b = el('button', null, 'item'); b.type = 'button';
      b.append(el('code', code), document.createTextNode(' — ' + label)); if (desc) b.append(el('span', desc));
      b.onclick = () => insert(code);
      items.append(b);
    }
  };
  q.addEventListener('input', render); kind.addEventListener('change', render); det.addEventListener('toggle', render);
  return det;
}

function sampleTxn(channel) {
  const now = new Date().toISOString(), id = 'PRUEBA-' + Math.random().toString(36).slice(2, 8).toUpperCase();
  if (channel === 'ACQUIRING') return {transaction_id: id, channel, method: 'CARD', timestamp: now, amount: 150000, entry_mode: 'ECOMMERCE',
    merchant: {merchant_id: 'MER-1', mcc: '5411'}, card: {card_fingerprint: 'CARD-PRUEBA', bin: '450799', last4: '1234', issuer_country: 'AR'},
    device: {ip: '181.1.1.1', ip_country: 'AR'}, three_ds_authenticated: false};
  return {transaction_id: id, channel, method: 'TRANSFER', timestamp: now, amount: 1500000,
    customer: {customer_id: 'CUST-PRUEBA', cuit: '20-12345678-9', risk_level: 'MEDIUM', is_pep: false, kyc_verified: true,
               account_opened_at: new Date(Date.now() - 20 * 86400000).toISOString(), declared_monthly_income_ars: 1200000},
    counterparty: {account_id: 'CVU-DESTINO-PRUEBA', country: 'AR'},
    device: {device_id: 'DEV-PRUEBA', ip: '181.1.1.1', session_age_seconds: 300}};
}

// ----------------------------------------------------------- parámetros
let paramsCache = null; const pending = {};
async function loadParams() {
  try { paramsCache = await api('/v1/params'); renderParams(); }
  catch (e) { $('p-groups').replaceChildren(el('div', 'No se pudieron cargar los parámetros: ' + e.message, 'msg err')); }
}
function paramStr(v) { return Array.isArray(v) ? v.join(', ') : String(v); }
function renderParams() {
  if (!paramsCache) return;
  const q = $('p-search').value.toLowerCase(), onlyUsed = $('p-used').checked;
  const groups = {};
  for (const p of paramsCache) {
    if (onlyUsed && !p.used_by.length && !p.affects_decision) continue;
    if (q && !(p.name + ' ' + p.description + ' ' + p.used_by.join(' ') + ' ' + p.section).toLowerCase().includes(q)) continue;
    (groups[p.section] = groups[p.section] || []).push(p);
  }
  const root = $('p-groups'); root.replaceChildren();
  for (const [section, items] of Object.entries(groups)) {
    const g = el('div', null, 'group'); g.append(el('h3', section));
    const t = el('table'); t.className = 'compact';
    t.append(row([el('th', 'Parámetro'), el('th', 'Descripción'), el('th', 'Valor', 'num'), el('th', 'Usado por')]));
    for (const p of items) {
      const inp = el('input', null, 'pv'); inp.value = p.name in pending ? pending[p.name] : paramStr(p.value);
      inp.classList.toggle('changed', p.name in pending);
      inp.oninput = () => {
        if (inp.value.trim() === paramStr(p.value)) delete pending[p.name]; else pending[p.name] = inp.value.trim();
        inp.classList.toggle('changed', p.name in pending); updateBar();
      };
      const vc = el('td', null, 'num'); vc.append(inp);
      const desc = el('td'); desc.append(el('div', p.description || '—', p.description ? '' : 'muted'));
      if (p.affects_features) desc.append(el('div', 'Interviene en el cálculo de variables: la vista previa es aproximada.', 'hint'));
      if (p.affects_decision) desc.append(el('div', 'Define la política de decisión del canal.', 'hint'));
      const used = el('td');
      p.used_by.forEach(id => { const b = el('button', id, 'chip'); b.onclick = () => { show('rules'); openRule(id); }; used.append(b); });
      if (!p.used_by.length) used.append(el('span', p.affects_decision ? 'decisión' : '—', 'muted'));
      t.append(row([el('td', p.name, 'id'), desc, vc, used]));
    }
    const w = el('div', null, 'wrap'); w.append(t); g.append(w); root.append(g);
  }
  if (!Object.keys(groups).length) root.append(el('div', 'Ningún parámetro coincide con la búsqueda.', 'empty'));
  updateBar();
}
function updateBar() {
  const n = Object.keys(pending).length;
  $('p-bar').hidden = !n;
  $('p-bar-text').textContent = n + (n === 1 ? ' cambio sin guardar: ' : ' cambios sin guardar: ') +
    Object.entries(pending).map(([k, v]) => k + ' → ' + v).join(' · ');
}
['p-search', 'p-used'].forEach(id => $(id).addEventListener('input', renderParams));
$('p-discard').onclick = () => { for (const k of Object.keys(pending)) delete pending[k]; $('p-impact').hidden = true; renderParams(); };
$('p-preview').onclick = async () => {
  const box = $('p-impact'); box.hidden = false; box.replaceChildren(el('div', 'Calculando impacto sobre las operaciones recientes…', 'muted'));
  try { renderImpact(box, await send('/v1/params/preview', 'POST', {changes: pending})); box.scrollIntoView({behavior: 'smooth', block: 'start'}); }
  catch (e) { box.replaceChildren(el('div', e.message, 'msg err')); }
};
$('p-save').onclick = async () => {
  const box = $('p-impact'); box.hidden = false;
  if (!requireUser((t) => box.replaceChildren(el('div', t, 'msg err')))) return;
  if (!confirm('Se aplicarán ' + Object.keys(pending).length + ' cambio(s) de parámetros de inmediato. ¿Continuar?')) return;
  try {
    const res = await send('/v1/params', 'PUT', {changes: pending});
    for (const k of Object.keys(pending)) delete pending[k];
    rulesCache = null; catalogCache = null;
    await loadParams();
    box.replaceChildren(el('div', 'Parámetros guardados. Nueva versión del conjunto de reglas: ' + res.ruleset_version, 'msg ok'));
  } catch (e) { box.replaceChildren(el('div', e.message, 'msg err')); }
};
function renderImpact(box, pv) {
  box.replaceChildren(el('h2', 'Impacto estimado sobre las últimas ' + fmtInt(pv.evaluated) + ' operaciones'));
  if (!pv.evaluated) { box.append(el('div', 'No hay operaciones recientes. Generá tráfico con el simulador para ver el impacto.', 'muted')); return; }
  if (pv.approximate.length) box.append(el('div', 'Estimación aproximada: ' + pv.approximate.join(', ') + ' interviene en el cálculo de variables, que no se recalculan para operaciones ya evaluadas.', 'warnbox'));
  const t = el('table'); t.className = 'compact diff';
  t.append(row([el('th', 'Decisión'), el('th', 'Hoy', 'num'), el('th', 'Con los cambios', 'num'), el('th', 'Diferencia', 'num')]));
  for (const a of ['APPROVE', 'REVIEW', 'DECLINE']) {
    const d = pv.decisions_after[a] - pv.decisions_before[a];
    t.append(row([el('td', a, a), el('td', fmtInt(pv.decisions_before[a]), 'num'), el('td', fmtInt(pv.decisions_after[a]), 'num'),
                  el('td', (d > 0 ? '+' : '') + fmtInt(d), 'num ' + (d > 0 && a !== 'APPROVE' ? 'up' : d < 0 && a !== 'APPROVE' ? 'down' : ''))]));
  }
  box.append(el('div', fmtInt(pv.changed) + ' decisiones cambiarían.'), t);
  const deltas = Object.entries(pv.rule_hit_delta);
  if (deltas.length) {
    const d = el('div', 'Reglas afectadas: ', 'hint');
    deltas.forEach(([id, n]) => d.append(el('span', id + ' ' + (n > 0 ? '+' : '') + n, 'chip')));
    box.append(d);
  }
  if (pv.samples.length) {
    const s = el('table'); s.className = 'compact';
    s.append(row([el('th', 'Transacción'), el('th', 'Monto', 'num'), el('th', 'Hoy'), el('th', 'Con cambios'), el('th', 'Reglas')]));
    for (const x of pv.samples)
      s.append(row([el('td', x.transaction_id, 'id'), el('td', fmtMoney.format(x.amount_ars || 0), 'num'), el('td', x.before, x.before),
        el('td', x.after, x.after), el('td', [...x.rules_added.map(r => '+' + r), ...x.rules_removed.map(r => '−' + r)].join(' '), 'reasons')]));
    const w = el('div', null, 'wrap'); w.append(s); box.append(w);
  }
}

// ------------------------------------------------------------ historial
const H_LABEL = {RULE_CREATED: 'Regla creada', RULE_UPDATED: 'Regla modificada', RULE_DELETED: 'Regla eliminada', PARAMS_UPDATED: 'Parámetros'};
async function loadHistory() {
  try {
    const items = await api('/v1/config/history');
    const tb = $('h-rows'); tb.replaceChildren(); $('h-empty').hidden = items.length > 0;
    for (const h of items) {
      let detail = '';
      if (h.type === 'PARAMS_UPDATED') detail = Object.keys(h.after || {}).map(k => k + ': ' + fmtVal(h.before[k]) + ' → ' + fmtVal(h.after[k])).join(' · ');
      else if (h.type === 'RULE_UPDATED') {
        const ch = Object.keys(h.after).filter(k => JSON.stringify(normalize(h.before[k], k)) !== JSON.stringify(normalize(h.after[k], k)));
        detail = h.rule_id + ': ' + (ch.map(k => k + ' ' + fmtVal(h.before[k]) + ' → ' + fmtVal(h.after[k])).join(' · ') || 'sin cambios');
      } else detail = h.rule_id + ' — ' + ((h.after || h.before || {}).name || '');
      const when = h.at ? new Date(h.at).toLocaleString('es-AR') : '';
      tb.append(row([el('td', (when ? when + ' · ' : '') + H_LABEL[h.type]), el('td', h.user), el('td', detail, 'reasons'), el('td', h.ruleset_version, 'id')]));
    }
  } catch (e) { $('h-empty').hidden = false; $('h-empty').textContent = 'Error: ' + e.message; }
}
function normalize(v, k) {
  if (k === 'condition' && typeof v === 'string') return v.split(/\s+/).join(' ').trim();
  if (k === 'enabled' && v === undefined) return true;
  if (k === 'mode' && v === undefined) return 'active';
  if (k === 'owner' && v === undefined) return 'Prevención de Fraude';
  return v;
}

// -------------------------------------------------------------- metrics
async function loadMetrics() {
  try {
    const m = await api('/v1/metrics');
    $('m-p50').textContent = m.latency_ms.p50 + ' ms'; $('m-p95').textContent = m.latency_ms.p95 + ' ms'; $('m-p99').textContent = m.latency_ms.p99 + ' ms';
    $('m-fail').textContent = fmtInt(m.counters.engine_failures_total); $('m-rerr').textContent = fmtInt(m.counters.rule_errors_total);
    const ch = {};
    for (const [k, v] of Object.entries(m.counters)) {
      const x = k.match(/^decisions_total\|channel="([^"]+)",action="([^"]+)"/);
      if (x) { ch[x[1]] = ch[x[1]] || {APPROVE:0, REVIEW:0, DECLINE:0}; ch[x[1]][x[2]] = v; }
    }
    const tb = $('m-channels'); tb.replaceChildren();
    for (const [c, v] of Object.entries(ch)) {
      const tot = v.APPROVE + v.REVIEW + v.DECLINE;
      tb.append(row([el('td', c), el('td', fmtInt(v.APPROVE), 'num'), el('td', fmtInt(v.REVIEW), 'num'), el('td', fmtInt(v.DECLINE), 'num'),
        el('td', tot ? (100 * v.DECLINE / tot).toFixed(1) + ' %' : '—', 'num')]));
    }
    if (!Object.keys(ch).length) tb.append(row([el('td', 'Sin datos todavía', 'muted')]));
    const hits = Object.entries(parseRuleHits(m.counters)).sort((a, b) => b[1] - a[1]).slice(0, 15);
    const max = hits.length ? hits[0][1] : 1;
    const tr = $('m-rules'); tr.replaceChildren();
    for (const [id, n] of hits) {
      const bar = el('div', null, 'bar'); bar.style.width = (100 * n / max) + '%';
      const cell = el('td'); cell.append(bar);
      tr.append(row([el('td', id, 'id'), el('td', fmtInt(n), 'num'), cell]));
    }
    if (!hits.length) tr.append(row([el('td', 'Sin disparos todavía', 'muted')]));
  } catch (e) { $('m-p50').textContent = 'Error'; }
}

// -------------------------------------------------------------- polling
fetch('/health').then(r => r.json()).then(h => $('rs-version').textContent = h.ruleset_version).catch(() => {});
setInterval(() => {
  if (current === 'alerts') loadAlerts(); else api('/v1/alerts/stats').then(s => {
    const open = (s.by_status || {}).OPEN || 0; $('badge-open').hidden = !open; $('badge-open').textContent = open; }).catch(() => {});
  if (current === 'metrics') loadMetrics();
}, 4000);
show(current);
