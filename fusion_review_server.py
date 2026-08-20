#!/usr/bin/env python
"""Lightweight local review server for OCR fusion outputs."""

from __future__ import annotations

import argparse
import csv
import json
import mimetypes
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from ocr_environment import environment_config, load_dotenv, resolve_environment_name, validate_environment_path, workspace_root


SELECTED_PAGES_RUN_SLUG = "1-6_3_1_selected_pages_946766cc69"
SELECTED_PAGES_JSON_PATH = workspace_root() / "ocr_selected_pages.json"


def _find_selected_pages_run_dir() -> Optional[Path]:
    staging_root = workspace_root() / "ocr_runs_staging"
    candidate = staging_root / SELECTED_PAGES_RUN_SLUG
    if candidate.is_dir():
        return candidate
    return None


SOURCE_PAGE_LABELS = ["13", "14", "15", "16", "19", "23", "29", "30", "31", "48", "49", "52", "71"]

import re as _re
from collections import defaultdict as _defaultdict

def _fix_thai(text: str) -> str:
    return _re.sub(r'(?<=[฀-๿]) (?=[฀-๿])', '', text)

def _read_tsv_pieces(tsv_path, page_w: int = 1966, page_h: int = 2787):
    """Parse TSV and return merged line pieces with (text, left_pct, top_pct)."""
    words = []
    try:
        with open(tsv_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) != 12:
                    continue
                level, _, block_num, par_num, line_num, _, left, top, _, _, conf, text = parts
                if level != "5":
                    continue
                try:
                    conf_f = float(conf)
                    left_i = int(left)
                    top_i  = int(top)
                    key    = (int(block_num), int(par_num), int(line_num))
                except ValueError:
                    continue
                text = text.strip()
                if conf_f < 0 or not text:
                    continue
                words.append({"t": text, "left": left_i, "top": top_i, "key": key})
    except OSError:
        return []

    line_groups: dict = _defaultdict(list)
    for w in words:
        line_groups[w["key"]].append(w)

    pieces = []
    for ws in line_groups.values():
        ws.sort(key=lambda w: w["left"])
        merged = _fix_thai(" ".join(w["t"] for w in ws))
        left = ws[0]["left"]
        top = sum(w["top"] for w in ws) / len(ws)
        pieces.append({
            "text": merged,
            "left_pct": left / page_w * 100,
            "top_pct": top / page_h * 100,
        })
    return pieces


def _reconstruct_tess_layout(tsv_path) -> str:
    """Plain text fallback — joined lines in reading order."""
    pieces = _read_tsv_pieces(tsv_path)
    pieces.sort(key=lambda p: p["top_pct"])
    return "\n".join(p["text"] for p in pieces)


def _reconstruct_tess_html(tsv_path) -> str:
    """Positioned HTML: each Tesseract line placed at its % position on a virtual A4 page."""
    pieces = _read_tsv_pieces(tsv_path)
    if not pieces:
        return ""
    spans = []
    for p in pieces:
        safe = (p["text"].replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))
        spans.append(
            f'<span style="position:absolute;left:{p["left_pct"]:.2f}%;'
            f'top:{p["top_pct"]:.2f}%;white-space:nowrap;">{safe}</span>'
        )
    return (
        '<div style="position:relative;padding-top:141.8%;pointer-events:none;">'
        + "".join(spans) + "</div>"
    )


