"""Controlli per confrontare una quantizzazione diretta con un checkpoint esistente."""

from pathlib import Path
import re


def conversion_plan(reference: Path, floating: Path) -> dict:
    """Fissa tipi e template; rifiuta variazioni di geometria, vocabolario e norme."""
    import numpy as np
    from gguf import GGUFReader, GGMLQuantizationType

    readers = []
    try:
        for path in (reference, floating):
            path = Path(path)
            if not path.is_file() or not 32 <= path.stat().st_size <= 128*2**30:
                raise ValueError('Dimensione GGUF fuori budget')
            readers.append(GGUFReader(str(path), mode='r'))
        old, new = readers
        a, b = ({t.name: t for t in r.tensors} for r in readers)
        if not 1 <= len(a) == len(b) <= 4096 or a.keys() != b.keys():
            raise ValueError('Insieme dei tensori diverso dalla baseline')
        def value(reader, key):
            return reader.fields[key].contents() if key in reader.fields else None

        architecture = value(old, 'general.architecture')
        if architecture != value(new, 'general.architecture'):
            raise ValueError('Architettura diversa dalla baseline')
        differences = []
        normalized = []
        for key in set(old.fields) | set(new.fields):
            if key.startswith(str(architecture)+'.') or (key.startswith('tokenizer.') and not key.startswith('tokenizer.chat_template')):
                if not np.array_equal(value(old, key), value(new, key)):
                    if key == str(architecture)+'.nextn_predict_layers' and value(old, key) == 0 and value(new, key) is None:
                        # La geometria e i nomi dei tensori sono gia' uguali: ripristiniamo lo zero esplicito.
                        normalized.append(key+'=int:0')
                    else:
                        differences.append(key)
        if differences:
            raise ValueError('Parametri o tokenizer differenti: '+', '.join(sorted(differences)[:12]))
        types, norm_checks = {}, []
        for name, tensor in a.items():
            source = b[name]
            if not np.array_equal(tensor.shape, source.shape):
                raise ValueError('Forma differente: '+name)
            if source.tensor_type not in (GGMLQuantizationType.F32, GGMLQuantizationType.F16, GGMLQuantizationType.BF16):
                raise ValueError('La sorgente contiene tensori gia quantizzati: '+name)
            types[name] = tensor.tensor_type.name.lower()
            if tensor.tensor_type == GGMLQuantizationType.F32:
                if tensor.n_elements > 4_000_000 or source.tensor_type != GGMLQuantizationType.F32:
                    raise ValueError('Tensore F32 non confrontabile: '+name)
                x, y = tensor.data.reshape(-1), source.data.reshape(-1)
                if not np.isfinite(y).all() or not np.allclose(x, y, atol=1e-6, rtol=1e-6):
                    raise ValueError('Pesi F32 trasformati diversamente: '+name)
                norm_checks.append(name)
        overrides = ['general.name=str:sigma', 'general.basename=str:sigma']+normalized
        templates = []
        for key in old.fields:
            if key.startswith('tokenizer.chat_template') and isinstance(value(old, key), str):
                if value(old, key) != value(new, key):
                    overrides.append(key+'=str:'+value(old, key))
                    templates.append(key)
        return {'public_name': 'sigma', 'tensors': len(a), 'tensor_types': types,
                'metadata_overrides': overrides, 'preserved_template_keys': templates,
                'f32_tensors_checked': len(norm_checks),
                'normalized_metadata_keys': [entry.split('=', 1)[0] for entry in normalized],
                'scope': 'Same tensor shapes, model parameters, tokenizer and F32 weights within1e-6; same per-tensor quantization types and reference templates. Calibration must be held fixed separately.'}
    finally:
        for reader in readers:
            reader.data._mmap.close()


def write_tensor_types(path: Path, plan: dict) -> None:
    """Le espressioni esatte evitano sostituzioni involontarie fra nomi simili."""
    entries = plan['tensor_types']
    if not 1 <= len(entries) <= 4096:
        raise ValueError('Piano dei tipi fuori budget')
    lines = []
    for name, dtype in entries.items():
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', name) or not re.fullmatch(r'[a-z0-9_]+', dtype):
            raise ValueError('Nome o tipo del tensore non valido')
        lines.append('^'+re.escape(name)+'$='+dtype+'\n')
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.writelines(lines)


def validate_candidate(reference: Path, candidate: Path) -> dict:
    """Controlla il file finale prima di renderlo selezionabile per i benchmark."""
    import numpy as np
    from gguf import GGUFReader

    readers = []
    try:
        for path in (reference, candidate):
            readers.append(GGUFReader(str(path), mode='r'))
        a, b = ({t.name: t for t in r.tensors} for r in readers)
        if a.keys() != b.keys() or any(not np.array_equal(t.shape, b[n].shape) or t.tensor_type != b[n].tensor_type for n, t in a.items()):
            raise ValueError('La quantizzazione finale non rispetta forme e tipi della baseline')
        fields = readers[1].fields
        if fields['general.name'].contents() != 'sigma' or fields['general.basename'].contents() != 'sigma':
            raise ValueError('Nome pubblico del candidato non valido')
        architecture = readers[0].fields['general.architecture'].contents()
        for key in set(readers[0].fields) | set(fields):
            if key.startswith(str(architecture)+'.') or key.startswith('tokenizer.'):
                x = readers[0].fields[key].contents() if key in readers[0].fields else None
                y = fields[key].contents() if key in fields else None
                if not np.array_equal(x, y):
                    raise ValueError('Metadati finali differenti: '+key)
        return {'public_name': 'sigma', 'tensors': len(a), 'bytes': Path(candidate).stat().st_size,
                'scope': 'Structural validation only; correctness and resource checks still required'}
    finally:
        for reader in readers:
            reader.data._mmap.close()
