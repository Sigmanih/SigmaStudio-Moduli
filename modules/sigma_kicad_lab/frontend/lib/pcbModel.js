// =============================================================================
// pcbModel — come si legge la scheda che arriva dal modulo
// =============================================================================
// Il backend manda `board_to_dict`: misure in millimetri, coordinate di ogni
// cosa gia' assolute. Sono le stesse che finiscono nel file, senza conversioni:
// la canvas disegna in coordinate KiCad (y verso il basso) e quello che si
// clicca e' quello che si scrive.
//
// La versione TypeScript di questo file rovesciava la y (`height - y`), e il
// risultato era la scheda specchiata in verticale rispetto a KiCad: un pezzo sul
// bordo alto compariva in basso. Qui non si rovescia niente, e non c'e' nessuna
// conversione da fare prima di scrivere.

/** I colori delle net: pochi e stabili, cosi' la stessa net ha lo stesso colore. */
const COLORI_NET = [
  '#38bdf8', '#f472b6', '#a3e635', '#fbbf24', '#c084fc',
  '#fb7185', '#2dd4bf', '#f97316', '#818cf8', '#4ade80',
];

/**
 * Il colore di una net, dedotto dal nome.
 *
 * Non e' casuale: la stessa net deve avere lo stesso colore fra un ricarico e
 * l'altro della pagina, o il colore non aiuta a seguire un collegamento.
 */
export function coloreNet(nome) {
  const testo = String(nome || '');
  if (!testo) return '#64748b';
  let hash = 5381;
  for (let i = 0; i < testo.length; i += 1) {
    hash = ((hash << 5) + hash + testo.charCodeAt(i)) >>> 0;
  }
  return COLORI_NET[hash % COLORI_NET.length];
}

/** Arrotonda al passo della griglia: le coordinate a caso non si incolonnano. */
export function snap(valore, passo) {
  const p = Number(passo) > 0 ? Number(passo) : 0;
  const v = Number(valore);
  if (!Number.isFinite(v) || p <= 0) return Number.isFinite(v) ? v : 0;
  return Math.round(v / p) * p;
}

function numero(valore, difetto = 0) {
  const n = typeof valore === 'number' ? valore : parseFloat(String(valore));
  return Number.isFinite(n) ? n : difetto;
}

/**
 * Normalizza la scheda grezza del backend.
 *
 * Difensiva di proposito: la canvas non deve sparire perche' un campo manca. Un
 * elenco assente diventa un elenco vuoto, un numero illeggibile diventa il suo
 * difetto — e la scheda si disegna lo stesso, con quello che c'e'.
 */
export function normalizzaScheda(grezza) {
  const g = grezza && typeof grezza === 'object' ? grezza : {};
  const componenti = Array.isArray(g.components) ? g.components : [];
  const piste = Array.isArray(g.tracks) ? g.tracks : [];
  const vie = Array.isArray(g.vias) ? g.vias : [];
  const net = Array.isArray(g.nets) ? g.nets : [];

  return {
    larghezza: numero(g.width_mm, 100),
    altezza: numero(g.height_mm, 80),
    nets: net
      .filter((n) => n && String(n.name || '').trim())
      .map((n) => ({ numero: numero(n.number), nome: String(n.name) })),
    componenti: componenti
      .filter((c) => c && String(c.reference || '').trim())
      .map((c) => ({
        reference: String(c.reference),
        valore: String(c.value || ''),
        libreria: String(c.footprint_lib || ''),
        x: numero(c.x_mm),
        y: numero(c.y_mm),
        rotazione: numero(c.rotation),
        layer: String(c.layer || 'F.Cu'),
        bloccato: Boolean(c.locked),
        larghezza: numero(c.width_mm, 2),
        altezza: numero(c.height_mm, 1.5),
        pads: (Array.isArray(c.pads) ? c.pads : []).map((p) => ({
          numero: String(p.number || ''),
          net: p.net_name ? String(p.net_name) : null,
          x: numero(p.x_mm),
          y: numero(p.y_mm),
          layer: String(p.layer || 'F.Cu'),
        })),
      })),
    piste: piste.map((t) => ({
      da: { x: numero(t.start_x), y: numero(t.start_y) },
      a: { x: numero(t.end_x), y: numero(t.end_y) },
      larghezza: numero(t.width_mm, 0.25),
      layer: String(t.layer || 'F.Cu'),
      net: t.net_name ? String(t.net_name) : null,
    })),
    vie: vie.map((v) => ({
      x: numero(v.x_mm),
      y: numero(v.y_mm),
      diametro: numero(v.size_mm, 0.8),
      foro: numero(v.drill_mm, 0.4),
      net: v.net_name ? String(v.net_name) : null,
    })),
  };
}

/** Il rettangolo della scheda, con un margine per non tagliare i pezzi sul bordo. */
export function vistaScheda(scheda, margine = 2) {
  const m = Number(margine) > 0 ? Number(margine) : 0;
  return {
    x: -m,
    y: -m,
    w: (scheda ? scheda.larghezza : 100) + m * 2,
    h: (scheda ? scheda.altezza : 80) + m * 2,
  };
}
