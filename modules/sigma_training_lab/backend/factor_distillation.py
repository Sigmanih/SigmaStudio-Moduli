"""Distillazione locale del decoder a basso rango, con classificatore congelato."""

from pathlib import Path
from time import monotonic
import math

from core.logger import get_logger

log = get_logger(__name__)


def load_frozen_head(path: Path, *, device="cpu", max_working_mib=512, seconds=180):
    """Dequantizza a blocchi: non materializza una seconda copia completa in RAM."""
    import numpy as np
    import torch
    from gguf import GGUFReader
    from gguf.quants import dequantize

    if not 16 <= max_working_mib <= 16384 or not 0 < seconds <= 300:
        raise ValueError("Budget del classificatore non valido")
    dev = torch.device(device)
    if dev.type not in ("cpu", "cuda") or (dev.type == "cuda" and not torch.cuda.is_available()):
        raise ValueError("Dispositivo non disponibile")
    reader = GGUFReader(str(path), mode="r")
    deadline = monotonic()+seconds
    try:
        tensors = {t.name: t for t in reader.tensors}
        if any(k.startswith("output.") and k != "output.weight" for k in tensors) or "output_norm.bias" in tensors:
            raise ValueError("Classificatore con scale o bias aggiuntivi non supportato")
        source = tensors["output.weight"]
        width, vocabulary = map(int, source.shape)
        needed = width*vocabulary*4+64*2**20
        if not 128 <= width <= 8192 or not 2 <= vocabulary <= 300000 or needed > max_working_mib*2**20:
            raise ValueError("Classificatore oltre il budget di memoria")
        if dev.type == "cuda" and needed+512*2**20 > torch.cuda.mem_get_info(dev)[0]:
            raise MemoryError("Memoria libera insufficiente per il classificatore congelato")
        architecture = reader.fields["general.architecture"]
        architecture = bytes(architecture.parts[architecture.data[0]]).decode("utf-8")
        field = reader.fields[architecture+".attention.layer_norm_rms_epsilon"]
        eps = float(field.parts[field.data[0]].flat[0])
        if not 0 < eps < 1:
            raise ValueError("Epsilon RMSNorm non valido")
        gamma_np = dequantize(tensors["output_norm.weight"].data,
                              tensors["output_norm.weight"].tensor_type).reshape(-1).copy()
        if gamma_np.shape != (width,) or not np.isfinite(gamma_np).all():
            raise ValueError("Pesi di normalizzazione non validi")
        head = torch.empty((vocabulary, width), dtype=torch.float32, device=dev)
        for start in range(0, vocabulary, 256):
            if monotonic() > deadline:
                raise TimeoutError("Tempo di caricamento del classificatore esaurito")
            stop = min(vocabulary, start+256)
            block = dequantize(source.data[start:stop], source.tensor_type).reshape(stop-start, width)
            if not np.isfinite(block).all():
                raise ValueError("Classificatore non finito")
            head[start:stop].copy_(torch.from_numpy(block.copy()))
        gamma = torch.from_numpy(gamma_np).to(device=dev, dtype=torch.float32)
        return head, gamma, eps
    finally:
        mapping = getattr(reader.data, "_mmap", None)
        if mapping is not None:
            mapping.close()


