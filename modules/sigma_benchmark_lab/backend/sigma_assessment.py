"""Collega codice e compiti dell'agente senza confondere punteggi o checkpoint."""

from collections import Counter
import hashlib
import json
import math
import re


def checkpoint_sha(identity: dict) -> str | None:
    if not isinstance(identity, dict):
        return None
    value = identity.get('sha256')
    return value if identity.get('verified') is True and isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) else None


def stable_checkpoint(before: dict, after: dict) -> str | None:
    first, last = checkpoint_sha(before), checkpoint_sha(after)
    return first if first and first == last else None


def runtime_signature(runtime: dict) -> str | None:
    if not isinstance(runtime, dict):
        return None
    settings = runtime.get('settings') or {}
    if not isinstance(settings, dict) or type(settings.get('n_ctx')) is not int or settings['n_ctx'] <= 0:
        return None
    value = {'backend': runtime.get('backend'), **{k: settings.get(k) for k in (
        'n_ctx', 'main_gpu', 'forced_single_gpu', 'tensor_split', 'kv_quant',
        'n_batch', 'parallel_slots', 'slot_ctx')}}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def task_verdict(scenario: dict):
    """Ricalcola il verdetto dalle prove; non basta il booleano del referto."""
    if type(scenario.get('compito_riuscito')) is not bool:
        return None
    proofs = scenario.get('prove') or []
    if not isinstance(proofs, list) or not 1 <= len(proofs) <= 64:
        return None
    if any(not isinstance(p, dict) for p in proofs):
        return None
    results = [p for p in proofs if p.get('id') == 'risultato_giusto']
    integrity = [p for p in proofs if p.get('id') in (
        'rispetto_sandbox', 'non_riscrive_la_prova', 'file_protetti_invariati')]
    if not results or not any(p.get('id') == 'rispetto_sandbox' for p in integrity):
        return None
    turns, limit = scenario.get('turni'), scenario.get('tetto_turni')
    seconds, seconds_limit = scenario.get('secondi'), scenario.get('tetto_secondi')
    if (type(turns) is not int or type(limit) is not int
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in (seconds, seconds_limit))):
        return None
    return bool(all(p.get('superata') is True for p in results+integrity)
                and scenario.get('obiettivo_raggiunto') is True
                and not any(scenario.get(k) for k in ('errore', 'scaduto', 'annullato'))
                and 0 < turns <= limit and 0 <= seconds <= seconds_limit)


def summarize_agent(job: dict) -> dict:
    result = job.get('results') or {}
    result = result if isinstance(result, dict) else {}
    scenarios = result.get('scenari') or []
    scenarios = scenarios[:64] if isinstance(scenarios, list) else []
    cases, seen, issues = [], set(), []
    failures = Counter()
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            issues.append('Scenario non valido')
            continue
        proofs = scenario.get('prove') or []
        if not isinstance(proofs, list) or len(proofs) > 64 or any(not isinstance(p, dict) for p in proofs):
            issues.append('Prove dello scenario non valide')
            proofs = []
        scenario = {**scenario, 'prove': proofs}
        failures.update(p.get('id') for p in proofs if p.get('superata') is False)
        key = scenario.get('scenario')
        if not isinstance(key, str) or not key or key in seen:
            issues.append('Scenari duplicati o privi di identificatore')
            continue
        seen.add(key)
        passed = task_verdict(scenario)
        if type(scenario.get('compito_riuscito')) is bool and passed != scenario['compito_riuscito']:
            issues.append('Verdetto aggregato non coerente con le prove')
        cases.append({'id': key, 'passed': passed, 'ended': not scenario.get('scaduto', False),
                      'integrity_failure': any(p.get('superata') is False for p in scenario.get('prove', [])
                                               if p.get('id') in ('rispetto_sandbox', 'non_riscrive_la_prova', 'file_protetti_invariati'))})
    planned = job.get('scenarios_planned') or list(seen)
    if (not isinstance(planned, list) or len(planned) > 64
            or any(not isinstance(p, str) for p in planned) or len(set(planned)) != len(planned)):
        issues.append('Piano degli scenari non valido')
        planned = list(seen)
    if set(planned) != seen:
        issues.append('Scenari pianificati mancanti o differenti')
    total = max(len(planned), len(cases))
    passed = sum(c['passed'] is True for c in cases)
    unknown = sum(c['passed'] is None for c in cases)+max(0, total-len(cases))
    before, after = result.get('runtime_before') or {}, result.get('runtime_after') or {}
    before = before if isinstance(before, dict) else {}
    after = after if isinstance(after, dict) else {}
    identity = stable_checkpoint(before.get('checkpoint'), after.get('checkpoint'))
    runtime = runtime_signature(before)
    if not identity:
        issues.append('Impronta del checkpoint assente o cambiata')
    if not runtime or runtime != runtime_signature(after) or before.get('model') != after.get('model'):
        issues.append('Ambiente di esecuzione assente o cambiato')
    fingerprint = result.get('evaluation_fingerprint')
    if not isinstance(fingerprint, str) or not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
        issues.append('Impronta dei compiti non registrata')
    harness = result.get('harness_fingerprint')
    if (not isinstance(harness, str) or not re.fullmatch(r'[0-9a-f]{64}', harness)
            or result.get('harness_stable') is not True
            or result.get('evaluation_implementation_stable') is not True):
        issues.append('Versione del motore agente assente o cambiata')
    return {'job_id': job.get('id'), 'model': job.get('model'), 'status': job.get('status'),
            'purpose': job.get('purpose', 'benchmark'),
            'score': result.get('punteggio'), 'failures': dict(failures),
            'tasks_passed': passed, 'tasks_total': total, 'tasks_unverified': unknown,
            'task_success_pct': round(100*passed/total, 1) if total else None,
            'cases': cases, 'checkpoint_sha256': identity, 'runtime_signature': runtime,
            'evaluation_fingerprint': fingerprint, 'evidence_issues': issues,
            'harness_fingerprint': harness,
            'comparable': job.get('status') == 'completed' and bool(total) and not unknown and not issues}


