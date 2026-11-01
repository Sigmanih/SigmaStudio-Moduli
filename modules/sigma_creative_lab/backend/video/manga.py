"""Da un capitolo di manga a una sceneggiatura vignetta per vignetta.

Una trasposizione fedele parte da cio' che c'e' sulla pagina, non da un
riassunto: il primo tentativo — OCR di riga e scene raggruppate a mano — ha
prodotto una storia inventata, perche' l'agente non vedeva le vignette e l'OCR
gli restituiva frammenti di parole senza dire a chi appartenessero.

Qui il lavoro e' diviso in due passi che si possono controllare a occhio:

  1. **segmentazione** (deterministica, OpenCV): la pagina si taglia lungo i
     margini bianchi fra le vignette con tagli ricorsivi, prima orizzontali e
     poi verticali. Ordinare le strisce dall'alto in basso e, dentro ogni
     striscia, le colonne **da destra a sinistra** da' gia' l'ordine di lettura
     giapponese, senza euristiche sulle coordinate;
  2. **lettura** (Qwen3-VL): ogni vignetta ritagliata e ingrandita viene
     descritta in JSON — inquadratura, personaggi, azione, e ogni testo col suo
     tipo (battuta, pensiero, didascalia, onomatopea) nell'ordine manga.

Il risultato e' un file per capitolo, `vignette.json`, accanto alle pagine:
la fonte da cui si costruiscono personaggi e storyboard.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from core.logger import get_logger

log = get_logger("creative_manga")

#: Sopra questa luminosita' un pixel e' carta bianca (le scan JPEG non sono mai 255).
BIANCO = 215
#: Quota di pixel bianchi perche' una riga o colonna sia margine. Non 1.0: una
#: sbavatura di retino o un balloon che sconfina non devono impedire il taglio.
QUOTA_MARGINE = 0.985
#: Spessore minimo di un margine, in frazione del lato della pagina. Sotto e'
#: lo spazio bianco dentro un disegno, non un margine fra vignette.
MARGINE_MIN = 0.006
#: Una vignetta piu' piccola di cosi' (frazione della pagina) e' un frammento.
AREA_MIN = 0.012
LATO_MIN = 0.06


@dataclass
class Vignetta:
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def box(self) -> list[int]:
        return [self.x0, self.y0, self.x1, self.y1]

    @property
    def area(self) -> int:
        return max(0, self.x1 - self.x0) * max(0, self.y1 - self.y0)


def _carica_grigio(pagina: Path) -> np.ndarray:
    from PIL import Image
    with Image.open(pagina) as img:
        return np.asarray(img.convert("L"))


def _corse(maschera: np.ndarray) -> list[tuple[int, int]]:
    """Intervalli [inizio, fine) dove la maschera e' vera."""
    corse, inizio = [], None
    for i, v in enumerate(maschera):
        if v and inizio is None:
            inizio = i
        elif not v and inizio is not None:
            corse.append((inizio, i))
            inizio = None
    if inizio is not None:
        corse.append((inizio, len(maschera)))
    return corse


def _segmenti(bianco: np.ndarray, asse: int, spessore_min: int) -> list[tuple[int, int]]:
    """I tratti pieni lungo un asse, separati da margini bianchi abbastanza spessi.

    asse 0: righe (tagli orizzontali); asse 1: colonne (tagli verticali).
    """
    quota = bianco.mean(axis=1 - asse)
    margini = [(a, b) for a, b in _corse(quota >= QUOTA_MARGINE) if b - a >= spessore_min]
    n = bianco.shape[asse]
    pieni, cursore = [], 0
    for a, b in margini:
        if a > cursore:
            pieni.append((cursore, a))
        cursore = b
    if cursore < n:
        pieni.append((cursore, n))
    return pieni


def _taglia(bianco: np.ndarray, ox: int, oy: int, spessore: tuple[int, int], profondita: int = 0) -> list[Vignetta]:
    """XY-cut ricorsivo nell'ordine di lettura manga."""
    h, w = bianco.shape
    if h == 0 or w == 0 or profondita > 8:
        return []
    righe = _segmenti(bianco, 0, spessore[1])
    if len(righe) > 1:
        out = []
        for a, b in righe:
            out += _taglia(bianco[a:b, :], ox, oy + a, spessore, profondita + 1)
        return out
    colonne = _segmenti(bianco, 1, spessore[0])
    if len(colonne) > 1:
        out = []
        # Da destra a sinistra: e' il verso di lettura del manga.
        for a, b in reversed(colonne):
            out += _taglia(bianco[:, a:b], ox + a, oy, spessore, profondita + 1)
        return out
    # Nessun margine: e' una vignetta. Si stringe sul contenuto.
    pieni = ~bianco
    ys, xs = np.where(pieni.any(axis=1))[0], np.where(pieni.any(axis=0))[0]
    if len(ys) == 0 or len(xs) == 0:
        return []
    return [Vignetta(ox + int(xs[0]), oy + int(ys[0]), ox + int(xs[-1]) + 1, oy + int(ys[-1]) + 1)]


def segmenta(pagina: Path) -> tuple[list[Vignetta], tuple[int, int]]:
    """Le vignette di una pagina nell'ordine di lettura, e le dimensioni della pagina."""
    grigio = _carica_grigio(pagina)
    h, w = grigio.shape
    bianco = grigio >= BIANCO
    spessore = (max(2, int(w * MARGINE_MIN)), max(2, int(h * MARGINE_MIN)))
    grezze = _taglia(bianco, 0, 0, spessore)
    pagina_area = w * h
    vignette = [v for v in grezze
                if v.area >= pagina_area * AREA_MIN
                and (v.x1 - v.x0) >= w * LATO_MIN and (v.y1 - v.y0) >= h * LATO_MIN]
    if not vignette:
        # Una splash page o un disegno a pagina piena: e' una vignetta sola.
        vignette = [Vignetta(0, 0, w, h)]
    return vignette, (w, h)


#: Il grounding di Qwen-VL restituisce coordinate su una griglia 0-1000.
SCALA_VLM = 1000
#: Quota dell'altezza del riquadro piu' basso oltre la quale due riquadri sovrapposti
#: stanno nella stessa fascia: sotto, e' un riquadro del modello che sborda nel margine.
SOVRAPPOSIZIONE_MIN = 0.3

PROMPT_VIGNETTE = """Locate every comic panel (frame) on this manga page. A panel is a framed drawing area; art that bleeds off the page edge still belongs to its panel. Do not split one panel into parts and do not return speech balloons as panels. If the page is a single illustration, return one box for the whole drawing.
Output ONLY a JSON list: [{"bbox_2d": [x1, y1, x2, y2], "label": "panel"}, ...]"""


def _tagli(intervalli: list[tuple[float, float]], lato: float) -> list[list[int]]:
    """Raggruppa gli indici in fasce separate da linee che nessun riquadro attraversa davvero.

    Due riquadri stanno nella stessa fascia se si sovrappongono per una parte
    consistente dell'altezza del piu' basso. Una soglia in pixel non basta:
    a pagina 010 una sovrapposizione di 40 px univa giustamente la vignetta
    alta di destra alla colonna di sinistra, a pagina 020 una di 37 px era
    solo la vignetta grande che sbordava nella riga sotto.
    """
    ordine = sorted(range(len(intervalli)), key=lambda i: intervalli[i][0])
    fasce: list[list[int]] = []
    fine, minima = None, None
    for i in ordine:
        a, b = intervalli[i]
        altezza = max(1.0, b - a)
        if fine is not None:
            sovrapposizione = fine - a
            if sovrapposizione > max(lato * 0.005, SOVRAPPOSIZIONE_MIN * min(altezza, minima)):
                fasce[-1].append(i)
                fine, minima = max(fine, b), min(minima, altezza)
                continue
        fasce.append([i])
        fine, minima = b, altezza
    return fasce