def _stages_data_for_page(run_dir: Path, page_number: int) -> Dict[str, Any]:
    """Return all engine outputs for one page as a dict."""
    result: Dict[str, Any] = {}

    # Native
    native_path = run_dir / "ocr" / "native" / f"page-{page_number:04d}.txt"
    native_text = native_path.read_text(encoding="utf-8", errors="replace").strip() if native_path.exists() else ""
    result["native"] = {"text": native_text, "confidence": None, "available": native_path.exists()}

    # Tesseract – pick best TSV by avg confidence
    tess_dir = run_dir / "ocr" / "tesseract"
    best_path: Optional[Path] = None
    best_score: Optional[float] = None
    variants: List[Dict[str, Any]] = []
    for tsv_path in sorted(tess_dir.glob(f"page-{page_number:04d}_*.tsv")):
        confs: List[float] = []
        try:
            with tsv_path.open(encoding="utf-8", errors="replace", newline="") as fh:
                for row in csv.DictReader(fh, delimiter="\t"):
                    txt = (row.get("text") or "").strip()
                    cr = row.get("conf", "")
                    if not txt or not cr or cr == "-1":
                        continue
                    try:
                        confs.append(float(cr))
                    except ValueError:
                        pass
        except Exception:
            continue
        score = sum(confs) / len(confs) if confs else 0.0
        variants.append({"name": tsv_path.stem, "confidence": round(score / 100, 4), "word_count": len(confs)})
        if best_score is None or score > best_score:
            best_path = tsv_path
            best_score = score
    tess_text = ""
    tess_conf = None
    if best_path:
        tess_text = _reconstruct_tess_layout(best_path)
        tess_html = _reconstruct_tess_html(best_path)
        tess_conf = round(best_score / 100, 4) if best_score is not None else None
    result["tesseract"] = {"text": tess_text, "html": tess_html, "confidence": tess_conf, "variants": variants, "available": best_path is not None}

    # EasyOCR
    easy_json = run_dir / "ocr" / "easyocr" / f"page-{page_number:04d}.json"
    if easy_json.exists():
        rows = json.loads(easy_json.read_text(encoding="utf-8"))
        confs = [float(r.get("confidence", 0)) for r in rows if r.get("confidence") is not None]
        lines = [r.get("text", "") for r in rows if r.get("text")]
        result["easyocr"] = {
            "text": "\n".join(lines),
            "confidence": round(sum(confs) / len(confs), 4) if confs else None,
            "word_count": len(rows),
            "available": True,
        }
    else:
        result["easyocr"] = {"text": "", "confidence": None, "word_count": 0, "available": False}

    # PaddleOCR – pick best language pass
    paddle_dir = run_dir / "ocr" / "paddle"
    best_paddle: Dict[str, Any] = {"text": "", "confidence": None, "lang": None, "word_count": 0, "available": False}
    for lang in ("th", "en"):
        pj = paddle_dir / f"page-{page_number:04d}_{lang}.json"
        if not pj.exists():
            continue
        rows = json.loads(pj.read_text(encoding="utf-8"))
        confs = [float(r.get("confidence", 0)) for r in rows if r.get("confidence") is not None]
        lines = [r.get("text", "") for r in rows if r.get("text")]
        conf = round(sum(confs) / len(confs), 4) if confs else None
        if conf is not None and (best_paddle["confidence"] is None or conf > best_paddle["confidence"]):
            best_paddle = {"text": "\n".join(lines), "confidence": conf, "lang": lang, "word_count": len(rows), "available": True}
    result["paddleocr"] = best_paddle

    # Fusion
    fused_path = run_dir / "fusion" / "fused_regions.json"
    if fused_path.exists():
        all_regions = json.loads(fused_path.read_text(encoding="utf-8"))
        page_regions = [r for r in all_regions if r.get("page") == page_number]
        page_regions.sort(key=lambda r: (r.get("bbox", [0, 0, 0, 0])[1], r.get("bbox", [0, 0, 0, 0])[0]))
        lines_f: List[str] = []
        confs_f: List[float] = []
        for reg in page_regions:
            t = reg.get("normalized_candidate_text") or ""
            if t:
                lines_f.append(t)
            for cand in reg.get("raw_candidates", {}).values():
                c = cand.get("confidence")
                if c is not None:
                    try:
                        cf = float(c)
                        if cf > 1.0:
                            cf /= 100.0
                        confs_f.append(cf)
                    except (TypeError, ValueError):
                        pass
        result["fusion"] = {
            "text": "\n".join(lines_f),
            "confidence": round(sum(confs_f) / len(confs_f), 4) if confs_f else None,
            "region_count": len(page_regions),
            "available": True,
        }
    else:
        result["fusion"] = {"text": "", "confidence": None, "region_count": 0, "available": False}

    return result


