# ==============================================================================
# core/modules/sigma_network_lab/handlers.py — Network Lab Backend Handlers
# Sigma Studio — Web Search, HTTP Request Builder, DNS Diagnostics & Ping
# ==============================================================================
import asyncio
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Request, Query, Body, HTTPException
from fastapi.responses import JSONResponse

from core.logger import get_logger

log = get_logger("sigma_network_lab")

router = APIRouter(tags=["Network Lab"])


# ------------------------------------------------------------------------------
# 1. System & Network Status
# ------------------------------------------------------------------------------
@router.get("/status")
@router.get("/info")
async def get_network_status():
    """Returns local network interfaces, host info, and internet connectivity."""
    hostname = socket.gethostname()
    local_ips = []
    try:
        _, _, ip_list = socket.gethostbyname_ex(hostname)
        local_ips = ip_list
    except Exception:
        try:
            local_ips = [socket.gethostbyname(hostname)]
        except Exception:
            local_ips = ["127.0.0.1"]

    # Test internet connectivity & latency
    internet_online = False
    gateway_latency_ms = None
    t0 = time.perf_counter()
    try:
        # Check fast connect to Cloudflare DNS (1.1.1.1:53)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(("1.1.1.1", 53))
        sock.close()
        gateway_latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        internet_online = True
    except Exception:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect(("8.8.8.8", 53))
            sock.close()
            gateway_latency_ms = round((time.perf_counter() - t0) * 1000, 1)
            internet_online = True
        except Exception:
            internet_online = False

    return JSONResponse({
        "success": True,
        "hostname": hostname,
        "local_ips": local_ips,
        "primary_ip": local_ips[0] if local_ips else "127.0.0.1",
        "internet_online": internet_online,
        "dns_latency_ms": gateway_latency_ms,
        "protocol_version": "IPv4/IPv6 Ready",
        "services": {
            "web_search": True,
            "http_client": True,
            "dns_resolver": True,
            "ping_tester": True,
            "mcp_server": True
        }
    })


# ------------------------------------------------------------------------------
# 2. Live Web Search (DuckDuckGo & Wikipedia)
# ------------------------------------------------------------------------------
@router.get("/search")
@router.post("/search")
async def execute_web_search(request: Request):
    """Executes live web search queries with snippet extraction."""
    body = {}
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}
    
    query = body.get("query") or request.query_params.get("query") or ""
    engine = body.get("engine") or request.query_params.get("engine") or "duckduckgo"
    max_results = int(body.get("max_results") or request.query_params.get("max_results") or 8)
    max_results = max(1, min(max_results, 25))

    if not query.strip():
        return JSONResponse({"success": False, "error": "Query di ricerca vuota.", "results": []}, status_code=400)

    target_query = query.strip()
    results = []

    def _scrape_duckduckgo(q: str, limit: int) -> List[Dict[str, str]]:
        encoded = urllib.parse.quote(q)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
            }
        )
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
            html = response.read().decode("utf-8", errors="ignore")

        items = []
        # Match result links & snippets
        raw_blocks = re.findall(r'<div class="result__body">([\s\S]*?)</div>\s*</div>', html)
        for block in raw_blocks[:limit]:
            link_m = re.search(r'<a class="result__url"[^>]*href="([^"]+)"', block) or re.search(r'<a class="result__snippet"[^>]*href="([^"]+)"', block)
            snippet_m = re.search(r'<a class="result__snippet"[^>]*>([\s\S]*?)</a>', block)

            href = link_m.group(1).strip() if link_m else ""
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                # Decode DuckDuckGo redirect uddg parameter
                if "uddg=" in href:
                    raw_uddg = href.split("uddg=")[1].split("&")[0]
                    href = urllib.parse.unquote(raw_uddg)

            snippet = re.sub(r'<[^>]+>', '', snippet_m.group(1)).strip() if snippet_m else ""
            
            # Extract clean title from block
            title_match = re.search(r'<h2 class="result__title">[\s\S]*?<a[^>]*>([\s\S]*?)</a>', block)
            title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else href

            if href and (snippet or title):
                items.append({
                    "title": title or href,
                    "url": href,
                    "snippet": snippet or "Nessun frammento disponibile.",
                    "engine": "DuckDuckGo"
                })

        return items

    def _scrape_wikipedia(q: str, limit: int) -> List[Dict[str, str]]:
        encoded = urllib.parse.quote(q)
        url = f"https://it.wikipedia.org/w/api.php?action=opensearch&search={encoded}&limit={limit}&namespace=0&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "SigmaStudio-NetworkLab/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        items = []
        if len(data) >= 4:
            titles = data[1]
            snippets = data[2]
            urls = data[3]
            for t, s, u in zip(titles, snippets, urls):
                items.append({
                    "title": t,
                    "url": u,
                    "snippet": s or f"Articolo Wikipedia: {t}",
                    "engine": "Wikipedia"
                })
        return items

    t_start = time.perf_counter()
    try:
        if engine == "wikipedia":
            results = await asyncio.to_thread(_scrape_wikipedia, target_query, max_results)
        else:
            results = await asyncio.to_thread(_scrape_duckduckgo, target_query, max_results)
            if not results:
                # Fallback to wikipedia if DDG returned empty (e.g. rate limit)
                results = await asyncio.to_thread(_scrape_wikipedia, target_query, max_results)
    except Exception as exc:
        log.warning("Web search exception for '%s': %s", target_query, exc)
        try:
            results = await asyncio.to_thread(_scrape_wikipedia, target_query, max_results)
        except Exception:
            results = []

    elapsed_ms = round((time.perf_counter() - t_start) * 1000, 1)

    return JSONResponse({
        "success": True,
        "query": target_query,
        "engine": engine,
        "results_count": len(results),
        "elapsed_ms": elapsed_ms,
        "results": results
    })


