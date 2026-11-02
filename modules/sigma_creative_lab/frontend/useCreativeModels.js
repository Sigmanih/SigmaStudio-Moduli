import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Registro modelli + inventario reale del backend locale.
 *
 * Il registro dice *cosa esiste concettualmente* (FLUX, Qwen-Image, SDXL...),
 * la discovery dice *cosa è davvero installato* su questo ComfyUI. La UI ha
 * bisogno di entrambi: senza il primo non sa cosa proporre, senza il secondo
 * propone modelli che poi non partono.
 */
export function useCreativeModels() {
  const [models, setModels] = useState([]);
  const [inventory, setInventory] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [warning, setWarning] = useState('');
  const [meta, setMeta] = useState(null);
  const pending = useRef(null);

  const refresh = useCallback(() => {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setLoading(true);
    setError('');
    setWarning('');
    const timer = setTimeout(() => controller.abort(), 20000);
    const read = async url => {
      const response = await fetch(url, { signal: controller.signal });
      if (!response.ok) throw new Error(`Il servizio modelli non risponde (HTTP ${response.status}).`);
      const data = await response.json();
      if (!data.success) throw new Error(data.error || 'Impossibile leggere i modelli.');
      return data;
    };
    return Promise.allSettled([read('/api/creative/models'), read('/api/creative/backends/discover')]).then(([reg, disc]) => {
      if (pending.current !== controller) return;
      if (reg.status === 'fulfilled') {
        setModels(Array.isArray(reg.value.models) ? reg.value.models : []);
        setMeta(reg.value);
      } else setError(controller.signal.aborted ? 'La lettura dei modelli sta impiegando troppo tempo. Premi Aggiorna per riprovare.' : reg.reason.message);
      if (disc.status === 'fulfilled') setInventory(disc.value.comfyui || null);
      else { setInventory(null); setWarning('Non riesco a leggere i file locali. Puoi riprovare con Aggiorna.'); }
      setLoading(false);
    }).finally(() => clearTimeout(timer));
  }, []);

  useEffect(() => { refresh(); return () => { const current = pending.current; pending.current = null; current?.abort(); }; }, [refresh]);

  const modelsFor = useCallback(
    (task) => models.filter(m => m.tasks?.includes(task)),
    [models],
  );

  return { models, modelsFor, inventory, loading, error, warning, meta, refresh };
}
