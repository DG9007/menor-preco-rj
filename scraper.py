#!/usr/bin/env python3
"""
Menor Preço RJ — Scraper de Encartes v4
- Roda em loop de 30 em 30 minutos (ou intervalo configurável)
- Modo HTML exclusivo (APIs VTEX bloqueadas/removidas em todos os alvos)
- Gera índice de busca full-text para pesquisa genérica e específica
- Anti-bloqueio: delays aleatórios, retry com backoff, rotação de User-Agent

CORREÇÕES v4:
  - Carrefour: meucarrefour.com.br → mercado.carrefour.com.br/ofertas-da-semana
  - Mundial:   /ofertas-da-semana  → /encarte  (URL oficial confirmado)
  - Novo parser específico para o encarte do Mundial (JSON embutido na página)
  - Novo parser para o Carrefour Mercado (JSON-LD + regex de preço melhorado)
"""

import json
import re
import time
import random
import hashlib
import logging
import argparse
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# ─── Configuração ────────────────────────────────────────────────────────────

DATA_DIR            = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
OUTPUT              = DATA_DIR / "encartes.json"
INDEX_OUT           = DATA_DIR / "search_index.json"

INTERVAL_MINUTES    = 30
MAX_PRODUCTS_PER_SM = 200
REQUEST_TIMEOUT     = 25
MAX_RETRIES         = 3
BACKOFF_BASE        = 4

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scraper")

# ─── Supermercados ────────────────────────────────────────────────────────────
#
# CORREÇÕES v4:
#   - Carrefour:  meucarrefour.com.br (fora do ar) →
#                 mercado.carrefour.com.br/ofertas-da-semana
#   - Mundial:    /ofertas-da-semana (404) →
#                 supermercadosmundial.com.br/encarte  (URL oficial ativo)
#
SUPERMARKETS = [
    {
        "name":       "Guanabara",
        "color":      "#c8102e",
        "light":      "#fee2e2",
        "site":       "supermercadosguanabara.com.br",
        "offers_url": "https://www.supermercadosguanabara.com.br/encarte",
        "parser":     "html",
    },
    {
        "name":       "Prezunic",
        "color":      "#15803d",
        "light":      "#dcfce7",
        "site":       "prezunic.com.br",
        "offers_url": "https://www.prezunic.com.br/ofertas",
        "parser":     "html",
    },
    {
        # FIX v4: meucarrefour.com.br está fora do ar.
        # mercado.carrefour.com.br/ofertas-da-semana é a página ativa de ofertas.
        "name":       "Carrefour",
        "color":      "#0057a8",
        "light":      "#dbeafe",
        "site":       "mercado.carrefour.com.br",
        "offers_url": "https://mercado.carrefour.com.br/ofertas-da-semana",
        "parser":     "html_carrefour",
    },
    {
        "name":       "Assaí",
        "color":      "#e85d00",
        "light":      "#ffedd5",
        "site":       "assai.com.br",
        "offers_url": "https://www.assai.com.br/ofertas",
        "parser":     "html",
    },
    {
        "name":       "Atacadão",
        "color":      "#b91c1c",
        "light":      "#fecaca",
        "site":       "atacadao.com.br",
        "offers_url": "https://www.atacadao.com.br/ofertas-arrasadoras",
        "parser":     "html",
    },
    {
        # FIX v4: /ofertas-da-semana devolvia 404.
        # /encarte é a URL oficial e ativa do encarte digital do Mundial.
        "name":       "Mundial",
        "color":      "#1d4ed8",
        "light":      "#dbeafe",
        "site":       "supermercadosmundial.com.br",
        "offers_url": "https://www.supermercadosmundial.com.br/encarte",
        "parser":     "html_mundial",
    },
    {
        "name":       "Supermarket",
        "color":      "#7c3aed",
        "light":      "#ede9fe",
        "site":       "redesupermarket.com.br",
        "offers_url": "https://www.redesupermarket.com.br/ofertas",
        "parser":     "html",
    },
    {
        "name":       "Rede Economia",
        "color":      "#b45309",
        "light":      "#fef3c7",
        "site":       "redeeconomia.com.br",
        "offers_url": "https://www.redeeconomia.com.br/encarte/",
        "parser":     "html",
    },
]

# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def random_headers(accept_json: bool = False, referer: str = "https://www.google.com.br/") -> dict:
    h = {
        "User-Agent":      random.choice(USER_AGENTS),
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
        "Cache-Control":   "no-cache",
        "Referer":         referer,
    }
    if accept_json:
        h["Accept"] = "application/json, text/plain, */*"
    else:
        h["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    return h


def fetch(url: str, as_json: bool = False, timeout: int = REQUEST_TIMEOUT,
          referer: str = "https://www.google.com.br/") -> Optional[Union[str, dict]]:
    """Faz requisição com retry e backoff exponencial."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = Request(url, headers=random_headers(accept_json=as_json, referer=referer))
            with urlopen(req, timeout=timeout) as r:
                raw = r.read()
                enc = r.headers.get_content_charset("utf-8")
                text = raw.decode(enc, errors="replace")
                if as_json:
                    return json.loads(text)
                return text
        except HTTPError as e:
            log.warning(f"  HTTP {e.code} em {url} (tentativa {attempt}/{MAX_RETRIES})")
            if e.code in (403, 429, 503):
                wait = BACKOFF_BASE ** attempt + random.uniform(1, 3)
                log.info(f"  Aguardando {wait:.1f}s antes de tentar novamente…")
                time.sleep(wait)
            else:
                break  # 404 etc. — não adianta tentar
        except (URLError, json.JSONDecodeError) as e:
            log.warning(f"  Erro {type(e).__name__} em {url} (tentativa {attempt}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_BASE * attempt)
        except Exception as e:
            log.warning(f"  Erro inesperado: {e}")
            break
    return None

# ─── Parsers ──────────────────────────────────────────────────────────────────

PRICE_RE    = re.compile(r"R?\$?\s*(\d{1,4}[.,]\d{2})(?!\d)")
NAME_BEFORE = re.compile(r"([A-Za-zÀ-ÿ][^\n\r<]{4,100}?)\s*R?\$\s*\d{1,4}[.,]\d{2}")


def _parse_price(raw: str) -> Optional[float]:
    """Converte '12,90' ou '12.90' → float."""
    try:
        clean = re.sub(r"[^\d,.]", "", str(raw))
        if "," in clean and "." in clean:
            clean = clean.replace(".", "").replace(",", ".")
        elif "," in clean:
            clean = clean.replace(",", ".")
        val = float(clean)
        return round(val, 2) if 0.5 < val < 10_000 else None
    except (ValueError, TypeError):
        return None


def parse_jsonld(html: str, base_url: str) -> list:
    """Extrai produtos de blocos JSON-LD (schema.org/Product ou Offer)."""
    offers = []
    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.S | re.I
    )
    for raw in blocks:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        items = data if isinstance(data, list) else [data]
        i = 0
        while i < len(items):
            item = items[i]
            i += 1
            if item.get("@type") not in ("Product", "Offer"):
                for node in item.get("@graph", []):
                    if node.get("@type") == "Product":
                        items.append(node)
                continue

            name = item.get("name", "").strip()
            url  = item.get("url", base_url)

            price_src = item if item.get("@type") == "Offer" else item.get("offers", {})
            if isinstance(price_src, list):
                price_src = price_src[0] if price_src else {}

            price = _parse_price(price_src.get("price", ""))
            if name and price:
                brand_raw  = item.get("brand", {})
                brand_name = brand_raw.get("name", "") if isinstance(brand_raw, dict) else ""
                offers.append({
                    "product":   name[:120],
                    "price":     price,
                    "unit":      "un",
                    "url":       url,
                    "promotion": True,
                    "brand":     brand_name,
                })
    return offers


def parse_html_fallback(html: str, base_url: str) -> list:
    """Extrai produto+preço do texto puro da página (genérico)."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = re.sub(r"\s+", " ", text)

    offers = []
    for m in NAME_BEFORE.finditer(text):
        name    = m.group(1).strip()
        price_m = PRICE_RE.search(m.group(0))
        if price_m and len(name) > 4:
            price = _parse_price(price_m.group(1))
            if price:
                offers.append({
                    "product":   name[:120],
                    "price":     price,
                    "unit":      "un",
                    "url":       base_url,
                    "promotion": True,
                    "brand":     "",
                })
    return offers


# ── Parser específico: Carrefour Mercado ─────────────────────────────────────
#
# mercado.carrefour.com.br renderiza produtos via React/Next.js.
# A página inclui um bloco __NEXT_DATA__ com toda a listagem de produtos.
# Fallback: JSON-LD → regex HTML genérica.
#
def parse_carrefour(html: str, base_url: str) -> list:
    offers = []

    # Tentativa 1: __NEXT_DATA__ (Next.js)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if m:
        try:
            data = json.loads(m.group(1))
            # Navegar pela estrutura: props → pageProps → ... → products
            products_raw = _deep_find(data, "products") or _deep_find(data, "items") or []
            for p in products_raw:
                name  = p.get("name") or p.get("productName") or p.get("title") or ""
                price = _parse_price(
                    p.get("price") or p.get("sellingPrice") or
                    p.get("offers", {}).get("lowPrice") or ""
                )
                url = p.get("linkText") or p.get("slug") or ""
                if url and not url.startswith("http"):
                    url = f"https://mercado.carrefour.com.br/{url.lstrip('/')}"
                brand = p.get("brand") or ""
                if name and price:
                    offers.append({
                        "product":   name[:120],
                        "price":     price,
                        "unit":      "un",
                        "url":       url or base_url,
                        "promotion": True,
                        "brand":     brand,
                    })
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    if offers:
        log.info(f"    [Carrefour] {len(offers)} produtos via __NEXT_DATA__")
        return offers

    # Tentativa 2: JSON-LD
    offers = parse_jsonld(html, base_url)
    if offers:
        log.info(f"    [Carrefour] {len(offers)} produtos via JSON-LD")
        return offers

    # Tentativa 3: regex HTML genérica
    offers = parse_html_fallback(html, base_url)
    log.info(f"    [Carrefour] {len(offers)} produtos via regex HTML")
    return offers


def _deep_find(obj, key: str, _depth: int = 0):
    """Busca recursiva por uma chave dentro de um JSON aninhado."""
    if _depth > 12:
        return None
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], list) and len(obj[key]) > 0:
            return obj[key]
        for v in obj.values():
            result = _deep_find(v, key, _depth + 1)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj[:5]:  # Limita para não explodir em listas enormes
            result = _deep_find(item, key, _depth + 1)
            if result:
                return result
    return None