# ------------------------------------------------------------------------------
# 3. HTTP API Request Builder (Postman-style)
# ------------------------------------------------------------------------------
@router.post("/request")
async def execute_http_request(request: Request):
    """Executes arbitrary HTTP requests (GET, POST, PUT, DELETE, PATCH, HEAD) with timing."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"success": False, "error": "Payload JSON non valido."}, status_code=400)

    method = str(payload.get("method") or "GET").upper().strip()
    url = str(payload.get("url") or "").strip()
    headers = payload.get("headers") or {}
    params = payload.get("params") or {}
    body_data = payload.get("body")
    timeout = max(1, min(int(payload.get("timeout") or 15), 60))

    if not url:
        return JSONResponse({"success": False, "error": "URL obbligatorio."}, status_code=400)

    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    # Append query params if provided
    if params and isinstance(params, dict):
        query_string = urllib.parse.urlencode(params)
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{query_string}"

    # Prepare body bytes
    encoded_body = None
    if body_data is not None and method in ("POST", "PUT", "PATCH", "DELETE"):
        if isinstance(body_data, (dict, list)):
            encoded_body = json.dumps(body_data).encode("utf-8")
            if not any(k.lower() == "content-type" for k in headers):
                headers["Content-Type"] = "application/json"
        elif isinstance(body_data, str):
            encoded_body = body_data.encode("utf-8")

    # Default User-Agent if not set
    if not any(k.lower() == "user-agent" for k in headers):
        headers["User-Agent"] = "SigmaStudio-HTTPClient/1.0 (Postman-Ready)"

    def _do_http():
        req = urllib.request.Request(url, data=encoded_body, headers=headers, method=method)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as response:
                latency = round((time.perf_counter() - t0) * 1000, 1)
                status_code = response.getcode()
                resp_headers = dict(response.headers)
                raw_bytes = response.read()
                size_bytes = len(raw_bytes)

                # Attempt decoding text or JSON
                content_type = resp_headers.get("Content-Type", "")
                text_content = raw_bytes.decode("utf-8", errors="replace")
                json_data = None
                if "json" in content_type or text_content.strip().startswith(("{", "[")):
                    try:
                        json_data = json.loads(text_content)
                    except Exception:
                        pass

                return {
                    "success": True,
                    "status_code": status_code,
                    "status_text": "OK" if status_code < 400 else "ERROR",
                    "latency_ms": latency,
                    "size_bytes": size_bytes,
                    "size_label": f"{round(size_bytes / 1024, 2)} KB" if size_bytes >= 1024 else f"{size_bytes} B",
                    "headers": resp_headers,
                    "is_json": json_data is not None,
                    "json_data": json_data,
                    "text_data": text_content[:200000],  # Cap response preview to 200KB
                    "url": url,
                    "method": method
                }
        except urllib.error.HTTPError as http_err:
            latency = round((time.perf_counter() - t0) * 1000, 1)
            raw_err = http_err.read().decode("utf-8", errors="replace")
            err_json = None
            try:
                err_json = json.loads(raw_err)
            except Exception:
                pass
            return {
                "success": False,
                "status_code": http_err.code,
                "status_text": http_err.reason,
                "latency_ms": latency,
                "headers": dict(http_err.headers),
                "is_json": err_json is not None,
                "json_data": err_json,
                "text_data": raw_err[:50000],
                "error": f"HTTP {http_err.code}: {http_err.reason}",
                "url": url,
                "method": method
            }
        except Exception as err:
            latency = round((time.perf_counter() - t0) * 1000, 1)
            return {
                "success": False,
                "status_code": 0,
                "status_text": "Connection Error",
                "latency_ms": latency,
                "headers": {},
                "is_json": False,
                "text_data": "",
                "error": str(err),
                "url": url,
                "method": method
            }

    result = await asyncio.to_thread(_do_http)
    return JSONResponse(result)


# ------------------------------------------------------------------------------
# 4. DNS Diagnostics & Lookup
# ------------------------------------------------------------------------------
@router.get("/dns")
@router.post("/dns")
async def execute_dns_lookup(request: Request):
    """Performs DNS resolution (A, AAAA, CNAME, reverse lookup) on target hostname."""
    body = {}
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}
    
    domain = body.get("domain") or request.query_params.get("domain") or ""
    domain = domain.strip().replace("http://", "").replace("https://", "").split("/")[0].split(":")[0]

    if not domain:
        return JSONResponse({"success": False, "error": "Dominio o IP target obbligatorio."}, status_code=400)

    def _resolve_dns(target: str) -> Dict[str, Any]:
        records = []
        t0 = time.perf_counter()

        # 1. Resolve IPv4 (A records)
        try:
            _, _, ipv4_list = socket.gethostbyname_ex(target)
            for ip in ipv4_list:
                records.append({
                    "type": "A",
                    "host": target,
                    "value": ip,
                    "status": "resolved"
                })
        except Exception as e:
            log.debug("A record lookup failed for %s: %s", target, e)

        # 2. Resolve IPv6 & CNAME via getaddrinfo
        try:
            addr_info = socket.getaddrinfo(target, None, proto=socket.IPPROTO_TCP)
            seen_ips = set()
            for item in addr_info:
                family, socktype, proto, canonname, sockaddr = item
                ip = sockaddr[0]
                if ip not in seen_ips:
                    seen_ips.add(ip)
                    rec_type = "AAAA" if family == socket.AF_INET6 else "A"
                    if not any(r["value"] == ip for r in records):
                        records.append({
                            "type": rec_type,
                            "host": target,
                            "value": ip,
                            "status": "resolved"
                        })
                    if canonname and canonname != target and not any(r["type"] == "CNAME" for r in records):
                        records.append({
                            "type": "CNAME",
                            "host": target,
                            "value": canonname,
                            "status": "resolved"
                        })
        except Exception:
            pass

        # 3. Reverse DNS Lookup if target is IP address
        reverse_name = None
        try:
            reverse_name, _, _ = socket.gethostbyaddr(target)
            records.append({
                "type": "PTR (Reverse DNS)",
                "host": target,
                "value": reverse_name,
                "status": "resolved"
            })
        except Exception:
            pass

        latency = round((time.perf_counter() - t0) * 1000, 1)

        return {
            "success": len(records) > 0,
            "domain": target,
            "records_count": len(records),
            "latency_ms": latency,
            "canonical_name": reverse_name or target,
            "records": records
        }

    res = await asyncio.to_thread(_resolve_dns, domain)
    return JSONResponse(res)


# ------------------------------------------------------------------------------
# 5. Ping & Latency Diagnostics
# ------------------------------------------------------------------------------
@router.get("/ping")
@router.post("/ping")
async def execute_ping_test(request: Request):
    """Executes multi-sample TCP latency ping test against target host and port."""
    body = {}
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}

    host = body.get("host") or request.query_params.get("host") or "1.1.1.1"
    host = host.strip().replace("http://", "").replace("https://", "").split("/")[0]
    
    port = int(body.get("port") or request.query_params.get("port") or 80)
    count = max(1, min(int(body.get("count") or request.query_params.get("count") or 4), 20))

    def _ping_samples(target_host: str, target_port: int, n: int) -> Dict[str, Any]:
        samples = []
        transmitted = n
        received = 0

        # Resolve IP first
        resolved_ip = target_host
        try:
            resolved_ip = socket.gethostbyname(target_host)
        except Exception:
            pass

        for seq in range(1, n + 1):
            t0 = time.perf_counter()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.5)
            try:
                sock.connect((resolved_ip, target_port))
                sock.close()
                sample_ms = round((time.perf_counter() - t0) * 1000, 2)
                received += 1
                samples.append({"seq": seq, "latency_ms": sample_ms, "status": "success", "ip": resolved_ip})
            except Exception as e:
                samples.append({"seq": seq, "latency_ms": None, "status": "timeout", "error": str(e)})
            time.sleep(0.08)

        latencies = [s["latency_ms"] for s in samples if s["latency_ms"] is not None]
        packet_loss = round(((transmitted - received) / transmitted) * 100, 1)

        return {
            "success": received > 0,
            "host": target_host,
            "ip": resolved_ip,
            "port": target_port,
            "transmitted": transmitted,
            "received": received,
            "loss_percentage": packet_loss,
            "min_ms": min(latencies) if latencies else None,
            "avg_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
            "max_ms": max(latencies) if latencies else None,
            "samples": samples
        }

    result = await asyncio.to_thread(_ping_samples, host, port, count)
    return JSONResponse(result)


# ------------------------------------------------------------------------------
# 6. Fetch & Parse Web Page (title, readable text, main links)
# ------------------------------------------------------------------------------
MAX_PAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
DEFAULT_FETCH_TIMEOUT = 10  # secondi


def _extract_title(html: str) -> str:
    """Estrae il contenuto del tag <title> dal HTML."""
    m = re.search(r'<title[^>]*>([\s\S]*?)</title>', html, re.IGNORECASE)
    if m:
        return re.sub(r'\s+', ' ', m.group(1)).strip()
    return ""


def _extract_readable_text(html: str) -> str:
    """Rimuove script, style e tag HTML per ottenere testo leggibile."""
    text = re.sub(r'<script[\s\S]*?</script>', '', html, flags=re.IGNORECASE)
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<nav[\s\S]*?</nav>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<footer[\s\S]*?</footer>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<header[\s\S]*?</header>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _extract_main_links(html: str, base_url: str) -> List[Dict[str, str]]:
    """Estrae i link principali (anchor tag con href) dal HTML."""
    links = []
    seen = set()
    for m in re.finditer(r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>', html, re.IGNORECASE):
        href = m.group(1).strip()
        anchor_text = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        # Salta link non navigabili
        if href.startswith(('javascript:', 'mailto:', '#', 'tel:')):
            continue
        # Risolvi URL relativi
        if href.startswith('/') and not href.startswith('//'):
            parsed = urllib.parse.urlparse(base_url)
            full_url = f"{parsed.scheme}://{parsed.netloc}{href}"
        elif href.startswith('//'):
            parsed = urllib.parse.urlparse(base_url)
            full_url = f"{parsed.scheme}:{href}"
        elif not href.startswith(('http://', 'https://')):
            full_url = urllib.parse.urljoin(base_url, href)
        else:
            full_url = href
        if full_url in seen:
            continue
        seen.add(full_url)
        links.append({"url": full_url, "text": anchor_text[:200]})
    return links[:50]  # limite a 50 link principali


@router.post("/fetch_page")
async def fetch_page(request: Request):
    """Scarica una pagina web ed estrae titolo, testo leggibile e link principali."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"success": False, "error": "Payload JSON non valido."}, status_code=400)

    url = str(payload.get("url") or "").strip()
    timeout = max(1, min(int(payload.get("timeout") or DEFAULT_FETCH_TIMEOUT), 60))

    if not url:
        return JSONResponse({"success": False, "error": "URL obbligatorio."}, status_code=400)

    # Normalizza URL: se manca lo schema, assume https
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    # Valida che sia un URL http/https
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return JSONResponse({"success": False, "error": "URL non valido: deve essere http:// o https:// con host."}, status_code=400)
    except Exception:
        return JSONResponse({"success": False, "error": "URL non valido."}, status_code=400)

    def _fetch_and_parse(target_url: str, req_timeout: int) -> Dict[str, Any]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        req = urllib.request.Request(target_url, headers=headers)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=req_timeout, context=ctx) as response:
            status_code = response.getcode()
            content_type = response.headers.get("Content-Type", "")
            raw_bytes = response.read(MAX_PAGE_SIZE_BYTES + 1)

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        size_bytes = len(raw_bytes)

        # Verifica limite dimensione
        if size_bytes > MAX_PAGE_SIZE_BYTES:
            return {
                "success": False,
                "error": f"Pagina troppo grande: {size_bytes} byte (limite {MAX_PAGE_SIZE_BYTES} byte).",
                "url": target_url,
                "status_code": status_code,
                "elapsed_ms": elapsed_ms
            }

        html = raw_bytes.decode("utf-8", errors="ignore")
        title = _extract_title(html)
        text = _extract_readable_text(html)
        links = _extract_main_links(html, target_url)

        return {
            "success": True,
            "url": target_url,
            "status_code": status_code,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "elapsed_ms": elapsed_ms,
            "title": title,
            "text": text[:50000],  # limite testo a 50KB
            "links_count": len(links),
            "links": links
        }

    try:
        result = await asyncio.to_thread(_fetch_and_parse, url, timeout)
    except urllib.error.HTTPError as http_err:
        return JSONResponse({
            "success": False,
            "error": f"Errore HTTP {http_err.code}: {http_err.reason}",
            "url": url,
            "status_code": http_err.code
        }, status_code=502)
    except Exception as exc:
        err_msg = str(exc)
        if "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
            return JSONResponse({
                "success": False,
                "error": f"Timeout dopo {timeout}s.",
                "url": url
            }, status_code=504)
        return JSONResponse({
            "success": False,
            "error": err_msg,
            "url": url
        }, status_code=502)

    if not result.get("success"):
        return JSONResponse(result, status_code=413 if "troppo grande" in result.get("error", "") else 200)
    return JSONResponse(result)


