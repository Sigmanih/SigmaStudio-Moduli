"""Sostituzione reversibile dell'audio MP4 senza copiare master video molto grandi."""
from __future__ import annotations

import hashlib
import os
import struct
import time
import uuid
from pathlib import Path

from .mp4_timing import _boxes, _header


def _box(kind, payload):
    size = len(payload) + 8
    if size >= 2**32:
        raise ValueError('Indice MP4 troppo grande')
    return struct.pack('>I4s', size, kind) + payload


def _read(path):
    tops = []
    moov = None
    with Path(path).open('rb') as stream:
        length = Path(path).stat().st_size
        position = 0
        while position + 8 <= length:
            stream.seek(position)
            size, kind = struct.unpack('>I4s', stream.read(8))
            header = 8
            if size == 1:
                size = struct.unpack('>Q', stream.read(8))[0]
                header = 16
            if not size:
                raise ValueError('Atomo esteso fino a EOF: serve un remux tradizionale')
            if size < header or position + size > length:
                raise ValueError('Struttura MP4 incompleta')
            if kind in (b'moof', b'mfra'):
                raise ValueError('MP4 frammentato non supportato')
            tops.append((kind, position, header, size))
            if kind == b'moov':
                if moov is not None or size > 128 * 1024 * 1024 or header != 8:
                    raise ValueError('Indice MP4 non supportato o oltre il budget')
                stream.seek(position)
                moov = stream.read(size)
            position += size
        if position != length or moov is None:
            raise ValueError('Indice o coda MP4 non validi')
    return tops, moov


def _parts(data, start=8, end=None):
    return {kind: (body, stop) for kind, body, stop in _boxes(data, start, len(data) if end is None else end)}


def _track_kind(raw):
    parts = _parts(raw)
    mdia = _parts(raw, *parts[b'mdia'])
    off = mdia[b'hdlr'][0] + 8
    return bytes(raw[off:off + 4])


def _track_id(raw):
    body = _parts(raw)[b'tkhd'][0]
    return struct.unpack_from('>I', raw, body + (20 if raw[body] else 12))[0]


