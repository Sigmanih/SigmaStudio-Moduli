export async function readCreativeResponse(response, onEvent = () => {}) {
  const type = response.headers.get('content-type') || '';
  if (type.includes('application/json')) {
    const data = await response.json();
    if (!response.ok || data.success === false) throw new Error(data.error || `Operazione non riuscita (HTTP ${response.status})`);
    onEvent(data);
    return data;
  }
  if (!response.ok || !type.includes('text/event-stream') || !response.body) throw new Error(`Il servizio Creative non risponde correttamente (HTTP ${response.status}).`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '', result = null, failure = '';
  const consume = frame => {
    const payload = frame.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
    if (!payload || payload === '[DONE]') return;
    let event;
    try { event = JSON.parse(payload); } catch { throw new Error('La risposta Creative è incompleta o non valida. Aggiorna la libreria per controllare gli esiti.'); }
    if (!event || typeof event !== 'object' || Array.isArray(event)) throw new Error('Il servizio Creative ha restituito un evento non valido.');
    onEvent(event);
    if (event.error || event.success === false) failure = event.error || 'Operazione Creative fallita';
    if (event.asset || event.results) result = event;
  };
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
        consume(buffer.slice(0, boundary.index));
        buffer = buffer.slice(boundary.index + boundary[0].length);
      }
      if (buffer.length > 4 * 1024 * 1024) throw new Error('La risposta Creative supera la dimensione consentita.');
    }
    buffer += decoder.decode();
    if (buffer.trim()) consume(buffer);
    if (failure) throw new Error(failure);
    if (!result) throw new Error('Operazione terminata senza un risultato verificabile. Aggiorna la libreria prima di riprovare.');
    return result;
  } finally { reader.releaseLock(); }
}