def ordina_manga(vignette: list[Vignetta], w: int, h: int, profondita: int = 0) -> list[Vignetta]:
    """Ordine di lettura giapponese: fasce dall'alto in basso, dentro ogni fascia da destra a sinistra.

    E' lo stesso XY-cut della segmentazione, ma sui riquadri: si taglia solo
    dove nessun riquadro attraversa la linea, quindi una vignetta alta a tutta
    pagina sulla destra viene prima dell'intera colonna di sinistra.
    """
    if len(vignette) <= 1 or profondita > 8:
        return list(vignette)
    righe = _tagli([(v.y0, v.y1) for v in vignette], h)
    if len(righe) > 1:
        return [x for fascia in righe
                for x in ordina_manga([vignette[i] for i in fascia], w, h, profondita + 1)]
    colonne = _tagli([(v.x0, v.x1) for v in vignette], w)
    if len(colonne) > 1:
        colonne.sort(key=lambda fascia: -max(vignette[i].x1 for i in fascia))
        return [x for fascia in colonne
                for x in ordina_manga([vignette[i] for i in fascia], w, h, profondita + 1)]
    # Riquadri intrecciati: vale il centro, prima l'alto, poi la destra.
    return sorted(vignette, key=lambda v: (round((v.y0 + v.y1) / 2 / (h * 0.1)), -(v.x0 + v.x1)))


def _json_lista(testo: str) -> list:
    m = re.search(r"\[.*\]", testo or "", flags=re.S)
    if not m:
        raise ValueError("nessuna lista JSON nella risposta")
    return json.loads(m.group(0))


def _riquadri_vlm(testo: str, w: int, h: int) -> list[Vignetta]:
    out = []
    for voce in _json_lista(testo):
        box = voce.get("bbox_2d") if isinstance(voce, dict) else voce
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        x0, y0, x1, y1 = (float(v) for v in box)
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        out.append(Vignetta(int(x0 / SCALA_VLM * w), int(y0 / SCALA_VLM * h),
                            int(round(x1 / SCALA_VLM * w)), int(round(y1 / SCALA_VLM * h))))
    return out


def _deduplica(vignette: list[Vignetta]) -> list[Vignetta]:
    """Toglie i riquadri contenuti quasi per intero in uno piu' grande (un balloon preso per vignetta)."""
    tenute = []
    for v in sorted(vignette, key=lambda v: -v.area):
        dentro = False
        for t in tenute:
            ix = max(0, min(v.x1, t.x1) - max(v.x0, t.x0))
            iy = max(0, min(v.y1, t.y1) - max(v.y0, t.y0))
            if v.area and ix * iy / v.area > 0.8:
                dentro = True
                break
        if not dentro:
            tenute.append(v)
    return tenute


#: Una zona disegnata scoperta piu' grande di cosi' (frazione della pagina) e' una vignetta persa.
SCOPERTA_MIN = 0.035


def completa_copertura(pagina: Path, vignette: list[Vignetta]) -> list[Vignetta]:
    """Aggiunge le vignette che il modello ha saltato: zone disegnate che nessun riquadro copre.

    Con le vignette diagonali il grounding a volte ne salta una intera, di
    solito la piu' grande (il pugno a tutta pagina, il primo piano dell'occhio).
    Una trasposizione che perde la vignetta chiave non e' fedele, e accorgersene
    costa poco: inchiostro dove non c'e' nessun riquadro.
    """
    import cv2
    grigio = _carica_grigio(pagina)
    h, w = grigio.shape
    inchiostro = (grigio < BIANCO).astype(np.uint8)
    # Chiude il retino e le linee sottili in macchie piene: una vignetta e' un'area, non dei tratti.
    lato = max(3, int(min(w, h) * 0.02))
    inchiostro = cv2.morphologyEx(inchiostro, cv2.MORPH_CLOSE, np.ones((lato, lato), np.uint8))
    for v in vignette:
        inchiostro[max(0, v.y0):v.y1, max(0, v.x0):v.x1] = 0
    # L'apertura toglie le strisce lasciate fra riquadri vicini e i bordi delle vignette.
    apertura = max(5, int(min(w, h) * 0.04))
    inchiostro = cv2.morphologyEx(inchiostro, cv2.MORPH_OPEN, np.ones((apertura, apertura), np.uint8))
    n, _etichette, stats, _ = cv2.connectedComponentsWithStats(inchiostro, connectivity=8)
    aggiunte = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area >= w * h * SCOPERTA_MIN and bw >= w * LATO_MIN * 2 and bh >= h * LATO_MIN * 2:
            aggiunte.append(Vignetta(int(x), int(y), int(x + bw), int(y + bh)))
    # Una vignetta diagonale, tolti i riquadri vicini, resta in pezzi che si toccano: e' una sola.
    vicino = int(min(w, h) * 0.02)
    unite = True
    while unite and len(aggiunte) > 1:
        unite = False
        for i in range(len(aggiunte)):
            for j in range(i + 1, len(aggiunte)):
                a_, b_ = aggiunte[i], aggiunte[j]
                if (a_.x0 - vicino < b_.x1 and b_.x0 - vicino < a_.x1
                        and a_.y0 - vicino < b_.y1 and b_.y0 - vicino < a_.y1):
                    aggiunte[i] = Vignetta(min(a_.x0, b_.x0), min(a_.y0, b_.y0),
                                           max(a_.x1, b_.x1), max(a_.y1, b_.y1))
                    del aggiunte[j]
                    unite = True
                    break
            if unite:
                break
    if aggiunte:
        log.info("[Manga] %s: %d vignette aggiunte dalla copertura", pagina.name, len(aggiunte))
    return vignette + aggiunte


def trova_vignette(pagina: Path, guarda: Callable[[bytes, str], tuple[str, str]] | None = None
                   ) -> tuple[list[Vignetta], tuple[int, int], str]:
    """Le vignette della pagina in ordine manga: riquadri dal modello, taglio XY come riserva.

    Il taglio sui margini bianchi da solo non basta: nelle scan i margini sono
    di 3 px e un personaggio che sconfina li interrompe. Il modello di visione
    trova le vignette come le vede un lettore; il taglio resta per quando il
    modello non risponde o restituisce qualcosa di inservibile.
    """
    from core.harness import vista
    if guarda is None:
        guarda = vista.occhio.guarda
    w, h = dimensioni_pagina(pagina)
    try:
        dati, _info = vista.prepara(pagina)
        testo, _modello = guarda(dati, PROMPT_VIGNETTE)
        vignette = [v for v in _deduplica(_riquadri_vlm(testo, w, h))
                    if v.area >= w * h * AREA_MIN]
        if vignette:
            completate = completa_copertura(pagina, vignette)
            origine = "vlm" if len(completate) == len(vignette) else "vlm+copertura"
            return ordina_manga(completate, w, h), (w, h), origine
        log.warning("[Manga] %s: il modello non ha trovato vignette, uso il taglio XY", pagina.name)
    except Exception as exc:
        log.warning("[Manga] %s: grounding fallito (%s), uso il taglio XY", pagina.name, exc)
    vignette, dimensioni = segmenta(pagina)
    return vignette, dimensioni, "xy"


