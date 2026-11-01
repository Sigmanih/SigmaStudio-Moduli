"""Scene didattiche a blocchi: il modello sceglie cosa mostrare, il disegno lo fa questo codice.

Con l'HTML libero il modello sbagliava i disegni (una parabola resa come retta,
un grafico sopra la formula) e nessun controllo automatico se ne accorgeva in
modo affidabile. Qui la scena e' un JSON di blocchi; impaginazione, assi,
curve e animazioni sono scritti una volta e sono esatti per costruzione:
una curva y = f(x) segue f, punto per punto.

Spec:
{"title": "...", "duration": 10,
 "params": {"g": 9.81, "v0": 20, "theta": 0.785},          costanti usabili nelle espressioni
 "blocks": [
   {"type": "formula", "tex": "...", "start": 1, "caption": "..."},
   {"type": "bullets", "items": ["...", "..."], "start": 2, "step": 1.2},
   {"type": "plot", "start": 3, "draw": 4, "x": [0, 10], "y": [0, 6], "xlabel": "x (m)", "ylabel": "y (m)",
    "curves": [{"expr": "x*tan(theta) - g*x^2/(2*v0^2*cos(theta)^2)", "label": "traiettoria"}],
    "point": true},
   {"type": "trajectory", "start": 3, "draw": 5, "t": [0, 2.9], "x": [0, 45], "y": [0, 12],
    "xt": "v0*cos(theta)*t", "yt": "v0*sin(theta)*t - g*t^2/2", "vx": "v0*cos(theta)", "vy": "v0*sin(theta) - g*t",
    "xlabel": "x (m)", "ylabel": "y (m)"}
 ]}
"""

from __future__ import annotations

import json
import re

BLOCK_TYPES = ("formula", "bullets", "plot", "trajectory", "shapes")
SHAPE_KINDS = ("polygon", "segment", "circle", "label", "square_on")
# Nomi ammessi nelle espressioni: funzioni di Math, costanti, variabili, parametri.
_FUNCS = {"sin", "cos", "tan", "asin", "acos", "atan", "atan2", "sinh", "cosh", "tanh", "sqrt", "cbrt", "exp",
          "log", "log10", "log2", "abs", "min", "max", "pow", "floor", "ceil", "round", "sign", "PI", "E", "pi", "e"}
_VARS = {"x", "t"}


def check_expr(expr: str, params: dict) -> str | None:
    """Errore leggibile se l'espressione usa nomi non ammessi o caratteri strani; None se va bene."""
    if not isinstance(expr, str) or not expr.strip():
        return "espressione vuota"
    if re.search(r"[^0-9a-zA-Z_+\-*/^().,\s]", expr):
        return f"caratteri non ammessi in '{expr}'"
    names = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", expr))
    unknown = names - _FUNCS - _VARS - set(params)
    return f"nomi sconosciuti {sorted(unknown)} in '{expr}'" if unknown else None


_SHAPE_ALIASES = {"square": "square_on", "square_on": "square_on", "polygon": "polygon", "triangle": "polygon",
                  "rectangle": "polygon", "segment": "segment", "line": "segment", "circle": "circle",
                  "label": "label", "text_label": "label"}


def _shape_points(it: dict) -> list:
    pts = list(it.get("points") or []) + [it[q] for q in ("from", "to", "center", "at") if isinstance(it.get(q), list)]
    if it.get("kind") == "square_on" and isinstance(it.get("from"), list) and isinstance(it.get("to"), list):
        (ax, ay), (cx, cy) = it["from"], it["to"]
        sd = -1 if it.get("side") == -1 else 1
        pts += [[cx - sd * (cy - ay), cy + sd * (cx - ax)], [ax - sd * (cy - ay), ay + sd * (cx - ax)]]
    if it.get("kind") == "circle" and isinstance(it.get("center"), list):
        r = float(it.get("r") or 1)
        pts += [[it["center"][0] - r, it["center"][1] - r], [it["center"][0] + r, it["center"][1] + r]]
    return [pt for pt in pts if isinstance(pt, list) and len(pt) == 2 and all(isinstance(v, (int, float)) for v in pt)]


def _range(r) -> tuple[float, float]:
    if isinstance(r, list) and len(r) == 2 and all(isinstance(v, (int, float)) for v in r) and r[0] < r[1]:
        return float(r[0]), float(r[1])
    return float("inf"), float("-inf")


