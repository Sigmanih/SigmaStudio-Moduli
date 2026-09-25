// =============================================================================
// pcbApi — le chiamate al modulo KiCad, in un posto solo
// =============================================================================
// Ogni operazione dell'editor passa da qui. Il modulo espone gli stessi tool che
// usa l'agente (`/api/kicad/...`), quindi quello che l'utente trascina e quello
// che l'agente scrive finiscono nella stessa funzione, con le stesse
// validazioni: due strade per la stessa modifica divergono sempre, e divergono
// prima sulle validazioni che sul risultato.

/** L'errore di un tool: porta il messaggio del server, non un codice HTTP. */
export class PcbApiError extends Error {}

async function leggiRisposta(res) {
  let dati = null;
  try {
    dati = await res.json();
  } catch {
    // Corpo non JSON: resta il codice HTTP, che e' comunque un'informazione.
  }
  if (!res.ok || !dati || dati.success === false) {
    const messaggio = (dati && (dati.error || dati.detail)) || `HTTP ${res.status}`;
    throw new PcbApiError(String(messaggio));
  }
  return dati;
}

/**
 * POST su una rotta del modulo. `project` e' la scheda su cui lavorare: la rotta
 * la apre prima di eseguire il tool, cosi' l'editor non tiene uno stato di
 * sessione con il server.
 */
export async function postTool(percorso, corpo = {}) {
  const res = await fetch(percorso, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(corpo),
  });
  return leggiRisposta(res);
}

export async function getJson(percorso) {
  return leggiRisposta(await fetch(percorso));
}

/** I progetti KiCad del workspace, dal piu' recente. */
export async function elencaProgetti() {
  const dati = await getJson('/api/kicad/projects');
  return Array.isArray(dati.projects) ? dati.projects : [];
}

/** La scheda intera, nella forma che disegna la canvas. */
export async function leggiScheda(pcbPath) {
  const dati = await getJson(
    `/api/kicad/board?pcb_path=${encodeURIComponent(pcbPath)}`,
  );
  return dati.board || null;
}