def _paired(left: list[dict], right: list[dict]) -> dict:
    a, b = {r['id']: r for r in left}, {r['id']: r for r in right}
    if not a or a.keys() != b.keys() or len(a) != len(left) or len(b) != len(right):
        return {'comparable': False}
    return {'comparable': True,
            'wins': [key for key in a if a[key]['passed'] is False and b[key]['passed'] is True],
            'regressions': [key for key in a if a[key]['passed'] is True and b[key]['passed'] is not True],
            'new_length_limits': [key for key in a if a[key]['ended'] and not b[key]['ended']]}


def compare_bundle(reference: dict, candidate: dict) -> dict:
    """Il referto suggerisce una validazione; non sostituisce mai il modello attivo."""
    issues = []
    for bundle in (reference, candidate):
        code, agent = bundle['coding'], bundle['agent']
        if (not code.get('checkpoint_sha256') or code.get('checkpoint_sha256') != agent.get('checkpoint_sha256')
                or not code.get('comparable') or not agent.get('comparable')):
            issues.append('Codice e agente non associati allo stesso checkpoint verificato')
        if code.get('purpose') == 'integration_smoke' or agent.get('purpose') == 'integration_smoke':
            issues.append('Il collaudo di integrazione non certifica la qualita del modello')
    comparisons = {}
    for domain, keys in [('coding', ('dataset_hash', 'settings_hash', 'runtime_signature')),
                         ('agent', ('evaluation_fingerprint', 'runtime_signature'))]:
        a, b = reference[domain], candidate[domain]
        if any(not a.get(k) or a.get(k) != b.get(k) for k in keys):
            issues.append(f'Protocolli o ambiente {domain} non confrontabili')
        comparisons[domain] = _paired(a.get('cases', []), b.get('cases', []))
        if not comparisons[domain]['comparable']:
            issues.append(f'Compiti {domain} differenti o incompleti')
    regressions = any(c.get('regressions') or c.get('new_length_limits') for c in comparisons.values())
    integrity = any(c.get('integrity_failure') for c in candidate['agent'].get('cases', []))
    wins = any(c.get('wins') for c in comparisons.values())
    status = ('insufficient_evidence' if issues else 'regression' if regressions or integrity
              else 'candidate_for_validation' if wins else 'no_demonstrated_gain')
    agent = candidate['agent']
    weights_changed = reference['coding'].get('checkpoint_sha256') != candidate['coding'].get('checkpoint_sha256')
    harness_changed = reference['agent'].get('harness_fingerprint') != candidate['agent'].get('harness_fingerprint')
    return {'reference': reference['id'], 'candidate': candidate['id'], 'status': status,
            'change_axis': ('weights_and_harness' if weights_changed and harness_changed else 'weights'
                            if weights_changed else 'harness' if harness_changed else 'repeat'),
            'issues': issues, 'domains': comparisons, 'auto_promote': False,
            'agent_target_observed': bool(not issues and agent.get('tasks_total') and not agent.get('tasks_unverified')
                                          and 100*agent['tasks_passed'] > 90*agent['tasks_total'])}


def associate_runs(coding: list[dict], agents: list[dict]) -> dict:
    bundles, seen, checkpoints = [], set(), set()
    for code in sorted(coding[:12], key=lambda r: r.get('purpose') == 'integration_smoke'):
        sha = code.get('checkpoint_sha256')
        if not sha or sha in checkpoints or not code.get('comparable'):
            continue
        checkpoints.add(sha)
        for agent in sorted(agents[:50], key=lambda r: r.get('purpose') == 'integration_smoke'):
            if (agent.get('checkpoint_sha256') != sha or not agent.get('comparable')
                    or code.get('runtime_signature') != agent.get('runtime_signature')):
                continue
            key = (sha, agent.get('harness_fingerprint'), agent.get('evaluation_fingerprint'))
            if key in seen or len(bundles) >= 12:
                continue
            seen.add(key)
            identifier = hashlib.sha256(json.dumps(key).encode()).hexdigest()
            bundles.append({'id': identifier, 'checkpoint_sha256': sha,
                            'model': code['model'], 'coding': code, 'agent': agent})
    return {'bundles': bundles,
            'comparisons': [compare_bundle(a, b) for a in bundles for b in bundles if a is not b],
            'policy': 'Correttezza del codice e completamento verificato restano separati. Nessuna attivazione automatica; nuovi compiti e risorse misurate richiesti prima del rilascio.'}