def _add_implied_triangle(b: dict) -> None:
    """Tre quadrati che poggiano su tre soli vertici: il triangolo c'e' anche se il modello non l'ha disegnato."""
    items = b.get("items") or []
    if any(isinstance(it, dict) and it.get("kind") == "polygon" for it in items):
        return
    ends = {tuple(pt) for it in items if isinstance(it, dict) and it.get("kind") == "square_on"
            for pt in _shape_points({"points": [it.get("from"), it.get("to")]})}
    if len(ends) == 3:
        b["items"] = [{"kind": "polygon", "points": [list(pt) for pt in sorted(ends)], "color": "#eef2f7"}] + items


def _squares_outside(items: list) -> None:
    """I quadrati sui lati di un poligono vanno all'esterno, qualunque "side" abbia scelto il modello.

    Il modello sbaglia il segno quasi sempre (lezione su Pitagora: tre quadrati
    su tre disegnati sopra il triangolo). Esterno = dalla parte opposta al
    baricentro dei poligoni della figura.
    """
    poly = [pt for it in items if isinstance(it, dict) and it.get("kind") == "polygon"
            for pt in _shape_points({"points": it.get("points")})]
    # Senza poligono (capita: solo i tre quadrati) la figura e' quella dei lati su cui poggiano.
    poly = poly or [pt for it in items if isinstance(it, dict) and it.get("kind") == "square_on"
                    for pt in _shape_points({"points": [it.get("from"), it.get("to")]})]
    if not poly:
        return
    gx, gy = sum(pt[0] for pt in poly) / len(poly), sum(pt[1] for pt in poly) / len(poly)
    for it in items:
        if not (isinstance(it, dict) and it.get("kind") == "square_on"):
            continue
        a, c = it.get("from"), it.get("to")
        if len(_shape_points({"points": [a, c]})) != 2:
            continue
        nx, ny = -(c[1] - a[1]), c[0] - a[0]                       # normale del lato per side = 1
        mid = ((a[0] + c[0]) / 2, (a[1] + c[1]) / 2)
        it["side"] = 1 if nx * (mid[0] - gx) + ny * (mid[1] - gy) > 0 else -1


def normalize(spec: dict) -> dict:
    """Corregge gli errori ricorrenti dei modelli prima di validare.

    Il caso visto davvero: figure scritte come blocchi a se' ("type": "square")
    invece che dentro un blocco "shapes", per tre tentativi di fila. Si
    raccolgono in un solo blocco di figure e, se mancano, gli assi si
    ricavano dai punti.
    """
    if not isinstance(spec, dict) or not isinstance(spec.get("blocks"), list):
        return spec
    blocks, loose = [], []
    for b in spec["blocks"]:
        kind = b.get("type") if isinstance(b, dict) else None
        if kind in _SHAPE_ALIASES and kind not in BLOCK_TYPES:
            loose.append({**{k: v for k, v in b.items() if k != "type"}, "kind": _SHAPE_ALIASES[kind]})
        else:
            blocks.append(b)
    if loose:
        start = min(float(x.get("start") or 0) for x in loose)
        blocks.append({"type": "shapes", "start": start, "draw": float(spec.get("duration") or 8) * 0.5, "items": loose})
    for n, b in enumerate(blocks):
        items = b.get("items") if isinstance(b, dict) and b.get("type") == "shapes" else None
        if isinstance(items, list) and items and all(isinstance(it, dict) and it.get("kind") in ("label", "text_label")
                                                      for it in items):
            # Solo scritte, senza figura: con una scala propria finivano sopra il disegno dell'altro blocco.
            blocks[n] = {"type": "bullets", "start": b.get("start", 0),
                         "items": [str(it.get("text", "")) for it in items if str(it.get("text", "")).strip()]}
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "shapes":
            for it in b.get("items") or []:
                if isinstance(it, dict) and it.get("kind") in _SHAPE_ALIASES:
                    it["kind"] = _SHAPE_ALIASES[it["kind"]]
            _add_implied_triangle(b)
            _squares_outside(b.get("items") or [])
            pts = [pt for it in b.get("items") or [] if isinstance(it, dict) for pt in _shape_points(it)]
            if pts:
                # Assi del modello tenuti solo se contengono tutto: nella lezione di prova il quadrato
                # sull'ipotenusa usciva dal riquadro.
                xs, ys = [pt[0] for pt in pts], [pt[1] for pt in pts]
                mx, my = max(1.0, (max(xs) - min(xs)) * 0.1), max(1.0, (max(ys) - min(ys)) * 0.1)
                x0, x1 = _range(b.get("x"))
                y0, y1 = _range(b.get("y"))
                b["x"] = [min(x0, min(xs) - mx), max(x1, max(xs) + mx)]
                b["y"] = [min(y0, min(ys) - my), max(y1, max(ys) + my)]
    return {**spec, "blocks": blocks}


