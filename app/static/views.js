export const q = (selector, root = document) => root.querySelector(selector);
export const text = (selector, value) => { q(selector).textContent = value ?? '—'; };
export const vector = (point) => point ? `(${point.join(', ')})` : '—';
export const number = (value) => value == null ? '—' : Number(value).toLocaleString('zh-CN');
export const labels = {
  PASS: '通过', FAIL: '失败', PENDING: '待测', CONFLICT: '冲突', ACTIVE: '有效芯粒',
  EDGE_EXCLUSION: '边缘保留带', NOTCH_VOID: '缺口空位', OUTSIDE_DISC: '圆片外',
  OUT_OF_GRID: '超出阵列', MATCH: '一致', REVIEW: '台账有差异', DIFFERENCE: '有差异',
  MISSING_REFERENCE: '缺交接台账', UNBALANCED: '阵列或行数失衡',
  RECOVER: '建议收回', RETAIN: '建议保留',
  RECOVERED: '边缘复测通过', EDGE_FAILURE: '边缘失效', REPEATED_EDGE_FAILURE: '边缘连续失效',
  EDGE_CONFLICT: '边缘复测冲突', NO_EDGE_EVIDENCE: '边缘无复测依据', BAD_EDGE_MEASUREMENT: '边缘测值无效',
  NOT_SELECTED: '未选收回',
};

export function element(tag, value, className) {
  const item = document.createElement(tag);
  if (value != null) item.textContent = value;
  if (className) item.className = className;
  return item;
}

export function options(select, choices, value) {
  select.replaceChildren(...choices.map(([id, title]) => new Option(title, id)));
  if (choices.some(([id]) => id === value)) select.value = value;
}

export function pairs(items) {
  const list = element('dl', null, 'pairs');
  for (const [title, value] of items) {
    const content = element('dd', null, 'mono');
    content.append(value instanceof Node ? value : String(value ?? '—'));
    list.append(element('dt', title), content);
  }
  return list;
}

export function status(code) {
  const variant = {PASS:'pass', FAIL:'fail', CONFLICT:'conflict', PENDING:'pending', MATCH:'pass',
    REVIEW:'pending', DIFFERENCE:'pending', UNBALANCED:'fail'}[code] ?? '';
  return element('span', labels[code] ?? code, `status ${variant}`);
}

export function failure(box, error) {
  box.replaceChildren(element('p', error.message || '请求失败，请重试。', 'inline-error'));
}

function table(box, records, columns, empty = '没有符合条件的记录。') {
  if (records.length === 0) {
    box.replaceChildren(element('p', empty, 'empty'));
    return;
  }
  const grid = element('table', null, 'ledger');
  const headers = grid.createTHead().insertRow();
  for (const [name, , css] of columns) {
    const th = element('th', name, css);
    th.scope = 'col';
    headers.append(th);
  }
  const body = grid.createTBody();
  for (const record of records) {
    const row = body.insertRow();
    for (const [, value, css] of columns) {
      const cell = row.insertCell();
      const item = typeof value === 'function' ? value(record) : record[value];
      if (css) cell.className = css;
      if (item instanceof Node) cell.append(item);
      else {
        cell.textContent = item ?? '—';
        cell.title = cell.textContent;
      }
    }
  }
  box.replaceChildren(grid);
}

function rowButton(label, action) {
  const button = element('button', label, 'row-link');
  button.type = 'button';
  button.addEventListener('click', () => {
    for (const peer of button.closest('tbody').querySelectorAll('[aria-pressed]')) peer.setAttribute('aria-pressed', 'false');
    button.setAttribute('aria-pressed', 'true');
    action();
  });
  button.setAttribute('aria-pressed', 'false');
  return button;
}

const original = (row) => row.fields ? vector([row.fields.x, row.fields.y]) : '—';
const line = (row) => row.end_line === row.line ? row.line : `${row.line}–${row.end_line}`;
const issueColumns = [
  ['图档', 'source', 'mono'], ['行号', line, 'num'], ['晶圆', 'wafer', 'mono'],
  ['原因码', 'code', 'mono'], ['原因', 'reason'], ['原始字段', (row) => row.raw.map((value) => JSON.stringify(value)).join(' · ')],
];

