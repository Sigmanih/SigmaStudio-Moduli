"""Compensazione lineare del pruning, senza intercetta ne' aggiornamenti del teacher."""

from time import monotonic

from core.logger import get_logger

log = get_logger(__name__)


def fit_reconstruction(cases, removed, anchors, column_energy, *, validation_indices,
                       ridge_values=(.001, .01, .1, 1.), seconds=180):
    """Predice i canali rimossi dai conservati; la validazione sceglie solo la ridge."""
    import numpy as np

    removed, anchors = np.asarray(removed), np.asarray(anchors)
    energy = np.asarray(column_energy, dtype=np.float64)
    if (not 2 <= len(cases) <= 16 or removed.ndim != 2 or anchors.ndim != 2
            or not 1 <= len(removed) == len(anchors) <= 64
            or not 1 <= removed.shape[1] <= 512 or not 1 <= anchors.shape[1] <= 1024
            or removed.dtype.kind not in 'iu' or anchors.dtype.kind not in 'iu'
            or energy.ndim != 2 or energy.shape[0] != len(removed)
            or not 128 <= energy.shape[1] <= 65536 or not np.isfinite(energy).all()
            or np.any(energy < 0) or not 0 < seconds <= 600):
        raise ValueError('Geometria o budget della ricostruzione non validi')
    validation = set(validation_indices)
    if (not validation or len(validation) >= len(cases)
            or any(type(i) is not int or not 0 <= i < len(cases) for i in validation)):
        raise ValueError('Validazione non separata')
    if (not 1 <= len(ridge_values) <= 8
            or any(not np.isfinite(v) or not 1e-5 <= v <= 10 for v in ridge_values)):
        raise ValueError('Regolarizzazione non valida')
    width = energy.shape[1]
    for rows in (removed, anchors):
        if np.any(rows < 0) or np.any(rows >= width) or any(len(set(r)) != len(r) for r in rows):
            raise ValueError('Indici dei canali non validi')
    if any(set(r) & set(a) for r, a in zip(removed, anchors)):
        raise ValueError('I canali conservati includono canali rimossi')
    if any(len(c['tensors']) != len(removed) for c in cases):
        raise ValueError('Cattura dei layer incompleta')
    deadline = monotonic()+seconds
    matrices, metrics = [], []
    for layer, (drop, keep) in enumerate(zip(removed, anchors)):
        features, weights, masks = [], [], []
        expected = np.sort(np.concatenate([drop, keep]))
        for i, case in enumerate(cases):
            item = case['tensors'][f'blk.{layer}.ffn_down.weight']
            values = np.asarray(item['features'])
            if (item['width'] != width or not np.array_equal(item['channels'], expected)
                    or values.shape != (item['tokens'], len(expected))
                    or not 1 <= len(values) <= 512 or not np.isfinite(values).all()):
                raise ValueError('Campioni incompatibili con i canali richiesti')
            w = np.ones(len(values)); w[0] *= 4; w[-1] *= 4; w /= w.sum()
            features.append(values); weights.extend(w); masks.extend([i in validation]*len(values))
        n = sum(len(v) for v in features)
        if n*len(expected) > 16_000_000:
            raise ValueError('Ricostruzione oltre il budget di memoria')
        values = np.concatenate(features).astype(np.float64)
        weights, mask = np.asarray(weights), np.asarray(masks)
        w_train = weights[~mask]; w_train /= w_train.sum()
        w_val = weights[mask]; w_val /= w_val.sum()
        x = values[:, np.searchsorted(expected, keep)]
        y = values[:, np.searchsorted(expected, drop)]
        scale = np.sqrt(np.sum(x[~mask]**2*w_train[:, None], axis=0))
        scale = np.maximum(scale, max(float(scale.max()), 1e-12)*1e-6)
        x_scaled = x/scale
        gram = x_scaled[~mask].T @ (x_scaled[~mask]*w_train[:, None])
        cross = x_scaled[~mask].T @ (y[~mask]*w_train[:, None])
        importance = energy[layer, drop]
        denominator = float(np.sum(y[mask]**2*w_val[:, None]*importance))
        best_ratio, best_ridge = 1.0 if denominator else 0.0, None
        best = np.zeros((len(drop), len(keep)), dtype=np.float32)
        trials = []
        for ridge in ridge_values:
            if monotonic() > deadline:
                raise TimeoutError('Tempo di ricostruzione esaurito')
            coefficients = (np.linalg.solve(gram+ridge*np.eye(len(keep)), cross).T/scale).astype(np.float32)
            if not np.isfinite(coefficients).all():
                raise FloatingPointError('Coefficienti di ricostruzione non finiti')
            error = y[mask]-x[mask] @ coefficients.T
            numerator = float(np.sum(error**2*w_val[:, None]*importance))
            ratio = numerator/denominator if denominator else (0.0 if not numerator else float('inf'))
            trials.append({'ridge': ridge, 'validation_diagonal_error_ratio': ratio})
            if ratio < best_ratio:
                best_ratio, best_ridge, best = ratio, ridge, coefficients
        matrices.append(best)
        metrics.append({'layer': layer, 'ridge': best_ridge,
                        'validation_diagonal_error_ratio': best_ratio, 'trials': trials})
    log.info('Ricostruzione stimata per %s layer, senza gradienti dalla validazione', len(matrices))
    return {'coefficients': np.stack(matrices), 'metrics': metrics,
            'scope': 'Original-model input replay; validation of weighted removed-activation residual only, not task accuracy or exact output error'}