STAGES_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OCR Pipeline Stages</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#0f1117;color:#e0e0e0;height:100vh;display:flex;flex-direction:column;overflow:hidden}
#hdr{background:#1a1d2e;padding:10px 20px;display:flex;align-items:center;gap:16px;border-bottom:1px solid #2a2d3e;flex-shrink:0}
#hdr h1{font-size:1rem;font-weight:600;color:#c0c8ff}
#hdr a{color:#6b7aaa;font-size:.85rem;text-decoration:none}
#hdr a:hover{color:#a0b0ff}
#refresh-status{font-size:.75rem;color:#5a6080;margin-left:auto}
#layout{display:flex;flex:1;overflow:hidden}
#sidebar{width:176px;flex-shrink:0;background:#13151f;border-right:1px solid #2a2d3e;overflow-y:auto;padding:6px 0}
.pg{padding:8px 10px;cursor:pointer;border-left:3px solid transparent;transition:.15s}
.pg:hover{background:#1e2235}
.pg.active{background:#1e2235;border-left-color:#5b7ffa}
.pg-label{font-size:.85rem;font-weight:500;color:#c0c8e8}
.pg-sub{font-size:.7rem;color:#5a6080;margin-top:1px}
.dots{display:flex;gap:4px;margin-top:4px}
.dot{width:8px;height:8px;border-radius:50%;background:#2a2d3e;flex-shrink:0}
.dot.ok{background:#4caf50}
.dot.run{background:#ff9800;animation:pulse 1s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
#main{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:12px}
#sum-bar{background:#1a1d2e;border-radius:8px;padding:10px 14px;display:flex;gap:18px;flex-wrap:wrap}
.si{font-size:.78rem}.sl{color:#5a6080}.sv{color:#c0c8e8;font-weight:600}
#img-sec{background:#1a1d2e;border-radius:8px;padding:10px 14px}
#img-sec h2{font-size:.78rem;color:#5a6080;margin-bottom:8px}
#page-img{max-width:100%;max-height:360px;object-fit:contain;display:block;margin:0 auto;border-radius:4px;background:#0a0c14}
#eng-grid{display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:10px;align-items:start}
.ec{background:#1a1d2e;border-radius:8px;overflow:hidden;display:flex;flex-direction:column;min-height:300px}
.ec.tess-primary{min-height:560px}
.ec.tess{border-top:3px solid #5b7ffa}
.ec.tess-primary{border-top:3px solid #5b7ffa}
.ec.paddle{border-top:3px solid #ff7043}
.ec.easy{border-top:3px solid #4caf50}
.ec.fusion{border-top:3px solid #ab47bc}
.eh{padding:9px 12px;display:flex;justify-content:space-between;align-items:center;flex-shrink:0}
.en{font-size:.85rem;font-weight:600}
.em{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.badge{font-size:.7rem;padding:2px 6px;border-radius:10px;font-weight:600}
.bg{background:#1a4a1a;color:#6fce6f}
.by{background:#4a3a0a;color:#e0b050}
.br{background:#4a1a1a;color:#e06060}
.bx{background:#2a2d3e;color:#6b7aaa}
.eb{padding:0 12px 12px;flex:1;display:flex;flex-direction:column;gap:5px}
.es{font-size:.72rem;color:#5a6080}
.es.ok{color:#4caf50}
.et{flex:1;font-family:'Courier New',monospace;font-size:.73rem;line-height:1.55;white-space:pre-wrap;word-break:break-word;background:#0f1117;border:1px solid #2a2d3e;border-radius:4px;padding:8px;overflow-y:auto;max-height:220px;color:#c8d0e8}
.ec.tess-primary .et{max-height:560px;font-size:.6rem;padding:0;overflow-y:auto;overflow-x:hidden;white-space:normal;word-break:normal}
.et.empty{color:#3a3d50;font-style:italic}
.emeta{font-size:.69rem;color:#5a6080}
#loading{display:flex;align-items:center;justify-content:center;flex:1;color:#5a6080;font-size:.9rem}
</style>
</head>
<body>
<div id="hdr">
  <h1>OCR Pipeline Stages</h1>
  <a href="/">&#8592; Back</a>
  <span id="refresh-status"></span>
</div>
<div id="layout">
  <div id="sidebar"></div>
  <div id="main"><div id="loading">Loading&#8230;</div></div>
</div>
<script>
const SRC = ["13","14","15","16","19","23","29","30","31","48","49","52","71"];
const N = 13;
let cur = 1, pgStatus = {}, timer = null;
const ENG = [
  {key:"tesseract", label:"Tesseract",  cls:"tess-primary",   color:"#5b7ffa"},
  {key:"paddleocr", label:"PaddleOCR",  cls:"paddle", color:"#ff7043"},
  {key:"easyocr",   label:"EasyOCR",    cls:"easy",   color:"#4caf50"},
  {key:"fusion",    label:"Fusion",     cls:"fusion", color:"#ab47bc"},
];

function badge(c){
  if(c===null||c===undefined) return '<span class="badge bx">N/A</span>';
  const p=Math.round(c*100);
  return `<span class="badge ${p>=80?'bg':p>=50?'by':'br'}">${p}%</span>`;
}
function esc(s){return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}
function dot(s){return `<span class="dot ${s||''}"></span>`;}

function buildSidebar(){
  const sb=document.getElementById("sidebar");
  sb.innerHTML="";
  for(let i=1;i<=N;i++){
    const st=pgStatus[i]||{};
    const div=document.createElement("div");
    div.className="pg"+(i===cur?" active":"");
    div.dataset.page=i;
    div.innerHTML=`<div class="pg-label">Page ${i}</div><div class="pg-sub">Source: ${SRC[i-1]}</div><div class="dots">${dot(st.t)}${dot(st.p)}${dot(st.e)}${dot(st.f)}</div>`;
    div.onclick=()=>selectPage(i);
    sb.appendChild(div);
  }
}

function metaSpan(eng, d){
  if(eng.key==="tesseract"&&d.variants) return `<span class="emeta">${d.variants.length} variants</span>`;
  if(eng.key==="paddleocr"&&d.lang) return `<span class="emeta">lang: ${d.lang}</span>`;
  if(eng.key==="fusion"&&d.region_count!==undefined) return `<span class="emeta">${d.region_count} regions</span>`;
  if(eng.key==="easyocr"&&d.word_count) return `<span class="emeta">${d.word_count} detections</span>`;
  return "";
}

function engCard(eng, d){
  const av=d.available, txt=d.text||"";
  const words=(txt.match(/\S+/g)||[]).length;
  const stat=!av?"Pending — not yet processed":(txt?`${words} words extracted`:"No text extracted");
  const statcls=!av?"":txt?"ok":"";
  return `<div class="ec ${eng.cls}">
  <div class="eh"><span class="en" style="color:${eng.color}">${eng.label}</span>
  <div class="em">${badge(d.confidence)}${metaSpan(eng,d)}</div></div>
  <div class="eb">
    <div class="es ${statcls}">${stat}</div>
    <div class="et ${!txt?'empty':''}">${
      eng.key==='tesseract'&&d.html
        ? d.html
        : (txt?esc(txt):(av?"(nothing extracted)":"waiting…"))
    }</div>
  </div></div>`;
}

function render(pn, data){
  pgStatus[pn]={
    t:data.tesseract?.available?"ok":"",
    p:data.paddleocr?.available?"ok":"",
    e:data.easyocr?.available?"ok":"run",
    f:data.fusion?.available?"ok":"run",
  };
  if(data.easyocr?.available) pgStatus[pn].e="ok";
  if(data.fusion?.available) pgStatus[pn].f="ok";

  const confItems=ENG.map(e=>{
    const c=(data[e.key]||{}).confidence;
    return `<div class="si"><span class="sl">${e.label}: </span><span class="sv">${c!==null&&c!==undefined?Math.round(c*100)+"%":"N/A"}</span></div>`;
  }).join("");

  document.getElementById("main").innerHTML=`
  <div id="sum-bar">
    <div class="si"><span class="sl">Page </span><span class="sv">${pn}/${N}</span></div>
    <div class="si"><span class="sl">Source doc pg </span><span class="sv">${SRC[pn-1]}</span></div>
    ${confItems}
  </div>
  <div id="img-sec">
    <h2>Page Image</h2>
    <img id="page-img" src="/api/selected-page-image?page=${pn}" alt="page ${pn}" onerror="this.style.display='none'">
  </div>
  <div id="eng-grid">${ENG.map(e=>engCard(e,data[e.key]||{})).join("")}</div>`;

  buildSidebar();
}

async function selectPage(pn){
  cur=pn;
  document.getElementById("main").innerHTML='<div id="loading">Loading page data…</div>';
  buildSidebar();
  clearTimeout(timer);
  try{
    const r=await fetch(`/api/stages-data?page=${pn}`);
    const data=await r.json();
    render(pn, data);
    const needsRefresh=!data.easyocr?.available||!data.fusion?.available;
    const rs=document.getElementById("refresh-status");
    if(needsRefresh){
      rs.textContent="Auto-refreshing every 15s (engines still processing)…";
      timer=setTimeout(()=>selectPage(cur),15000);
    } else {
      rs.textContent="All engines complete ✓";
    }
  }catch(e){
    document.getElementById("main").innerHTML=`<div id="loading" style="color:#e06060">Error: ${e.message}</div>`;
  }
}

for(let i=1;i<=N;i++) pgStatus[i]={};
buildSidebar();
selectPage(1);
</script>
</body>
</html>"""


SELECTED_PAGES_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OCR Selected Pages Viewer</title>
<style>
  body { font-family: system-ui, sans-serif; background: #f5f5f5; margin: 0; padding: 16px; }
  h1 { font-size: 1.4rem; margin-bottom: 8px; }
  .summary { background: #fff; border: 1px solid #ddd; border-radius: 6px; padding: 12px 16px; margin-bottom: 20px; }
  .summary h2 { font-size: 1rem; margin: 0 0 8px; }
  .summary table { border-collapse: collapse; width: 100%; }
  .summary td { padding: 3px 8px; font-size: 0.875rem; }
  .summary td:first-child { color: #555; width: 200px; }
  .poor-list { color: #c0392b; margin: 4px 0 0 0; padding-left: 20px; font-size: 0.85rem; }
  .page-block { background: #fff; border: 1px solid #ddd; border-radius: 6px; margin-bottom: 20px; overflow: hidden; }
  .page-header { background: #2c3e50; color: #fff; padding: 8px 14px; display: flex; align-items: center; gap: 12px; }
  .page-header h2 { margin: 0; font-size: 1rem; flex: 1; }
  .page-header .badge { font-size: 0.75rem; background: rgba(255,255,255,0.2); border-radius: 10px; padding: 2px 8px; }
  .conf-badge { font-size: 0.75rem; padding: 2px 8px; border-radius: 10px; }
  .conf-high { background: #27ae60; color: #fff; }
  .conf-med { background: #f39c12; color: #fff; }
  .conf-low { background: #e74c3c; color: #fff; }
  .conf-none { background: #95a5a6; color: #fff; }
  .page-body { display: flex; gap: 0; }
  .page-image-col { width: 340px; min-width: 340px; border-right: 1px solid #eee; padding: 12px; }
  .page-image-col img { width: 100%; height: auto; border: 1px solid #ccc; border-radius: 3px; display: block; }
  .page-image-col .no-image { background: #f0f0f0; height: 200px; display: flex; align-items: center; justify-content: center; color: #999; font-size: 0.85rem; border-radius: 3px; }
  .page-text-col { flex: 1; padding: 12px; overflow: hidden; }
  .engine-label { font-size: 0.75rem; color: #777; margin-bottom: 4px; }
  .ocr-text { white-space: pre-wrap; font-size: 0.8rem; font-family: 'Courier New', monospace; background: #fafafa; border: 1px solid #e0e0e0; border-radius: 3px; padding: 10px; max-height: 500px; overflow-y: auto; line-height: 1.5; }
  .status-ok { color: #27ae60; }
  .status-fail { color: #e74c3c; }
  .loading { text-align: center; padding: 40px; color: #666; }
  .error { color: #c0392b; background: #fdf0f0; border: 1px solid #f5c6cb; border-radius: 4px; padding: 12px; margin: 16px 0; }
  @media (max-width: 700px) { .page-body { flex-direction: column; } .page-image-col { width: 100%; min-width: 0; border-right: none; border-bottom: 1px solid #eee; } }
</style>
</head>
<body>
<h1>OCR Selected Pages Viewer</h1>
<div id="root"><div class="loading">Loading OCR results...</div></div>
<script>
async function load() {
  const root = document.getElementById('root');
  let data;
  try {
    const res = await fetch('/api/selected-pages-data');
    if (!res.ok) throw new Error('HTTP ' + res.status + ': ' + await res.text());
    data = await res.json();
  } catch(e) {
    root.innerHTML = '<div class="error">Failed to load OCR results: ' + e.message + '</div>';
    return;
  }
  const summary = data._summary || {};
  const pages = Object.keys(data).filter(k => k.startsWith('page_')).sort((a,b)=>{
    return parseInt(a.split('_')[1]) - parseInt(b.split('_')[1]);
  });

  let html = '<div class="summary"><h2>Summary</h2><table>';
  html += '<tr><td>Pages processed</td><td>' + (summary.pages_processed || pages.length) + '</td></tr>';
  html += '<tr><td>OCR engines used</td><td>' + (summary.engines_used || []).join(', ') + '</td></tr>';
  html += '<tr><td>Average confidence</td><td>' + (summary.average_confidence != null ? (summary.average_confidence * 100).toFixed(1) + '%' : 'N/A') + '</td></tr>';
  const poor = summary.poor_quality_pages || [];
  html += '<tr><td>Poor quality pages</td><td>';
  if (poor.length === 0) { html += '<span class="status-ok">None</span>'; }
  else { html += '<ul class="poor-list">' + poor.map(p=>'<li>'+p+'</li>').join('') + '</ul>'; }
  html += '</td></tr></table></div>';

  for (const key of pages) {
    const entry = data[key];
    const label = entry.source_page_label || key;
    const conf = entry.confidence;
    const engine = entry.primary_engine || '';
    const text = entry.text || '';
    const status = entry.status || '';

    let confClass = 'conf-none', confLabel = 'N/A';
    if (conf != null) {
      confLabel = (conf * 100).toFixed(1) + '%';
      if (conf >= 0.80) confClass = 'conf-high';
      else if (conf >= 0.50) confClass = 'conf-med';
      else confClass = 'conf-low';
    }
    const pageNum = parseInt(key.split('_')[1]);

    html += '<div class="page-block">';
    html += '<div class="page-header">';
    html += '<h2>Page ' + label + '</h2>';
    html += '<span class="badge">' + key + '</span>';
    html += '<span class="badge">Engine: ' + engine + '</span>';
    html += '<span class="conf-badge ' + confClass + '">Conf: ' + confLabel + '</span>';
    html += '<span class="badge ' + (status === 'ok' ? 'status-ok' : 'status-fail') + '">' + status + '</span>';
    html += '</div>';
    html += '<div class="page-body">';
    html += '<div class="page-image-col">';
    html += '<img src="/api/selected-page-image?page=' + pageNum + '" alt="Page ' + label + '" loading="lazy" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\'">';
    html += '<div class="no-image" style="display:none">Image not available</div>';
    html += '</div>';
    html += '<div class="page-text-col">';
    html += '<div class="engine-label">OCR Text (' + engine + ')</div>';
    html += '<div class="ocr-text">' + (text ? text.replace(/</g,'&lt;').replace(/>/g,'&gt;') : '<em style="color:#aaa">No text extracted</em>') + '</div>';
    html += '</div></div></div>';
  }

  root.innerHTML = html;
}
load();
</script>
</body>
</html>"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "region_id",
        "page",
        "selected_candidate_engine",
        "selected_candidate_text",
        "review_status",
        "review_notes",
        "saved_at",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in headers})


def confidence_to_unit(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except Exception:
        return None
    if numeric > 1.0:
        numeric = numeric / 100.0
    return max(0.0, min(1.0, numeric))


class ReviewApp:
    def __init__(self, run_dir: Path, environment: str) -> None:
        self.environment = resolve_environment_name(environment)
        self.environment_config = environment_config(self.environment)
        self.run_dir = run_dir
        self.pages_dir = run_dir / "pages"
        self.fusion_dir = run_dir / "fusion"
        self.tables_dir = run_dir / "tables"
        self.static_dir = Path(__file__).resolve().parent / "fusion_review_ui"
        self.fused_regions = read_json(self.fusion_dir / "fused_regions.json", [])
        self.zoned_regions = read_json(self.fusion_dir / "zoned_regions_v2.json", read_json(self.fusion_dir / "zoned_regions.json", []))
        self.conflicts = read_json(self.fusion_dir / "conflicts.json", [])
        self.unique_regions = read_json(self.fusion_dir / "unique_regions.json", [])
        self.table_bands_payload = read_json(self.tables_dir / "table_bands.json", {"bands": []})
        self.table_bands = self.table_bands_payload.get("bands", [])
        self.table_rows_payload = read_json(self.tables_dir / "table_rows.json", {"rows": []})
        self.table_rows = self.table_rows_payload.get("rows", [])
        self.review_json_path = self.fusion_dir / "review_decisions.json"
        self.review_csv_path = self.fusion_dir / "review_decisions.csv"
        self.summary = self._build_summary()

    def _build_summary(self) -> Dict[str, Any]:
        page_numbers = sorted({int(region.get("page", 0)) for region in self.fused_regions if region.get("page")})
        classifications = sorted({region.get("classification", "") for region in self.fused_regions if region.get("classification")})
        categories = sorted({cat for region in self.fused_regions for cat in region.get("category_labels", [])})
        engines = sorted({engine for region in self.fused_regions for engine in region.get("source_engines_present", [])})
        zones = sorted({region.get("zone", "") for region in self.zoned_regions if region.get("zone")})
        suggested_zones = sorted({region.get("suggested_zone", "") for region in self.zoned_regions if region.get("suggested_zone")})
        pages = []
        for page_number in page_numbers:
            image_path = self.pages_dir / f"page-{page_number:04d}.png"
            pages.append(
                {
                    "page": page_number,
                    "image_url": f"/api/page-image?page={page_number}",
                    "width": next((region.get("page_width") for region in self.fused_regions if region.get("page") == page_number), None),
                    "height": next((region.get("page_height") for region in self.fused_regions if region.get("page") == page_number), None),
                    "exists": image_path.exists(),
                }
            )
        return {
            "environment": self.environment,
            "environment_label": self.environment_config["label"],
            "run_dir": str(self.run_dir),
            "generated_at": now_iso(),
            "counts": {
                "fused_regions": len(self.fused_regions),
                "conflicts": len(self.conflicts),
                "unique_regions": len(self.unique_regions),
                "table_bands": len(self.table_bands),
                "table_rows": len(self.table_rows),
            },
            "pages": pages,
            "classifications": classifications,
            "category_labels": categories,
            "engines": engines,
            "zones": zones,
            "suggested_zones": suggested_zones,
        }

    def decision_store(self) -> Dict[str, Any]:
        return read_json(self.review_json_path, {"run_dir": str(self.run_dir), "saved_at": None, "decisions": []})

    def decision_map(self) -> Dict[str, Dict[str, Any]]:
        decisions = self.decision_store().get("decisions", [])
        return {entry["region_id"]: entry for entry in decisions if entry.get("region_id")}

    def save_decision(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        store = self.decision_store()
        decisions = self.decision_map()
        region_id = decision["region_id"]
        decisions[region_id] = {
            "region_id": region_id,
            "page": decision.get("page"),
            "selected_candidate_engine": decision.get("selected_candidate_engine"),
            "selected_candidate_text": decision.get("selected_candidate_text"),
            "review_status": decision.get("review_status"),
            "review_notes": decision.get("review_notes", ""),
            "saved_at": now_iso(),
        }
        rows = sorted(decisions.values(), key=lambda item: (int(item.get("page") or 0), item.get("region_id", "")))
        payload = {"run_dir": str(self.run_dir), "saved_at": now_iso(), "decisions": rows}
        write_json(self.review_json_path, payload)
        write_csv(self.review_csv_path, rows)
        return payload

    def region_payload(self) -> List[Dict[str, Any]]:
        decisions = self.decision_map()
        zones_by_region = {region.get("region_id"): region for region in self.zoned_regions if region.get("region_id")}
        enriched: List[Dict[str, Any]] = []
        for region in self.fused_regions:
            raw_candidates = region.get("raw_candidates", {})
            candidate_confidences = [confidence_to_unit(candidate.get("confidence")) for candidate in raw_candidates.values()]
            candidate_confidences = [value for value in candidate_confidences if value is not None]
            confidence_score = max(candidate_confidences) if candidate_confidences else None
            zone_region = zones_by_region.get(region.get("region_id"), {})
            enriched.append(
                {
                    **region,
                    "zone": zone_region.get("zone", "unknown"),
                    "zone_confidence": zone_region.get("zone_confidence"),
                    "zone_reasons": zone_region.get("zone_reasons", []),
                    "zone_score": zone_region.get("zone_score"),
                    "zone_score_margin": zone_region.get("zone_score_margin"),
                    "zone_rankings": zone_region.get("zone_rankings", []),
                    "why_unknown": zone_region.get("why_unknown", ""),
                    "suggested_zone": zone_region.get("suggested_zone", ""),
                    "confidence_score": confidence_score,
                    "review_decision": decisions.get(region.get("region_id")),
                }
            )
        return enriched


def make_handler(app: ReviewApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FusionReviewHTTP/0.1"

        def _send_json(self, payload: Any, status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_file(self, path: Path) -> None:
            if not path.exists() or not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "File not found")
                return
            mime_type, _ = mimetypes.guess_type(str(path))
            content = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mime_type or "application/octet-stream")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_file(app.static_dir / "index.html")
                return
            if parsed.path.startswith("/static/"):
                rel = parsed.path.replace("/static/", "", 1)
                self._send_file(app.static_dir / rel)
                return
            if parsed.path == "/api/data":
                self._send_json(
                    {
                        "summary": app.summary,
                        "regions": app.region_payload(),
                        "conflicts": app.conflicts,
                        "unique_regions": app.unique_regions,
                        "table_bands": app.table_bands,
                        "table_bands_payload": app.table_bands_payload,
                        "table_rows": app.table_rows,
                        "table_rows_payload": app.table_rows_payload,
                        "review_decisions": app.decision_store(),
                    }
                )
                return
            if parsed.path == "/api/page-image":
                params = parse_qs(parsed.query)
                try:
                    page_number = int(params.get("page", ["0"])[0])
                except ValueError:
                    self.send_error(HTTPStatus.BAD_REQUEST, "Invalid page")
                    return
                self._send_file(app.pages_dir / f"page-{page_number:04d}.png")
                return
            if parsed.path == "/api/review-decisions":
                self._send_json(app.decision_store())
                return
            if parsed.path == "/ocr-stages":
                data = STAGES_HTML.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if parsed.path == "/api/stages-data":
                params = parse_qs(parsed.query)
                try:
                    page_number = int(params.get("page", ["1"])[0])
                except ValueError:
                    self.send_error(HTTPStatus.BAD_REQUEST, "Invalid page")
                    return
                run_dir = _find_selected_pages_run_dir()
                if run_dir is None:
                    self._send_json({"error": "Run directory not found"}, status=404)
                    return
                self._send_json(_stages_data_for_page(run_dir, page_number))
                return
            if parsed.path == "/ocr-selected-pages":
                data = SELECTED_PAGES_HTML.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if parsed.path == "/api/selected-pages-data":
                if not SELECTED_PAGES_JSON_PATH.exists():
                    self._send_json({"error": "ocr_selected_pages.json not found. Run build_selected_pages_json.py first."}, status=404)
                    return
                payload = json.loads(SELECTED_PAGES_JSON_PATH.read_text(encoding="utf-8"))
                self._send_json(payload)
                return
            if parsed.path == "/api/selected-page-image":
                params = parse_qs(parsed.query)
                try:
                    page_number = int(params.get("page", ["0"])[0])
                except ValueError:
                    self.send_error(HTTPStatus.BAD_REQUEST, "Invalid page")
                    return
                run_dir = _find_selected_pages_run_dir()
                if run_dir is None:
                    self.send_error(HTTPStatus.NOT_FOUND, "Selected pages run directory not found")
                    return
                self._send_file(run_dir / "pages" / f"page-{page_number:04d}.png")
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/api/review-decisions":
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON")
                return
            if not payload.get("region_id"):
                self.send_error(HTTPStatus.BAD_REQUEST, "region_id is required")
                return
            saved = app.save_decision(payload)
            self._send_json(saved, status=200)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the OCR fusion review UI.")
    parser.add_argument("--env", choices=["production", "staging"], help="Environment profile for run-dir and port defaults.")
    parser.add_argument("--run-dir", type=Path, help="Existing run directory containing pages/ and fusion/ outputs.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, help="Port to bind.")
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()
    environment = resolve_environment_name(args.env)
    env_config = environment_config(environment)
    run_dir = (args.run_dir or Path(env_config["run_dir"])).resolve()
    validate_environment_path(environment, run_dir, purpose="Review run directory")
    port = args.port or int(env_config["review_port"])
    app = ReviewApp(run_dir, environment)
    handler = make_handler(app)
    httpd = ThreadingHTTPServer((args.host, port), handler)
    print(f"Fusion review UI: http://{args.host}:{port}")
    print(f"Environment: {env_config['label']}")
    print(f"Run directory: {run_dir}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
