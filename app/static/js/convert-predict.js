// Konvertierungs-Editor: Vorhersage (Größe und Dauer je Rechner), Probe-Kodierung mit Vorher/Nachher-Schieber und Hinweise. Besitzer: PF.
import { $, api, baseName, esc, fmtB } from './core.js';
import { strip } from './convert-meta.js';

export const fmtT = s => {
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.round(s % 3600 / 60);
  return h >= 24 ? `${Math.floor(h / 24)} T ${h % 24} Std.` : h ? `${h}:${String(m).padStart(2, '0')} Std.` : `${Math.max(1, m)} Min.`;
};

export function predictHtml(hasFile, probe){
  return `<div class="cv-pred"><h4>Vorhersage <span class="st" data-b="forwhat">…</span></h4>
    <div class="cv-big"><b data-b="inb">…</b><span class="arrow">→</span><b data-b="out">…</b><span class="minus" data-b="save"></span></div><div class="cv-sizebar"><i data-w="outw"></i></div>
    <div class="cv-nodes" data-nodes></div><p class="hint" data-b="basis" style="margin:0"></p><div data-notices></div>
    ${probe ? `<div class="cv-probe"><div class="cv-inline"><button type="button" class="secondary" data-probe ${hasFile ? '' : 'disabled'}>Probe starten (2 × 25 s)</button><button type="button" class="secondary" data-probe-cancel hidden>Abbrechen</button>
      <span class="hint" data-b="probehint">${hasFile ? 'Kodiert zwei kurze Ausschnitte der Datei und rechnet genauer hoch.' : 'Die Probe braucht eine Datei aus der Bibliothek.'}</span></div>
      <div class="cv-prog" data-probeprog hidden><i style="width:0"></i></div><div data-proberes></div></div>` : ''}</div>`;
}