function evidenceCard(row) {
  const card = element('article', null, 'evidence-row');
  const header = element('div', null, 'evidence-id');
  header.append(element('strong', `${row.source}:${line(row)}`, 'mono'), element('span', row.code ?? '采信'));
  const fields = row.fields;
  const measurement = fields ? `${original(row)}   T${fields.attempt}   ${fields.result || '∅'}   BIN ${fields.bin || '∅'}` : '';
  card.append(header, element('p', measurement, 'evidence-values'));
  if (row.transform) {
    const {translated, mirrored, turn_degrees, canonical} = row.transform;
    card.append(element('p', `轴向 ${vector(translated)} · 镜像 ${vector(mirrored)} · ${turn_degrees}° → ${vector(canonical)}`, 'evidence-note'));
  }
  if (fields?.note) card.append(element('p', fields.note, 'evidence-note'));
  return card;
}

export function renderCell(box, cell, extra = null) {
  const decision = cell.decision;
  const heading = element('div', null, 'detail-title');
  heading.append(element('strong', vector([cell.x, cell.y])), status(decision?.result ?? cell.eligibility));
  if (cell.cluster) heading.append(element('span', cell.cluster, 'mono'));
  box.replaceChildren(heading, pairs([['晶圆', cell.wafer], ['测次', decision?.attempt], ['分档', decision?.bin], ['原始行', cell.evidence.length]]));
  if (decision?.history.length) {
    const history = decision.history.map((item) => `T${item.attempt} ${labels[item.result]}`).join(' → ');
    box.append(element('p', history, 'data-strip detail-group'));
  }
  for (const row of cell.evidence) box.append(evidenceCard(row));
  if (!cell.evidence.length) box.append(element('p', '该位置暂无原始行。', 'empty'));
  if (extra) box.append(extra);
}

async function intake({api, base}) {
  const data = await api(`${base}/intake`);
  text('#source-total', `${data.files.length} 档`);
  table(q('#intake-files'), data.files, [
    ['图档', 'name', 'mono'], ['编码', 'encoding', 'mono'], ['段', 'segments', 'num'],
    ['物理行', 'physical_lines', 'num'], ['数据记录', 'data_count', 'num'],
  ]);
  q('#intake-summary').replaceChildren(pairs([
    ['数据记录', data.files.reduce((sum, file) => sum + file.data_count, 0)],
    ['重复档头', data.issues.filter((row) => row.bucket === 'header').length],
    ['空记录', data.issues.filter((row) => row.bucket === 'blank').length],
    ['栏数不符', data.issues.filter((row) => row.code === 'COLUMN_COUNT').length],
  ]));
  table(q('#intake-issues'), data.issues, issueColumns);
}

async function coordinates({api, base, signal}) {
  const data = await api(`${base}/coordinates`);
  table(q('#coordinate-sources'), data.sources, [
    ['图档', 'name', 'mono'], ['原点', (s) => vector([s.origin_x, s.origin_y]), 'num'],
    ['原缺口', 'notch', 'mono'], ['原轴向', (s) => `${s.x_left ? 'X←' : 'X→'} / ${s.y_down ? 'Y↓' : 'Y↑'}`],
    ['镜像', (s) => s.mirror ? 'X 反射' : '—'], ['对表', 'aligned', 'num'],
  ]);
  const form = q('#probe-form');
  const choices = data.sources.map((s) => [s.name, s.name]);
  options(form.elements.source, choices, choices.at(-1)?.[0]);
  const drawProbe = async () => {
    const target = q('#probe-output');
    const button = q('button', form);
    button.disabled = true;
    try {
      const result = await api(`${base}/coordinates/probe?${new URLSearchParams(new FormData(form))}`);
      target.replaceChildren(pairs([['平移与轴向', vector(result.translated)], ['镜像后', vector(result.mirrored)],
        ['逆时针旋转', `${result.turn_degrees}°`], ['标准坐标', vector(result.canonical)]]));
    } catch (error) {
      if (!signal.aborted) failure(target, error);
    } finally {
      if (!signal.aborted) button.disabled = false;
    }
  };
  form.addEventListener('submit', (event) => { event.preventDefault(); drawProbe(); }, {signal});
  drawProbe();
  const filter = q('#coordinate-filter');
  options(filter, [['all', '全部'], ...choices]);
  const draw = () => {
    const rows = data.rows.filter((row) => filter.value === 'all' || row.source === filter.value);
    text('#aligned-total', `${rows.length} 行`);
    table(q('#coordinate-rows'), rows, [
      ['图档', 'source', 'mono'], ['行号', line, 'num'], ['晶圆', 'wafer', 'mono'], ['原点位', original, 'num'],
      ['轴向后', (row) => vector(row.transform.translated), 'num'],
      ['镜像后', (row) => vector(row.transform.mirrored), 'num'], ['旋转 °', (row) => row.transform.turn_degrees, 'num'],
      ['标准点位', (row) => vector(row.transform.canonical), 'num'],
    ]);
  };
  filter.addEventListener('change', draw, {signal});
  draw();
  table(q('#coordinate-issues'), data.issues, issueColumns);
}

