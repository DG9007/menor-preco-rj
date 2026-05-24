#!/usr/bin/env python3
"""
Menor Preço RJ — Scraper de Encartes v2
- Roda em loop de 30 em 30 minutos (ou intervalo configurável)
- Usa APIs JSON dos supermercados quando disponível
- Gera índice de busca full-text para pesquisa genérica e específica
- Anti-bloqueio: delays aleatórios, retry com backoff, rotação de User-Agent
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
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# ─── Configuração ────────────────────────────────────────────────────────────

DATA_DIR   = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
OUTPUT     = DATA_DIR / "encartes.json"
INDEX_OUT  = DATA_DIR / "search_index.json"

INTERVAL_MINUTES = 30          # intervalo entre ciclos completos
MAX_PRODUCTS_PER_SM = 200      # máximo de produtos por supermercado
REQUEST_TIMEOUT    = 25        # segundos por requisição
MAX_RETRIES        = 3         # tentativas por URL
BACKOFF_BASE       = 4         # segundos base para retry (dobra a cada falha)

# Pool de User-Agents para rotação
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

# ─── Definição dos supermercados e suas APIs ──────────────────────────────────
#
# Cada entrada pode ter:
#   "api_url"    → endpoint JSON (preferido)
#   "api_pages"  → lista de URLs paginadas para varrer
#   "offers_url" → fallback HTML
#   "parser"     → nome do parser específico (para APIs proprietárias)
#
SUPERMARKETS = [
    {
        "name":       "Guanabara",
        "color":      "#c8102e",
        "light":      "#fee2e2",
        "site":       "supermercadosguanabara.com.br",
        "offers_url": "https://www.supermercadosguanabara.com.br/",
        # API de produtos em promoção (paginada)
        "api_pages": [
            f"https://www.supermercadosguanabara.com.br/api/catalog_system/pub/products/search?O=OrderByPriceDESC&_from={i}&_to={i+49}&fq=specificationFilter_40:Oferta"
            for i in range(0, 200, 50)
        ],
        "parser": "vtex",
    },
    {
        "name":       "Prezunic",
        "color":      "#15803d",
        "light":      "#dcfce7",
        "site":       "prezunic.com.br",
        "offers_url": "https://www.prezunic.com.br/encartes",
        "api_pages": [
            f"https://www.prezunic.com.br/api/catalog_system/pub/products/search?O=OrderByPriceDESC&_from={i}&_to={i+49}&fq=specificationFilter_193:Ofertas"
            for i in range(0, 200, 50)
        ],
        "parser": "vtex",
    },
    {
        "name":       "Carrefour",
        "color":      "#0057a8",
        "light":      "#dbeafe",
        "site":       "carrefour.com.br",
        "offers_url": "https://www.carrefour.com.br/ofertas/supermercado",
        # Carrefour usa API GraphQL — usamos o endpoint REST público
        "api_pages": [
            f"https://mercado.carrefour.com.br/api/catalog_system/pub/products/search?O=OrderByPriceDESC&_from={i}&_to={i+49}&fq=specificationFilter_62:Ofertas"
            for i in range(0, 200, 50)
        ],
        "parser": "vtex",
    },
    {
        "name":       "Assaí",
        "color":      "#e85d00",
        "light":      "#ffedd5",
        "site":       "assai.com.br",
        "offers_url": "https://www.assai.com.br/ofertas",
        "api_pages": [
            f"https://www.assai.com.br/api/catalog_system/pub/products/search?O=OrderByPriceDESC&_from={i}&_to={i+49}&fq=specificationFilter_1:Ofertas"
            for i in range(0, 200, 50)
        ],
        "parser": "vtex",
    },
    {
        "name":       "Atacadão",
        "color":      "#b91c1c",
        "light":      "#fecaca",
        "site":       "atacadao.com.br",
        "offers_url": "https://www.atacadao.com.br/folheto-de-ofertas",
        "api_pages": [
            f"https://www.atacadao.com.br/api/catalog_system/pub/products/search?O=OrderByPriceDESC&_from={i}&_to={i+49}"
            for i in range(0, 200, 50)
        ],
        "parser": "vtex",
    },
    {
        "name":       "Mundial",
        "color":      "#1d4ed8",
        "light":      "#dbeafe",
        "site":       "supermercadosmundial.com.br",
        "offers_url": "https://www.supermercadosmundial.com.br/ofertas-da-semana",
        "api_pages": [
            f"https://www.supermercadosmundial.com.br/api/catalog_system/pub/products/search?O=OrderByPriceDESC&_from={i}&_to={i+49}&fq=specificationFilter_1:Promo%C3%A7%C3%B5es"
            for i in range(0, 150, 50)
        ],
        "parser": "vtex",
    },
    {
        "name":       "Supermarket",
        "color":      "#7c3aed",
        "light":      "#ede9fe",
        "site":       "supermarket.com.br",
        "offers_url": "https://www.supermarket.com.br/ofertas",
        "api_pages": [
            f"https://www.supermarket.com.br/api/catalog_system/pub/products/search?O=OrderByPriceDESC&_from={i}&_to={i+49}&fq=specificationFilter_1:Ofertas"
            for i in range(0, 150, 50)
        ],
        "parser": "vtex",
    },
    {
        "name":       "Rede Economia",
        "color":      "#b45309",
        "light":      "#fef3c7",
        "site":       "redeeconomia.com.br",
        "offers_url": "https://www.redeeconomia.com.br/encarte",
        # Fallback HTML (site menor, sem API conhecida)
        "parser": "html",
    },
]

# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def random_headers(accept_json: bool = False) -> dict:
    h = {
        "User-Agent":      random.choice(USER_AGENTS),
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
        "Cache-Control":   "no-cache",
    }
    if accept_json:
        h["Accept"] = "application/json, text/plain, */*"
    else:
        h["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    return h


def fetch(url: str, as_json: bool = False, timeout: int = REQUEST_TIMEOUT) -> str | dict | None:
    """Faz requisição com retry e backoff exponencial."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = Request(url, headers=random_headers(accept_json=as_json))
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


