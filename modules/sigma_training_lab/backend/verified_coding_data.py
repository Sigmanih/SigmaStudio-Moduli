"""Problemi sintetici con oracoli eseguibili, separati per famiglia e ruolo."""

from dataclasses import asdict, dataclass
from pathlib import Path
from textwrap import dedent, indent
from time import monotonic
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
import urllib.request

from core.logger import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class CodingCase:
    id: str
    split: str
    function: str
    instruction: str
    reference: str
    checks: str
    mutant: str


def coding_cases() -> list[CodingCase]:
    cases = []

    def add(key, split, description, reference, checks, mutant):
        reference, mutant = dedent(reference).strip(), dedent(mutant).strip()
        function = next(n.name for n in ast.parse(reference).body if isinstance(n, ast.FunctionDef))
        ast.parse(mutant)
        suite = "def check(f):\n"+indent(dedent(checks).strip(), "    ")
        ast.parse(suite)
        instruction = (description+"\nSignature: "+reference.splitlines()[0]+
                       "\nReturn a complete Python solution in one python code block, using only the standard library.")
        cases.append(CodingCase("sigma_verified_"+key, split, function, instruction, reference,
                                suite, mutant))

    add("merge", "train", "Merge overlapping closed intervals, including touching endpoints. Normalize reversed endpoints and return sorted tuples. Do not mutate the input.", '''
    def merge_closed(intervals):
        ordered = sorted((min(a, b), max(a, b)) for a, b in intervals)
        result = []
        for start, end in ordered:
            if result and start <= result[-1][1]:
                result[-1] = (result[-1][0], max(result[-1][1], end))
            else:
                result.append((start, end))
        return result
    ''', '''
    import random
    rng = random.Random(42)
    for _ in range(80):
        data = [(rng.randint(-8, 8), rng.randint(-8, 8)) for _ in range(rng.randrange(9))]
        before = data[:]
        normalized = [(min(a,b), max(a,b)) for a,b in data]
        unseen = set(range(len(data))); expected = []
        while unseen:
            component = {unseen.pop()}
            while True:
                added = {j for j in unseen if any(max(normalized[j][0], normalized[i][0]) <= min(normalized[j][1], normalized[i][1]) for i in component)}
                if not added: break
                component |= added; unseen -= added
            expected.append((min(normalized[i][0] for i in component), max(normalized[i][1] for i in component)))
        assert f(data) == sorted(expected)
        assert data == before
    assert f([(0,1),(1,2)]) == [(0,2)]
    ''', 'def merge_closed(intervals):\n    return sorted((min(a,b),max(a,b)) for a,b in intervals)')

    add("paths", "train", "Return shortest distances from source in a directed graph with n positive-numbered-count vertices indexed 0..n-1. Edges are (u,v,nonnegative_integer_weight). Unreachable entries are None. Invalid vertices or negative weights raise ValueError.", '''
    def shortest_distances(n, edges, source):
        import heapq
        if n < 1 or not 0 <= source < n:
            raise ValueError("source")
        graph = [[] for _ in range(n)]
        for u, v, weight in edges:
            if not (0 <= u < n and 0 <= v < n) or weight < 0:
                raise ValueError("edge")
            graph[u].append((v, weight))
        distances = [None] * n
        distances[source] = 0
        pending = [(0, source)]
        while pending:
            distance, u = heapq.heappop(pending)
            if distances[u] != distance:
                continue
            for v, weight in graph[u]:
                candidate = distance + weight
                if distances[v] is None or candidate < distances[v]:
                    distances[v] = candidate
                    heapq.heappush(pending, (candidate, v))
        return distances
    ''', '''
    import random
    rng = random.Random(43)
    for _ in range(60):
        n = rng.randint(1,7); source = rng.randrange(n)
        edges = [(a,b,rng.randrange(6)) for a in range(n) for b in range(n) if rng.random()<.22]
        expected = [float('inf')]*n; expected[source] = 0
        for _ in range(n-1):
            for a,b,w in edges: expected[b] = min(expected[b], expected[a]+w)
        expected = [None if x==float('inf') else x for x in expected]
        assert f(n,edges,source) == expected
    assert f(3,[(0,1,0),(1,2,2)],0) == [0,0,2]
    for args in [(2,[(0,1,-1)],0),(2,[(0,3,1)],0),(2,[],2)]:
        try: f(*args)
        except ValueError: continue
        raise AssertionError('invalid graph accepted')
    ''', 'def shortest_distances(n, edges, source):\n    return [0 if i==source else None for i in range(n)]')

    invoice = '''
    def invoice_total(text):
        import csv
        import io
        from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
        rows = csv.DictReader(io.StringIO(text))
        if rows.fieldnames != ["quantity", "price"]:
            raise ValueError("header")
        total = Decimal("0.00")
        try:
            for row in rows:
                quantity = int(row["quantity"])
                price = Decimal(row["price"])
                if not 0 <= quantity <= 1000000 or not price.is_finite() or not 0 <= price <= 1000000:
                    raise ValueError("amount")
                if None in row or price.as_tuple().exponent < -3:
                    raise ValueError("row")
                total += (quantity * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, TypeError, KeyError) as exc:
            raise ValueError("row") from exc
        return total
    '''
    add("invoice", "train", "Parse CSV with the exact header quantity,price and no extra fields. Quantity is an integer between 0 and 1000000. Price is a finite decimal between 0 and 1000000 with at most three decimal places. Round each line total to cents with ROUND_HALF_UP before summing. Return Decimal. Reject invalid headers or values with ValueError.", invoice, r'''
    from decimal import Decimal
    import random
    rng = random.Random(44)
    for _ in range(50):
        rows = [(rng.randrange(5),rng.randrange(3000)) for _ in range(rng.randrange(8))]
        text = 'quantity,price\n' + ''.join(f'{q},{p//1000}.{p%1000:03d}\n' for q,p in rows)
        expected = Decimal(sum((q*p+5)//10 for q,p in rows))/100
        assert f(text) == expected and isinstance(f(text), Decimal)
    assert f('quantity,price\n"1","0.005"\n') == Decimal('0.01')
    for text in ['q,price\n1,2\n','quantity,price\n-1,2\n','quantity,price\n1,NaN\n','quantity,price\n1,Infinity\n','quantity,price\nx,2\n','quantity,price\n1,2,3\n','quantity,price\n1,1E100\n','quantity,price\n1000001,2\n','quantity,price\n1,0.0001\n']:
        try: f(text)
        except ValueError: continue
        raise AssertionError('invalid CSV accepted')
    ''', invoice.replace("ROUND_HALF_UP", "ROUND_DOWN"))

    add("unicode", "train", "Count whitespace-separated words after NFKC normalization, casefolding, and NFC normalization. Return a dict; accented letters are retained.", '''
    def normalized_counts(text):
        import unicodedata
        text = unicodedata.normalize("NFKC", text).casefold()
        text = unicodedata.normalize("NFC", text)
        counts = {}
        for word in text.split():
            counts[word] = counts.get(word, 0) + 1
        return counts
    ''', r'''
    assert f('Straße STRASSE') == {'strasse':2}
    assert f('e\u0301 É é') == {'é':3}
    assert f('ＡＢ ab ﬁ fi') == {'ab':2,'fi':2}
    assert f(' \n\t') == {}
    assert f('caffè caffe') == {'caffè':1,'caffe':1}
    for word in ['é','Straße','ＡＢ','ﬁ']:
        one = f(word)
        assert f((word+' ')*7) == {k:7*v for k,v in one.items()}
    ''', 'def normalized_counts(text):\n    return {x:text.lower().split().count(x) for x in text.lower().split()}')

    add("lru", "train", "Simulate LRU accesses. Return (miss_count, cache_order_oldest_to_newest). Hits refresh recency. Capacity zero produces a miss for every access; negative capacity raises ValueError.", '''
    def lru_accesses(accesses, capacity):
        from collections import OrderedDict
        if capacity < 0:
            raise ValueError("capacity")
        cache = OrderedDict()
        misses = 0
        for key in accesses:
            if key in cache:
                cache.move_to_end(key)
            else:
                misses += 1
                if capacity:
                    cache[key] = None
                    if len(cache) > capacity:
                        cache.popitem(last=False)
        return misses, list(cache)
    ''', '''
    import random
    rng = random.Random(45)
    for _ in range(80):
        accesses = [rng.randrange(6) for _ in range(rng.randrange(35))]; capacity = rng.randrange(5)
        order = []; misses = 0
        for key in accesses:
            if key in order: order.remove(key)
            else: misses += 1
            order.append(key)
            order = order[-capacity:] if capacity else []
        assert f(accesses,capacity) == (misses,order)
    assert f([1,2,1,3,2],2) == (4,[3,2])
    try: f([], -1)
    except ValueError: return
    raise AssertionError('negative capacity accepted')
    ''', '''
    def lru_accesses(accesses, capacity):
        order = []; misses = 0
        for key in accesses:
            if key not in order:
                misses += 1
                order.append(key)
                if len(order)>capacity: order.pop(0)
        return misses, order
    ''')

    add("topological", "train", "Return the lexicographically smallest topological ordering of vertices 0..n-1. Duplicate edges have no effect. Invalid vertices or directed cycles raise ValueError. For n=0 and no edges return [].", '''
    def smallest_topological(n, edges):
        import heapq
        if n < 0:
            raise ValueError("n")
        graph = [set() for _ in range(n)]
        indegree = [0] * n
        for u, v in edges:
            if not (0 <= u < n and 0 <= v < n):
                raise ValueError("edge")
            if v not in graph[u]:
                graph[u].add(v)
                indegree[v] += 1
        ready = [u for u in range(n) if not indegree[u]]
        heapq.heapify(ready)
        result = []
        while ready:
            u = heapq.heappop(ready)
            result.append(u)
            for v in graph[u]:
                indegree[v] -= 1
                if not indegree[v]:
                    heapq.heappush(ready, v)
        if len(result) != n:
            raise ValueError("cycle")
        return result
    ''', '''
    import itertools, random
    rng = random.Random(46)
    assert f(0,[]) == []
    assert f(3,[(2,0),(2,0)]) == [1,2,0]
    for _ in range(35):
        n = rng.randint(1,5)
        edges = [(a,b) for a in range(n) for b in range(n) if rng.random()<.17]
        valid = [p for p in itertools.permutations(range(n)) if all(p.index(a)<p.index(b) for a,b in edges)]
        if valid: assert f(n,edges) == list(min(valid))
        else:
            try: f(n,edges)
            except ValueError: continue
            raise AssertionError('cycle accepted')
    ''', 'def smallest_topological(n, edges):\n    return list(range(n))')

    add("windows", "validation", "Return the maximum in each contiguous window of length k, without mutating the sequence. k must be positive. If k exceeds the sequence length, return [].", '''
    def window_maxima(values, k):
        from collections import deque
        if k <= 0:
            raise ValueError("k")
        pending = deque()
        result = []
        for i, value in enumerate(values):
            while pending and pending[0] <= i-k:
                pending.popleft()
            while pending and values[pending[-1]] <= value:
                pending.pop()
            pending.append(i)
            if i >= k-1:
                result.append(values[pending[0]])
        return result
    ''', '''
    import random
    rng = random.Random(47)
    for _ in range(80):
        values = [rng.randint(-20,20) for _ in range(rng.randrange(35))]; k = rng.randint(1,40)
        before = values[:]
        assert f(values,k) == [max(values[i:i+k]) for i in range(len(values)-k+1)]
        assert values == before
    try: f([1],0)
    except ValueError: return
    raise AssertionError('zero window accepted')
    ''', 'def window_maxima(values, k):\n    return [max(values[i:i+k]) for i in range(len(values)-k)]')

    add("coins", "validation", "For an unlimited supply of positive integer coin denominations, return the minimum coin count for a nonnegative amount, or None if impossible. Reject negative amounts and nonpositive coins with ValueError.", '''
    def minimum_coins(coins, amount):
        if amount < 0 or any(c <= 0 for c in coins):
            raise ValueError("input")
        best = [0] + [amount+1] * amount
        for value in range(1, amount+1):
            for coin in coins:
                if coin <= value:
                    best[value] = min(best[value], best[value-coin]+1)
        return best[amount] if best[amount] <= amount else None
    ''', '''
    from collections import deque
    import random
    rng = random.Random(48)
    assert f([1,3,4],6) == 2
    for _ in range(60):
        coins = list({rng.randint(1,12) for _ in range(rng.randrange(5))}); amount = rng.randrange(60)
        queue = deque([(0,0)]); seen = {0}; expected = None
        while queue:
            value, count = queue.popleft()
            if value == amount: expected = count; break
            for coin in coins:
                nxt = value+coin
                if nxt <= amount and nxt not in seen: seen.add(nxt); queue.append((nxt,count+1))
        assert f(coins,amount) == expected
    for coins,amount in [([0],2),([-1],2),([1],-1)]:
        try: f(coins,amount)
        except ValueError: continue
        raise AssertionError('invalid input accepted')
    ''', '''
    def minimum_coins(coins, amount):
        count = 0
        for coin in sorted(coins,reverse=True):
            n, amount = divmod(amount,coin)
            count += n
        return count if amount==0 else None
    ''')

    add("runs", "confirmation", "Run-length encode a Unicode string as maximal (character,count) tuples. Empty input returns [].", '''
    def pack_runs(text):
        result = []
        for char in text:
            if result and result[-1][0] == char:
                result[-1] = (char, result[-1][1]+1)
            else:
                result.append((char,1))
        return result
    ''', '''
    import random
    rng = random.Random(49)
    for _ in range(100):
        text = ''.join(rng.choice('abé🙂') for _ in range(rng.randrange(60)))
        runs = f(text)
        assert all(isinstance(c,str) and len(c)==1 and isinstance(n,int) and n>0 for c,n in runs)
        assert ''.join(c*n for c,n in runs) == text
        assert all(a[0]!=b[0] for a,b in zip(runs,runs[1:]))
    ''', 'def pack_runs(text):\n    return [(c,1) for c in text]')

    add("bounds", "confirmation", "For a sorted sequence, return (number of elements strictly less than target, number of elements less than or equal to target). Handle duplicates and empty input.", '''
    def equal_bounds(values, target):
        def bound(inclusive):
            lo, hi = 0, len(values)
            while lo < hi:
                mid = (lo+hi)//2
                if values[mid] < target or (inclusive and values[mid] == target):
                    lo = mid+1
                else:
                    hi = mid
            return lo
        return bound(False), bound(True)
    ''', '''
    import random
    rng = random.Random(50)
    for _ in range(100):
        data = sorted(rng.randint(-8,8) for _ in range(rng.randrange(40))); target=rng.randint(-10,10)
        assert f(data,target) == (sum(x<target for x in data),sum(x<=target for x in data))
    ''', 'def equal_bounds(values, target):\n    return 0,len(values)')

    add("brackets", "confirmation", "Check properly nested (), [] and {} brackets, ignoring brackets inside single or double quoted strings. Backslash escapes the next character inside strings. Unclosed quotes are invalid. Other characters are ignored.", '''
    def balanced_text(text):
        stack = []
        quote = None
        escaped = False
        closing = {')':'(', ']':'[', '}':'{'}
        for char in text:
            if quote is not None:
                if escaped:
                    escaped = False
                elif ord(char) == 92:
                    escaped = True
                elif char == quote:
                    quote = None
            elif char in ("'", '"'):
                quote = char
            elif char in '([{':
                stack.append(char)
            elif char in closing:
                if not stack or stack.pop() != closing[char]:
                    return False
        return not stack and quote is None
    ''', '''
    for text,expected in [('',True),('([{}])',True),('([)]',False),(')',False),("'[)]'()",True),("'unterminated",False),('"["{}',True)]:
        assert f(text) is expected
    for depth in range(20):
        assert f('('*depth+"'[)]'"+')'*depth) is True
        assert f('('*depth+')'*(depth+1)) is False
    assert f("'a"+chr(92)+"'b'()") is True
    ''', 'def balanced_text(text):\n    return text.count("(")==text.count(")")')

    add("sqrt", "confirmation", "Return the floor of the square root of a nonnegative integer, including arbitrarily large integers. Negative input raises ValueError. Use integer arithmetic.", '''
    def integer_root(n):
        if n < 0:
            raise ValueError("negative")
        if n < 2:
            return n
        x = 1 << ((n.bit_length()+1)//2)
        while True:
            y = (x+n//x)//2
            if y >= x:
                return x
            x = y
    ''', '''
    import math, random
    rng = random.Random(51)
    for n in [0,1,2,3,4,15,16,17,10**100-1]+[rng.getrandbits(rng.randrange(257)) for _ in range(80)]:
        value = f(n)
        assert value == math.isqrt(n) and value*value<=n<(value+1)*(value+1)
    try: f(-1)
    except ValueError: return
    raise AssertionError('negative root accepted')
    ''', 'def integer_root(n):\n    return int(n**.5)')

    add("crc", "confirmation", "Return the unsigned IEEE CRC-32 of a bytes object, matching zlib.crc32. Empty bytes return zero.", '''
    def crc32_bytes(data):
        crc = 0xffffffff
        for byte in data:
            crc ^= byte
            for _ in range(8):
                crc = (crc >> 1) ^ (0xedb88320 if crc & 1 else 0)
        return crc ^ 0xffffffff
    ''', '''
    import random,zlib
    rng = random.Random(52)
    assert f(b'123456789') == 0xcbf43926
    for _ in range(80):
        data = bytes(rng.randrange(256) for _ in range(rng.randrange(100)))
        assert f(data) == zlib.crc32(data)
    ''', 'def crc32_bytes(data):\n    import zlib\n    return zlib.crc32(data)^1')

    add("distance", "confirmation", "Return the Levenshtein edit distance between two Unicode strings. Insertions, deletions and substitutions each cost one.", '''
    def edit_distance(a, b):
        previous = list(range(len(b)+1))
        for i, char in enumerate(a,1):
            current = [i]
            for j, other in enumerate(b,1):
                current.append(min(current[-1]+1, previous[j]+1, previous[j-1]+(char != other)))
            previous = current
        return previous[-1]
    ''', '''
    from functools import lru_cache
    import random
    def oracle(a,b):
        @lru_cache(None)
        def solve(i,j):
            if i==len(a): return len(b)-j
            if j==len(b): return len(a)-i
            return min(1+solve(i+1,j),1+solve(i,j+1),(a[i]!=b[j])+solve(i+1,j+1))
        return solve(0,0)
    rng = random.Random(53)
    assert f('kitten','sitting') == 3
    for _ in range(70):
        a=''.join(rng.choice('abé') for _ in range(rng.randrange(6)));b=''.join(rng.choice('abé') for _ in range(rng.randrange(6)))
        assert f(a,b)==oracle(a,b)==f(b,a)
    ''', 'def edit_distance(a,b):\n    return abs(len(a)-len(b))')

    add("rational", "confirmation", "Add two integer fractions represented as (numerator,denominator). Return a reduced tuple with positive denominator; zero is (0,1). A zero denominator raises ValueError.", '''
    def add_fractions(a, b):
        from math import gcd
        p, q = a
        r, s = b
        if q == 0 or s == 0:
            raise ValueError("denominator")
        numerator, denominator = p*s+r*q, q*s
        common = gcd(numerator, denominator)
        numerator //= common
        denominator //= common
        if denominator < 0:
            numerator, denominator = -numerator, -denominator
        return numerator, denominator
    ''', '''
    from fractions import Fraction
    import random
    rng = random.Random(54)
    for _ in range(100):
        a=(rng.randint(-30,30),rng.choice([i for i in range(-10,11) if i]));b=(rng.randint(-30,30),rng.choice([i for i in range(-10,11) if i]))
        value=Fraction(*a)+Fraction(*b)
        assert f(a,b)==(value.numerator,value.denominator)
    try: f((1,0),(1,2))
    except ValueError: return
    raise AssertionError('zero denominator accepted')
    ''', 'def add_fractions(a,b):\n    return a[0]*b[1]+b[0]*a[1],a[1]*b[1]')

    rooms = '''
    def peak_rooms(intervals):
        events = []
        for start, end in intervals:
            if start > end:
                raise ValueError("interval")
            if start < end:
                events.extend([(start,1),(end,-1)])
        active = peak = 0
        for _, delta in sorted(events):
            active += delta
            peak = max(peak, active)
        return peak
    '''
    add("rooms", "confirmation", "Return peak simultaneous occupancy of half-open intervals [start,end). Zero-length intervals are ignored, reversed intervals raise ValueError, and touching intervals do not overlap.", rooms, '''
    import random
    rng = random.Random(55)
    assert f([(0,1),(1,2)]) == 1
    assert f([(1,1),(1,1)]) == 0
    for _ in range(100):
        data=[tuple(sorted((rng.randint(-8,8),rng.randint(-8,8)))) for _ in range(rng.randrange(12))]
        expected=max([sum(a<=t<b for a,b in data) for t,_ in data]+[0])
        assert f(data)==expected
    try: f([(2,1)])
    except ValueError: return
    raise AssertionError('reversed interval accepted')
    ''', rooms.replace("sorted(events)", "sorted(events, key=lambda x: (x[0], -x[1]))"))
    return cases