function detailLoader(target, signal) {
  let current = 0;
  return async (request, render) => {
    const token = ++current;
    target.replaceChildren(element('p', '正在读取证据…', 'empty'));
    try {
      const result = await request();
      if (!signal.aborted && token === current) render(result);
    } catch (error) {
      if (!signal.aborted && token === current) failure(target, error);
    }
  };
}

async function retest(context) {
  const {api, base, wafer, signal} = context;
  const data = await api(`${base}/retest/${wafer}`);
  const filter = q('#retest-filter');
  const target = q('#retest-detail');
  const load = detailLoader(target, signal);
  const show = (x, y) => load(() => api(`${base}/mask/${wafer}/cell?x=${x}&y=${y}`), (cell) => renderCell(target, cell));
  const draw = () => {
    const rows = data.cells.filter((cell) => filter.value === 'all' || cell.result === filter.value);
    text('#retest-total', `${rows.length} 枚`);
    table(q('#retest-rows'), rows, [
      ['坐标', (cell) => rowButton(vector([cell.x,cell.y]), () => show(cell.x, cell.y))],
      ['裁决', (cell) => status(cell.result)], ['末次', 'attempt', 'num'], ['分档', 'bin', 'num'],
      ['测次链', (cell) => cell.history.map((step) => `T${step.attempt} ${labels[step.result]}`).join(' → ')],
    ]);
    if (rows.length) q('button', q('#retest-rows')).click();
    else load(async () => null, () => target.replaceChildren(element('p', '该状态无芯粒。', 'empty')));
  };
  filter.addEventListener('change', draw, {signal});
  draw();
  table(q('#retest-issues'), data.issues, issueColumns);
}

async function clusters(context) {
  const {api, base, wafer, run, signal} = context;
  const data = await api(`${base}/clusters/${wafer}`);
  const target = q('#cluster-detail');
  const load = detailLoader(target, signal);
  const evidence = q('#cluster-evidence');
  const show = (id) => {
    evidence.replaceChildren(element('p', '正在载入原行…', 'empty'));
    return load(() => api(`${base}/clusters/${wafer}/${id}`).catch((error) => ({error})), (group) => {
      if (group.error) {
        failure(target, group.error);
        evidence.replaceChildren();
        return;
      }
      const graph = element('a', '在阵列查看', 'btn link-btn');
      const params = new URLSearchParams({run: run.run_id, wafer, cluster: id, x: group.anchor[0], y: group.anchor[1]});
      graph.href = `/?${params}`;
      target.replaceChildren(pairs([['簇号', group.id], ['成员', group.size], ['分档', Object.entries(group.bins).map(([bin, qty]) => `${bin} × ${qty}`).join(' · ')],
        ['点位', group.points.map(vector).join(' ')], ['晶圆阵列', graph]]));
      table(evidence, group.rows, [['图档', 'source', 'mono'], ['行号', line, 'num'], ['原点位', original, 'num'],
        ['标准点位', (row) => vector(row.transform.canonical), 'num'], ['测次', (row) => row.measurement.attempt, 'num'],
        ['分档', (row) => row.measurement.bin, 'num']]);
    });
  };
  text('#cluster-total', `${data.length} 簇 · ${data.reduce((sum, group) => sum + group.size, 0)} 枚`);
  table(q('#cluster-rows'), data, [['簇号', (group) => rowButton(group.id, () => show(group.id))], ['成员', 'size', 'num'],
    ['起点', (group) => vector(group.anchor), 'num'], ['包围盒', (group) => `${vector(group.bounds.slice(0,2))} → ${vector(group.bounds.slice(2))}`]]);
  if (data.length) q('button', q('#cluster-rows')).click();
  else for (const box of [target, evidence]) box.replaceChildren(element('p', '此片无最终失败芯粒。', 'empty'));
}