def _parse_price(raw: str) -> float | None:
    """Converte '12,90' ou '12.90' → float."""
    try:
        # Remove tudo exceto dígitos, vírgula e ponto
        clean = re.sub(r"[^\d,.]", "", str(raw))
        # Formato brasileiro: último separador é vírgula → decimal
        if "," in clean and "." in clean:
            clean = clean.replace(".", "").replace(",", ".")
        elif "," in clean:
            clean = clean.replace(",", ".")
        val = float(clean)
        return round(val, 2) if 0.5 < val < 10_000 else None
    except (ValueError, TypeError):
        return None


def parse_vtex(pages_data: list[list], base_url: str) -> list[dict]:
    """
    Parser para lojas VTEX (Guanabara, Prezunic, Carrefour, Assaí, etc.)
    Formato: lista de produtos com 'productName', 'items[].sellers[].commertialOffer'
    """
    offers = []
    for products in pages_data:
        if not isinstance(products, list):
            continue
        for p in products:
            try:
                name = p.get("productName", "").strip()
                brand = p.get("brand", "").strip()
                link  = p.get("link", base_url)

                # Pega o menor preço entre os itens/sellers
                best_price = None
                best_unit  = "un"
                for item in p.get("items", []):
                    unit_m = item.get("unitMultiplier", 1)
                    meas   = item.get("measurementUnit", "un")
                    unit_label = f"{unit_m}{meas}" if unit_m != 1 else meas

                    for seller in item.get("sellers", []):
                        offer = seller.get("commertialOffer", {})
                        price = offer.get("Price") or offer.get("ListPrice")
                        if price:
                            price = _parse_price(str(price))
                            if price and (best_price is None or price < best_price):
                                best_price = price
                                best_unit  = unit_label

                if name and best_price:
                    full_name = f"{name} {brand}".strip() if brand and brand.lower() not in name.lower() else name
                    offers.append({
                        "product":   full_name[:120],
                        "price":     best_price,
                        "unit":      best_unit,
                        "url":       link,
                        "promotion": True,
                        "brand":     brand,
                    })
            except Exception:
                continue
    return offers