def validate(spec: dict) -> list[str]:
    problems = []
    if not isinstance(spec, dict):
        return ["the scene must be a JSON object"]
    params = spec.get("params") or {}
    if not isinstance(params, dict) or not all(isinstance(v, (int, float)) for v in params.values()):
        problems.append("params must map names to numbers")
        params = {}
    blocks = spec.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        return problems + ["blocks must be a non-empty list"]
    for i, b in enumerate(blocks):
        kind = b.get("type") if isinstance(b, dict) else None
        if kind not in BLOCK_TYPES:
            problems.append(f"block {i}: type must be one of {BLOCK_TYPES}")
            continue
        if kind == "formula" and not str(b.get("tex", "")).strip():
            problems.append(f"block {i}: formula without tex")
        if kind == "bullets" and not b.get("items"):
            problems.append(f"block {i}: bullets without items")
        if kind == "plot":
            for c in b.get("curves") or []:
                err = check_expr(c.get("expr", ""), params)
                if err:
                    problems.append(f"block {i}: {err}")
            if not b.get("curves"):
                problems.append(f"block {i}: plot without curves")
        if kind == "trajectory":
            for key in ("xt", "yt"):
                err = check_expr(b.get(key, ""), params)
                if err:
                    problems.append(f"block {i}: {key}: {err}")
            for key in ("vx", "vy"):
                if b.get(key):
                    err = check_expr(b[key], params)
                    if err:
                        problems.append(f"block {i}: {key}: {err}")
        if kind == "shapes":
            items = b.get("items")
            if not isinstance(items, list) or not items:
                problems.append(f"block {i}: shapes without items")
            for k, it in enumerate(items or []):
                if not isinstance(it, dict) or it.get("kind") not in SHAPE_KINDS:
                    problems.append(f"block {i} item {k}: kind must be one of {SHAPE_KINDS}")
                    continue
                pts = [*(it.get("points") or []), *([it[q] for q in ("from", "to", "center", "at") if q in it])]
                if not pts or not all(isinstance(pt, list) and len(pt) == 2 and all(isinstance(v, (int, float)) for v in pt)
                                      for pt in pts):
                    problems.append(f"block {i} item {k}: coordinates must be [x, y] numbers")
        for key in ("x", "y", "t"):
            r = b.get(key)
            if r is not None and not (isinstance(r, list) and len(r) == 2 and all(isinstance(v, (int, float)) for v in r)
                                      and r[1] > r[0]):
                problems.append(f"block {i}: {key} must be [min, max] with max > min")
    return problems