def _convert(raw, mappings, track_id, source_scale, movie_scale):
    kind = raw[4:8]
    body = bytearray(raw[8:])
    if kind in (b'stco', b'co64'):
        count = struct.unpack_from('>I', body, 4)[0]
        width = 8 if kind == b'co64' else 4
        if count > 3_000_000 or 8 + count * width != len(body):
            raise ValueError('Tabella dei chunk audio non valida')
        offsets = []
        for i in range(count):
            old = struct.unpack_from('>Q' if width == 8 else '>I', body, 8 + width * i)[0]
            mapped = next((target + old - start for start, end, target in mappings if start <= old < end), None)
            if mapped is None:
                raise ValueError('Un chunk audio punta fuori dai dati sorgente')
            offsets.append(struct.pack('>Q', mapped))
        return _box(b'co64', bytes(body[:8]) + b''.join(offsets))
    if kind == b'tkhd':
        version = body[0]
        struct.pack_into('>I', body, 20 if version else 12, track_id)
        pos, fmt = (28, '>Q') if version else (20, '>I')
        duration = struct.unpack_from(fmt, body, pos)[0]
        struct.pack_into(fmt, body, pos, (duration * movie_scale + source_scale // 2) // source_scale)
    elif kind == b'elst':
        version = body[0]
        count = struct.unpack_from('>I', body, 4)[0]
        if count > 1024:
            raise ValueError('Troppe edit list audio')
        for i in range(count):
            pos = 8 + i * (20 if version else 12)
            fmt = '>Q' if version else '>I'
            duration = struct.unpack_from(fmt, body, pos)[0]
            struct.pack_into(fmt, body, pos, (duration * movie_scale + source_scale // 2) // source_scale)
    elif kind in (b'trak', b'mdia', b'minf', b'stbl', b'edts'):
        body = b''.join(_convert(bytes(raw[a - 8:b]), mappings, track_id, source_scale, movie_scale)
                        for _, a, b in _boxes(raw, 8, len(raw)))
    return _box(kind, bytes(body))


def replace_audio_inplace(video: Path, audio: Path, backup_dir: Path) -> dict:
    """Appende i soli dati audio e cambia l'indice; gli offset e i byte video restano identici."""
    video, audio = Path(video).resolve(), Path(audio).resolve()
    if video == audio:
        raise ValueError('Video e audio devono essere file diversi')
    old_tops, old_moov = _read(video)
    audio_tops, audio_moov = _read(audio)
    old_children = [(k, bytes(old_moov[a - 8:b])) for k, a, b in _boxes(old_moov, 8, len(old_moov))]
    source_children = [(k, bytes(audio_moov[a - 8:b])) for k, a, b in _boxes(audio_moov, 8, len(audio_moov))]
    old_audio = [raw for k, raw in old_children if k == b'trak' and _track_kind(raw) == b'soun']
    new_audio = [raw for k, raw in source_children if k == b'trak' and _track_kind(raw) == b'soun']
    if len(old_audio) != 1 or len(new_audio) != 1:
        raise ValueError('È richiesta una sola traccia audio per ciascun file')
    old_parts, new_parts = _parts(old_moov), _parts(audio_moov)
    movie_scale = _header(old_moov, old_parts[b'mvhd'][0])[0]
    source_scale = _header(audio_moov, new_parts[b'mvhd'][0])[0]
    original_size = video.stat().st_size
    position = original_size
    mappings, copies = [], []
    for kind, offset, header, size in audio_tops:
        if kind != b'mdat':
            continue
        payload = size - header
        if payload > 4 * 1024**3 - 8:
            raise ValueError('Audio oltre il budget per la sostituzione rapida')
        mappings.append((offset + header, offset + size, position + 8))
        copies.append((offset + header, payload))
        position += payload + 8
    if not copies:
        raise ValueError('Dati audio assenti')
    replacement = _convert(new_audio[0], mappings, _track_id(old_audio[0]), source_scale, movie_scale)
    children = [replacement if k == b'trak' and _track_kind(raw) == b'soun' else raw for k, raw in old_children]
    new_moov = _box(b'moov', b''.join(children))
    padding = len(old_moov) - len(new_moov)
    if padding < 0 or 0 < padding < 8:
        raise ValueError('Spazio nell’indice insufficiente: serve un remux tradizionale')
    region = new_moov + (_box(b'free', bytes(padding - 8)) if padding else b'')
    moov_offset = next(offset for kind, offset, _, _ in old_tops if kind == b'moov')
    video_tracks = [raw for k, raw in old_children if k == b'trak' and _track_kind(raw) == b'vide']
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f'moov_prima_audio_{uuid.uuid4().hex[:10]}.bin'
    with backup.open('xb') as stream:
        stream.write(old_moov)
        stream.flush()
        os.fsync(stream.fileno())
    deadline = time.monotonic() + 180
    with video.open('r+b') as target, audio.open('rb') as source:
        try:
            if video.stat().st_size != original_size:
                raise ValueError('Il video è cambiato durante la preparazione')
            target.seek(original_size)
            for offset, size in copies:
                target.write(struct.pack('>I4s', size + 8, b'mdat'))
                source.seek(offset)
                remaining = size
                while remaining:
                    if time.monotonic() > deadline:
                        raise TimeoutError('Tempo esaurito durante l’aggiunta dell’audio')
                    block = source.read(min(4 * 1024 * 1024, remaining))
                    if not block:
                        raise ValueError('Dati audio incompleti')
                    target.write(block)
                    remaining -= len(block)
            target.flush()
            os.fsync(target.fileno())
            target.seek(moov_offset)
            target.write(region)
            target.flush()
            os.fsync(target.fileno())
        except Exception:
            # Il rollback rimuove soltanto l'appendice appena creata e ripristina l'indice originale.
            target.seek(moov_offset)
            target.write(old_moov)
            target.truncate(original_size)
            target.flush()
            os.fsync(target.fileno())
            raise
    _, actual = _read(video)
    after_video = [bytes(actual[a - 8:b]) for k, a, b in _boxes(actual, 8, len(actual))
                   if k == b'trak' and _track_kind(bytes(actual[a - 8:b])) == b'vide']
    if after_video != video_tracks:
        raise ValueError('Indice video modificato durante il riaggancio audio')
    return {'backup_moov': str(backup.resolve()), 'moov_offset': moov_offset, 'old_moov_bytes': len(old_moov),
            'original_size': original_size, 'new_size': video.stat().st_size,
            'video_track_sha256': [hashlib.sha256(raw).hexdigest() for raw in video_tracks],
            'video_track_unchanged': True, 'new_audio_file': str(audio)}
