import { useCallback, useEffect, useRef, useState } from 'react';
import { readCreativeResponse } from './creativeResponse';

/**
 * Client per le API creative.
 *
 * Gli endpoint pesanti rispondono in SSE (`text/event-stream`) e gli altri in
 * JSON: `runTask` gestisce entrambi i casi con lo stesso contratto, così i
 * pannelli non devono sapere quale forma userà il server.
 */
export function useCreativeApi() {
  const [busy, setBusy] = useState(null);   // { label, progress, message }
  const [error, setError] = useState(null);
  const active = useRef(null);
  useEffect(() => () => active.current?.abort(), []);

  const runTask = useCallback(async (url, body, { label = 'Elaborazione', onEvent } = {}) => {
    if (active.current) throw new Error('Attendi il termine dell’operazione in corso.');
    const controller = new AbortController();
    active.current = controller;
    setBusy({ label, message: 'Avvio…' });
    setError(null);
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream, application/json' },
        signal: controller.signal,
        body: JSON.stringify(body),
      });
      return await readCreativeResponse(response, event => {
        onEvent?.(event);
        if (event.progress !== undefined || event.message) setBusy(previous => ({
          ...(previous || { label }), progress: event.progress ?? previous?.progress,
          message: event.message || previous?.message,
        }));
      });
    } catch (err) {
      if (err.name !== 'AbortError') setError(err.message);
      throw err;
    } finally {
      active.current = null;
      setBusy(null);
    }
  }, []);

  return { runTask, busy, error, clearError: () => setError(null) };
}