def dimensioni_pagina(pagina: Path) -> tuple[int, int]:
    from PIL import Image
    with Image.open(pagina) as img:
        return img.size


#: Saturazione media sopra la quale una pagina e' a colori: le scan in bianco e
#: nero hanno 0, quelle ingiallite qualche punto; una tavola a colori oltre 40.
SATURAZIONE_COLORE = 25
#: Luminosita' media sotto la quale una pagina e' nera (separatori, retro di copertina).
LUMINOSITA_NERA = 30


def classifica_pagina(pagina: Path) -> str:
    """'colore', 'nera' o 'bn': i segnali che servono a un adattatore prima di leggere.

    Le tavole a colori sono l'unica fonte dei colori veri dei personaggi: nel
    collaudo Mx0 l'agente ha ridisegnato il protagonista da una vignetta in
    bianco e nero e l'ha vestito di nero, mentre la tavola 005 lo mostrava coi
    capelli castani e la felpa arancione.
    """
    from PIL import Image
    with Image.open(pagina) as img:
        piccola = img.convert("RGB").resize((96, 144))
        hsv = np.asarray(piccola.convert("HSV"), dtype=np.float32)
        grigio = np.asarray(piccola.convert("L"), dtype=np.float32)
    if grigio.mean() < LUMINOSITA_NERA:
        return "nera"
    return "colore" if hsv[..., 1].mean() > SATURAZIONE_COLORE else "bn"