# Il motore della scena: legge window.SPEC e disegna tutto in seek(t). Nessun timer.
_RUNTIME = r"""
<div id="root"></div>
<script>
(function () {
  const S = window.SPEC, P = S.params || {};
  const names = Object.keys(P);
  const fn = (expr, vars) => {
    const body = expr.replace(/\^/g, '**').replace(/\bpi\b/g, 'PI').replace(/\be\b/g, 'E');
    const f = new Function(...vars, ...names, 'with (Math) { return (' + body + '); }');
    return (...a) => f(...a, ...names.map(n => P[n]));
  };
  window.sceneDuration = +S.duration || 10;
  const root = document.getElementById('root');
  const el = (tag, css, parent) => { const e = document.createElement(tag); e.style.cssText = css; (parent || root).appendChild(e); return e; };
  const title = el('div', 'position:absolute;top:56px;left:0;right:0;text-align:center;font-size:60px;font-weight:600');
  title.textContent = S.title || '';
  const graphic = S.blocks.some(b => b.type === 'plot' || b.type === 'trajectory' || b.type === 'shapes');
  // Con un grafico: testo a sinistra, grafico a destra. Senza: testo centrato a tutta larghezza.
  const textCol = el('div', graphic ? 'position:absolute;left:80px;top:190px;width:700px;bottom:60px;display:flex;flex-direction:column;gap:34px'
                                    : 'position:absolute;left:220px;right:220px;top:220px;bottom:60px;display:flex;flex-direction:column;gap:40px;align-items:center');
  const items = [];
  S.blocks.forEach(b => {
    if (b.type === 'formula') {
      const box = el('div', 'font-size:' + (graphic ? 44 : 56) + 'px', textCol);
      const f = el('div', '', box); tex(f, b.tex, true);
      let cap = null;
      if (b.caption) { cap = el('div', 'font-size:30px;color:#9fb0c4;margin-top:6px;text-align:center', box); cap.textContent = b.caption; }
      items.push(t => { const p = progress(t, +b.start || 0, 0.8); box.style.opacity = p; box.style.transform = 'translateY(' + (1 - p) * 20 + 'px)'; });
    } else if (b.type === 'bullets') {
      const list = el('div', 'display:flex;flex-direction:column;gap:22px;font-size:' + (graphic ? 34 : 42) + 'px;align-self:stretch', textCol);
      (b.items || []).forEach((txt, k) => {
        const row = el('div', 'display:flex;gap:18px;align-items:flex-start', list);
        el('span', 'color:#4fc3f7', row).textContent = '▸';
        const body = el('span', '', row);
        // $...$ nel testo diventa formula in linea.
        String(txt).split(/(\$[^$]+\$)/).forEach(part => {
          if (/^\$[^$]+\$$/.test(part)) { const m = el('span', '', body); tex(m, part.slice(1, -1), false); }
          else body.appendChild(document.createTextNode(part));
        });
        const at = (+b.start || 0) + k * (+b.step || 1.2);
        items.push(t => { const p = progress(t, at, 0.6); row.style.opacity = p; row.style.transform = 'translateX(' + (1 - p) * 24 + 'px)'; });
      });
    } else if (b.type === 'shapes') {
      const W = S.blocks.some(x => x.type === 'formula' || x.type === 'bullets') ? 960 : 1500, H = 720;
      const cv = el('canvas', 'position:absolute;right:80px;top:200px'); cv.width = W; cv.height = H;
      const g = cv.getContext('2d');
      const xr = b.x || [0, 10], yr = b.y || [0, 10], M = 60;
      // Stessa scala sui due assi: un quadrato deve restare un quadrato.
      const k = Math.min((W - 2 * M) / (xr[1] - xr[0]), (H - 2 * M) / (yr[1] - yr[0]));
      const ox = (W - k * (xr[1] - xr[0])) / 2, oy = (H - k * (yr[1] - yr[0])) / 2;
      const X = v => ox + (v - xr[0]) * k, Y = v => H - oy - (v - yr[0]) * k;
      const colors = ['#4fc3f7', '#ffb74d', '#81c784', '#e57373', '#ba68c8'];
      const its = b.items || [], step = (+b.draw || 4) / Math.max(1, its.length);
      items.push(t => {
        g.clearRect(0, 0, W, H);
        its.forEach((it, n) => {
          const p = progress(t, (+b.start || 0) + n * step, Math.max(0.4, step * 0.8));
          if (p <= 0) return;
          const color = it.color || colors[n % colors.length];
          g.globalAlpha = p; g.lineWidth = 5; g.strokeStyle = color; g.fillStyle = color; g.font = '34px Segoe UI, Arial';
          let poly = null;
          if (it.kind === 'polygon') poly = it.points;
          if (it.kind === 'square_on') {
            // Quadrato costruito sul lato from->to, dalla parte indicata (side: 1 o -1).
            const [a, c] = [it.from, it.to], dx = c[0] - a[0], dy = c[1] - a[1], sd = it.side === -1 ? -1 : 1;
            poly = [a, c, [c[0] - sd * dy, c[1] + sd * dx], [a[0] - sd * dy, a[1] + sd * dx]];
          }
          if (poly) {
            g.beginPath(); poly.forEach((pt, q) => q ? g.lineTo(X(pt[0]), Y(pt[1])) : g.moveTo(X(pt[0]), Y(pt[1]))); g.closePath();
            g.save(); g.globalAlpha = 0.18 * p; g.fill(); g.restore(); g.stroke();
            if (it.label) { const cx = poly.reduce((s_, pt) => s_ + pt[0], 0) / poly.length, cy = poly.reduce((s_, pt) => s_ + pt[1], 0) / poly.length;
              g.fillStyle = '#eef2f7'; g.textAlign = 'center'; g.fillText(it.label, X(cx), Y(cy) + 12); g.textAlign = 'start'; }
          } else if (it.kind === 'segment') {
            g.beginPath(); g.moveTo(X(it.from[0]), Y(it.from[1]));
            g.lineTo(X(it.from[0] + (it.to[0] - it.from[0]) * p), Y(it.from[1] + (it.to[1] - it.from[1]) * p)); g.stroke();
          } else if (it.kind === 'circle') {
            g.beginPath(); g.arc(X(it.center[0]), Y(it.center[1]), (+it.r || 1) * k, 0, 2 * Math.PI * p); g.stroke();
          } else if (it.kind === 'label') {
            g.fillStyle = it.color || '#eef2f7'; g.fillText(String(it.text || ''), X(it.at[0]), Y(it.at[1]));
          }
          g.globalAlpha = 1;
        });
      });
    } else {
      const W = graphic && S.blocks.some(x => x.type === 'formula' || x.type === 'bullets') ? 960 : 1500, H = 720;
      const cv = el('canvas', 'position:absolute;right:80px;top:200px'); cv.width = W; cv.height = H;
      const g = cv.getContext('2d');
      const xr = b.x || [0, 10], yr = b.y || [0, 10], M = 70;
      const X = v => M + (v - xr[0]) / (xr[1] - xr[0]) * (W - 2 * M);
      const Y = v => H - M - (v - yr[0]) / (yr[1] - yr[0]) * (H - 2 * M);
      const curves = b.type === 'plot'
        ? (b.curves || []).map(c => ({ c, f: fn(c.expr, ['x']) }))
        : [{ c: { label: b.label || '' }, fx: fn(b.xt, ['t']), fy: fn(b.yt, ['t']),
             vx: b.vx ? fn(b.vx, ['t']) : null, vy: b.vy ? fn(b.vy, ['t']) : null }];
      const colors = ['#4fc3f7', '#ffb74d', '#81c784', '#e57373'];
      const axes = (alpha) => {
        g.globalAlpha = alpha; g.strokeStyle = '#6b7c93'; g.lineWidth = 3; g.fillStyle = '#c9d4e3'; g.font = '30px Segoe UI, Arial';
        const x0 = X(Math.max(xr[0], Math.min(xr[1], 0))), y0 = Y(Math.max(yr[0], Math.min(yr[1], 0)));
        g.beginPath(); g.moveTo(M, y0); g.lineTo(W - M + 20, y0); g.moveTo(x0, H - M); g.lineTo(x0, M - 20); g.stroke();
        g.fillText(b.xlabel || 'x', W - M - 80, y0 - 16); g.fillText(b.ylabel || 'y', x0 + 14, M - 4);
        g.globalAlpha = 1;
      };
      const arrow = (x1, y1, x2, y2, color) => {
        const a = Math.atan2(y2 - y1, x2 - x1);
        g.strokeStyle = g.fillStyle = color; g.lineWidth = 5;
        g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke();
        g.beginPath(); g.moveTo(x2, y2); g.lineTo(x2 - 18 * Math.cos(a - 0.4), y2 - 18 * Math.sin(a - 0.4));
        g.lineTo(x2 - 18 * Math.cos(a + 0.4), y2 - 18 * Math.sin(a + 0.4)); g.closePath(); g.fill();
      };
      items.push(t => {
        g.clearRect(0, 0, W, H);
        const show = progress(t, +b.start || 0, 0.6);
        if (show <= 0) return;
        axes(show);
        const p = progress(t, (+b.start || 0) + 0.4, +b.draw || 4);
        g.save(); g.beginPath(); g.rect(M - 4, M - 30, W - 2 * M + 8, H - 2 * M + 34); g.clip();
        curves.forEach((cv_, k) => {
          const color = colors[k % colors.length], N = 400;
          g.strokeStyle = color; g.lineWidth = 5; g.beginPath();
          let last = null;
          for (let i = 0; i <= N * p; i++) {
            let px, py;
            if (b.type === 'plot') { const x = xr[0] + (xr[1] - xr[0]) * i / N; px = X(x); py = Y(cv_.f(x)); }
            else { const tt = b.t[0] + (b.t[1] - b.t[0]) * i / N; px = X(cv_.fx(tt)); py = Y(cv_.fy(tt)); }
            if (!isFinite(py) || !isFinite(px)) { last = null; continue; }
            last ? g.lineTo(px, py) : g.moveTo(px, py); last = [px, py];
          }
          g.stroke();
          if (last && (b.point !== false)) { g.fillStyle = '#ffb74d'; g.beginPath(); g.arc(last[0], last[1], 13, 0, 7); g.fill(); }
          if (b.type === 'trajectory' && last && cv_.vx && cv_.vy && p > 0) {
            const tt = b.t[0] + (b.t[1] - b.t[0]) * p, k2 = +b.vscale || 6;
            const vx = cv_.vx(tt), vy = cv_.vy(tt);
            arrow(last[0], last[1], last[0] + vx * k2, last[1], '#81c784');
            arrow(last[0], last[1], last[0], last[1] - vy * k2, '#e57373');
          }
          if (cv_.c.label && p > 0.98 && last) { g.fillStyle = color; g.font = '30px Segoe UI, Arial'; g.fillText(cv_.c.label, Math.min(last[0] + 18, W - 260), last[1] - 18); }
        });
        g.restore();
      });
    }
  });
  window.seek = function (t) {
    title.style.opacity = progress(t, 0, 0.8);
    items.forEach(f => f(t));
  };
})();
</script>"""


