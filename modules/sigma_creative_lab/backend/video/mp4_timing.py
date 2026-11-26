"""Limita piccoli sforamenti dei frame B modificando solo la temporizzazione MP4."""
from __future__ import annotations

import math
import os
import struct
from pathlib import Path


def _boxes(data, start, end):
    while start + 8 <= end:
        size, kind = struct.unpack_from('>I4s', data, start)
        header = 8
        if size == 1:
            size = struct.unpack_from('>Q', data, start + 8)[0]
            header = 16
        if size == 0:
            size = end - start
        if size < header or start + size > end:
            raise ValueError('Struttura MP4 non valida')
        yield kind, start + header, start + size
        start += size


def _header(data, body):
    version = data[body]
    offset = body + (20 if version else 12)
    scale = struct.unpack_from('>I', data, offset)[0]
    duration = struct.unpack_from('>Q' if version else '>I', data, offset + 4)[0]
    return scale, duration, offset + 4, '>Q' if version else '>I'


def _presentation(entries, offsets):
    i = j = dts = maximum = 0
    consumed = peak_samples = 0
    left = entries[0][0]
    right = offsets[0][0]
    while i < len(entries) and j < len(offsets):
        take = min(left, right)
        dts += take * entries[i][1]
        consumed += take
        if dts + offsets[j][1] > maximum:
            maximum = dts + offsets[j][1]
            peak_samples = consumed
        left -= take
        right -= take
        if not left:
            i += 1
            if i < len(entries):
                left = entries[i][0]
        if not right:
            j += 1
            if j < len(offsets):
                right = offsets[j][0]
    if i != len(entries) or j != len(offsets):
        raise ValueError('Conteggi della temporizzazione MP4 incoerenti')
    return maximum, dts, peak_samples