const countNames = {valid: '有效', passed: '通过', failed: '失败', pending: '待测', conflict: '冲突'};
const rowNames = {total: '实收记录', declared_data: '声明数据', accepted: '采信', isolated: '隔离', duplicate: '重复', blank: '空记录', header: '重复档头'};

function auditView({audit, signal}) {
  text('#audit-total', `${audit.wafers.length} 片 · 批良率 ${audit.summary.yield_pct ?? '—'}%`);
  const names = Object.entries(countNames);
  const wa = audit.wafers.flatMap((wafer) => [
    {...wafer, field: '阵列', waferStatus: wafer.balanced ? 'MATCH' : 'UNBALANCED'},
    {...wafer.reference, wafer: wafer.wafer, field: '台账', waferStatus: wafer.status},
  ]);
  table(q('#audit-wafers'), wa, [['晶圆', 'wafer', 'mono'], ['来源', 'field'], ...names.map(([key, name]) => [name,key,'num']),
    ['良率 %', 'yield_pct', 'num'], ['核验', (item) => status(item.waferStatus)]]);
  const differences = audit.wafers.filter((row) => row.status !== 'MATCH' || !row.balanced).map((row) => {
    const values = names.filter(([key]) => row.delta?.[key]).map(([key, name]) => {
      const delta = row.delta[key];
      return `${name} ${delta > 0 ? '+' : ''}${delta}`;
    });
    if (row.missing.length || row.extra.length) values.push(`缺 ${row.missing.join(' ') || '—'} · 多 ${row.extra.join(' ') || '—'}`);
    return [row.wafer, values.join('　') || labels[row.status]];
  });
  if (audit.unknown_reference.length) differences.push(['台账多片', audit.unknown_reference.join('、')]);
  q('#audit-differences').replaceChildren(differences.length ? pairs(differences) : status('MATCH'));
  q('#audit-rows').replaceChildren(status(audit.rows.balanced ? 'MATCH' : 'UNBALANCED'),
    pairs(Object.entries(rowNames).map(([key, name]) => [name, audit.rows[key]])));
  const filter = q('#reason-filter');
  options(filter, [['all', `全部 · ${audit.isolated.length}`], ...Object.entries(audit.reasons).map(([code,count]) => [code, `${code} · ${count}`])]);
  const draw = () => table(q('#audit-issues'), audit.isolated.filter((row) => filter.value === 'all' || row.code === filter.value), issueColumns, '当前图批无隔离行。');
  filter.addEventListener('change', draw, {signal});
  draw();
}

function runs({run, manifests, api, base, signal}) {
  text('#history-total', `${manifests.length} 批`);
  table(q('#history-rows'), manifests, [
    ['运行号', (item) => {
      const link = element('a', item.run_id.slice(0, 12), 'row-link');
      link.href = `/runs?${new URLSearchParams({run: item.run_id})}`;
      if (item.run_id === run.run_id) link.setAttribute('aria-current','true');
      return link;
    }], ['图批', 'lot', 'mono'], ['样例', 'label'], ['状态', (item) => status(item.status)],
    ['生成 UTC', 'created_at', 'mono'],
  ]);
  q('#run-manifest').replaceChildren(pairs([['运行号', run.run_id], ['规则版本', run.rule_version],
    ['计算耗时', `${run.duration_ms} ms`], ['晶圆', run.wafers.join('、')], ['契约 SHA-256', run.contract_sha256], ['结果 SHA-256', run.result_sha256]]));
  table(q('#run-sources'), Object.entries(run.sources).map(([name, value]) => ({name, ...value})), [
    ['图档', 'name', 'mono'], ['字节', 'bytes', 'num'], ['SHA-256', 'sha256', 'mono'],
  ]);
  const target = q('#run-recoveries');
  target.replaceChildren(element('p', '正在读取收回结论…', 'empty'));
  api(`${base}/recovery`).then((preview) => {
    if (signal.aborted) return;
    text('#run-recovery-total', `${preview.editions.length} 版`);
    if (!preview.editions.length) {
      target.replaceChildren(element('p', '本部图批尚未发布边缘收回结论。', 'empty'));
      return;
    }
    table(target, preview.editions, [
      ['结论号', (item) => {
        const link = element('a', item.recovery_id.slice(0, 12), 'row-link');
        link.href = `/edge?${new URLSearchParams({run: run.run_id, edition: item.recovery_id})}`;
        return link;
      }, 'mono'],
      ['收回', 'recovered', 'num'], ['保留', 'retained', 'num'],
      ['批良率 %', (item) => item.summary.yield_pct ?? '—', 'num'],
      ['状态', (item) => status(item.status)], ['生成 UTC', 'created_at', 'mono'],
    ]);
  }).catch((error) => { if (!signal.aborted) failure(target, error); });
}