# ── Parser específico: Mundial ───────────────────────────────────────────────
#
# supermercadosmundial.com.br/encarte é um SPA (React).
# A página embute os produtos do encarte em um objeto JS window.__DATA__
# ou em blocos JSON-LD. Também tentamos capturar os preços diretamente
# do texto HTML renderizado (SSR parcial).
#
# Estratégia:
#   1. Tenta extrair JSON do bloco window.__DATA__ / __STATE__ / __STORE__
#   2. JSON-LD (schema.org)
#   3. Regex: padrão "R$ X,XX" + nome próximo (SSR ou hydration parcial)
#   4. Fallback: link para encarte + alerta de página JS-only
#
def parse_mundial(html: str, base_url: str) -> list:
    offers = []

    # Tentativa 1: objeto JS embutido (vários nomes possíveis)
    js_patterns = [
        r'window\.__(?:DATA|STATE|STORE|INITIAL_STATE)__\s*=\s*(\{.*?\});',
        r'__NUXT__\s*=\s*(\{.*?\})',
        r'__NEXT_DATA__[^>]*>(.*?)</script>',
    ]
    for pat in js_patterns:
        m = re.search(pat, html, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                products_raw = (
                    _deep_find(data, "products") or
                    _deep_find(data, "offers")   or
                    _deep_find(data, "items")    or []
                )
                for p in products_raw:
                    name  = (p.get("name") or p.get("title") or
                             p.get("descricao") or p.get("produto") or "")
                    price = _parse_price(
                        p.get("price") or p.get("preco") or
                        p.get("valor") or p.get("precoPromocional") or ""
                    )
                    if name and price:
                        offers.append({
                            "product":   name[:120],
                            "price":     price,
                            "unit":      "un",
                            "url":       base_url,
                            "promotion": True,
                            "brand":     p.get("brand") or p.get("marca") or "",
                        })
            except (json.JSONDecodeError, TypeError):
                pass
        if offers:
            log.info(f"    [Mundial] {len(offers)} produtos via JS object")
            return offers

    # Tentativa 2: JSON-LD
    offers = parse_jsonld(html, base_url)
    if offers:
        log.info(f"    [Mundial] {len(offers)} produtos via JSON-LD")
        return offers

    # Tentativa 3: regex HTML (SSR parcial)
    # O encarte do Mundial usa padrões como:
    #   <div class="product-name">Arroz Tio João 5kg</div>
    #   <span class="price">R$ 18,90</span>
    product_blocks = re.findall(
        r'(?:product-name|nome-produto|title)["\'][^>]*>([^<]{4,100})<',
        html, re.I
    )
    price_blocks = re.findall(
        r'(?:price|preco|valor)["\'][^>]*>\s*(?:R\$\s*)?(\d{1,4}[.,]\d{2})',
        html, re.I
    )
    if product_blocks and price_blocks:
        for name, raw_price in zip(product_blocks, price_blocks):
            price = _parse_price(raw_price)
            if price and len(name.strip()) > 3:
                offers.append({
                    "product":   name.strip()[:120],
                    "price":     price,
                    "unit":      "un",
                    "url":       base_url,
                    "promotion": True,
                    "brand":     "",
                })
        if offers:
            log.info(f"    [Mundial] {len(offers)} produtos via regex de classes CSS")
            return offers

    # Tentativa 4: regex genérica
    offers = parse_html_fallback(html, base_url)
    if offers:
        log.info(f"    [Mundial] {len(offers)} produtos via regex HTML genérica")
    return offers


# ─── Busca e indexação ────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def tokenize(text: str) -> list:
    return [t for t in re.split(r"[^a-z0-9]+", normalize(text)) if len(t) >= 2]


def build_search_index(sm_data: dict) -> dict:
    index: dict        = {}
    products_flat: list = []

    for sm_name, sm in sm_data.items():
        for offer in sm.get("offers", []):
            pid = len(products_flat)
            products_flat.append({
                "id":    pid,
                "sm":    sm_name,
                "color": sm.get("color", "#333"),
                "light": sm.get("light", "#eee"),
                **offer,
            })
            full_text = f"{offer.get('product', '')} {offer.get('brand', '')}"
            for token in tokenize(full_text):
                index.setdefault(token, []).append(pid)

    for token in index:
        index[token] = list(dict.fromkeys(index[token]))

    return {
        "products":  products_flat,
        "index_map": {str(p["id"]): p for p in products_flat},
        "index":     index,
    }


def search(query: str, index_data: dict, max_results: int = 50) -> list:
    tokens = tokenize(query)
    if not tokens:
        return []

    products = index_data["index_map"]
    idx      = index_data["index"]
    scores: dict = {}

    for token in tokens:
        for pid in idx.get(token, []):
            scores[pid] = scores.get(pid, 0) + 1

    n       = len(tokens)
    matched = [products[str(pid)] for pid, score in scores.items() if score >= n]
    matched.sort(key=lambda p: p.get("price", 9999))
    return matched[:max_results]


# ─── Core scraping ───────────────────────────────────────────────────────────

def scrape_supermarket(sm: dict) -> list:
    name   = sm["name"]
    base   = sm["offers_url"]
    parser = sm.get("parser", "html")
    offers: list = []

    log.info(f"  [{name}] Buscando HTML: {base}")

    # Carrefour: precisamos de referer do próprio site para evitar bloqueio
    if parser == "html_carrefour":
        html = fetch(base, referer="https://mercado.carrefour.com.br/")
    elif parser == "html_mundial":
        html = fetch(base, referer="https://www.supermercadosmundial.com.br/")
    else:
        html = fetch(base)

    if html:
        if parser == "html_carrefour":
            offers = parse_carrefour(html, base)
        elif parser == "html_mundial":
            offers = parse_mundial(html, base)
        else:
            # Pipeline genérico: JSON-LD → regex
            offers = parse_jsonld(html, base)
            if offers:
                log.info(f"  [{name}] {len(offers)} produtos via JSON-LD")
            else:
                offers = parse_html_fallback(html, base)
                log.info(f"  [{name}] {len(offers)} produtos via regex HTML")
    else:
        log.warning(f"  [{name}] Falha ao obter HTML de {base}")

    # Garantia mínima: pelo menos um item de link para o site
    if not offers:
        offers = [{
            "product":   f"Ver encarte {name} no site",
            "price":     0,
            "unit":      "",
            "url":       base,
            "promotion": False,
            "brand":     "",
        }]

    # Deduplicação por nome normalizado
    seen: set    = set()
    unique: list = []
    for o in offers:
        key = normalize(o["product"])[:60]
        if key not in seen:
            seen.add(key)
            unique.append(o)

    return unique[:MAX_PRODUCTS_PER_SM]


def content_hash(offers: list) -> str:
    s = json.dumps(offers, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(s.encode()).hexdigest()[:10]


def load_existing() -> dict:
    if OUTPUT.exists():
        try:
            return json.loads(OUTPUT.read_text("utf-8"))
        except Exception:
            pass
    return {"updated_at": "", "supermarkets": {}}


def save_all(data: dict, index_data: dict):
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    INDEX_OUT.write_text(json.dumps(index_data, ensure_ascii=False), "utf-8")
    total = sum(len(sm.get("offers", [])) for sm in data["supermarkets"].values())
    log.info(f"✅ Salvo: {total} produtos em {OUTPUT}")
    log.info(f"🔍 Índice de busca: {INDEX_OUT}")


# ─── Loop principal ───────────────────────────────────────────────────────────

def run_cycle():
    log.info(f"{'='*60}")
    log.info(f"🔍 Ciclo iniciado — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    log.info(f"{'='*60}")

    existing = load_existing()
    sm_data  = existing.get("supermarkets", {})
    changed  = False

    for sm in SUPERMARKETS:
        name = sm["name"]
        log.info(f"\n→ Processando: {name}")

        offers   = scrape_supermarket(sm)
        real     = [o for o in offers if o["price"] > 0]
        new_hash = content_hash(offers)
        old_hash = sm_data.get(name, {}).get("hash", "")

        log.info(f"  {'✓' if real else '–'} {len(real)} produto(s) com preço")

        if new_hash != old_hash:
            sm_data[name] = {
                "name":       name,
                "color":      sm["color"],
                "light":      sm["light"],
                "site":       sm["site"],
                "offers_url": sm["offers_url"],
                "hash":       new_hash,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "offers":     offers,
            }
            changed = True

        delay = random.uniform(8, 20)
        log.info(f"  ⏳ Aguardando {delay:.1f}s antes do próximo supermercado…")
        time.sleep(delay)

    if changed or not existing.get("updated_at"):
        existing["updated_at"]   = datetime.now(timezone.utc).isoformat()
        existing["supermarkets"] = sm_data
        index_data = build_search_index(sm_data)
        save_all(existing, index_data)
    else:
        log.info("\n⏩ Nenhuma mudança detectada, JSON não atualizado.")

    log.info(f"\n✅ Ciclo concluído.")
    return changed


def main():
    parser = argparse.ArgumentParser(description="Scraper de encartes — Menor Preço RJ")
    parser.add_argument("--interval", type=int, default=INTERVAL_MINUTES,
                        help=f"Intervalo em minutos entre ciclos (padrão: {INTERVAL_MINUTES})")
    parser.add_argument("--once", action="store_true",
                        help="Roda apenas uma vez e sai (útil para GitHub Actions / cron)")
    parser.add_argument("--search", type=str, default=None,
                        help="Testa busca no índice existente e imprime resultados")
    args = parser.parse_args()

    if args.search:
        if not INDEX_OUT.exists():
            print("❌ Índice não encontrado. Rode o scraper primeiro.")
            return
        index_data = json.loads(INDEX_OUT.read_text("utf-8"))
        results    = search(args.search, index_data)
        if not results:
            print(f'Nenhum resultado para "{args.search}"')
        else:
            print(f'\n🔎 {len(results)} resultado(s) para "{args.search}":\n')
            for r in results[:20]:
                print(f"  [{r['sm']}] {r['product']} — R$ {r['price']:.2f} ({r['unit']})")
                print(f"          {r['url']}")
        return

    if args.once:
        run_cycle()
        return

    log.info(f"🕐 Modo loop: ciclo a cada {args.interval} minuto(s). Ctrl+C para parar.")
    while True:
        run_cycle()
        log.info(f"\n⏰ Próximo ciclo em {args.interval} minutos…\n")
        time.sleep(args.interval * 60)


if __name__ == "__main__":
    main()