def distill_decoder(cases, encoder, head, gamma, eps, *, validation_indices,
                    steps=240, learning_rate=1e-4, batch_size=16, validate_every=20,
                    reconstruction_weight=.001, seed=42, seconds=600,
                    max_working_mib=8192, progress=None, protected_directions=None, reference_weight=0.0,
                    protect_training_ends=False, max_terminal_nll_increase=None):
    """Aggiorna D; i vincoli terminali preservano la mappa iniziale su stati fissi.

    La selezione usa solo la validazione. Il vincolo non garantisce l'arresto
    delle generazioni libere, che possono raggiungere contesti diversi.
    """
    import numpy as np
    import torch
    import torch.nn.functional as F

    if (not 2 <= len(cases) <= 16 or not 1 <= steps <= 1000 or not 1 <= batch_size <= 64
            or not 1 <= validate_every <= 100 or not 0 < learning_rate <= .01
            or not 0 <= reconstruction_weight <= 1 or not 0 < seconds <= 1200
            or not 16 <= max_working_mib <= 16384 or not 0 <= reference_weight <= 4):
        raise ValueError("Budget di distillazione non valido")
    if (type(protect_training_ends) is not bool
            or (max_terminal_nll_increase is not None
                and (type(max_terminal_nll_increase) not in (int, float)
                     or not math.isfinite(max_terminal_nll_increase)
                     or not 0 <= max_terminal_nll_increase <= 1))):
        raise ValueError("Vincoli di terminazione non validi")
    if (head.ndim != 2 or gamma.shape != (head.shape[1],) or head.dtype != torch.float32
            or gamma.dtype != torch.float32 or gamma.device != head.device or not 0 < eps < 1):
        raise ValueError("Classificatore o normalizzazione non validi")
    validation = set(validation_indices)
    if (not validation or len(validation) >= len(cases)
            or any(type(i) is not int or not 0 <= i < len(cases) for i in validation)):
        raise ValueError("Separazione delle validazioni non valida")
    width, vocabulary = head.shape[1], head.shape[0]
    encoder = np.asarray(encoder, dtype=np.float32)
    if (encoder.ndim != 2 or encoder.shape[1] != width or not 1 <= len(encoder) <= min(512, width)
            or not np.isfinite(encoder).all()):
        raise ValueError("Encoder non valido")
    items, masks, weights, choices, probabilities, references = [], [], [], [], [], []
    labeled_cases = set()
    for i, case in enumerate(cases):
        if len(case["tensors"]) != 1:
            raise ValueError("Occorre una sola uscita FFN per caso")
        item = next(iter(case["tensors"].values()))
        y, h = item["features"], case["hidden"]
        if y.shape != h.shape or y.shape[1] != width or not 1 <= len(y) <= 512:
            raise ValueError("Stati incompatibili")
        if not np.isfinite(y).all() or not np.isfinite(h).all():
            raise ValueError("Stati non finiti")
        w = np.ones(len(y), dtype=np.float32)
        w[0] *= 4; w[-1] *= 4
        w /= w.sum()
        weights.extend(w.tolist());masks.extend([i in validation]*len(y));items.append((y, h))
        choices.append(np.stack([case["decisions"]["first"], case["decisions"]["second"]], axis=1))
        probabilities.append(case["native_top_probabilities"])
        if "reference_tokens" in case:
            tokens = np.asarray(case["reference_tokens"])
            if (case.get("reference_verified") is not True or tokens.shape != (len(y),)
                    or tokens.dtype.kind not in "iu" or np.any(tokens < 0) or np.any(tokens >= vocabulary)):
                raise ValueError("Riferimenti correttivi non verificati o non validi")
            references.extend(tokens.tolist());labeled_cases.add(i)
        else:
            references.extend([-100]*len(y))
    if reference_weight and not (labeled_cases-validation):
        raise ValueError("Mancano riferimenti verificati per i gradienti correttivi")
    if validation&labeled_cases and not validation <= labeled_cases:
        raise ValueError("La validazione deve avere riferimenti omogenei")
    select_reference = validation <= labeled_cases
    if max_terminal_nll_increase is not None and not select_reference:
        raise ValueError("Il vincolo di validazione richiede riferimenti verificati")
    n = sum(len(x[0]) for x in items)
    needed = head.numel()*4+n*vocabulary*2+n*width*16+batch_size*vocabulary*32+encoder.size*24
    if n*width > 16_000_000 or n*vocabulary > 512_000_000 or needed > max_working_mib*2**20:
        raise ValueError("Distillazione oltre il budget di memoria")
    if head.is_cuda and needed-head.numel()*4+256*2**20 > torch.cuda.mem_get_info(head.device)[0]:
        raise MemoryError("Memoria libera insufficiente per i riferimenti della distillazione")
    if head.requires_grad or gamma.requires_grad:
        raise ValueError("Il classificatore deve restare congelato")
    if head.is_cuda:
        precision = getattr(torch.backends.cuda.matmul, "fp32_precision", None)
        if (precision is not None and precision != "ieee") or (precision is None and torch.backends.cuda.matmul.allow_tf32):
            raise ValueError("La distillazione richiede matmul float32 IEEE")
    dev = head.device
    y = torch.from_numpy(np.concatenate([x[0] for x in items])).to(dev)
    h = torch.from_numpy(np.concatenate([x[1] for x in items])).to(dev)
    e = torch.from_numpy(encoder.copy()).to(dev)
    protected = None
    if protected_directions is not None:
        directions = np.asarray(protected_directions, dtype=np.float64)
        if (directions.ndim != 2 or directions.shape[1] != width or not 1 <= len(directions) <= 128
                or not np.isfinite(directions).all()):
            raise ValueError("Vincoli del decoder non validi")
        _, singular, vt = np.linalg.svd(directions, full_matrices=False)
        tolerance = singular[0]*max(directions.shape)*np.finfo(np.float64).eps
        protected_rank = int(np.sum(singular > tolerance))
        if not protected_rank:
            raise ValueError("Vincoli del decoder nulli")
        protected = torch.from_numpy(vt[:protected_rank].astype(np.float32)).to(dev)
    latent = y @ e.T
    terminal_offsets = np.cumsum([len(item[0]) for item in items])-1
    training_ends = torch.tensor([int(terminal_offsets[i]) for i in range(len(cases))
                                  if i not in validation], dtype=torch.long, device=dev)
    validation_ends = torch.tensor([int(terminal_offsets[i]) for i in sorted(validation)],
                                    dtype=torch.long, device=dev)
    protected_inputs = None
    if protect_training_ends:
        # Il vincolo usa solo stati di addestramento: nessun gradiente dalla validazione.
        _, singular_inputs, vt_inputs = torch.linalg.svd(latent[training_ends], full_matrices=False)
        tolerance_inputs = singular_inputs[0]*max(len(training_ends), len(encoder))*torch.finfo(latent.dtype).eps
        input_rank = int((singular_inputs > tolerance_inputs).sum())
        if input_rank >= len(encoder):
            raise ValueError("I vincoli terminali esauriscono il rango del decoder")
        if input_rank:
            protected_inputs = vt_inputs[:input_rank]
    residual = h-y
    reference_ids = torch.tensor(references, dtype=torch.long, device=dev)
    decoder = torch.nn.Parameter(e.clone())
    target = torch.empty((n, vocabulary), dtype=torch.float16, device=dev)
    deadline = monotonic()+seconds

    def logits(hidden):
        normalized = hidden*torch.rsqrt(hidden.square().mean(dim=1, keepdim=True)+eps)
        return (normalized*gamma) @ head.T

    def check_time():
        if monotonic() > deadline:
            raise TimeoutError("Tempo di distillazione esaurito")

    agreement, coarse_kl = 0, 0.0
    ids = torch.from_numpy(np.concatenate(choices).astype(np.int64)).to(dev)
    native = torch.from_numpy(np.concatenate(probabilities).astype(np.float32)).to(dev)
    if (ids.shape != (n, 2) or native.shape != (n, 2) or torch.any(ids < 0) or torch.any(ids >= vocabulary)
            or not torch.isfinite(native).all() or torch.any(native < 0) or torch.any(native.sum(dim=1) > 1+1e-6)):
        raise ValueError("Riferimenti nativi non validi")
    with torch.no_grad():
        for start in range(0, n, batch_size):
            check_time();stop=min(n, start+batch_size)
            p = F.softmax(logits(h[start:stop]), dim=1)
            target[start:stop].copy_(p)
            agreement += int((p.argmax(dim=1)==ids[start:stop, 0]).sum())
            q = p.gather(1, ids[start:stop])
            q = torch.cat([q, (1-q.sum(dim=1, keepdim=True)).clamp_min(1e-12)], dim=1)
            reference = native[start:stop]
            reference = torch.cat([reference, (1-reference.sum(dim=1, keepdim=True)).clamp_min(0)], dim=1)
            reference = reference/reference.sum(dim=1, keepdim=True)
            coarse_kl += float(F.kl_div(q.clamp_min(1e-12).log(), reference, reduction="sum"))
    fidelity = {"native_argmax_agreement": agreement/n, "native_top2_tail_kl": coarse_kl/n}
    if (not all(math.isfinite(v) for v in fidelity.values())
            or fidelity["native_argmax_agreement"] < .98 or fidelity["native_top2_tail_kl"] > .01):
        raise ValueError(f"Il classificatore offline non riproduce il nativo: {fidelity}")
    mask = torch.tensor(masks, dtype=torch.bool)
    train_ids = torch.nonzero(~mask, as_tuple=True)[0]
    val_ids = torch.nonzero(mask, as_tuple=True)[0]
    all_weights = torch.tensor(weights, dtype=torch.float32)
    train_weights = all_weights[train_ids];train_weights /= train_weights.sum()

    def per_token_loss(indices):
        expected = target[indices].float()
        expected = expected/expected.sum(dim=1, keepdim=True)
        reconstructed = latent[indices] @ decoder
        q = F.log_softmax(logits(residual[indices]+reconstructed), dim=1)
        kl = F.kl_div(q, expected, reduction="none").sum(dim=1)
        mse = (reconstructed-y[indices]).square().mean(dim=1)/y[indices].square().mean(dim=1).clamp_min(1e-8)
        ce = F.nll_loss(q, reference_ids[indices], reduction="none", ignore_index=-100)
        return kl.clamp_min(0), mse, ce

    def evaluate(indices):
        total, normalization, reference_total, reference_normalization = 0.0, 0.0, 0.0, 0.0
        with torch.no_grad():
            for part in indices.split(batch_size):
                check_time();indices=part.to(dev);kl, _, ce = per_token_loss(indices)
                w = all_weights[part].to(dev)
                total += float((kl*w).sum());normalization += float(w.sum())
                labeled = reference_ids[indices] >= 0
                reference_total += float((ce*w*labeled).sum())
                reference_normalization += float((w*labeled).sum())
        return {"kl": total/normalization,
                "reference_nll": reference_total/reference_normalization if reference_normalization else None}

    def terminal_nll():
        if not select_reference:
            return None
        with torch.no_grad():
            check_time()
            _, _, ce = per_token_loss(validation_ends)
            return ce.cpu().tolist()

    initial = evaluate(val_ids)
    initial_terminal = terminal_nll()
    selection = "reference_nll" if select_reference else "kl"
    best_loss, best_step, best = initial[selection], 0, decoder.detach().cpu().clone()
    best_metrics = initial
    best_terminal = initial_terminal
    rejected_terminal = 0
    history = [{"step": 0, "validation_kl": initial["kl"], "validation_reference_nll": initial["reference_nll"]}]
    optimizer = torch.optim.Adam([decoder], lr=learning_rate)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    for step in range(1, steps+1):
        check_time()
        sampled = train_ids[torch.multinomial(train_weights, batch_size, replacement=True, generator=generator)].to(dev)
        optimizer.zero_grad(set_to_none=True)
        kl, mse, ce = per_token_loss(sampled)
        loss = kl.mean()+reconstruction_weight*mse.mean()+reference_weight*ce.mean()
        if not torch.isfinite(loss):
            raise FloatingPointError("Obiettivo di distillazione non finito")
        loss.backward()
        norm = torch.nn.utils.clip_grad_norm_([decoder], 1.0)
        if not torch.isfinite(norm):
            raise FloatingPointError("Gradiente di distillazione non finito")
        optimizer.step()
        if protected is not None or protected_inputs is not None:
            # Adam scala ogni coordinata: il vincolo va ripristinato dopo il passo.
            with torch.no_grad():
                delta = decoder-e
                if protected is not None:
                    delta -= (delta @ protected.T) @ protected
                if protected_inputs is not None:
                    delta -= protected_inputs.T @ (protected_inputs @ delta)
                decoder.copy_(e+delta)
        if step % validate_every == 0 or step == steps:
            validation_metrics = evaluate(val_ids)
            validation_loss = validation_metrics[selection]
            current_terminal = terminal_nll()
            eligible = (max_terminal_nll_increase is None
                        or all(current <= start+max_terminal_nll_increase
                               for current, start in zip(current_terminal, initial_terminal)))
            rejected_terminal += int(not eligible)
            if eligible and validation_loss < best_loss:
                best_loss, best_step, best = validation_loss, step, decoder.detach().cpu().clone()
                best_metrics = validation_metrics
                best_terminal = current_terminal
            item = {"step": step, "training_loss": float(loss.detach()), "validation_kl": validation_metrics["kl"],
                    "validation_reference_nll": validation_metrics["reference_nll"],
                    "validation_terminal_reference_nll": current_terminal, "terminal_guard_passed": eligible}
            history.append(item)
            if progress:
                progress(item)
    log.info("Distillazione decoder completata: passo %s, %s %.6f -> %.6f", best_step, selection, initial[selection], best_loss)
    return {"encoder": encoder.copy(), "decoder": best.numpy(),
            "metrics": {**fidelity, "initial_validation_kl": initial["kl"], "best_validation_kl": best_metrics["kl"],
                        "initial_validation_reference_nll": initial["reference_nll"],
                        "best_validation_reference_nll": best_metrics["reference_nll"],
                        "selection_metric": selection, "reference_weight": reference_weight,
                        "verified_reference_cases": len(labeled_cases),
                        "protected_training_end_rank": len(protected_inputs) if protected_inputs is not None else 0,
                        "max_terminal_nll_increase": max_terminal_nll_increase,
                        "initial_validation_terminal_reference_nll": initial_terminal,
                        "best_validation_terminal_reference_nll": best_terminal,
                        "terminal_guard_rejected_checkpoints": rejected_terminal,
                        "best_step": best_step, "steps": steps, "trainable_parameters": encoder.size,
                        "protected_direction_rank": len(protected) if protected is not None else 0,
                        "effective_free_parameters": (len(encoder)-(len(protected_inputs) if protected_inputs is not None else 0))*(width-(len(protected) if protected is not None else 0)),
                        "training_cases": len(cases)-len(validation), "update_validation_cases": len(validation),
                        "history": history, "scope": "frozen offline head; decoder-only KL and optional verified-token supervision; correctness requires execution"}}