const recoveryState = {picked: new Set(), preview: null, runId: null, signal: null};

function pointKey(cell) { return `${cell.wafer}|${cell.x}|${cell.y}`; }
function pointText(cell) { return `${cell.wafer} ${vector([cell.x, cell.y])}`; }

function drawCandidates() {
  const {preview, picked} = recoveryState;
  const rows = preview.cells.filter((cell) => cell.evidence.length || cell.recommend === 'RECOVER');
  text('#recovery-scope', `${preview.wafers.reduce((sum, wafer) => sum + wafer.edge_cells, 0)} 格 · 可收回 ${preview.recoverable.length} 枚`);
  table(q('#recovery-candidates'), rows, [
    ['收回', (cell) => {
      const box = element('input');
      box.type = 'checkbox';
      box.checked = picked.has(pointKey(cell));
      box.disabled = cell.recommend !== 'RECOVER';
      box.setAttribute('aria-label', `${pointText(cell)} ${labels[cell.state]}`);
      box.addEventListener('change', () => {
        if (box.checked) picked.add(pointKey(cell)); else picked.delete(pointKey(cell));
        drawCandidates();
        drawPicked();
      });
      return box;
    }],
    ['晶圆', 'wafer', 'mono'], ['坐标', (cell) => vector([cell.x, cell.y]), 'num'],
    ['复测状态', (cell) => status(cell.recommend === 'RECOVER' ? 'RECOVER' : cell.state)],
    ['末次', 'attempt', 'num'], ['分档', 'bin', 'num'],
    ['依据行', (cell) => cell.evidence_ids.join(' · ') || '—'],
    ['建议', (cell) => labels[cell.recommend]],
  ], '此片边缘保留带没有可复核的复测行。');
  q('#recovery-publish').disabled = picked.size === 0;
}

function drawPicked() {
  const {preview, picked} = recoveryState;
  const chosen = preview.cells.filter((cell) => picked.has(pointKey(cell)));
  text('#recovery-picked', `${chosen.length} 枚`);
  const target = q('#recovery-detail');
  if (!chosen.length) {
    target.replaceChildren(element('p', '勾选左侧芯粒以查看其复测链和原始行。', 'empty'));
    return;
  }
  const box = element('div');
  for (const cell of chosen) {
    const card = element('article', null, 'recovery-cell');
    card.append(element('div', null, 'detail-title'));
    const title = card.firstChild;
    title.append(element('strong', pointText(cell)), status('RECOVER'));
    const chain = cell.history.map((step) => `T${step.attempt} ${labels[step.result] ?? step.result}${step.bin ? ` / BIN ${step.bin}` : ''}`).join(' → ') || '无可采测次';
    card.append(element('p', `测次链：${chain}`, 'data-strip'));
    for (const row of cell.evidence) {
      const item = element('div', null, 'evidence-row');
      item.append(element('div', null, 'evidence-id'));
      item.firstChild.append(element('strong', `${row.source}:${row.line}`, 'mono'),
        element('span', row.usable ? '采信为收回依据' : `${row.code} · ${labels[row.code] ?? row.code}`));
      item.append(element('p', `T${row.attempt} ${row.result || '∅'} BIN ${row.bin || '∅'}${row.note ? `　${row.note}` : ''}`, 'evidence-values'));
      card.append(item);
    }
    box.append(card);
  }
  target.replaceChildren(box);
}