export class Predictor {
  constructor(root, getCfg, opts){ this.root = root; this.getCfg = getCfg; this.opts = opts; this.t = null; this.last = null; this.seq = 0; this.cmd = ''; this.probe = null; }
  files(){ return (this.opts.files || []).slice(0, 50); }
  schedule(ms = 300){ clearTimeout(this.t); this.t = setTimeout(() => this.run(), ms); }
  async run(){
    const cfg = strip(this.getCfg()), fs = this.files(), n = ++this.seq;
    try{
      const [est, norm] = await Promise.all([
        api('/api/convert/estimate', 'POST', {cfg, paths: fs.filter(f => f.path).map(f => f.path), files: fs.filter(f => !f.path)}),
        this.opts.noCommand ? Promise.resolve(null) : api('/api/convert/normalize', 'POST', {cfg}),
      ]);
      if(n !== this.seq) return;
      this.last = est; if(norm) this.cmd = norm.command;
      this.paint();
      if(this.opts.onPrediction) this.opts.onPrediction(est, norm);
    }catch{ /* api() zeigt den Fehler an */ }
  }
  paint(){
    const r = this.root, e = this.last; if(!e) return;
    const B = {}, one = this.files().length === 1 && this.files()[0].path;
    B.forwhat = e.example ? 'Beispiel: 24-GB-Film, 2 Std.' : one ? `${baseName(this.files()[0].path)} · ${fmtB(e.in_bytes)}` : `${e.files} Datei${e.files === 1 ? '' : 'en'} · ${fmtB(e.in_bytes)}`;
    B.inb = fmtB(e.in_bytes); B.out = fmtB(e.out_bytes); B.save = `−${Math.max(0, Math.round((1 - e.out_bytes / Math.max(1, e.in_bytes)) * 100))} %`;
    B.outw = Math.min(100, e.out_bytes / Math.max(1, e.in_bytes) * 100) + '%';
    B.basis = e.samples >= 2 ? `Berechnet aus ${e.samples} früheren Konvertierungen auf diesem Rechner.` : 'Schätzung: Es gibt noch keine Statistik früherer Konvertierungen (sie wird mit jeder fertigen Datei genauer).';
    B.cmd = this.cmd; B.crf = null;
    const mx = Math.max(1, ...e.nodes.filter(n => n.ok).map(n => n.secs));
    const nodes = $('[data-nodes]', r);
    if(nodes) nodes.innerHTML = e.nodes.map(n => `<div class="cv-node ${n.ok ? '' : 'off'}"><span><b>${esc(n.name)}</b> <em>${n.legacy ? 'älterer Stand' : n.cores + ' Threads'}${n.local ? ' · dieser' : ''}</em></span>
      <div class="bar"><i style="width:${n.ok ? Math.min(100, n.secs / mx * 100) : 0}%"></i></div><span title="${esc(n.reason || '')}">${n.ok ? '≈ ' + fmtT(n.secs) : esc(n.reason.length > 46 ? n.reason.slice(0, 44) + ' …' : n.reason)}</span></div>`).join('');
    const loc = e.nodes.find(n => n.local); B.dur = loc && loc.ok ? `ca. ${fmtT(loc.secs)} auf diesem Rechner` : '';
    r.querySelectorAll('[data-b]').forEach(el => { const k = el.dataset.b; if(B[k] != null && k !== 'crf' && k !== 'qword') el.textContent = B[k]; });
    r.querySelectorAll('[data-w]').forEach(el => { if(B[el.dataset.w] != null) el.style.width = B[el.dataset.w]; });
    const note = $('[data-notices]', r);
    if(note){
      const fl = Object.entries(e.flags || {}), dv = fl.filter(([, f]) => f.dovi), bad = fl.filter(([, f]) => f.issue);
      note.innerHTML = (dv.length ? `<div class="cv-notice">Dolby Vision: ${dv.length === 1 ? esc(baseName(dv[0][0])) : dv.length + ' Dateien'} enthält Dolby Vision. Mit diesen Einstellungen geht die Dolby-Vision-Ebene verloren (die HDR10-Basis bleibt). Vor dem Start fragt die Bibliothek nach.</div>` : '')
        + (bad.length ? `<div class="cv-notice">${bad.length === 1 ? esc(baseName(bad[0][0])) + ': ' : bad.length + ' Dateien werden übersprungen, z. B. ' + esc(baseName(bad[0][0])) + ': '}${esc(bad[0][1].issue)}</div>` : '');
    }
  }
  // ---- Probe
  async startProbe(){
    const f = this.files().find(x => x.path), r = this.root; if(!f) return;
    const btn = $('[data-probe]', r), prog = $('[data-probeprog]', r), res = $('[data-proberes]', r), hint = $('[data-b=probehint]', r), cancel = $('[data-probe-cancel]', r);
    let id; try{ id = (await api('/api/convert/probe', 'POST', {path: f.path, cfg: strip(this.getCfg())})).id; }catch{ return; }
    btn.disabled = true; cancel.hidden = false; prog.hidden = false; res.innerHTML = ''; this.probe = id;
    const tick = async () => {
      if(this.probe !== id || !document.contains(r)) return;
      let j; try{ j = await (await fetch('/api/convert/probe/' + id)).json(); }catch{ return setTimeout(tick, 2000); }
      $('i', prog).style.width = Math.round((j.pct || 0) * 100) + '%'; hint.textContent = j.text || '';
      if(j.status === 'running') return setTimeout(tick, 900);
      btn.disabled = false; cancel.hidden = true; prog.hidden = true; this.probe = null;
      if(j.status === 'error'){ hint.textContent = ''; res.innerHTML = `<p class="hint warn">Probe: ${esc(j.error || 'fehlgeschlagen')}</p>`; return; }
      const p = j.result; hint.textContent = '';
      res.innerHTML = `<p class="hint" style="color:var(--text)">Probe (${p.slices} × ${p.slice_s} s): Ergebnis ≈ <b>${fmtB(p.out_bytes)}</b> statt ${fmtB(p.in_bytes)} (−${Math.round((1 - p.out_bytes / p.in_bytes) * 100)} %), Dauer auf diesem Rechner ≈ ${fmtT(p.secs_here)} (ein Prozess).</p>
        <div class="cv-cmp img" style="--p:50%"><div class="before" style="background-image:url('${p.before}')"></div><div class="after" style="background-image:url('${p.after}')"></div><span class="lab" style="left:8px">Original</span><span class="lab" style="right:8px">Ergebnis</span><div class="bar"></div>
        <input type="range" min="0" max="100" value="50" data-cmp aria-label="Vorher/Nachher-Schieber"></div>`;
    };
    setTimeout(tick, 700);
  }
  async cancelProbe(){ if(this.probe){ try{ await api(`/api/convert/probe/${this.probe}/cancel`); }catch{} } }
  destroy(){ clearTimeout(this.t); this.seq++; this.probe = null; }
}