_IMPORTS = {"math", "collections", "heapq", "decimal", "csv", "io", "unicodedata", "bisect",
            "functools", "itertools", "typing", "re", "zlib", "fractions", "copy"}
_FORBIDDEN = {"open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars",
              "getattr", "setattr", "delattr", "__builtins__"}


def verify_solution(case: CodingCase, solution: str, *, timeout=5) -> dict:
    """Controlla codice limitato in un processo isolato; nessun confronto testuale."""
    if not 0 < timeout <= 10 or not 0 < len(solution.encode("utf-8")) <= 32768:
        raise ValueError("Codice o timeout fuori budget")
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)(?:```|\Z)", solution, flags=re.S|re.I)
    code = max(blocks, key=len) if blocks else solution
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(x.name.split('.')[0] not in _IMPORTS for x in node.names):
                raise ValueError("Import non ammesso")
            if isinstance(node, ast.ImportFrom) and (node.level or (node.module or '').split('.')[0] not in _IMPORTS):
                raise ValueError("Import non ammesso")
            if isinstance(node, ast.Name) and node.id in _FORBIDDEN:
                raise ValueError("Operazione non ammessa")
            if isinstance(node, ast.Attribute) and node.attr.startswith('__'):
                raise ValueError("Attributo non ammesso")
    except (SyntaxError, ValueError) as exc:
        return {"passed": False, "status": "invalid_code", "detail": str(exc)[:300]}
    nonce = uuid.uuid4().hex
    runner = ("import sys,traceback\nnamespace={'__name__':'sigma_candidate'}\ntry:\n"
              +"    exec(compile("+repr(code)+",'<candidate>','exec'),namespace)\n"
              +"    checks={}\n    exec(compile("+repr(case.checks)+",'<oracle>','exec'),checks)\n"
              +"    checks['check'](namespace["+repr(case.function)+"])\n"
              +"except BaseException:\n    traceback.print_exc()\n    sys.exit(1)\n"
              +"sys.stdout.write("+repr(nonce)+")\n")
    start = monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="sigma_verified_") as directory:
            path = Path(directory)/"check.py"
            path.write_text(runner, encoding="utf-8")
            result = subprocess.run([sys.executable,"-I","-B",str(path)], cwd=directory,
                                    capture_output=True, timeout=timeout, encoding="utf-8", errors="replace",
                                    env={**os.environ,"PYTHONIOENCODING":"utf-8","PYTHONUTF8":"1"})
        passed = result.returncode == 0 and result.stdout.endswith(nonce)
        return {"passed": passed, "status": "passed" if passed else "failed",
                "detail": result.stderr[-1000:] if not passed else "oracoli superati",
                "seconds": monotonic()-start}
    except subprocess.TimeoutExpired:
        return {"passed": False, "status": "timeout", "detail": "tempo di verifica esaurito"}
    except OSError as exc:
        log.warning("Verifica sintetica fallita: %s", exc)
        return {"passed": False, "status": "error", "detail": str(exc)[:300]}


def verify_corpus() -> list[dict]:
    results = []
    for case in coding_cases():
        reference = verify_solution(case, case.reference)
        mutant = verify_solution(case, case.mutant)
        results.append({"id": case.id, "split": case.split, "reference": reference,
                        "mutant": mutant, "reference_sha256": hashlib.sha256(case.reference.encode()).hexdigest(),
                        "checks_sha256": hashlib.sha256(case.checks.encode()).hexdigest()})
    return results


def tokenize_cases(native_port: int) -> dict:
    """Prepara solo token: la certificazione eseguibile avviene separatamente."""
    if not 1024 <= native_port <= 65535:
        raise ValueError("Porta locale non valida")
    deadline = monotonic()+90

    def post(endpoint, payload):
        if monotonic() > deadline:
            raise TimeoutError("Tempo di preparazione esaurito")
        request = urllib.request.Request(f"http://127.0.0.1:{native_port}/{endpoint}",
                    data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            data = response.read(1024*1024+1)
        if len(data) > 1024*1024:
            raise ValueError("Risposta del tokenizer fuori budget")
        return json.loads(data)

    eog = post("tokenize", {"content":"<|im_end|>","parse_special":True,"add_special":False})["tokens"]
    if len(eog) != 1:
        raise ValueError("Token di arresto non univoco")
    rows = []
    for case in coding_cases():
        messages = [{"role":"system","content":"You are an expert Python engineer. Output only working code in one code block."},
                    {"role":"user","content":case.instruction}]
        prompt = post("apply-template", {"messages":messages,"chat_template_kwargs":{"enable_thinking":False}})["prompt"]
        prefix = post("tokenize", {"content":prompt,"parse_special":True,"add_special":True})["tokens"]
        answer = "```python\n"+case.reference+"\n```"
        full = post("tokenize", {"content":prompt+answer,"parse_special":True,"add_special":True})["tokens"]
        if full[:len(prefix)] != prefix or not 1 <= len(full)-len(prefix)+1 <= 512:
            raise ValueError("Riferimento fuori budget o confine non allineato: "+case.id)
        rows.append({**asdict(case),"prefix_tokens":prefix,"answer_tokens":full[len(prefix):]+eog,
                     "rendered_prompt":prompt,"reference_answer":answer})
    return {"protocol":"sigma.verified-coding/1","cases":rows,"eog_id":eog[0],
            "references_verified":False,"scope":"authored synthetic families; split fixed before model outputs"}