def to_html(spec: dict) -> str:
    """Pagina della scena: la spec come dato, il motore come codice fisso."""
    # </ dentro un JSON in <script> chiuderebbe il tag: si spezza.
    data = json.dumps(spec, ensure_ascii=False).replace("</", "<\\/")
    return f"<script>window.SPEC = {data};</script>{_RUNTIME}"


AUTHOR_SYSTEM = """You design ONE animated teaching slide for a lesson video, as JSON only (no markdown, no prose).
Schema:
{"title": string, "duration": seconds,
 "params": {name: number, ...},
 "blocks": [ ... ]}
Block types (use 1 to 4 blocks; a slide with a graphic puts text on the left, the graphic on the right):
- {"type":"formula","tex": LaTeX string,"start": s,"caption": optional short Italian text}
- {"type":"bullets","items":[Italian sentences, may contain $inline latex$],"start": s,"step": seconds between items}
- {"type":"plot","start": s,"draw": seconds,"x":[min,max],"y":[min,max],"xlabel":..,"ylabel":..,
   "curves":[{"expr": expression in x,"label":..}],"point": true}
- {"type":"trajectory","start": s,"draw": seconds,"t":[t0,t1],"x":[min,max],"y":[min,max],
   "xt": x(t),"yt": y(t),"vx": optional velocity x(t),"vy": optional velocity y(t),"xlabel":..,"ylabel":..}
- {"type":"shapes","start": s,"draw": seconds,"x":[min,max],"y":[min,max],"items":[ drawn one after the other:
   {"kind":"polygon","points":[[x,y],...],"label":..}, {"kind":"segment","from":[x,y],"to":[x,y]},
   {"kind":"circle","center":[x,y],"r": number}, {"kind":"label","at":[x,y],"text":..},
   {"kind":"square_on","from":[x,y],"to":[x,y],"side": 1 or -1,"label":..} = square built on that side ]}
   Same scale on both axes: make x/y ranges contain every point, squares included.
Expressions: JavaScript-like math with ^ for powers, functions sin cos tan sqrt exp log abs, constants pi,
variables x (plot) or t (trajectory) and the names defined in params. Angles in radians.
Choose x/y ranges that really contain the curve (compute a few values). All on-screen text in Italian.
Stagger "start" so things appear one after the other and stay readable; duration about the requested seconds."""


def json_from(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in the answer")
    raw = text[start:end + 1]
    try:
        return json.loads(raw, strict=False)
    except ValueError:
        pass
    # Il LaTeX scritto dentro il JSON con un solo backslash: "rac" diventa form feed
    # piu' "rac", "	heta" un tab. Si raddoppiano i backslash dei comandi LaTeX
    # (escape valida seguita da altre lettere) e quelli che non sono escape JSON.
    fixed = re.sub(r'\\(?=[bfnrt][A-Za-z])', r'\\\\', raw)
    fixed = re.sub(r'\\u(?![0-9a-fA-F]{4})', r'\\\\u', fixed)
    fixed = re.sub(r'\\(?![\\"/bfnrtu])', r'\\\\', fixed)
    try:
        return json.loads(fixed, strict=False)
    except ValueError as e:
        pos = getattr(e, "pos", 0) or 0
        raise ValueError(f"{e}; near: ...{fixed[max(0, pos - 60):pos + 40]}...") from e