def parse_jsonld(html: str, base_url: str) -> list[dict]:
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

        # Pode ser um objeto ou lista
        items = data if isinstance(data, list) else [data]
        for item in items:
            # Suporta @type Product, ItemList, BreadcrumbList...
            if item.get("@type") not in ("Product", "Offer"):
                # Tenta extrair de @graph
                for node in item.get("@graph", []):
                    if node.get("@type") == "Product":
                        items.append(node)
                continue

            name = item.get("name", "").strip()
            url  = item.get("url", base_url)

            # Preço pode estar em "offers" aninhado
            price_src = item if item.get("@type") == "Offer" else item.get("offers", {})
            if isinstance(price_src, list):
                price_src = price_src[0] if price_src else {}

            price = _parse_price(price_src.get("price", ""))
            if name and price:
                offers.append({
                    "product":   name[:120],
                    "price":     price,
                    "unit":      "un",
                    "url":       url,
                    "promotion": True,
                    "brand":     item.get("brand", {}).get("name", "") if isinstance(item.get("brand"), dict) else "",
                })
    return offers


def parse_html_fallback(html: str, base_url: str) -> list[dict]:
    """Extrai produto+preço do texto puro da página."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = re.sub(r"\s+", " ", text)

    offers = []
    for m in NAME_BEFORE.finditer(text):
        name = m.group(1).strip()
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


# ─── Busca e indexação ────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    """Remove acentos e coloca em minúsculas para busca."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def tokenize(text: str) -> list[str]:
    """Divide em tokens alfanuméricos com pelo menos 2 chars."""
    return [t for t in re.split(r"[^a-z0-9]+", normalize(text)) if len(t) >= 2]


def build_search_index(sm_data: dict) -> dict:
    """
    Cria índice invertido: token → lista de {sm, product_idx}
    Permite busca genérica ("leite") e específica ("leite integral italac").
    """
    index: dict[str, list] = {}
    products_flat: list[dict] = []

    for sm_name, sm in sm_data.items():
        for offer in sm.get("offers", []):
            pid = len(products_flat)
            products_flat.append({
                "id":      pid,
                "sm":      sm_name,
                "color":   sm.get("color", "#333"),
                "light":   sm.get("light", "#eee"),
                **offer,
            })
            # Indexa nome + marca
            full_text = f"{offer.get('product','')} {offer.get('brand','')}"
            for token in tokenize(full_text):
                index.setdefault(token, []).append(pid)

    # Remove duplicatas dentro de cada lista de token
    for token in index:
        index[token] = list(dict.fromkeys(index[token]))

    return {"products": products_flat, "index": index}


def search(query: str, index_data: dict, max_results: int = 50) -> list[dict]:
    """
    Busca no índice. Retorna produtos ordenados por relevância (contagem de tokens encontrados)
    e depois por preço crescente.
    """
    tokens = tokenize(query)
    if not tokens:
        return []

    products = index_data["index_map"]
    idx      = index_data["index"]

    # Conta quantos tokens batem para cada produto
    scores: dict[int, int] = {}
    for token in tokens:
        for pid in idx.get(token, []):
            scores[pid] = scores.get(pid, 0) + 1

    # Filtra só quem tem TODOS os tokens (busca AND)
    n = len(tokens)
    matched = [products[pid] for pid, score in scores.items() if score >= n]

    # Ordena por preço crescente
    matched.sort(key=lambda p: p.get("price", 9999))
    return matched[:max_results]

# ─── Core scraping ───────────────────────────────────────────────────────────