def provino(cartella: Path, out: Path, colonne: int = 10) -> Path:
    """Tutte le pagine in miniatura col loro numero: un solo sguardo per orientarsi nel capitolo."""
    from PIL import Image, ImageDraw
    pagine = sorted(p for p in Path(cartella).iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
    w, h = 150, 230
    righe = max(1, (len(pagine) + colonne - 1) // colonne)
    tela = Image.new("RGB", (colonne * w, righe * h), "white")
    d = ImageDraw.Draw(tela)
    for i, p in enumerate(pagine):
        with Image.open(p) as img:
            mini = img.convert("RGB")
            mini.thumbnail((w - 6, h - 20))
        x, y = (i % colonne) * w, (i // colonne) * h
        tela.paste(mini, (x + 3, y + 18))
        d.text((x + 3, y + 3), p.stem, fill=(220, 0, 0))
    out.parent.mkdir(parents=True, exist_ok=True)
    tela.save(out)
    return out


def disegna_controllo(pagina: Path, vignette: list[Vignetta], out: Path) -> Path:
    """La pagina coi riquadri numerati: serve a vedere in un colpo se il taglio e' giusto."""
    from PIL import Image, ImageDraw
    with Image.open(pagina) as img:
        tela = img.convert("RGB")
    d = ImageDraw.Draw(tela)
    for i, v in enumerate(vignette, 1):
        d.rectangle(v.box, outline=(230, 30, 30), width=3)
        cx, cy = (v.x0 + v.x1) // 2, (v.y0 + v.y1) // 2
        d.ellipse([cx - 16, cy - 16, cx + 16, cy + 16], fill=(230, 30, 30))
        d.text((cx - 5 if i < 10 else cx - 9, cy - 7), str(i), fill="white")
    out.parent.mkdir(parents=True, exist_ok=True)
    tela.save(out)
    return out


# ---------------------------------------------------------------------------
# Lettura delle vignette
# ---------------------------------------------------------------------------

#: Le inquadrature col loro nome italiano: lo storyboard le traduce nel prompt video.
INQUADRATURE = ("campo lunghissimo", "campo lungo", "figura intera", "piano americano",
                "mezza figura", "primo piano", "primissimo piano", "dettaglio")
TIPI_TESTO = ("battuta", "pensiero", "didascalia", "onomatopea")
#: Margine attorno al ritaglio: i balloon sconfinano spesso oltre il bordo della vignetta.
MARGINE_RITAGLIO = 0.03

PROMPT_LETTURA = """Questa e' UNA vignetta di un manga in bianco e nero, tradotto in italiano.
Descrivi SOLO cio' che vedi in questa vignetta. Non inventare nomi, trama o contesto.

Rispondi SOLO con un oggetto JSON con questi campi:
{
  "inquadratura": uno fra "campo lunghissimo", "campo lungo", "figura intera", "piano americano",
                  "mezza figura", "primo piano", "primissimo piano", "dettaglio",
  "angolazione": "frontale", "dal basso", "dall'alto", "di profilo", "di spalle", "soggettiva" o "inclinata",
  "luogo": dove si svolge (es. "cancello di una scuola", "corridoio"), o "" se non si vede,
  "personaggi": [{"aspetto": capelli, vestiti, eta' apparente, "posizione": dove sta nella vignetta,
                  "espressione": ..., "azione": cosa fa}],
  "azione": una frase su cosa succede,
  "effetti": linee cinetiche, retino, sfondo astratto, ecc. o "",
  "testi": [{"tipo": "battuta" | "pensiero" | "didascalia" | "onomatopea",
             "testo": il testo PAROLA PER PAROLA,
             "chi": il personaggio che lo dice (descritto come in "personaggi"), o "fuori campo",
             "box": [x1, y1, x2, y2] il riquadro del balloon o del testo nella vignetta, su scala 0-1000}]
}

Regole per i testi:
- Ordine di lettura manga: da DESTRA a SINISTRA e dall'alto in basso.
- "battuta": balloon liscio con la coda verso chi parla. "pensiero": balloon a nuvola, senza coda o con
  bollicine, oppure testo libero senza contorno vicino a un personaggio. "didascalia": riquadro rettangolare
  del narratore. "onomatopea": suoni ed effetti disegnati (anche in giapponese: scrivili come li vedi).
- Le parole spezzate a capo col trattino vanno ricomposte ("SCA-" + "VALCARE" = "SCAVALCARE").
- Non correggere, non tradurre. Se un testo e' illeggibile scrivi [illeggibile]."""


def ritaglia(pagina: Path, v: Vignetta, out: Path) -> Path:
    """La vignetta su disco, con un po' di margine per i balloon che sbordano."""
    from PIL import Image
    with Image.open(pagina) as img:
        w, h = img.size
        mx, my = int(w * MARGINE_RITAGLIO), int(h * MARGINE_RITAGLIO)
        box = (max(0, v.x0 - mx), max(0, v.y0 - my), min(w, v.x1 + mx), min(h, v.y1 + my))
        out.parent.mkdir(parents=True, exist_ok=True)
        img.convert("RGB").crop(box).save(out)
    return out


def _json_oggetto(testo: str) -> dict:
    m = re.search(r"\{.*\}", testo or "", flags=re.S)
    if not m:
        raise ValueError("nessun oggetto JSON nella risposta")
    return json.loads(m.group(0))


#: Due balloon la cui cima differisce meno di cosi' (scala 0-1000) stanno sulla stessa riga di lettura.
RIGA_BALLOON = 150


def ordina_testi(testi: list[dict]) -> list[dict]:
    """I testi nell'ordine manga, dalle loro posizioni: righe dall'alto, dentro una riga da destra.

    L'ordine dichiarato dal modello non basta: due pensieri affiancati li
    elencava da sinistra a destra, e «devo liberarmi di questo peso» finiva
    dopo la frase che lo segue. Dove manca il riquadro vale l'ordine del modello.
    """
    if not testi or any("box" not in t for t in testi):
        return testi
    righe: list[list[dict]] = []
    for t in sorted(testi, key=lambda t: t["box"][1]):
        if righe and t["box"][1] - righe[-1][0]["box"][1] < RIGA_BALLOON:
            righe[-1].append(t)
        else:
            righe.append([t])
    return [t for riga in righe for t in sorted(riga, key=lambda t: -t["box"][2])]


def _normalizza_lettura(grezza: dict) -> dict:
    """Valori ammessi e tipi coerenti: lo storyboard non deve indovinare cosa intendeva il modello."""
    inq = str(grezza.get("inquadratura") or "").strip().lower()
    testi = []
    for t in grezza.get("testi") or []:
        if not isinstance(t, dict):
            continue
        testo = re.sub(r"\s+", " ", str(t.get("testo") or "")).strip()
        # Nei balloon le parole vanno a capo col trattino: il modello lo copia
        # ("SO-SPETTO"), e la voce lo leggerebbe come una pausa.
        # Tranne prima di un onorifico: «HIRAGI-SENSEI» e' nome e titolo, non una parola a capo.
        testo = re.sub(r"(?<=[^\W\d_])- ?(?!(?:SENSEI|SENPAI|SAMA|KUN|CHAN|SAN)\b)(?=[^\W\d_])", "", testo,
                       flags=re.IGNORECASE)
        if not testo:
            continue
        tipo = str(t.get("tipo") or "").strip().lower()
        voce = {"tipo": tipo if tipo in TIPI_TESTO else "battuta", "testo": testo,
                "chi": str(t.get("chi") or "").strip()}
        box = t.get("box")
        if isinstance(box, (list, tuple)) and len(box) == 4:
            try:
                voce["box"] = [int(float(x)) for x in box]
            except (TypeError, ValueError):
                pass
        testi.append(voce)
    testi = ordina_testi(testi)
    personaggi = [p for p in (grezza.get("personaggi") or []) if isinstance(p, dict)]
    return {
        "inquadratura": inq if inq in INQUADRATURE else (inq or "mezza figura"),
        "angolazione": str(grezza.get("angolazione") or "").strip().lower(),
        "luogo": str(grezza.get("luogo") or "").strip(),
        "personaggi": personaggi,
        "azione": str(grezza.get("azione") or "").strip(),
        "effetti": str(grezza.get("effetti") or "").strip(),
        "testi": testi,
    }


def leggi_vignetta(ritaglio: Path, guarda: Callable[[bytes, str], tuple[str, str]] | None = None,
                   tentativi: int = 2) -> dict:
    """Inquadratura, personaggi, azione e testi di una vignetta ritagliata."""
    from core.harness import vista
    if guarda is None:
        guarda = vista.occhio.guarda
    dati, _info = vista.prepara(ritaglio)
    ultimo = ""
    for _ in range(max(1, tentativi)):
        testo, _modello = guarda(dati, PROMPT_LETTURA)
        ultimo = testo
        try:
            return _normalizza_lettura(_json_oggetto(testo))
        except (ValueError, json.JSONDecodeError) as exc:
            log.warning("[Manga] %s: risposta non JSON (%s), riprovo", ritaglio.name, exc)
    return {**_normalizza_lettura({}), "errore": "risposta illeggibile", "grezzo": ultimo[:2000]}


# ---------------------------------------------------------------------------
# Regia: personaggi riconosciuti, chi parla, inquadratura animata
# ---------------------------------------------------------------------------

PROMPT_REGIA = """This is one panel of a manga that is being turned into an anime, shot by shot.
Characters of the story (the manga is black and white, colors are given here):
{personaggi}

Texts of this panel, in reading order:
{testi}

Reply ONLY with a JSON object:
{{
  "present": [names of the listed characters VISIBLE in the panel; [] if none; an unknown person is "extra"],
  "speakers": [for EACH text above, in order: {{"i": index, "who": a listed name, "narrator" for a caption box,
               or "sfx" for a sound effect; "off_screen": true if the speaker is not visible in the panel}}],
  "shot": "the panel as a 3-5 second anime shot, in English, 40-80 words: shot size and camera angle exactly as \
in the panel, where each character is and where they look, their expression, the ONE action that happens, \
the place, and one simple camera movement (static, slow push-in, slow pan). Use the character names. \
Never mention text or speech bubbles.",
  "colors": "the main colors of the place and of objects in this panel, in English, one short sentence"
}}
Recognize characters from hair, face and clothes. A speech balloon's tail points to the speaker."""


def _elenco_personaggi(personaggi: list[dict]) -> str:
    return "\n".join(f"- {p['name']}: {p.get('description', '').strip()}" for p in personaggi) or "- (none)"


def regia_vignetta(vignetta: dict, ritaglio: Path, personaggi: list[dict],
                   guarda: Callable[[bytes, str], tuple[str, str]] | None = None) -> dict:
    """Chi c'e', chi dice cosa e come si gira la vignetta, guardandola coi nomi della bibbia."""
    from core.harness import vista
    if guarda is None:
        guarda = vista.occhio.guarda
    testi = vignetta.get("testi") or []
    elenco = "\n".join(f"{i}. [{t['tipo']}] {t['testo']}" for i, t in enumerate(testi)) or "(no text)"
    dati, _info = vista.prepara(ritaglio)
    domanda = PROMPT_REGIA.format(personaggi=_elenco_personaggi(personaggi), testi=elenco)
    nomi = {p["name"].lower(): p["name"] for p in personaggi}
    for _ in range(2):
        risposta, _modello = guarda(dati, domanda)
        try:
            grezza = _json_oggetto(risposta)
        except (ValueError, json.JSONDecodeError):
            continue
        presenti = [nomi[str(n).strip().lower()] for n in grezza.get("present") or []
                    if str(n).strip().lower() in nomi]
        voci = {}
        for s in grezza.get("speakers") or []:
            if not isinstance(s, dict):
                continue
            try:
                i = int(s.get("i"))
            except (TypeError, ValueError):
                continue
            chi = str(s.get("who") or "").strip()
            voci[i] = {"chi": nomi.get(chi.lower(), chi.lower() if chi.lower() in ("narrator", "sfx") else chi),
                       "fuori_campo": bool(s.get("off_screen"))}
        return {"presenti": presenti, "voci": voci,
                "shot_en": str(grezza.get("shot") or "").strip(),
                "colori_en": str(grezza.get("colors") or "").strip()}
    return {"presenti": [], "voci": {}, "shot_en": "", "colori_en": "", "errore": "regia illeggibile"}


def _chiave_testo(testo: str) -> str:
    return re.sub(r"[^\w]+", "", testo.lower())


def togli_sconfinati(vignette: list[dict]) -> int:
    """Toglie da una vignetta i testi che appartengono a quella accanto.

    Il ritaglio ha un margine perche' i balloon sbordano, e quel margine a
    volte prende un pezzo del balloon della vignetta vicina: la stessa battuta
    comparirebbe due volte nel film. Fra due vignette consecutive, un testo
    contenuto in un altro piu' lungo resta solo dove e' completo.
    """
    tolti = 0
    for i, v in enumerate(vignette):
        vicine = [vignette[j] for j in (i - 1, i + 1) if 0 <= j < len(vignette)]
        altri = [_chiave_testo(t["testo"]) for w in vicine for t in w.get("testi", [])]
        tenuti = []
        for t in v.get("testi", []):
            k = _chiave_testo(t["testo"])
            if k and len(k) >= 4 and any(k != a and k in a for a in altri):
                tolti += 1
                continue
            tenuti.append(t)
        v["testi"] = tenuti
    return tolti


def leggi_capitolo(cartella: Path, pagine: list[str] | None = None, escluse: list[str] | None = None,
                   note: Callable[[str], None] | None = None) -> Path:
    """Tutto il capitolo in `vignette.json`, ripartendo dalle pagine gia' lette.

    Il file si riscrive dopo ogni pagina: un capitolo intero sono qualche
    centinaio di sguardi, e un'interruzione non deve costare quelli gia' fatti.
    """
    cartella = Path(cartella)
    uscita = cartella / "vignette.json"
    ritagli = cartella / "vignette"
    escluse_set = {Path(p).stem for p in (escluse or [])}
    tutte = sorted(p for p in cartella.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
    if pagine:
        volute = {Path(p).stem for p in pagine}
        tutte = [p for p in tutte if p.stem in volute]
    tutte = [p for p in tutte if p.stem not in escluse_set]

    stato = {"capitolo": cartella.name, "ordine_lettura": "manga (destra-sinistra, alto-basso)",
             "escluse": sorted(escluse_set), "pagine": []}
    if uscita.is_file():
        try:
            stato = {**stato, **json.loads(uscita.read_text(encoding="utf-8"))}
        except (OSError, ValueError) as exc:
            log.warning("[Manga] %s illeggibile (%s): riparto da zero", uscita, exc)
    fatte = {p["pagina"] for p in stato["pagine"] if not p.get("errore")}
    stato["pagine"] = [p for p in stato["pagine"] if p["pagina"] in fatte]

    # Le vignette rimaste illeggibili in una pagina gia' fatta si riprovano:
    # rileggere solo loro costa secondi, rileggere la pagina minuti.
    for p in stato["pagine"]:
        rifatte = False
        for i, v in enumerate(p.get("vignette") or []):
            if not v.get("errore") or not (cartella / v["ritaglio"]).is_file():
                continue
            if note:
                note(f"Rilettura {v['id']}")
            nuova = leggi_vignetta(cartella / v["ritaglio"])
            if not nuova.get("errore"):
                p["vignette"][i] = {k: v[k] for k in ("id", "ordine", "box", "ritaglio")} | nuova
                rifatte = True
        if rifatte:
            togli_sconfinati(p["vignette"])
            uscita.write_text(json.dumps(stato, ensure_ascii=False, indent=2), encoding="utf-8")

    # L'avanzamento si conta sulle pagine ancora da leggere: «Pagina 001 (1/56)»
    # quando ne mancavano sei ha fatto credere all'agente che la lettura fosse ripartita da capo.
    da_leggere = [p for p in tutte if p.name not in fatte]
    for k, pagina in enumerate(da_leggere, 1):
        t0 = time.monotonic()
        if note:
            note(f"Pagina {pagina.name}: {k} di {len(da_leggere)} ancora da leggere "
                 f"({len(fatte)} gia' lette)")
        try:
            vignette, (w, h), origine = trova_vignette(pagina)
            disegna_controllo(pagina, vignette, ritagli / f"{pagina.stem}_controllo.png")
            lette = []
            for i, v in enumerate(vignette, 1):
                file = ritagli / f"{pagina.stem}_{i:02d}.png"
                ritaglia(pagina, v, file)
                lette.append({"id": f"{pagina.stem}_{i:02d}", "ordine": i, "box": v.box,
                              "ritaglio": str(file.relative_to(cartella)).replace("\\", "/"),
                              **leggi_vignetta(file)})
            togli_sconfinati(lette)
            stato["pagine"].append({"pagina": pagina.name, "larghezza": w, "altezza": h,
                                    "segmentazione": origine, "vignette": lette,
                                    "secondi": round(time.monotonic() - t0, 1)})
        except Exception as exc:
            log.exception("[Manga] pagina %s non letta", pagina.name)
            stato["pagine"].append({"pagina": pagina.name, "errore": str(exc), "vignette": []})
        stato["pagine"].sort(key=lambda p: p["pagina"])
        uscita.write_text(json.dumps(stato, ensure_ascii=False, indent=2), encoding="utf-8")
    return uscita


def regia_capitolo(cartella: Path, personaggi: list[dict], note: Callable[[str], None] | None = None) -> Path:
    """Aggiunge a ogni vignetta di `vignette.json` la regia (presenti, voci, inquadratura in inglese).

    Separata dalla lettura perche' dipende dalla bibbia: cambiando un
    personaggio si rifa' solo questa, senza rileggere le pagine.
    """
    cartella = Path(cartella)
    file = cartella / "vignette.json"
    stato = json.loads(file.read_text(encoding="utf-8"))
    firma = _elenco_personaggi(personaggi)
    tutte = [v for p in stato["pagine"] for v in p.get("vignette") or []]
    for k, v in enumerate(tutte, 1):
        if (v.get("regia") or {}).get("revisione_umana"):
            continue
        if (v.get("regia") or {}).get("firma") == firma and not v["regia"].get("errore"):
            continue
        if note:
            note(f"Regia {v['id']} ({k}/{len(tutte)})")
        try:
            regia = regia_vignetta(v, cartella / v["ritaglio"], personaggi)
        except Exception as exc:
            log.exception("[Manga] regia di %s fallita", v["id"])
            regia = {"presenti": [], "voci": {}, "shot_en": "", "colori_en": "", "errore": str(exc)}
        v["regia"] = {**regia, "firma": firma}
        file.write_text(json.dumps(stato, ensure_ascii=False, indent=2), encoding="utf-8")
    return file


# ---------------------------------------------------------------------------
# Storyboard
# ---------------------------------------------------------------------------

#: Durata di un'inquadratura muta, per piano: i campi larghi si leggono piu' lentamente.
DURATA_MUTA = {"campo lunghissimo": 4.0, "campo lungo": 4.0, "figura intera": 3.5}
DURATA_MUTA_PREDEFINITA = 3.0

INQUADRATURE_EN = {
    "campo lunghissimo": "extreme wide shot", "campo lungo": "wide shot", "figura intera": "full shot",
    "piano americano": "medium-long shot", "mezza figura": "medium shot", "primo piano": "close-up",
    "primissimo piano": "extreme close-up", "dettaglio": "detail insert shot",
}


def _prompt_di_riserva(v: dict) -> str:
    """Quando la regia manca: piano e angolazione dalla lettura, il resto lo traduce la produzione."""
    piano = INQUADRATURE_EN.get(v.get("inquadratura", ""), "medium shot")
    return f"{piano}, {v.get('angolazione') or 'eye level'}. {v.get('azione', '')} {v.get('luogo', '')}".strip()


def storyboard(cartella: Path, narratore: str, comparsa: str = "Comparsa",
               escluse: list[str] | None = None) -> list[dict]:
    """Le inquadrature della produzione, una o piu' per vignetta, nell'ordine del manga.

    Una vignetta con N testi diventa N inquadrature: la produzione da' una sola
    battuta per inquadratura, e tagliare un dialogo per farcelo stare
    tradirebbe il fumetto. La prima e' un `cut`, le altre proseguono la stessa
    ripresa (`continue`). Le onomatopee non si dicono: diventano suono.
    """
    cartella = Path(cartella)
    stato = json.loads((cartella / "vignette.json").read_text(encoding="utf-8"))
    pagine_fuori = {Path(str(p)).stem for p in escluse or []}
    shots = []
    for pagina in stato["pagine"]:
        if Path(pagina["pagina"]).stem in pagine_fuori:
            continue
        for v in pagina.get("vignette") or []:
            regia = v.get("regia") or {}
            prompt = regia.get("shot_en") or _prompt_di_riserva(v)
            base = {
                "scene": f"Pagina {Path(pagina['pagina']).stem}",
                "prompt": prompt,
                "refs": list(regia.get("presenti") or []),
                "source_panel": str((cartella / v["ritaglio"]).resolve()),
                "panel_id": v["id"],
                "panel_colors": regia.get("colori_en", ""),
            }
            suoni = [t["testo"] for t in v.get("testi") or [] if t["tipo"] == "onomatopea"]
            if suoni:
                base["audio"] = "sound effects matching: " + ", ".join(suoni)
            righe = [(i, t) for i, t in enumerate(v.get("testi") or []) if t["tipo"] != "onomatopea"]
            if not righe:
                shots.append({**base, "id": f"{v['id']}", "transition": "cut",
                              "duration_s": DURATA_MUTA.get(v.get("inquadratura", ""), DURATA_MUTA_PREDEFINITA)})
                continue
            for k, (i, t) in enumerate(righe):
                voce = (regia.get("voci") or {}).get(str(i)) or (regia.get("voci") or {}).get(i) or {}
                chi = voce.get("chi") or ""
                if t["tipo"] == "didascalia" or chi == "narrator":
                    chi, off = narratore, True
                else:
                    off = bool(voce.get("fuori_campo")) or chi not in base["refs"]
                if not chi or chi in ("sfx", "extra"):
                    chi = comparsa
                shots.append({**base, "id": f"{v['id']}_{k + 1}",
                              "transition": "cut" if k == 0 else "continue",
                              "duration_s": DURATA_MUTA_PREDEFINITA,
                              "dialogue": {"character": chi, "text": t["testo"], "kind": t["tipo"],
                                           "off_screen": off}})
    return shots


# ---------------------------------------------------------------------------
# Job della coda dell'editor: lettura e regia girano per ore, non in un turno dell'agente
# ---------------------------------------------------------------------------

def cartella_di(prod: dict) -> Path:
    """La cartella del capitolo collegata alla produzione da `video_manga_read`."""
    cartella = str((prod.get("manga") or {}).get("folder") or "")
    if not cartella or not Path(cartella).is_dir():
        raise ValueError("la produzione non ha un capitolo collegato: usa prima video_manga_read")
    return Path(cartella)


def _conta(cartella: Path) -> tuple[int, int]:
    file = cartella / "vignette.json"
    if not file.is_file():
        return 0, 0
    stato = json.loads(file.read_text(encoding="utf-8"))
    return len(stato.get("pagine") or []), sum(len(p.get("vignette") or []) for p in stato.get("pagine") or [])


class GpuPerLaVista:
    """Per la durata di un job di visione: la GPU piccola alla vista, l'LLM della chat altrove.

    Prova Mx0: col 27B della chat diviso fra le due schede non restava VRAM
    per Qwen3-VL, che ripiegava sulla CPU a due minuti per vignetta — piu' di
    due ore per un capitolo — mentre l'agente si limitava ad aspettare il job.
    Con un lease sulla GPU piccola l'LLM viene scaricato e, quando l'agente
    torna a chiedere lo stato, si ricarica sulle altre schede.
    """

    def __init__(self, motivo: str):
        self.motivo = motivo
        self.lease = None
        self._env = None

    def __enter__(self) -> "GpuPerLaVista":
        import os
        from core.harness import vista
        gpus = vista._inventario_gpu()
        if len(gpus) < 2:
            return self
        piccola = min(gpus, key=lambda g: (g["vram_gb"], -g["index"]))
        if piccola["vram_gb"] < 7.0:
            return self
        # Prima si spegne la vista: se era accesa teneva gia' un lease sulla stessa scheda.
        vista.occhio.ferma()
        try:
            from core.engine.gpu_lease import leases
            self.lease = leases.acquire(f"vista:{self.motivo}", [piccola["index"]], self.motivo)
        except RuntimeError as exc:
            # Un render ha gia' la scheda: la vista resta dove puo'.
            log.info("[Manga] GPU della vista non riservata: %s", exc)
            return self
        try:
            from core.engine.unified_runtime import sigma_engine
            if getattr(sigma_engine, "loaded_model_name", None):
                # Si aspetta la fine della generazione in corso: scaricare a meta'
                # troncava la risposta dell'agente che aveva appena lanciato il job.
                lock = getattr(sigma_engine, "_generation_lock", None)
                if lock is None or lock.acquire(timeout=600):
                    try:
                        sigma_engine.unload()
                    finally:
                        if lock is not None:
                            lock.release()
        except Exception as exc:
            log.warning("[Manga] LLM della chat non scaricato: %s", exc)
        self._env = os.environ.get("SIGMA_VISTA_DEVICE")
        os.environ["SIGMA_VISTA_DEVICE"] = f"gpu:{piccola['index']}"
        # Un server di visione gia' acceso sulla CPU va rifatto sulla scheda appena liberata.
        vista.occhio.ferma()
        return self

    def rinnova(self) -> None:
        if self.lease:
            from core.engine.gpu_lease import leases
            leases.renew(self.lease)

    def __exit__(self, *_exc) -> None:
        import os
        if self.lease:
            from core.engine.gpu_lease import leases
            leases.release(self.lease)
            if self._env is None:
                os.environ.pop("SIGMA_VISTA_DEVICE", None)
            else:
                os.environ["SIGMA_VISTA_DEVICE"] = self._env


async def job_manga_read(jobs, job: dict) -> dict:
    import asyncio
    pid = job["production"]
    args = job["args"]
    cartella = Path(str(args["folder"]))
    escluse = [str(x) for x in args.get("exclude") or []]
    pagine = sorted(p.stem for p in cartella.iterdir()
                    if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") and p.stem not in set(escluse))
    totale = max(1, len(pagine))

    with GpuPerLaVista(f"lettura {cartella.name}") as gpu:
        def nota(msg: str) -> None:
            gpu.rinnova()
            fatte, _ = _conta(cartella)
            jobs._note(job, msg, fatte / totale)

        await asyncio.to_thread(leggi_capitolo, cartella, None, escluse, nota)
    pagine_lette, vignette = _conta(cartella)
    return {"folder": str(cartella), "pages": pagine_lette, "panels": vignette,
            "file": str(cartella / "vignette.json")}


async def job_manga_direct(jobs, job: dict) -> dict:
    import asyncio
    prod = jobs.prods.get(job["production"])
    cartella = cartella_di(prod)
    personaggi = [{"name": c["name"], "description": c.get("description", "")}
                  for c in (prod.get("bible") or {}).get("characters") or [] if c.get("name")]
    if not personaggi:
        raise ValueError("la bibbia non ha personaggi: aggiungili con video_char_to_production prima della regia")
    _, totale = _conta(cartella)

    with GpuPerLaVista(f"regia {cartella.name}") as gpu:
        def nota(msg: str) -> None:
            gpu.rinnova()
            m = re.search(r"\((\d+)/(\d+)\)", msg)
            jobs._note(job, msg, int(m.group(1)) / max(1, int(m.group(2))) if m else None)

        await asyncio.to_thread(regia_capitolo, cartella, personaggi, nota)
    return {"folder": str(cartella), "panels": totale, "characters": [p["name"] for p in personaggi]}


# ---------------------------------------------------------------------------
# Chi parla: rilettura del copione intero con l'LLM, dopo la regia
# ---------------------------------------------------------------------------

PROMPT_VOCI = """You are fixing speaker attribution in a manga chapter that is being adapted into an anime.
A vision model looked at each panel ALONE and guessed who says each line; it often gives a line to the
character who is visible, even when the visible character is the one being talked about or looked at.
Use the story context to decide.

Characters: {personaggi}
Lines with no named speaker (guards, passers-by, classmates) go to "{comparsa}".
Captions in first person are the narrator: "{narratore}".

Story so far (previous lines, already attributed):
{contesto}

Panels of page {pagina}, in manga reading order:
{vignette}

For EVERY line marked [L<n>] answer who says it and whether that character is visible in the panel.
Reply ONLY with JSON: {{"lines": [{{"id": "L1", "who": "<name>", "off_screen": true|false}}, ...]}}"""


def _righe_pagina(pagina: dict) -> tuple[str, list[tuple[str, dict, int]]]:
    """Il testo da mostrare all'LLM per una pagina e la mappa id riga -> (vignetta, indice testo)."""
    blocchi, mappa, n = [], [], 0
    for v in pagina.get("vignette") or []:
        regia = v.get("regia") or {}
        voci = regia.get("voci") or {}
        righe = []
        for i, t in enumerate(v.get("testi") or []):
            if t["tipo"] == "onomatopea":
                continue
            n += 1
            ipotesi = (voci.get(str(i)) or voci.get(i) or {}).get("chi", "?")
            righe.append(f"  [L{n}] ({t['tipo']}) \"{t['testo']}\" — balloon near: {t.get('chi') or '?'}; "
                         f"vision guess: {ipotesi}")
            mappa.append((f"L{n}", v, i))
        presenti = ", ".join(regia.get("presenti") or []) or "nobody identified"
        blocchi.append(f"Panel {v['id']} — visible: {presenti}. {regia.get('shot_en', '')[:220]}\n"
                       + ("\n".join(righe) if righe else "  (no lines)"))
    return "\n".join(blocchi), mappa


def rivedi_voci(cartella: Path, personaggi: list[str], narratore: str, comparsa: str,
                genera: Callable[[list, int], str], note: Callable[[str], None] | None = None) -> dict:
    """Riattribuisce le battute pagina per pagina, col contesto delle pagine precedenti.

    Nel collaudo Mx0 la regia vignetta per vignetta dava «QUESTO TIZIO... STA
    VOLANDO!» a Hiragi-sensei, che e' in scena perche' e' lui che vola, mentre
    lo dice Taiga guardandolo. Con il copione davanti un LLM lo capisce.
    """
    from core.modules.sigma_creative_lab.video.production import extract_json
    cartella = Path(cartella)
    file = cartella / "vignette.json"
    stato = json.loads(file.read_text(encoding="utf-8"))
    validi = set(personaggi) | {comparsa, narratore}
    contesto: list[str] = []
    cambiate = totale = 0
    pagine = [p for p in stato["pagine"] if p.get("vignette")]
    for k, pagina in enumerate(pagine, 1):
        testo, mappa = _righe_pagina(pagina)
        mappa = [m for m in mappa if not (m[1].get("regia") or {}).get("revisione_umana")]
        if not mappa:
            continue
        if note:
            note(f"Voci pagina {pagina['pagina']} ({k}/{len(pagine)})")
        prompt = PROMPT_VOCI.format(personaggi=", ".join(personaggi), comparsa=comparsa, narratore=narratore,
                                    contesto="\n".join(contesto[-14:]) or "(start of chapter)",
                                    pagina=Path(pagina["pagina"]).stem, vignette=testo)
        try:
            risposta = extract_json(genera([{"role": "user", "content": prompt}], 1500), dict)
        except Exception as exc:
            log.warning("[Manga] voci della pagina %s non riviste: %s", pagina["pagina"], exc)
            continue
        decise = {str(x.get("id")): x for x in (risposta or {}).get("lines") or [] if isinstance(x, dict)}
        for rid, v, i in mappa:
            totale += 1
            scelta = decise.get(rid)
            if not scelta:
                continue
            chi = str(scelta.get("who") or "").strip()
            if chi not in validi:
                chi = next((n for n in validi if n.lower() == chi.lower()), "")
            if not chi:
                continue
            regia = v.setdefault("regia", {})
            voci = regia.setdefault("voci", {})
            prima = (voci.get(str(i)) or voci.get(i) or {}).get("chi")
            voci[str(i)] = {"chi": "narrator" if chi == narratore and v["testi"][i]["tipo"] == "didascalia"
                            else chi, "fuori_campo": bool(scelta.get("off_screen"))}
            if prima != chi:
                cambiate += 1
            regia["voci_riviste"] = True
            contesto.append(f"{chi}: {v['testi'][i]['testo'][:120]}")
        file.write_text(json.dumps(stato, ensure_ascii=False, indent=2), encoding="utf-8")
    # L'impronta dice allo storyboard che le voci sono cambiate dopo di lui.
    stato["voci_riviste_il"] = time.time()
    file.write_text(json.dumps(stato, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"lines": totale, "changed": cambiate}


async def job_manga_speakers(jobs, job: dict) -> dict:
    import asyncio
    prod = jobs.prods.get(job["production"])
    cartella = cartella_di(prod)
    nomi = [c["name"] for c in (prod.get("bible") or {}).get("characters") or [] if c.get("name")]
    narratore = str(job["args"].get("narrator") or "")
    comparsa = next((n for n in nomi if "compars" in n.lower() or "extra" in n.lower()), "Comparsa")
    if narratore not in nomi:
        raise ValueError(f"il narratore '{narratore}' non e' nella bibbia: {nomi}")

    def nota(msg: str) -> None:
        m = re.search(r"\((\d+)/(\d+)\)", msg)
        jobs._note(job, msg, int(m.group(1)) / max(1, int(m.group(2))) if m else None)

    from core.harness import vista

    def genera(messaggi: list, max_tokens: int) -> str:
        return vista.occhio.chiedi(messaggi[-1]["content"], max_tokens)

    with GpuPerLaVista(f"voci {cartella.name}") as gpu:
        def nota_e_rinnova(msg: str) -> None:
            gpu.rinnova()
            nota(msg)

        return await asyncio.to_thread(rivedi_voci, cartella, nomi, narratore, comparsa, genera, nota_e_rinnova)


# ---------------------------------------------------------------------------
# Revisione umana: chi c'e' e chi parla, corretto da chi conosce il fumetto
# ---------------------------------------------------------------------------

def elenco_revisione(cartella: Path, escluse: list[str] | None = None) -> list[dict]:
    """Le vignette con battute o personaggi, con cio' che serve per correggerle a colpo d'occhio.

    Ne' la vista (8B) ne' il 27B riconoscono i personaggi del bianco e nero:
    nel collaudo Mx0 davano «STA VOLANDO!!!» a chi vola invece che a chi lo
    guarda. Chi conosce il fumetto lo corregge in un clic, e la correzione
    resta: regia e rilettura automatica non la sovrascrivono piu'.
    """
    stato = json.loads((Path(cartella) / "vignette.json").read_text(encoding="utf-8"))
    fuori_storia = {Path(str(p)).stem for p in escluse or []}
    out = []
    for pagina in stato["pagine"]:
        if Path(pagina["pagina"]).stem in fuori_storia:
            continue
        for v in pagina.get("vignette") or []:
            regia = v.get("regia") or {}
            voci = regia.get("voci") or {}
            righe = []
            for i, t in enumerate(v.get("testi") or []):
                if t["tipo"] == "onomatopea":
                    continue
                voce = voci.get(str(i)) or voci.get(i) or {}
                righe.append({"i": i, "tipo": t["tipo"], "testo": t["testo"], "chi": voce.get("chi", ""),
                              "fuori_campo": bool(voce.get("fuori_campo"))})
            if not righe and not regia.get("presenti"):
                continue
            out.append({"id": v["id"], "pagina": pagina["pagina"], "ritaglio": str(Path(cartella) / v["ritaglio"]),
                        "presenti": list(regia.get("presenti") or []), "righe": righe,
                        "rivista": bool(regia.get("revisione_umana"))})
    return out


TIPI_RIGA = ("battuta", "pensiero", "didascalia")


def _riscrivi_righe(v: dict, righe: list[dict]) -> dict:
    """Sostituisce battute, pensieri e didascalie di una vignetta; ritorna le voci rinumerate.

    La lettura salta balloon piccoli o ne inventa da un'onomatopea: chi rivede
    deve poter aggiungere, togliere e correggere le righe, non solo cambiare chi
    parla. Le onomatopee restano (diventano suono) e la lettura originale si
    conserva in `testi_letti`.
    """
    testi = v.get("testi") or []
    v.setdefault("testi_letti", [dict(t) for t in testi])
    nuove, voci = [t for t in testi if t.get("tipo") == "onomatopea"], {}
    for r in righe:
        testo = " ".join(str(r.get("testo") or "").split())
        if not testo:
            continue
        tipo = r.get("tipo") if r.get("tipo") in TIPI_RIGA else "battuta"
        voci[str(len(nuove))] = {"chi": str(r.get("chi") or ""), "fuori_campo": bool(r.get("fuori_campo"))}
        nuove.append({"tipo": tipo, "testo": testo})
    v["testi"] = nuove
    return voci


def correggi_vignetta(cartella: Path, panel_id: str, presenti: list[str] | None,
                      voci: dict | None, righe: list[dict] | None = None) -> dict:
    """Salva la correzione di una vignetta e la rende definitiva.

    Con `righe` (l'elenco completo, nell'ordine di lettura) cambiano anche i
    testi: e' la forma per aggiungere o togliere battute; `voci` allora e' ignorato.
    """
    file = Path(cartella) / "vignette.json"
    stato = json.loads(file.read_text(encoding="utf-8"))
    for pagina in stato["pagine"]:
        for v in pagina.get("vignette") or []:
            if v["id"] != panel_id:
                continue
            regia = v.setdefault("regia", {})
            if presenti is not None:
                regia["presenti"] = [str(n) for n in presenti]
            if righe is not None:
                regia["voci"] = _riscrivi_righe(v, righe)
            elif voci is not None:
                attuali = regia.setdefault("voci", {})
                for i, voce in voci.items():
                    attuali[str(i)] = {"chi": str(voce.get("chi") or ""), "fuori_campo": bool(voce.get("fuori_campo"))}
            regia["revisione_umana"] = True
            regia["voci_riviste"] = True
            file.write_text(json.dumps(stato, ensure_ascii=False, indent=2), encoding="utf-8")
            return v
    raise ValueError(f"vignetta non trovata: {panel_id}")


def applica_allo_storyboard(prod: dict, cartella: Path, panel_id: str, narratore: str, comparsa: str) -> int:
    """Rifa' in place le inquadrature di una vignetta corretta; ritorna quante ne sono cambiate.

    Ricostruire lo storyboard intero perderebbe fotogrammi chiave e clip gia'
    fatti per tutte le altre vignette. Qui si tocca solo il blocco di questa
    vignetta: un'inquadratura con lo stesso testo resta (fotogramma e clip
    compresi, ma torna da rifare se cambia chi parla o chi c'e'); una battuta
    aggiunta diventa un'inquadratura nuova, una tolta sparisce.
    """
    from .production import _prompt_hash, new_shot
    shots = prod.get("shots") or []
    nuove = [s for s in storyboard(cartella, narratore, comparsa) if s.get("panel_id") == panel_id]
    posizioni = [k for k, s in enumerate(shots) if s.get("panel_id") == panel_id]
    vecchie = [shots[k] for k in posizioni]
    if posizioni:
        dove = posizioni[0]
    else:
        # Vignetta che prima non aveva inquadrature: va dopo l'ultima che la precede.
        dove = next((k for k, s in enumerate(shots) if str(s.get("panel_id") or "") > panel_id), len(shots))

    def testo(s: dict) -> str:
        return (s.get("dialogue") or {}).get("text", "")

    cambiate, blocco = 0, []
    for nuova in nuove:
        shot = next((s for s in vecchie if testo(s) == testo(nuova)), None)
        if shot is None:
            shot = new_shot(**nuova)
            shot["ltx_prompt"] = {"text": shot["prompt"], "source": _prompt_hash(shot["prompt"])}
            blocco.append(shot)
            cambiate += 1
            continue
        vecchie.remove(shot)
        prima = (shot.get("refs"), (shot.get("dialogue") or {}).get("character"),
                 (shot.get("dialogue") or {}).get("off_screen"), (shot.get("dialogue") or {}).get("kind"))
        shot.update(id=nuova["id"], transition=nuova["transition"], refs=nuova["refs"])
        if nuova.get("dialogue"):
            d = shot.setdefault("dialogue", {})
            if d.get("character") != nuova["dialogue"]["character"]:
                # La voce sintetizzata era di un altro personaggio: va rifatta.
                d.pop("audio", None)
                d.pop("source", None)
            d.update(nuova["dialogue"])
        else:
            shot.pop("dialogue", None)
        dopo = (shot.get("refs"), (shot.get("dialogue") or {}).get("character"),
                (shot.get("dialogue") or {}).get("off_screen"), (shot.get("dialogue") or {}).get("kind"))
        if dopo != prima:
            cambiate += 1
            if shot.get("status") == "done":
                shot.update(status="pending", attempts=0)
        blocco.append(shot)
    cambiate += len(vecchie)
    resto = [s for s in shots if s.get("panel_id") != panel_id]
    prima_di = sum(1 for k in range(dove) if shots[k].get("panel_id") != panel_id)
    prod["shots"] = resto[:prima_di] + blocco + resto[prima_di:]
    return cambiate
