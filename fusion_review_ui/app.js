const CLASS_COLORS = {
  agreed_by_all: '#157f3b',
  agreed_by_two: '#1f6feb',
  unique_to_one: '#9a6700',
  conflicting: '#c93c37',
};

let state = {
  data: null,
  filteredRegions: [],
  activeRegionId: null,
  activeRowId: null,
  visibleZones: new Set(),
};

function el(id) {
  return document.getElementById(id);
}

function escapeHtml(text) {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function classificationTag(value) {
  const color = CLASS_COLORS[value] || '#6b7280';
  return `<span class="classification-tag" style="background:${color}">${escapeHtml(value)}</span>`;
}

function rowConfidenceColor(confidence) {
  const value = Number(confidence || 0);
  if (value >= 0.85) return '#157f3b';
  if (value >= 0.65) return '#1f6feb';
  if (value >= 0.45) return '#9a6700';
  return '#c93c37';
}

function fillSelect(selectId, values, includeAll = true) {
  const select = el(selectId);
  const current = select.value;
  const options = [];
  if (includeAll) {
    options.push('<option value="">All</option>');
  }
  values.forEach((value) => {
    options.push(`<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`);
  });
  select.innerHTML = options.join('');
  if ([...select.options].some((opt) => opt.value === current)) {
    select.value = current;
  }
}

function buildPageSelect(pages) {
  const select = el('page-filter');
  const current = select.value;
  const options = pages.map((page) => `<option value="${page.page}">Page ${page.page}</option>`);
  select.innerHTML = options.join('');
  if ([...select.options].some((opt) => opt.value === current)) {
    select.value = current;
  } else if (pages.length) {
    select.value = String(pages[0].page);
  }
}

function confidenceValue(region) {
  return typeof region.confidence_score === 'number' ? region.confidence_score : 0;
}

function visibleZoneSet() {
  const checked = [...document.querySelectorAll('.zone-toggle')]
    .filter((input) => input.checked)
    .map((input) => input.value);
  return new Set(checked);
}

function renderZoneVisibility(zones) {
  const container = el('zone-visibility');
  if (!state.visibleZones.size) {
    zones.forEach((zone) => state.visibleZones.add(zone));
  }
  container.innerHTML = zones.map((zone) => `
    <label class="checkbox">
      <input class="zone-toggle" type="checkbox" value="${escapeHtml(zone)}" ${state.visibleZones.has(zone) ? 'checked' : ''}>
      ${escapeHtml(zone)}
    </label>
  `).join('');
  container.querySelectorAll('.zone-toggle').forEach((input) => {
    input.addEventListener('change', () => {
      state.visibleZones = visibleZoneSet();
      applyFilters();
    });
  });
}

function applyFilters() {
  const page = Number(el('page-filter').value || 0);
  const classification = el('classification-filter').value;
  const category = el('category-filter').value;
  const zone = el('zone-filter').value;
  const suggestedZone = el('suggested-zone-filter').value;
  const engine = el('engine-filter').value;
  const minConfidence = Number(el('confidence-min').value || 0);
  const maxConfidence = Number(el('confidence-max').value || 1);
  const conflictsOnly = el('conflicts-only').checked;
  const visibleZones = state.visibleZones.size ? state.visibleZones : new Set(state.data.summary.zones);

  const regions = state.data.regions.filter((region) => {
    if (page && region.page !== page) return false;
    if (classification && region.classification !== classification) return false;
    if (category && !region.category_labels.includes(category)) return false;
    if (zone && region.zone !== zone) return false;
    if (suggestedZone && region.suggested_zone !== suggestedZone) return false;
    if (!visibleZones.has(region.zone || 'unknown')) return false;
    if (engine && !region.source_engines_present.includes(engine)) return false;
    const confidence = confidenceValue(region);
    if (confidence < minConfidence || confidence > maxConfidence) return false;
    if (conflictsOnly && region.classification !== 'conflicting') return false;
    return true;
  });

  state.filteredRegions = regions;
  if (!regions.some((region) => region.region_id === state.activeRegionId)) {
    state.activeRegionId = regions[0]?.region_id || null;
  }
  const visibleRowIds = new Set(((state.data.table_rows || []).filter((row) => row.page === page)).map((row) => row.row_id));
  if (!visibleRowIds.has(state.activeRowId)) {
    state.activeRowId = [...visibleRowIds][0] || null;
  }
  renderViewerSummary();
  renderOverlay();
  renderRegionList();
  renderConflictList();
  renderDetail();
  renderRowList();
  renderRowDetail();
}

function renderHeader() {
  const summary = state.data.summary;
  el('run-meta').textContent = summary.run_dir;
  const badge = el('environment-badge');
  badge.textContent = summary.environment_label || (summary.environment || '').toUpperCase();
  badge.className = `environment-badge env-${summary.environment || 'unknown'}`;
  const counts = state.data.summary.counts;
  el('run-counts').innerHTML = `
    <span class="count-pill">Fused ${counts.fused_regions}</span>
    <span class="count-pill">Conflicts ${counts.conflicts}</span>
    <span class="count-pill">Unique ${counts.unique_regions}</span>
    <span class="count-pill">Table Bands ${counts.table_bands || 0}</span>
    <span class="count-pill">Rows ${counts.table_rows || 0}</span>
  `;
}

function renderViewerSummary() {
  const page = el('page-filter').value;
  const filteredCount = state.filteredRegions.length;
  const pageBand = (state.data.table_bands || []).find((band) => String(band.page) === String(page));
  const pageRows = (state.data.table_rows || []).filter((row) => String(row.page) === String(page));
  el('viewer-summary').innerHTML = `
    <div><strong>Page ${page}</strong> ${filteredCount} visible regions</div>
    ${pageBand ? `<div><strong>Table band</strong> ${escapeHtml(pageBand.confidence || '')} (${escapeHtml(String(pageBand.confidence_score || ''))})</div>` : ''}
    ${pageBand ? `<div class="viewer-note">${escapeHtml((pageBand.reasons || []).join(' | '))}</div>` : ''}
    ${pageRows.length ? `<div><strong>Candidate rows</strong> ${pageRows.length}</div>` : ''}
    <div class="legend">
      ${Object.entries(CLASS_COLORS).map(([key, color]) => `
        <span class="legend-item"><span class="legend-swatch" style="background:${color}"></span>${key}</span>
      `).join('')}
    </div>
  `;
}

function getActiveRegion() {
  return state.data.regions.find((region) => region.region_id === state.activeRegionId) || null;
}

function getActiveRow() {
  return (state.data.table_rows || []).find((row) => row.row_id === state.activeRowId) || null;
}

function setActiveRegion(regionId) {
  state.activeRegionId = regionId;
  renderOverlay();
  renderRegionList();
  renderConflictList();
  renderDetail();
  renderRowList();
  renderRowDetail();
}

function setActiveRow(rowId) {
  state.activeRowId = rowId;
  const row = getActiveRow();
  if (row && row.source_region_ids?.length && !row.source_region_ids.includes(state.activeRegionId)) {
    state.activeRegionId = row.source_region_ids[0];
  }
  renderOverlay();
  renderRegionList();
  renderConflictList();
  renderDetail();
  renderRowList();
  renderRowDetail();
}

function renderOverlay() {
  const page = Number(el('page-filter').value || 0);
  const pageMeta = state.data.summary.pages.find((item) => item.page === page);
  el('page-image').src = pageMeta?.image_url || '';
  const overlay = el('overlay');
  overlay.innerHTML = '';
  const pageBand = (state.data.table_bands || []).find((band) => band.page === page);
  if (pageBand && pageBand.normalized_bbox) {
    const bandRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    const bandWidth = (pageBand.normalized_bbox.x2 - pageBand.normalized_bbox.x1) * 100;
    const bandHeight = (pageBand.normalized_bbox.y2 - pageBand.normalized_bbox.y1) * 100;
    bandRect.setAttribute('x', `${pageBand.normalized_bbox.x1 * 100}%`);
    bandRect.setAttribute('y', `${pageBand.normalized_bbox.y1 * 100}%`);
    bandRect.setAttribute('width', `${bandWidth}%`);
    bandRect.setAttribute('height', `${bandHeight}%`);
    bandRect.setAttribute('fill', 'rgba(31,111,235,0.10)');
    bandRect.setAttribute('stroke', '#1f6feb');
    bandRect.setAttribute('stroke-width', '4');
    bandRect.setAttribute('stroke-dasharray', '10 8');
    overlay.appendChild(bandRect);
  }
  const showRows = el('show-rows')?.checked;
  if (showRows) {
    const pageRows = (state.data.table_rows || []).filter((row) => row.page === page);
    pageRows.forEach((row) => {
      const rowBox = row.normalized_row_bbox || row.row_bbox_normalized;
      if (!rowBox) return;
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      const width = (rowBox.x2 - rowBox.x1) * 100;
      const height = (rowBox.y2 - rowBox.y1) * 100;
      rect.setAttribute('x', `${rowBox.x1 * 100}%`);
      rect.setAttribute('y', `${rowBox.y1 * 100}%`);
      rect.setAttribute('width', `${width}%`);
      rect.setAttribute('height', `${height}%`);
      rect.setAttribute('fill', row.row_id === state.activeRowId ? 'rgba(21,127,59,0.12)' : 'rgba(0,0,0,0)');
      rect.setAttribute('stroke', rowConfidenceColor(row.row_confidence));
      rect.setAttribute('stroke-width', row.row_id === state.activeRowId ? '4' : '2');
      rect.setAttribute('stroke-dasharray', row.row_id === state.activeRowId ? '0' : '7 5');
      rect.style.cursor = 'pointer';
      rect.addEventListener('click', () => setActiveRow(row.row_id));
      overlay.appendChild(rect);
    });
  }
  const pageRegions = state.filteredRegions.filter((region) => region.page === page);
  pageRegions.forEach((region) => {
    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    const width = region.normalized_bbox ? (region.normalized_bbox.x2 - region.normalized_bbox.x1) * 100 : 0;
    const height = region.normalized_bbox ? (region.normalized_bbox.y2 - region.normalized_bbox.y1) * 100 : 0;
    rect.setAttribute('x', `${(region.normalized_bbox?.x1 || 0) * 100}%`);
    rect.setAttribute('y', `${(region.normalized_bbox?.y1 || 0) * 100}%`);
    rect.setAttribute('width', `${width}%`);
    rect.setAttribute('height', `${height}%`);
    rect.setAttribute('fill', 'rgba(0,0,0,0)');
    rect.setAttribute('stroke', CLASS_COLORS[region.classification] || '#6b7280');
    rect.setAttribute('stroke-width', region.region_id === state.activeRegionId ? '4' : '2');
    rect.style.cursor = 'pointer';
    rect.addEventListener('click', () => setActiveRegion(region.region_id));
    overlay.appendChild(rect);
  });
}

function renderRegionList() {
  const container = el('region-list');
  const activeRow = getActiveRow();
  container.innerHTML = state.filteredRegions.map((region) => `
    <div class="region-card ${region.region_id === state.activeRegionId ? 'active' : ''} ${activeRow?.source_region_ids?.includes(region.region_id) ? 'member-of-row' : ''}" data-region-id="${region.region_id}">
      <div><strong>${escapeHtml(region.region_id)}</strong></div>
      <div>${classificationTag(region.classification)}</div>
      <div>Zone: ${escapeHtml(region.zone || 'unknown')}</div>
      <div>Suggested: ${escapeHtml(region.suggested_zone || '')}</div>
      <div>Categories: ${escapeHtml(region.category_labels.join(', '))}</div>
      <div>Engines: ${escapeHtml(region.source_engines_present.join(', '))}</div>
      <div>Candidate: ${escapeHtml(region.normalized_candidate_text || '')}</div>
    </div>
  `).join('');
  container.querySelectorAll('.region-card').forEach((node) => {
    node.addEventListener('click', () => setActiveRegion(node.dataset.regionId));
  });
}

function renderRowList() {
  const container = el('row-list');
  const page = Number(el('page-filter').value || 0);
  const rows = (state.data.table_rows || []).filter((row) => row.page === page);
  if (!rows.length) {
    container.innerHTML = '<p>No candidate rows for this page.</p>';
    return;
  }
  container.innerHTML = rows.map((row) => `
    <div class="row-card ${row.row_id === state.activeRowId ? 'active' : ''}" data-row-id="${row.row_id}">
      <div><strong>${escapeHtml(row.row_id)}</strong></div>
      <div>Confidence: <span style="color:${rowConfidenceColor(row.row_confidence)}">${escapeHtml(String(row.row_confidence || ''))}</span></div>
      <div>Regions: ${escapeHtml(String(row.region_count || 0))}</div>
      <div>Conflicts: ${escapeHtml(String(row.conflict_count || 0))}</div>
      <div>${escapeHtml((row.notes || []).slice(0, 2).join(' | '))}</div>
    </div>
  `).join('');
  container.querySelectorAll('.row-card').forEach((node) => {
    node.addEventListener('click', () => setActiveRow(node.dataset.rowId));
  });
}

function renderConflictList() {
  const container = el('conflict-list');
  const page = Number(el('page-filter').value || 0);
  const conflicts = state.data.regions.filter((region) => region.page === page && region.classification === 'conflicting');
  container.innerHTML = conflicts.map((region) => `
    <div class="conflict-card ${region.region_id === state.activeRegionId ? 'active' : ''}" data-region-id="${region.region_id}">
      <div><strong>${escapeHtml(region.region_id)}</strong></div>
      <div>Zone: ${escapeHtml(region.zone || 'unknown')}</div>
      <div>Suggested: ${escapeHtml(region.suggested_zone || '')}</div>
      <div>${escapeHtml(region.category_labels.join(', '))}</div>
      <div>Paddle: ${escapeHtml(region.raw_candidates.paddle?.text || '')}</div>
      <div>EasyOCR: ${escapeHtml(region.raw_candidates.easyocr?.text || '')}</div>
      <div>Tesseract: ${escapeHtml(region.raw_candidates.tesseract?.text || '')}</div>
    </div>
  `).join('');
  container.querySelectorAll('.conflict-card').forEach((node) => {
    node.addEventListener('click', () => setActiveRegion(node.dataset.regionId));
  });
}

function renderDetail() {
  const region = getActiveRegion();
  const detail = el('region-detail');
  const engineSelect = el('selected-engine');
  if (!region) {
    detail.innerHTML = '<p>No region selected.</p>';
    engineSelect.innerHTML = '';
    el('selected-text').value = '';
    el('review-status').value = '';
    el('review-notes').value = '';
    return;
  }

  const candidates = Object.entries(region.raw_candidates || {});
  const reviewDecision = region.review_decision || {};
  const candidateOptions = ['<option value="">Choose</option>']
    .concat(candidates.map(([engine]) => `<option value="${escapeHtml(engine)}">${escapeHtml(engine)}</option>`));
  engineSelect.innerHTML = candidateOptions.join('');
  if (reviewDecision.selected_candidate_engine) {
    engineSelect.value = reviewDecision.selected_candidate_engine;
  }
  const prefilledText = reviewDecision.selected_candidate_text
    || region.raw_candidates[engineSelect.value]?.text
    || region.normalized_candidate_text
    || '';
  el('selected-text').value = prefilledText;
  el('review-status').value = reviewDecision.review_status || '';
  el('review-notes').value = reviewDecision.review_notes || '';

  const candidateHtml = candidates.map(([engine, candidate]) => `
    <div class="candidate-row">
      <strong>${escapeHtml(engine)}</strong>
      <div>Confidence: ${escapeHtml(candidate.confidence ?? '')}</div>
      <pre>${escapeHtml(candidate.text || '')}</pre>
    </div>
  `).join('');

  detail.innerHTML = `
    <div><strong>Region ID</strong><div>${escapeHtml(region.region_id)}</div></div>
    <div><strong>Page</strong><div>${escapeHtml(region.page)}</div></div>
    <div><strong>Classification</strong><div>${classificationTag(region.classification)}</div></div>
    <div><strong>Zone</strong><div>${escapeHtml(region.zone || 'unknown')} (${escapeHtml(region.zone_confidence || 'n/a')})</div></div>
    <div><strong>Suggested Zone</strong><div>${escapeHtml(region.suggested_zone || '')}</div></div>
    <div><strong>Normalized coordinates</strong><pre>${escapeHtml(JSON.stringify(region.normalized_bbox, null, 2))}</pre></div>
    <div><strong>Category labels</strong><div>${escapeHtml(region.category_labels.join(', '))}</div></div>
    <div><strong>Source engines</strong><div>${escapeHtml(region.source_engines_present.join(', '))}</div></div>
    <div><strong>Relative y-band</strong><div>${escapeHtml(region.relative_y_band || '')}</div></div>
    <div><strong>Zone reasons</strong><div>${escapeHtml((region.zone_reasons || []).join('; '))}</div></div>
    <div><strong>Why Unknown</strong><div>${escapeHtml(region.why_unknown || '')}</div></div>
    <div><strong>Raw candidates</strong>${candidateHtml}</div>
  `;
}

function renderRowDetail() {
  const row = getActiveRow();
  const detail = el('row-detail');
  if (!row) {
    detail.innerHTML = '<p>No row selected.</p>';
    return;
  }
  const engines = Object.entries(row.candidate_texts_by_engine || {}).map(([engine, payload]) => `
    <div class="candidate-row">
      <strong>${escapeHtml(engine)}</strong>
      <div>Conflicts represented: ${escapeHtml(String(payload.conflict_count || 0))}</div>
      <pre>${escapeHtml((payload.candidates || []).join('\n'))}</pre>
    </div>
  `).join('');
  detail.innerHTML = `
    <div><strong>Row ID</strong><div>${escapeHtml(row.row_id)}</div></div>
    <div><strong>Page</strong><div>${escapeHtml(String(row.page))}</div></div>
    <div><strong>Confidence</strong><div style="color:${rowConfidenceColor(row.row_confidence)}">${escapeHtml(String(row.row_confidence || ''))} (${escapeHtml(row.row_confidence_level || '')})</div></div>
    <div><strong>Row bbox</strong><pre>${escapeHtml(JSON.stringify(row.row_bbox, null, 2))}</pre></div>
    <div><strong>Region count</strong><div>${escapeHtml(String(row.region_count || 0))}</div></div>
    <div><strong>Conflict count</strong><div>${escapeHtml(String(row.conflict_count || 0))}</div></div>
    <div><strong>Source regions</strong><div>${escapeHtml((row.source_region_ids || []).join(', '))}</div></div>
    <div><strong>Notes</strong><div>${escapeHtml((row.notes || []).join('; '))}</div></div>
    <div><strong>Candidate texts by engine</strong>${engines}</div>
  `;
}

async function saveDecision(event) {
  event.preventDefault();
  const region = getActiveRegion();
  if (!region) return;
  const engine = el('selected-engine').value;
  const payload = {
    region_id: region.region_id,
    page: region.page,
    selected_candidate_engine: engine,
    selected_candidate_text: el('selected-text').value,
    review_status: el('review-status').value,
    review_notes: el('review-notes').value,
  };
  const response = await fetch('/api/review-decisions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  const decision = result.decisions.find((item) => item.region_id === region.region_id);
  const target = state.data.regions.find((item) => item.region_id === region.region_id);
  if (target) {
    target.review_decision = decision;
  }
  el('save-status').textContent = response.ok ? `Saved ${decision.saved_at}` : 'Save failed';
  renderDetail();
}

function bindEvents() {
  ['page-filter', 'classification-filter', 'category-filter', 'zone-filter', 'suggested-zone-filter', 'engine-filter', 'confidence-min', 'confidence-max', 'conflicts-only', 'show-rows']
    .forEach((id) => el(id).addEventListener('change', applyFilters));
  el('selected-engine').addEventListener('change', () => {
    const region = getActiveRegion();
    const engine = el('selected-engine').value;
    if (region && engine && region.raw_candidates[engine]) {
      el('selected-text').value = region.raw_candidates[engine].text || '';
    }
  });
  el('decision-form').addEventListener('submit', saveDecision);
}

async function init() {
  const response = await fetch('/api/data');
  state.data = await response.json();
  renderHeader();
  buildPageSelect(state.data.summary.pages);
  fillSelect('classification-filter', state.data.summary.classifications);
  fillSelect('category-filter', state.data.summary.category_labels);
  fillSelect('zone-filter', state.data.summary.zones);
  fillSelect('suggested-zone-filter', state.data.summary.suggested_zones);
  fillSelect('engine-filter', state.data.summary.engines);
  renderZoneVisibility(state.data.summary.zones);
  bindEvents();
  applyFilters();
}

init();