def scrape_supermarket(sm: dict) -> list[dict]:
    name   = sm["name"]
    parser = sm.get("parser", "html")
    base   = sm["offers_url"]

    offers: list[dict] = []

    # ── API JSON (VTEX) ────────────────────────────────────────────────────
    if parser == "vtex" and "api_pages" in sm:
        pages_data = []
        for i, url in enumerate(sm["api_pages"]):
            log.info(f"  [{name}] API página {i+1}/{len(sm['api_pages'])}: {url}")
            data = fetch(url, as_json=True)
            if data:
                pages_data.append(data)
            # Delay anti-bloqueio entre páginas da mesma loja
            time.sleep(random.uniform(1.5, 4.0))

        if pages_data:
            offers = parse_vtex(pages_data, base)
            log.info(f"  [{name}] {len(offers)} produtos via API VTEX")

    # ── Fallback HTML ──────────────────────────────────────────────────────
    if not offers:
        log.info(f"  [{name}] Tentando HTML: {base}")
        html = fetch(base)
        if html:
            # Tenta JSON-LD primeiro (mais preciso)
            offers = parse_jsonld(html, base)
            if offers:
                log.info(f"  [{name}] {len(offers)} produtos via JSON-LD")
            else:
                offers = parse_html_fallback(html, base)
                log.info(f"  [{name}] {len(offers)} produtos via regex HTML")

    # ── Fallback final ─────────────────────────────────────────────────────
    if not offers:
        offers = [{
            "product":   f"Ver encarte {name} no site",
            "price":     0,
            "unit":      "",
            "url":       base,
            "promotion": False,
            "brand":     "",
        }]

    # ── Deduplicação ───────────────────────────────────────────────────────
    seen: set[str] = set()
    unique: list[dict] = []
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
    # Salva índice separado (pode ser grande)
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

        # Delay entre supermercados (anti-bloqueio)
        delay = random.uniform(8, 20)
        log.info(f"  ⏳ Aguardando {delay:.1f}s antes do próximo supermercado…")
        time.sleep(delay)

    if changed or not existing.get("updated_at"):
        existing["updated_at"]   = datetime.now(timezone.utc).isoformat()
        existing["supermarkets"] = sm_data

        # Reconstrói índice de busca
        raw_index = build_search_index(sm_data)
        # Prepara estrutura para a função search()
        index_ready = {
            "index_map": {p["id"]: p for p in raw_index["products"]},
            "index":     raw_index["index"],
        }
        save_all(existing, raw_index)
    else:
        log.info("\n⏩ Nenhuma mudança detectada, JSON não atualizado.")

    log.info(f"\n✅ Ciclo concluído.")
    return changed


def main():
    parser = argparse.ArgumentParser(description="Scraper de encartes — Menor Preço RJ")
    parser.add_argument(
        "--interval", type=int, default=INTERVAL_MINUTES,
        help=f"Intervalo em minutos entre ciclos (padrão: {INTERVAL_MINUTES})"
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Roda apenas uma vez e sai (útil para GitHub Actions)"
    )
    parser.add_argument(
        "--search", type=str, default=None,
        help="Testa busca no índice existente e imprime resultados"
    )
    args = parser.parse_args()

    # ── Modo busca (debug) ─────────────────────────────────────────────────
    if args.search:
        if not INDEX_OUT.exists():
            print("❌ Índice não encontrado. Rode o scraper primeiro.")
            return
        raw = json.loads(INDEX_OUT.read_text("utf-8"))
        index_ready = {
            "index_map": {p["id"]: p for p in raw["products"]},
            "index":     raw["index"],
        }
        results = search(args.search, index_ready)
        if not results:
            print(f'Nenhum resultado para "{args.search}"')
        else:
            print(f'\n🔎 {len(results)} resultado(s) para "{args.search}":\n')
            for r in results[:20]:
                print(f"  [{r['sm']}] {r['product']} — R$ {r['price']:.2f} ({r['unit']})")
                print(f"          {r['url']}")
        return

    # ── Modo loop ──────────────────────────────────────────────────────────
    if args.once:
        run_cycle()
        return

    log.info(f"🕐 Modo loop: ciclo a cada {args.interval} minuto(s). Ctrl+C para parar.")
    while True:
        run_cycle()
        next_run = datetime.now(timezone.utc)
        log.info(f"\n⏰ Próximo ciclo em {args.interval} minutos…\n")
        time.sleep(args.interval * 60)


if __name__ == "__main__":
    main()