function drawRetained() {
  const {preview} = recoveryState;
  const rows = preview.cells.filter((cell) => cell.evidence.length && cell.recommend !== 'RECOVER');
  const noEvidence = preview.cells.filter((cell) => !cell.evidence.length).length;
  text('#recovery-retained-total', `有依据保留 ${rows.length} 枚 · 无复测依据 ${noEvidence} 枚整体保留`);
  table(q('#recovery-retained'), rows, [
    ['晶圆', 'wafer', 'mono'], ['坐标', (cell) => vector([cell.x, cell.y]), 'num'],
    ['状态', (cell) => status(cell.state)], ['末次', 'attempt', 'num'], ['分档', 'bin', 'num'],
    ['依据行', (cell) => cell.evidence_ids.join(' · ')],
    ['测次链', (cell) => cell.history.map((step) => `T${step.attempt} ${labels[step.result] ?? step.result}`).join(' → ')],
  ], '边缘保留带没有留下有复测依据的芯粒。');
}

function drawEditions(selectId) {
  const {preview} = recoveryState;
  const editions = preview.editions;
  text('#recovery-edition-total', `${editions.length} 版结论`);
  const box = q('#recovery-editions');
  if (!editions.length) {
    box.replaceChildren(element('p', '本部图批尚未发布边缘收回结论。', 'empty'));
    q('#recovery-conclusion').replaceChildren();
    return;
  }
  const list = element('div', null, 'edition-list');
  for (const edition of editions) {
    const button = element('button', null, 'row-link');
    button.type = 'button';
    button.dataset.recovery = edition.recovery_id;
    button.textContent = `${edition.recovery_id.slice(0, 12)} · ${edition.created_at.slice(0, 19).replace('T', ' ')} · 收回 ${edition.recovered}`;
    button.setAttribute('aria-pressed', String(edition.recovery_id === selectId));
    button.addEventListener('click', () => showEdition(edition.recovery_id));
    list.append(button);
  }
  box.replaceChildren(list);
  const active = selectId ?? editions[0].recovery_id;
  showEdition(active);
}