# ------------------------------------------------------------------------------
# 7. Research Note — salva una nota di ricerca in Markdown sotto data/ricerche/
# ------------------------------------------------------------------------------
import datetime
from pathlib import Path


@router.post("/research_note")
async def create_research_note(request: Request):
    """Legge una pagina web e salva una nota di ricerca in Markdown sotto data/ricerche/."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"success": False, "error": "Payload JSON non valido."}, status_code=400)

    url = str(payload.get("url") or "").strip()
    argomento = str(payload.get("argomento") or "").strip()
    timeout = max(1, min(int(payload.get("timeout") or DEFAULT_FETCH_TIMEOUT), 60))

    if not url:
        return JSONResponse({"success": False, "error": "URL obbligatorio."}, status_code=400)
    if not argomento:
        return JSONResponse({"success": False, "error": "Argomento obbligatorio."}, status_code=400)

    # Normalizza URL
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return JSONResponse({"success": False, "error": "URL non valido: deve essere http:// o https:// con host."}, status_code=400)
    except Exception:
        return JSONResponse({"success": False, "error": "URL non valido."}, status_code=400)

    def _fetch_for_note(target_url: str, req_timeout: int) -> Dict[str, Any]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        req = urllib.request.Request(target_url, headers=headers)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        with urllib.request.urlopen(req, timeout=req_timeout, context=ctx) as response:
            raw_bytes = response.read(MAX_PAGE_SIZE_BYTES + 1)

        if len(raw_bytes) > MAX_PAGE_SIZE_BYTES:
            raise ValueError(f"Pagina troppo grande: {len(raw_bytes)} byte.")

        html = raw_bytes.decode("utf-8", errors="ignore")
        title = _extract_title(html)
        text = _extract_readable_text(html)

        if not text.strip():
            raise ValueError("Nessun testo estratto dalla pagina.")

        return {"title": title, "text": text[:50000]}

    try:
        page_data = await asyncio.to_thread(_fetch_for_note, url, timeout)
    except urllib.error.HTTPError as http_err:
        return JSONResponse({
            "success": False,
            "error": f"Errore HTTP {http_err.code}: {http_err.reason}",
            "url": url
        }, status_code=502)
    except ValueError as ve:
        return JSONResponse({"success": False, "error": str(ve), "url": url}, status_code=422)
    except Exception as exc:
        err_msg = str(exc)
        if "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
            return JSONResponse({"success": False, "error": f"Timeout dopo {timeout}s.", "url": url}, status_code=504)
        return JSONResponse({"success": False, "error": err_msg, "url": url}, status_code=502)

    # Genera nome file basato su titolo e data
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d_%H%M%S")
    safe_title = re.sub(r'[^\w\s-]', '', page_data["title"] or "senza_titolo").strip().replace(" ", "_")[:60] or "senza_titolo"
    filename = f"{date_str}_{safe_title}.md"

    # Percorso di destinazione: data/ricerche/
    base_dir = Path("data") / "ricerche"
    base_dir.mkdir(parents=True, exist_ok=True)
    file_path = base_dir / filename

    # Costruisci la nota in Markdown
    md_lines = [
        f"# {page_data['title'] or 'Senza titolo'}",
        "",
        f"**URL:** {url}",
        f"**Data:** {now.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Argomento:** {argomento}",
        "",
        "---",
        "",
        "## Testo estratto",
        "",
        page_data["text"],
        ""
    ]
    content = "\n".join(md_lines)

    try:
        file_path.write_text(content, encoding="utf-8")
    except OSError as oe:
        return JSONResponse({"success": False, "error": f"Errore di scrittura: {oe}"}, status_code=500)

    # Percorso relativo per la risposta
    rel_path = str(file_path).replace("\\", "/")

    return JSONResponse({
        "success": True,
        "path": rel_path,
        "title": page_data["title"],
        "url": url,
        "argomento": argomento,
        "date": now.strftime("%Y-%m-%d %H:%M:%S")
    })


# ------------------------------------------------------------------------------
# Module Registration Hooks
# ------------------------------------------------------------------------------
def register_routes(app):
    """Called by ModuleLoader on startup to mount Network Lab API routes."""
    if app is None:
        try:
            from core.fastapi_app import app as _app
            app = _app
        except Exception:
            pass
    if app is None:
        log.warning("[NetworkLab] Cannot register routes: app is None")
        return
    app.include_router(router, prefix="/api/network")
    log.info("[NetworkLab] Registered /api/network routes on FastAPI app.")


def register_mcp(mcp_hub):
    """Called by ModuleLoader to register Network MCP Server with the AI Agent."""
    try:
        from .network_server import NetworkMCPServer
        mcp_hub.register_server(NetworkMCPServer())
        log.info("[NetworkLab] Registered NetworkMCPServer in MCP Hub.")
    except Exception as e:
        log.warning("[NetworkLab] Failed to register NetworkMCPServer: %s", e)
