(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const text = value => value === null || value === undefined || value === '' ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value);
  const labels = {product_code:'รหัสสินค้าบริษัท',sku:'รหัสสินค้าบริษัท',supplier_code:'รหัสสินค้าบนใบ',description:'ชื่อสินค้าบนเอกสาร',product_name:'ชื่อสินค้า',quantity:'จำนวน',unit:'หน่วย',lot:'เลขล็อต',lot_number:'เลขล็อต',mfg_date:'วันผลิต',exp_date:'วันหมดอายุ',expiry_date:'วันหมดอายุ',invoice_number:'เลขที่เอกสาร',invoice_date:'วันที่เอกสาร',receiving_date:'วันที่รับจริง',location:'สถานที่รับ',unit_price:'ราคาต่อหน่วย',amount:'จำนวนเงิน',pack_count:'จำนวนต่อบรรจุภัณฑ์',line_kind:'ประเภทรายการ'};
  const state = {config:null, document:null, documentId:null, pageId:null, rowId:null, field:null, filter:'all', zoom:false, frameReady:false, generation:0, poll:null, busy:false, imageSize:null, drafts:{},completenessRevision:null};
  const FIELD_ORDER = ['product_code','sku','description','quantity','unit','lot','lot_number','mfg_date','exp_date','expiry_date','invoice_number','invoice_date','receiving_date','location','unit_price','amount'];
  const title = key => labels[key] || key;
  const asset = (documentId, assetId) => `/api/documents/${encodeURIComponent(documentId)}/assets/${encodeURIComponent(assetId)}`;
  const excluded = row => row.decision === 'excluded';
  const goods = row => ['purchase','free'].includes(row.line_kind);
  const rowState = row => excluded(row) ? 'excluded' : ['approved','approve','corrected','correct'].includes(row.decision) ? 'approved' : ['held','hold'].includes(row.decision) || (row.issues || []).length ? 'issue' : 'pending';
  const decided = row => excluded(row) || rowState(row) === 'approved';
  const rowStateLabel = row => excluded(row) ? 'ไม่นับเป็นสินค้า' : ['corrected','correct'].includes(row.decision) ? 'แก้ไขและยืนยันแล้ว' : decided(row) ? 'ยืนยันแล้ว' : ['held','hold'].includes(row.decision) ? 'พักไว้ รอหลักฐาน' : (row.issues || []).length ? 'มีประเด็นให้ตรวจ' : 'รอยืนยัน';
  const processing = document => ['queued','processing','preparing'].includes(document.status);
  const statusLabel = status => ({queued:'รอระบบเตรียมเอกสาร',processing:'กำลังเตรียมเอกสาร',preparing:'กำลังเตรียมเอกสาร',review:'พร้อมตรวจครั้งสุดท้าย',approved:'ยืนยันข้อมูลเอกสารแล้ว',exported:'ส่งออกข้อมูลที่ยืนยันแล้ว',failed:'เตรียมเอกสารไม่สำเร็จ',held:'มีรายการรอหลักฐาน'}[status] || status || 'รอเตรียมข้อมูล');

  async function request(url, options = {}) {
    const headers = {...(options.headers || {})};
    if (options.method && options.method !== 'GET') headers['X-Document-AI-Client'] = 'final-review-v1';
    const response = await fetch(url, {...options, headers, credentials:'same-origin', cache:'no-store'});
    let value;
    try { value = await response.json(); } catch (_) { throw new Error('เปิดข้อมูลไม่ได้ กรุณาลองใหม่'); }
    if (!response.ok) {
      const error = new Error(value.error?.message || 'ดำเนินการไม่สำเร็จ');
      error.code = value.error?.code;
      throw error;
    }
    return value;
  }
  function alert(message = '') {
    $('alert').textContent = message;
    $('alert').classList.toggle('hidden', !message);
  }
  function stopPolling() { if (state.poll) clearTimeout(state.poll); state.poll = null; }
  function draftKey(rowId) { return `document-ai-review-draft-v1:${state.documentId}:${rowId}`; }
  function draftFor(row) {
    const key = draftKey(row.id);
    if (!state.drafts[key]) {
      let draft = null;
      try { draft = JSON.parse(localStorage.getItem(key) || 'null'); } catch (_) {}
      state.drafts[key] = draft && draft.revision === state.document.revision ? draft : {revision:state.document.revision, values:{}, note:row.note || '', dirty:false};
    }
    return state.drafts[key];
  }
  function saveDraft(row) {
    const draft = draftFor(row);
    try { localStorage.setItem(draftKey(row.id), JSON.stringify(draft)); } catch (_) {}
  }
  function clearDraft(row) {
    delete state.drafts[draftKey(row.id)];
    try { localStorage.removeItem(draftKey(row.id)); } catch (_) {}
  }
  function currentPage() { return (state.document?.pages || []).find(p => String(p.id) === String(state.pageId)); }
  function currentRow() { return (state.document?.rows || []).find(r => String(r.id) === String(state.rowId)); }
  function pageRows() { return (state.document?.rows || []).filter(r => String(r.page_id) === String(state.pageId)); }
  function visibleRows() {
    return pageRows().filter(r => state.filter === 'all' || state.filter === 'approved' && rowState(r) === 'approved' || state.filter === 'excluded' && excluded(r) || state.filter === 'pending' && !decided(r) || state.filter === 'issues' && rowState(r) === 'issue');
  }
  function fields(row) {
    return Object.entries(row.fields || {}).sort(([a],[b]) => {
      const ai = FIELD_ORDER.indexOf(a), bi = FIELD_ORDER.indexOf(b);
      return (ai < 0 ? 100 : ai) - (bi < 0 ? 100 : bi) || a.localeCompare(b);
    });
  }
  function rowName(row) {
    if(excluded(row))return 'ข้อความที่ไม่นับเป็นสินค้า';
    if(row.line_kind==='context')return 'หัวเอกสาร / ตรวจรายการตกหล่น';
    const values = row.fields || {};
    return text(values.description?.final ?? values.description?.normalized ?? values.description?.raw ?? values.product_name?.final ?? values.product_name?.normalized ?? values.product_code?.final ?? values.product_code?.normalized ?? values.product_code?.raw);
  }
  function issues(row) { const known={human_added_missing_row:'คุณเพิ่มรายการนี้จากต้นฉบับ กรุณาตรวจและยืนยันข้อมูลอีกครั้ง',synthetic_demo_confirmation:'ตัวอย่างสาธิต: ลองยืนยันรหัสสินค้าในรายการนี้จากภาพจำลองก่อนส่งออก',lot_multiple_candidates:'พบเลขล็อตได้มากกว่าหนึ่งค่า ต้องเทียบว่าเลขใดเป็นของสินค้าบรรทัดนี้',lot_missing:'ยังอ่านเลขล็อตของสินค้าบรรทัดนี้ไม่ได้',mfg_and_exp_missing:'ยังอ่านวันผลิตและวันหมดอายุไม่ได้ ต้องตรวจจากต้นฉบับ',low_ocr_confidence:'เครื่องอ่านตัวอักษรไม่มั่นใจ ต้องเทียบข้อความในภาพ',human_review_required:'ต้องตรวจข้อมูลกับต้นฉบับก่อนยืนยัน',secondary_read_row_owner_not_unique:'ผลอ่านซ้ำยังระบุไม่ได้ชัดว่าเป็นของแถวใด จึงยังไม่ใช้เติมข้อมูล'};return (row.issues || []).map(i => {const code=typeof i==='string'?i:i.code;return known[code]||(typeof i==='object'&&i.message)||`ต้องตรวจเพิ่มเติมจากต้นฉบับ (รหัสประเด็น: ${code||'ไม่ระบุ'})`;}); }

  async function listDocuments() {
    try {
      const value = await request('/api/documents');
      const documents = value.documents;
      if (!Array.isArray(documents)) throw new Error('รูปแบบรายการเอกสารไม่ถูกต้อง');
      $('document-list').innerHTML = documents.length ? documents.map((d,i) => `<article class="document-card"><div class="details"><h3>${escape(d.filename || 'เอกสาร')}</h3><span class="badge ${d.status === 'failed' ? 'issue' : ['approved','exported'].includes(d.status) ? 'approved' : 'pending'}">${escape(statusLabel(d.status))}</span><span class="small"> ${escape(d.created_at || '')}</span></div><button data-open-document="${i}">เปิดเอกสาร</button></article>`).join('') : '<div class="empty">ยังไม่มีเอกสาร วางไฟล์ด้านบนเพื่อเริ่มได้เลย</div>';
      $('document-list').querySelectorAll('[data-open-document]').forEach(button => button.onclick = () => openDocument(documents[Number(button.dataset.openDocument)].id));
    } catch (error) { alert(error.message); }
  }
  async function openDocument(id) {
    stopPolling();
    state.documentId = String(id); state.pageId = null; state.rowId = null; state.field = null; state.zoom = false;
    $('inbox-view').classList.add('hidden'); $('document-view').classList.remove('hidden'); alert();
    await loadDocument();
  }
  async function loadDocument() {
    const id = state.documentId;
    try {
      const document = await request(`/api/documents/${encodeURIComponent(id)}`);
      if (state.documentId !== id) return;
      state.document = document;
      renderDocument();
      if (processing(document)) state.poll = setTimeout(loadDocument, 2000);
      else stopPolling();
    } catch (error) { if (state.documentId === id) alert(error.message); }
  }
  async function uploadFile(file) {
    if (!file || state.busy) return;
    if (file.size > state.config.max_upload_bytes) { alert('ไฟล์ใหญ่เกินขนาดที่รับได้ กรุณาแยกไฟล์ก่อน'); return; }
    state.busy = true; $('drop-zone').classList.add('busy'); $('file-input').disabled = true;
    $('upload-status').textContent = `กำลังรับไฟล์ ${file.name}…`; alert();
    try {
      const document = await request(`/api/documents?filename=${encodeURIComponent(file.name)}`, {method:'POST', headers:{'Content-Type':file.type || 'application/octet-stream'}, body:file});
      $('upload-status').textContent = 'รับต้นฉบับแล้ว ระบบกำลังเตรียมข้อมูล';
      await openDocument(document.id);
    } catch (error) { alert(error.message); $('upload-status').textContent = 'ยังรับเอกสารไม่สำเร็จ'; }
    finally { state.busy = false; $('drop-zone').classList.remove('busy'); $('file-input').disabled = false; $('file-input').value = ''; }
  }
  function renderDocument() {
    const document = state.document;
    const completenessRevision=`${document.id}:${document.revision}`;
    if(state.completenessRevision!==completenessRevision){$('completeness-confirmed').checked=false;state.completenessRevision=completenessRevision;}
    $('document-title').textContent = document.filename || 'เอกสาร';
    $('document-status').textContent = statusLabel(document.status);
    $('processing-message').classList.toggle('hidden', !processing(document));
    if (document.status === 'failed') alert(document.error?.message || document.error || 'ระบบเตรียมเอกสารไม่สำเร็จ ต้นฉบับยังถูกเก็บไว้');
    const pages = document.pages || [];
    if (!pages.some(p => String(p.id) === String(state.pageId))) state.pageId = pages[0]?.id ?? null;
    const availableRows = pageRows();
    if (!availableRows.some(r => String(r.id) === String(state.rowId))) state.rowId = availableRows.find(r => !decided(r))?.id ?? availableRows[0]?.id ?? null;
    const rows = document.rows || [], resolved = rows.filter(decided).length, held = rows.filter(r => ['held','hold'].includes(r.decision)).length, goodsCount=rows.filter(goods).length, excludedCount=rows.filter(excluded).length, contextCount=rows.length-goodsCount-excludedCount;
    $('document-summary').innerHTML = `<span><strong>${rows.length}</strong>แถวทั้งหมด</span><span><strong>${goodsCount}</strong>แถวสินค้า / ของแถม</span><span><strong>${contextCount}</strong>ข้อความประกอบ</span><span><strong>${excludedCount}</strong>ไม่นับเป็นสินค้า</span><span><strong>${resolved}</strong>ตัดสินแล้ว</span><span><strong>${rows.length-resolved}</strong>ยังไม่ตัดสิน</span>${held ? `<span><strong>${held}</strong>พักไว้</span>` : ''}`;
    updateExportState();
    $('page-select').innerHTML = pages.length ? pages.map(p => `<option value="${escape(p.id)}">หน้า ${escape(p.number)}</option>`).join('') : '<option value="">ยังไม่มีภาพหน้าเอกสาร</option>';
    $('page-select').value = state.pageId ?? '';
    const index = pages.findIndex(p => String(p.id) === String(state.pageId));
    $('previous-page').disabled = index <= 0; $('next-page').disabled = index < 0 || index >= pages.length-1;
    $('row-filter').value = state.filter;
    renderRows(); renderRow(); renderPage();
    $('add-row-submit').disabled=processing(document)||!state.pageId;
  }
  function updateExportState(){
    const document=state.document,rows=document?.rows||[],approved=rows.filter(decided).length;
    $('export-document').disabled=!document||processing(document)||document.summary?.exportable!==true||!rows.length||approved!==rows.length||!$('completeness-confirmed').checked;
    $('export-document').title=approved!==rows.length?'ต้องยืนยันรายการทั้งหมดและแก้ข้อค้างก่อนส่งออก':!$('completeness-confirmed').checked?'ตรวจเทียบต้นฉบับครบทุกหน้าก่อนส่งออก':'ดาวน์โหลดข้อมูลเอกสารที่ยืนยันแล้ว พร้อมหลักฐาน';
  }
  function selectPage(id) {
    state.pageId = id; state.rowId = null; state.field = null; state.zoom = false;
    renderDocument();
  }
  function renderRows() {
    const rows = visibleRows(), all = pageRows();
    $('row-list').innerHTML = rows.length ? rows.map((row,i) => `<button class="row-button ${rowState(row)}" data-select-row="${i}" aria-pressed="${String(row.id) === String(state.rowId)}"><strong>${all.indexOf(row)+1}. ${escape(rowName(row))}</strong><span class="small">${escape(rowStateLabel(row))}${row.line_kind === 'free' || row.line_kind === 'bonus' ? ' · ของแถม' : ''}</span></button>`).join('') : `<p class="empty">${processing(state.document) ? 'รายการจะปรากฏเมื่อระบบเตรียมเสร็จ' : 'ไม่มีรายการในตัวกรองนี้'}</p>`;
    $('row-list').querySelectorAll('[data-select-row]').forEach(button => button.onclick = () => selectRow(rows[Number(button.dataset.selectRow)].id));
  }
  function selectRow(id, field = null) {
    state.rowId = id; state.field = field; state.zoom = false;
    renderRows(); renderRow(); drawPage();
    if (innerWidth <= 1050) $('row-detail').scrollIntoView({block:'start'});
  }
  function validBox(field, page) {
    const b = field.bbox;
    return state.frameReady && field.bbox_frame === 'original_image' && Array.isArray(b) && b.length === 4 && b.every(Number.isFinite) && b[0] >= 0 && b[1] >= 0 && b[2] > b[0] && b[3] > b[1] && b[2] <= page.width && b[3] <= page.height && ((b[2]-b[0])*(b[3]-b[1])/(page.width*page.height)) < .35;
  }
  function regionView(box, page) {
    const padding = Math.max(30,(box[3]-box[1])*.8), x = Math.max(0,box[0]-padding), y = Math.max(0,box[1]-padding);
    return [x,y,Math.min(page.width,box[2]+padding)-x,Math.min(page.height,box[3]+padding)-y];
  }
  function svgImage(page) { return `<image class="source-page-image" href="${asset(state.documentId,page.image_asset_id)}" width="${page.width}" height="${page.height}"/>`; }
  function renderPage() {
    const page = currentPage(), stage = $('page-stage');
    state.frameReady = false; const generation = ++state.generation;
    $('fit-page').disabled = true; $('focus-field').disabled = true;
    $('coordinate-note').textContent = '';
    if (!page?.image_asset_id) {
      const sourceId = page?.source_asset_id || 'source', sourceUrl = asset(state.documentId,sourceId);
      if (page?.media_type === 'application/pdf' || state.document.media_type === 'application/pdf') {
        stage.innerHTML = `<iframe title="ต้นฉบับ PDF" src="${sourceUrl}#page=${Number(page?.number || 1)}"></iframe>`;
        $('coordinate-note').textContent = 'แสดง PDF ต้นฉบับก่อน ภาพหน้าที่ผูกพิกัดจะแสดงเมื่อระบบเตรียมเสร็จ ยังไม่วาดกรอบบน PDF ที่ไม่มีภาพหน้ารองรับ';
      } else stage.innerHTML = '<div class="page-placeholder"><p>ยังไม่มีภาพหน้าที่พร้อมแสดง</p><p class="small">ระบบจะไม่เดาตำแหน่งกรอบขึ้นมาแทน</p></div>';
      return;
    }
    stage.innerHTML = '<div class="page-placeholder">กำลังเปิดต้นฉบับ…</div>';
    const image = new Image();
    image.onload = () => {
      if (generation !== state.generation) return;
      state.imageSize = [image.naturalWidth,image.naturalHeight];
      state.frameReady = image.naturalWidth === page.width && image.naturalHeight === page.height && page.width > 0 && page.height > 0;
      $('fit-page').disabled = !state.frameReady;
      drawPage(); renderRow();
    };
    image.onerror = () => { if (generation === state.generation) { stage.innerHTML = '<div class="page-placeholder">เปิดภาพต้นฉบับไม่สำเร็จ</div>'; $('coordinate-note').textContent = 'ยังไม่แสดงกรอบ เพราะตรวจภาพต้นทางไม่ได้'; } };
    image.src = asset(state.documentId,page.image_asset_id);
  }
  function drawPage() {
    const page = currentPage(); if (!page?.image_asset_id) return;
    if (!state.frameReady) {
      $('page-stage').innerHTML = `<img src="${asset(state.documentId,page.image_asset_id)}" alt="ต้นฉบับหน้า ${escape(page.number)}">`;
      $('coordinate-note').textContent = 'ขนาดหรือการหมุนภาพไม่ตรงกับพิกัดที่บันทึกไว้ จึงไม่วาดกรอบเพื่อป้องกันการชี้ผิดตำแหน่ง';
      return;
    }
    const selectedField = currentRow()?.fields?.[state.field], focus = selectedField && validBox(selectedField,page);
    $('focus-field').disabled = !focus;
    const view = state.zoom && focus ? regionView(selectedField.bbox,page) : [0,0,page.width,page.height];
    const groups = new Map(); let number = 0, positioned = 0, missing = 0;
    for (const row of pageRows()) for (const [key,field] of fields(row)) {
      number++;
      if (!validBox(field,page)) { missing++; continue; }
      positioned++;
      const groupKey = field.bbox.join(',');
      if (!groups.has(groupKey)) groups.set(groupKey,{box:field.bbox,items:[]});
      groups.get(groupKey).items.push({row,key,field,number});
    }
    const ordered = [...groups.values()].sort((a,b) => (b.box[2]-b.box[0])*(b.box[3]-b.box[1])-(a.box[2]-a.box[0])*(a.box[3]-a.box[1]));
    const colors = {approved:'#147a56',pending:'#a86600',issue:'#b52d40',excluded:'#65738a'}, font = Math.max(16,view[2]/65);
    $('page-stage').innerHTML = `<svg id="source-page-svg" xmlns="http://www.w3.org/2000/svg" viewBox="${view.join(' ')}" role="group" aria-label="ต้นฉบับหน้า ${escape(page.number)} พร้อมบริเวณข้อมูล" data-coordinate-frame="original_image">${svgImage(page)}${ordered.map((group,i) => { const b = group.box,selected = group.items.some(x => String(x.row.id) === String(state.rowId) && (!state.field || x.key === state.field)); const kind = group.items.some(x => rowState(x.row) === 'issue') ? 'issue' : group.items.every(x=>excluded(x.row)) ? 'excluded' : group.items.every(x=>rowState(x.row)==='approved') ? 'approved' : 'pending'; return `<g class="source-region ${selected?'selected':''}" data-region-index="${i}" role="button" tabindex="0" aria-label="จุด ${group.items.map(x=>x.number).join(', ')} ${escape(group.items.map(x=>title(x.key)).join(' / '))}"><title>${escape(group.items.map(x=>`${title(x.key)} · เครื่องอ่าน: ${text(x.field.raw)} · ค่าที่เสนอ: ${text(x.field.final)} · ${rowStateLabel(x.row)}`).join('\n'))}</title><rect x="${b[0]}" y="${b[1]}" width="${b[2]-b[0]}" height="${b[3]-b[1]}" stroke="${colors[kind]}" fill="${colors[kind]}"/><text x="${b[0]+3}" y="${Math.max(font,b[1]-4)}" font-size="${font}">${group.items.slice(0,3).map(x=>x.number).join(',')}${group.items.length>3?'…':''}</text></g>`; }).join('')}</svg>`;
    $('coordinate-note').textContent = `${positioned} ช่องมีพิกัดบนภาพ · ${missing} ช่องยังไม่มีพิกัดคำที่แสดงได้ เลือกจากรายการเพื่อดูข้อมูลได้ บริเวณไม่มีกรอบไม่ได้หมายความว่าถูกหรือครบแล้ว`;
    $('page-stage').querySelectorAll('[data-region-index]').forEach(element => {
      const activate = () => { const group = ordered[Number(element.dataset.regionIndex)]; const choice = group.items.find(x=>String(x.row.id)===String(state.rowId)&&x.key===state.field)||group.items[0]; selectRow(choice.row.id,choice.key); };
      element.onclick = activate; element.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate(); } };
    });
  }
  function renderRow() {
    const row = currentRow();
    if (!row) { $('row-detail').innerHTML = '<p class="muted">ยังไม่มีรายการให้ตรวจในหน้านี้ เมื่อระบบเตรียมเสร็จ รายการและประเด็นจะปรากฏที่นี่</p>'; return; }
    const pairs = fields(row), draft = draftFor(row), page = currentPage();
    const originalDescription=row.fields?.description?.raw ?? row.fields?.description?.normalized ?? row.fields?.description?.final;
    $('row-detail').innerHTML = `<button id="return-to-photo" class="secondary">↑ ดูภาพหน้านี้</button><div class="row-heading"><div><h3>${escape(rowName(row))}</h3><span class="small">${escape(row.line_kind === 'free' || row.line_kind === 'bonus' ? 'ของแถม' : 'ข้อมูลบนเอกสาร')}</span></div><span class="badge ${rowState(row)}">${escape(rowStateLabel(row))}</span></div>${!goods(row)&&originalDescription?`<p class="small">ข้อความต้นทาง: ${escape(text(originalDescription))}</p>`:''}${excluded(row)?'<p class="exclusion-note">แถวนี้เก็บไว้ในประวัติ แต่ไม่นำไปเป็นรายการสินค้า ค่าที่เครื่องอ่านด้านล่างยังไม่ได้รับรองว่าถูกต้อง</p>':row.line_kind==='context'?'<p class="small">ใช้ตรวจหัวเอกสารและเทียบว่ารายการสินค้าในภาพตกหล่นหรือไม่ แถวนี้ไม่ใช่รายการสินค้า</p>':''}${issues(row).length?`<div class="issues"><strong>จุดที่ระบบขอให้ตัดสินใจ</strong><ul>${issues(row).map(issue=>`<li>${escape(issue)}</li>`).join('')}</ul></div>`:''}<p class="small">ตรวจค่าที่เสนอใช้ด้านล่างได้ คำอ่านต้นฉบับและข้อมูลทะเบียนยังคงแยกไว้ หลังยืนยันแล้วจึงใช้เป็นข้อเท็จจริงของเอกสารสำหรับส่งต่อ</p><div class="field-list">${pairs.map(([key,field],i)=>{const value=Object.hasOwn(draft.values,key)?draft.values[key]:field.final;return `<section class="field-card ${state.field===key?'selected':''}" data-field-index="${i}"><div class="field-title"><strong>${escape(title(key))}</strong><button data-focus-index="${i}" type="button">ชี้บนภาพ</button></div><div class="field-values"><div><span class="label">คำอ่านดิบจากภาพ</span><div class="value">${escape(text(field.raw))}</div></div><div><span class="label">ข้อมูลทะเบียนที่เทียบ</span><div class="value">${escape(text(field.catalogue))}</div></div></div><div class="small">ค่าที่ระบบจัดรูป: ${escape(text(field.normalized))}</div><div class="field-final"><label for="final-field-${i}">${excluded(row)?'ค่าที่เสนอเดิม (ไม่นับเป็นสินค้า)':rowState(row)==='approved'?'ค่าที่คุณยืนยันแล้ว':'ค่าที่เสนอใช้ / แก้ได้'}</label><input id="final-field-${i}" data-edit-index="${i}" value="${escape(value ?? '')}" autocomplete="off"></div>${field.reason?`<p class="field-reason">${escape(field.reason)}</p>`:''}${(field.alternatives||[]).length?`<div class="alternatives">ทางเลือกที่พบ: ${(field.alternatives||[]).map((alternative,j)=>`<button type="button" data-alternative-index="${i}:${j}" title="${escape(alternative.reason||'')}">${escape(text(alternative.label || alternative.value))}</button>`).join('')}</div>`:''}<div id="crop-field-${i}"></div><p class="field-reason">${page&&validBox(field,page)?'มีพิกัดที่บันทึกไว้บนต้นฉบับ':'ยังไม่มีพิกัดคำที่ยืนยันได้ ไม่สร้างกรอบแทนขึ้นมา'}</p></section>`;}).join('')}</div><label for="final-review-note"><strong>ข้อสังเกต / เหตุผลที่พักหรือไม่นับเป็นสินค้า</strong></label><textarea id="final-review-note" class="review-note" placeholder="จดสิ่งที่เห็นในเอกสาร หรือหลักฐานที่ยังต้องใช้…">${escape(draft.note)}</textarea><label class="review-checkbox"><input type="checkbox" id="review-confirmed"><span>ตรวจต้นฉบับและหลักฐานแล้ว และยืนยันการตัดสินใจนี้</span></label><div class="review-actions"><button id="approve-row" class="success">ยืนยันรายการนี้</button><button id="correct-row">บันทึกค่าที่แก้และยืนยัน</button><button id="hold-row" class="danger">พักรายการไว้ก่อน</button><button id="exclude-row" class="secondary">ไม่ใช่รายการสินค้า</button></div><p id="review-save-status" class="small review-save-status">${draft.dirty?'มีร่างคำตอบในเบราว์เซอร์ ยังไม่ได้บันทึกผลตรวจ':'การยืนยันนี้รับรองข้อมูลเอกสาร ไม่ได้บันทึกรับสินค้าจริงหรือเขียน ERP อัตโนมัติ'}</p>`;
    $('return-to-photo').onclick = () => document.querySelector('.paper-panel').scrollIntoView({block:'start'});
    for (const [key,field] of pairs) if (state.field === key && page && validBox(field,page)) {
      const i = pairs.findIndex(([k])=>k===key), b=field.bbox, vb=regionView(b,page);
      $(`crop-field-${i}`).innerHTML=`<div class="field-crop"><svg xmlns="http://www.w3.org/2000/svg" viewBox="${vb.join(' ')}" role="img" aria-label="ภาพขยาย ${escape(title(key))}">${svgImage(page)}<rect x="${b[0]}" y="${b[1]}" width="${b[2]-b[0]}" height="${b[3]-b[1]}" stroke="#2457c5" fill="none" stroke-width="2" vector-effect="non-scaling-stroke"/></svg></div>`;
    }
    $('row-detail').querySelectorAll('[data-focus-index]').forEach(button=>button.onclick=()=>{
      state.field=pairs[Number(button.dataset.focusIndex)][0];renderRow();drawPage();
      if (innerWidth <= 1050) document.querySelector('.paper-panel').scrollIntoView({block:'start'});
    });
    $('row-detail').querySelectorAll('[data-edit-index]').forEach(input=>input.oninput=()=>{
      const [key]=pairs[Number(input.dataset.editIndex)]; draft.values[key]=input.value===''?null:input.value;draft.dirty=true;saveDraft(row);$('review-save-status').textContent='เก็บร่างคำตอบในเบราว์เซอร์แล้ว ยังไม่ได้บันทึกผลตรวจ';
    });
    $('row-detail').querySelectorAll('[data-alternative-index]').forEach(button=>button.onclick=()=>{
      const [i,j]=button.dataset.alternativeIndex.split(':').map(Number),[key,field]=pairs[i];draft.values[key]=field.alternatives[j].value;draft.dirty=true;saveDraft(row);renderRow();
    });
    $('final-review-note').oninput=()=>{draft.note=$('final-review-note').value;draft.dirty=true;saveDraft(row);};
    $('approve-row').onclick=()=>saveReview('approve');$('correct-row').onclick=()=>saveReview('correct');$('hold-row').onclick=()=>saveReview('hold');$('exclude-row').onclick=()=>saveReview('exclude');
  }
  async function saveReview(decision) {
    const row=currentRow();if(!row||state.busy)return;
    const draft=draftFor(row),corrections={};
    if(decision!=='exclude')for(const [key,value]of Object.entries(draft.values))if(JSON.stringify(value)!==JSON.stringify(row.fields[key]?.final))corrections[key]=value;
    if(decision!=='hold'&&!$('review-confirmed').checked){alert('กรุณาตรวจต้นฉบับและทำเครื่องหมายยืนยันก่อนบันทึก');return;}
    if(['hold','exclude'].includes(decision)&&!draft.note.trim()){alert(decision==='exclude'?'ระบุเหตุผลว่าเหตุใดข้อความนี้ไม่ใช่รายการสินค้า เช่น เป็นยอดรวมหรือข้อความท้ายใบ':'ระบุสั้น ๆ ว่ารายการนี้ยังขาดอะไร เพื่อให้กลับมาตัดสินใจต่อได้');return;}
    if(decision==='approve'&&Object.keys(corrections).length){alert('มีค่าที่คุณแก้ไว้ ให้กด “บันทึกค่าที่แก้และยืนยัน” เพื่อเก็บประวัติการแก้ให้ครบ');return;}
    state.busy=true;alert();$('review-save-status').textContent='กำลังบันทึกผลตรวจ…';
    try{
      await request(`/api/documents/${encodeURIComponent(state.documentId)}/rows/${encodeURIComponent(row.id)}/review`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decision,corrections,note:draft.note,expected_revision:state.document.revision,exclusion_confirmed:decision==='exclude'&&$('review-confirmed').checked})});
      clearDraft(row);await loadDocument();$('review-save-status').textContent='บันทึกผลตรวจพร้อมประวัติแล้ว';
    }catch(error){alert(error.message);if(error.code==='REVISION_CONFLICT')await loadDocument();}
    finally{state.busy=false;}
  }
  async function exportDocument() {
    if(!state.document||state.busy)return;state.busy=true;alert();
    try{
      const value=await request(`/api/documents/${encodeURIComponent(state.documentId)}/export`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({completeness_confirmed:$('completeness-confirmed').checked,expected_revision:state.document.revision,source_sha256:state.document.source_sha256})});
      const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),link=document.createElement('a');
      link.href=url;link.download='erp-reviewed-handoff.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);await loadDocument();
    }catch(error){alert(error.message);}finally{state.busy=false;}
  }
  async function loadHistory() {
    if(!state.documentId)return;
    try{
      const value=await request(`/api/documents/${encodeURIComponent(state.documentId)}/history`);
      const eventNames={source_ingested:'รับต้นฉบับ',proposals_prepared:'เตรียมรายการพร้อมตรวจ',row_reviewed:'บันทึกผลตรวจรายการ',missing_row_added:'เพิ่มรายการที่ตกหล่น',reviewed_document_exported:'ส่งออกข้อมูลเอกสารที่ยืนยันแล้ว',processing_failed:'เตรียมเอกสารไม่สำเร็จ'};
      $('document-history').innerHTML=value.events.length?value.events.map(event=>`<article class="history-item"><strong>${escape(event.event_type==='row_reviewed'&&event.payload?.decision==='excluded'?'ไม่นับแถวนี้เป็นสินค้า':eventNames[event.event_type]||event.event_type||'บันทึก')}</strong><div class="small">${escape(event.created_at||'')} · ${escape(event.actor||'ระบบ')}</div>${event.payload?.note?`<p>${escape(event.payload.note)}</p>`:''}<details><summary>รายละเอียดและหลักฐาน</summary><pre>${escape(JSON.stringify(event,null,2))}</pre></details></article>`).join(''):'<p class="small">ยังไม่มีประวัติ</p>';
    }catch(error){$('document-history').textContent=error.message;}
  }
  async function addMissingRow(){
    if(!state.document||!state.pageId||state.busy)return;
    const values={};$('add-row-fields').querySelectorAll('[data-added-field]').forEach(input=>{if(input.value.trim())values[input.dataset.addedField]=input.value.trim();});
    const note=$('add-row-note').value.trim();
    if(!values.product_code||!values.quantity||!values.unit||!note){alert('ระบุรหัสสินค้า จำนวน หน่วย และเหตุผลของรายการที่เพิ่มให้ครบ');return;}
    state.busy=true;alert();$('add-row-status').textContent='กำลังเพิ่มรายการพร้อมที่มา…';
    try{
      await request(`/api/documents/${encodeURIComponent(state.documentId)}/rows`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({fields:values,note,expected_revision:state.document.revision,page_id:String(state.pageId)})});
      $('add-row-fields').querySelectorAll('input').forEach(input=>input.value='');$('add-row-note').value='';$('add-row-status').textContent='เพิ่มรายการแล้ว กรุณาตรวจและยืนยันรายการใหม่นี้';await loadDocument();
    }catch(error){alert(error.message);$('add-row-status').textContent='ยังเพิ่มรายการไม่สำเร็จ';}finally{state.busy=false;}
  }
  $('file-input').onchange=()=>uploadFile($('file-input').files[0]);
  $('drop-zone').onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();$('file-input').click();}};
  for(const event of ['dragenter','dragover'])$('drop-zone').addEventListener(event,e=>{e.preventDefault();$('drop-zone').classList.add('dragging');});
  for(const event of ['dragleave','drop'])$('drop-zone').addEventListener(event,e=>{e.preventDefault();$('drop-zone').classList.remove('dragging');});
  $('drop-zone').addEventListener('drop',event=>{if(event.dataTransfer.files.length!==1){alert('ส่งเอกสารครั้งละหนึ่งไฟล์เพื่อเก็บหลักฐานแต่ละชุดให้ครบ');return;}uploadFile(event.dataTransfer.files[0]);});
  $('refresh-documents').onclick=listDocuments;
  $('back-inbox').onclick=()=>{stopPolling();state.documentId=null;state.document=null;$('document-view').classList.add('hidden');$('inbox-view').classList.remove('hidden');alert();listDocuments();};
  $('page-select').onchange=()=>selectPage($('page-select').value);
  $('previous-page').onclick=()=>{const pages=state.document.pages,index=pages.findIndex(p=>String(p.id)===String(state.pageId));if(index>0)selectPage(pages[index-1].id);};
  $('next-page').onclick=()=>{const pages=state.document.pages,index=pages.findIndex(p=>String(p.id)===String(state.pageId));if(index>=0&&index<pages.length-1)selectPage(pages[index+1].id);};
  $('row-filter').onchange=()=>{state.filter=$('row-filter').value;renderRows();};
  $('fit-page').onclick=()=>{state.zoom=false;drawPage();};$('focus-field').onclick=()=>{state.zoom=true;drawPage();};
  $('export-document').onclick=exportDocument;
  $('completeness-confirmed').onchange=updateExportState;
  $('add-row-fields').innerHTML=['product_code','description','quantity','unit','lot','mfg_date','exp_date'].map(key=>`<label>${escape(title(key))}${['product_code','quantity','unit'].includes(key)?' *':''}<input data-added-field="${key}" aria-label="เพิ่ม ${escape(title(key))}" autocomplete="off"></label>`).join('');
  $('add-row-submit').onclick=addMissingRow;
  document.querySelector('.history').addEventListener('toggle',event=>{if(event.currentTarget.open)loadHistory();});
  request('/api/config').then(config=>{state.config=config;$('reviewer-name').textContent=`ผู้ตรวจ: ${config.reviewer}`;$('upload-limit').textContent=`ไฟล์ละไม่เกิน ${Math.floor(config.max_upload_bytes/1024/1024)} MB`;return listDocuments();}).catch(error=>alert(error.message));
})();