async function showEdition(recoveryId) {
  const {preview, runId, signal} = recoveryState;
  const target = q('#recovery-conclusion');
  target.replaceChildren(element('p', '正在读取结论…', 'empty'));
  try {
    const response = await fetch(`/api/runs/${runId}/recovery/${recoveryId}`, {signal});
    const data = await response.json();
    if (!response.ok) throw new Error(data?.message ?? '读取结论失败');
    if (signal.aborted) return;
    for (const button of q('#recovery-editions').querySelectorAll('button')) {
      button.setAttribute('aria-pressed', String(button.dataset.recovery === recoveryId));
    }
    const manifest = data.manifest;
    const detail = data.detail;
    const before = Object.fromEntries(preview.base.wafers.map((row) => [row.wafer, row]));
    const node = element('div', null, 'conclusion');
    node.append(pairs([['结论号', manifest.recovery_id], ['基准运行', manifest.run_id],
      ['收回', `${manifest.recovered} 枚`], ['保留（有依据）', `${manifest.retained} 枚`]]));
    const rows = detail.wafers.map((wafer) => ({...wafer,
      before_valid: before[wafer.wafer].valid, before_pass: before[wafer.wafer].passed,
      before_fail: before[wafer.wafer].failed, before_pending: before[wafer.wafer].pending,
      before_conflict: before[wafer.wafer].conflict,
      before_clusters: preview.base.clusters[wafer.wafer], before_yield: before[wafer.wafer].yield_pct}));
    const tableBox = element('div', null, 'detail-group');
    table(tableBox, rows, [
      ['晶圆', 'wafer', 'mono'], ['收回', 'recovered', 'num'], ['保留', 'retained_with_evidence', 'num'],
      ['有效 前→后', (row) => `${row.before_valid} → ${row.summary.valid}`, 'num'],
      ['通过 前→后', (row) => `${row.before_pass} → ${row.summary.passed}`, 'num'],
      ['失败 前→后', (row) => `${row.before_fail} → ${row.summary.failed}`, 'num'],
      ['待测 前→后', (row) => `${row.before_pending} → ${row.summary.pending}`, 'num'],
      ['冲突 前→后', (row) => `${row.before_conflict} → ${row.summary.conflict}`, 'num'],
      ['簇 前→后', (row) => `${row.before_clusters} → ${row.clusters}`, 'num'],
      ['良率 % 前→后', (row) => `${row.before_yield ?? '—'} → ${row.summary.yield_pct ?? '—'}`, 'num'],
      ['台账差', (row) => row.delta ? Object.entries(row.delta).filter(([,value]) => value).map(([key,value]) => `${key} ${value > 0 ? '+' : ''}${value}`).join(' ') || '无' : '缺台账'],
    ]);
    node.append(tableBox);
    const lot = element('div', null, 'pairs detail-group');
    lot.append(element('dt', '批良率 前→后'), element('dd', `${preview.base.summary.yield_pct ?? '—'}% → ${data.summary.yield_pct ?? '—'}%`, 'mono'));
    node.append(lot);
    const evidence = element('div', null, 'detail-group');
    evidence.append(element('h3', '收回芯粒依据行'));
    for (const cell of detail.recovered) {
      const card = element('article', null, 'recovery-cell');
      card.append(element('p', `${pointText(cell)} → ${labels[cell.result]} / BIN ${cell.bin}`, 'data-strip'));
      for (const id of cell.evidence) {
        const row = data.rows.find((item) => item.id === id);
        if (!row) continue;
        const source = row.raw.join(' · ');
        card.append(element('p', `${row.id}　${source}`, 'evidence-note'));
      }
      evidence.append(card);
    }
    node.append(evidence);
    const kept = detail.retained.filter((cell) => cell.evidence.length);
    if (kept.length) {
      const keep = element('div', null, 'detail-group');
      keep.append(element('h3', '仍应保留的边缘位'));
      table(keep, kept, [['晶圆', 'wafer', 'mono'], ['坐标', (cell) => vector([cell.x, cell.y]), 'num'],
        ['原因', 'reason'], ['依据行', (cell) => cell.evidence.join(' · ')]]);
      node.append(keep);
    }
    const link = element('a', '导出收回证据 ↓', 'btn link-btn');
    link.href = `/api/runs/${runId}/recovery/${manifest.recovery_id}/export`;
    node.append(link);
    target.replaceChildren(node);
  } catch (error) {
    if (!signal.aborted) failure(target, error);
  }
}

async function edgeView(context) {
  const {api, base, run, signal, params} = context;
  const preview = await api(`${base}/recovery`);
  recoveryState.preview = preview;
  recoveryState.runId = run.run_id;
  recoveryState.signal = signal;
  recoveryState.picked = new Set();
  drawCandidates();
  drawPicked();
  drawRetained();
  drawEditions(params.get('edition'));

  q('#recovery-select').addEventListener('click', () => {
    recoveryState.picked = new Set(preview.recoverable.map(([wafer,x,y]) => `${wafer}|${x}|${y}`));
    drawCandidates(); drawPicked();
  }, {signal});
  q('#recovery-clear').addEventListener('click', () => {
    recoveryState.picked.clear(); drawCandidates(); drawPicked();
  }, {signal});
  q('#recovery-publish').addEventListener('click', async () => {
    const button = q('#recovery-publish');
    button.disabled = true;
    button.textContent = '正在发布…';
    try {
      const selection = [...recoveryState.picked].map((key) => key.split('|')).map(([wafer, x, y]) => [wafer, Number(x), Number(y)]);
      const response = await fetch(`${base}/recovery`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({selection}), signal});
      const data = await response.json();
      if (!response.ok) throw new Error(data?.message ?? '发布失败');
      const refreshed = await api(`${base}/recovery`);
      recoveryState.preview = refreshed;
      drawEditions(data.manifest.recovery_id);
      q('#feedback').hidden = false;
      q('#feedback').classList.remove('error');
      q('#feedback').textContent = data.reused ? '相同收回选择已归档，复用原结论。' : '收回结论已发布。';
    } catch (error) {
      if (!signal.aborted) failure(q('#recovery-conclusion'), error);
    } finally {
      button.textContent = '发布收回结论';
      button.disabled = recoveryState.picked.size === 0;
    }
  }, {signal});
}

export const views = {intake, coordinates, retest, clusters, yield: auditView, edge: edgeView, runs};