def cap_duration(path: Path, seconds: float) -> dict:
    """Conserva tutti i frame; recupera meno di mezzo secondo distribuito sui timestamp."""
    path = Path(path)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('Durata MP4 richiesta non valida')
    with path.open('r+b') as stream:
        length = path.stat().st_size
        position = 0
        while position + 8 <= length:
            stream.seek(position)
            size, kind = struct.unpack('>I4s', stream.read(8))
            header = 8
            if size == 1:
                size = struct.unpack('>Q', stream.read(8))[0]
                header = 16
            if size == 0:
                size = length - position
            if size < header or position + size > length:
                raise ValueError('Atomo MP4 non valido')
            if kind == b'moov':
                if size > 128 * 1024 * 1024:
                    raise ValueError('Indice MP4 oltre il budget di lettura')
                stream.seek(position)
                original = stream.read(size)
                break
            position += size
        else:
            raise ValueError('Indice moov assente dal video MP4')
        data = bytearray(original)
        children = list(_boxes(data, header, len(data)))
        mvhd = next(x[1] for x in children if x[0] == b'mvhd')
        movie_scale, _, movie_duration, movie_format = _header(data, mvhd)
        tracks = []
        changes = []
        for kind, start, end in children:
            if kind != b'trak':
                continue
            parts = {k: (a, b) for k, a, b in _boxes(data, start, end)}
            tkhd = parts[b'tkhd'][0]
            track_duration = tkhd + (28 if data[tkhd] else 20)
            track_format = '>Q' if data[tkhd] else '>I'
            tracks.append((track_duration, track_format))
            mdia = {k: (a, b) for k, a, b in _boxes(data, *parts[b'mdia'])}
            if data[mdia[b'hdlr'][0] + 8:mdia[b'hdlr'][0] + 12] != b'vide':
                continue
            scale, _, media_duration, media_format = _header(data, mdia[b'mdhd'][0])
            minf = {k: (a, b) for k, a, b in _boxes(data, *mdia[b'minf'])}
            stbl = {k: (a, b) for k, a, b in _boxes(data, *minf[b'stbl'])}
            stts = stbl[b'stts'][0]
            count = struct.unpack_from('>I', data, stts + 4)[0]
            if count > 2_000_000 or stts + 8 + count * 8 > stbl[b'stts'][1]:
                raise ValueError('Tabella dei tempi oltre il budget o incompleta')
            entries = [list(struct.unpack_from('>II', data, stts + 8 + i * 8)) for i in range(count)]
            samples = sum(x[0] for x in entries)
            if not samples or any(delta < 2 for _, delta in entries):
                raise ValueError('Temporizzazione video non modificabile')
            offsets = [(samples, 0)]
            if b'ctts' in stbl:
                ctts = stbl[b'ctts'][0]
                n = struct.unpack_from('>I', data, ctts + 4)[0]
                fmt = '>Ii' if data[ctts] else '>II'
                offsets = [struct.unpack_from(fmt, data, ctts + 8 + i * 8) for i in range(n)]
            media_start = 0
            edit = None
            if b'edts' in parts:
                edits = {k: (a, b) for k, a, b in _boxes(data, *parts[b'edts'])}
                edit = edits.get(b'elst', (None, None))[0]
                if edit is not None:
                    if struct.unpack_from('>I', data, edit + 4)[0] != 1:
                        raise ValueError('Il limite richiede una sola edit list per traccia video')
                    media_start = struct.unpack_from('>q' if data[edit] else '>i', data,
                                                     edit + (16 if data[edit] else 12))[0]
                    if media_start < 0:
                        raise ValueError('Edit list video con intervallo vuoto non supportata')
            presentation, decode, peak_samples = _presentation(entries, offsets)
            limit = math.floor(seconds * scale)
            excess = max(presentation - media_start - limit, decode - limit, 0)
            if not excess:
                continue
            if excess > scale / 2:
                raise ValueError('Sforamento oltre mezzo secondo: serve un nuovo montaggio')
            # Le run brevi del master Matroska permettono di distribuire microsecondi senza alterare i frame.
            removed = consumed = 0
            peak_entry = 0
            for i, (n, delta) in enumerate(entries):
                consumed += n
                if consumed - n < peak_samples:
                    peak_entry = i
                desired = round(excess * min(consumed, peak_samples) / peak_samples)
                reduction = max(0, round((desired - removed) / n))
                if reduction >= delta:
                    raise ValueError('Correzione temporale non rappresentabile')
                entries[i][1] -= reduction
                removed += n * reduction
            remaining = excess - removed
            for entry in reversed(entries[:peak_entry + 1]):
                if remaining <= 0:
                    break
                n, delta = entry
                if n <= remaining + max(1, scale // 1000) and delta > 1:
                    entry[1] -= 1
                    remaining -= n
                    removed += n
            if remaining > 0 or removed > excess + max(1, scale // 1000):
                raise ValueError('Indice troppo compatto: non modifico il video')
            presentation, decode, _ = _presentation(entries, offsets)
            over = presentation - media_start - limit
            if over > 0:
                for entry in entries[:peak_entry]:
                    n, delta = entry
                    correction = math.ceil(over / n)
                    if n <= over + max(1, scale // 1000) and correction < delta:
                        entry[1] -= correction
                        removed += n * correction
                        break
                presentation, decode, _ = _presentation(entries, offsets)
            new_end = (presentation - media_start) / scale
            if new_end > seconds:
                raise ValueError('La correzione non rispetta il limite richiesto')
            for i, (n, delta) in enumerate(entries):
                struct.pack_into('>II', data, stts + 8 + i * 8, n, delta)
            struct.pack_into(media_format, data, media_duration, decode)
            movie_ticks = min(math.floor(seconds * movie_scale), math.ceil(new_end * movie_scale))
            struct.pack_into(track_format, data, track_duration, movie_ticks)
            if edit is not None:
                struct.pack_into('>Q' if data[edit] else '>I', data, edit + 8, movie_ticks)
            changes.append({'frames': samples, 'adjustment_s': removed / scale, 'presentation_end_s': new_end})
        if changes:
            duration = max(struct.unpack_from(fmt, data, off)[0] for off, fmt in tracks)
            if duration > seconds * movie_scale:
                raise ValueError('Una traccia audio oltrepassa il limite richiesto')
            struct.pack_into(movie_format, data, movie_duration, duration)
            try:
                stream.seek(position)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            except OSError:
                stream.seek(position)
                stream.write(original)
                stream.flush()
                raise
        return {'changed': bool(changes), 'tracks': changes, 'size_unchanged': path.stat().st_size == length}
