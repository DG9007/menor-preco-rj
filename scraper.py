#!/usr/bin/env python3
"""
Menor Preço RJ — Scraper v4 (Playwright)
Coleta ofertas de 4 supermercados do RJ a cada 30 minutos via GitHub Actions.

Supermercados:
  1. Guanabara   → home SSR  (urllib, sem JS necessário)
  2. Prezunic    → API VTEX  (urllib, JSON puro)
  3. Mundial     → home SSR  (urllib, sem JS necessário)
  4. Supermarket → Playwright (Cloudflare, precisa de browser real)
"""

import json, re, time, random, hashlib, gzip
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from html.parser import HTMLParser

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
OUTPUT   = DATA_DIR / "encartes.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept-Encoding": "identity",
    "Cache-Control": "no-cache",
}
HEADERS_JSON = {**HEADERS, "Accept": "application/json, */*"}
PRICE_RE = re.compile(r"R?\$?\s*(\d{1,4}[.,]\d{2})")

# ─── CONFIG ───────────────────────────────────────────────────────────────────

SUPERMARKETS = {
    "Guanabara": {
        "color": "#c8102e", "light": "#fee2e2",
        "site":  "supermercadosguanabara.com.br",
        "url":   "https://www.supermercadosguanabara.com.br/",
        "method": "ssr_guanabara",
    },
    "Prezunic": {
        "color": "#15803d", "light": "#dcfce7",
        "site":  "prezunic.com.br",
        "url":   "https://www.prezunic.com.br/api/catalog_system/pub/products/search"
                 "?fq=productClusterIds:1737&_from=0&_to=49&O=OrderByPriceASC",
        "method": "vtex_api",
    },
    "Mundial": {
        "color": "#1d4ed8", "light": "#dbeafe",
        "site":  "supermercadosmundial.com.br",
        "url":   "https://www.supermercadosmundial.com.br/",
        "method": "ssr_mundial",
    },
    "Supermarket": {
        "color": "#7c3aed", "light": "#ede9fe",
        "site":  "redesupermarket.com.br",
        "url":   "https://redesupermarket.com.br/ofertas/",
        "method": "playwright",
    },
}

# ─── FETCH SIMPLES ────────────────────────────────────────────────────────────

def fetch(url, headers=HEADERS, timeout=25):
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return raw.decode(r.headers.get_content_charset("utf-8") or "utf-8", errors="replace"), r.status
    except HTTPError as e:
        return None, e.code
    except URLError as e:
        print(f"    URLError: {e.reason}")
        return None, 0
    except Exception as e:
        print(f"    Erro: {e}")
        return None, 0

# ─── VTEX API (Prezunic) ──────────────────────────────────────────────────────

def scrape_vtex(sm_name, url, offers_url):
    html, status = fetch(url, HEADERS_JSON)
    if not html or status != 200:
        print(f"  ✗ VTEX HTTP {status}")
        return []
    try:
        data = json.loads(html)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    results = []
    for item in data:
        try:
            name = (item.get("productName") or "").strip()
            if not name:
                continue
            sellers = (item.get("items") or [{}])[0].get("sellers") or [{}]
            offer   = (sellers[0] if sellers else {}).get("commertialOffer") or {}
            price   = offer.get("Price") or 0
            if not price or price <= 0:
                continue
            link = item.get("link") or offers_url
            results.append({
                "product":   name[:80],
                "price":     round(float(price), 2),
                "unit":      "un",
                "url":       link,
                "promotion": True,
            })
        except Exception:
            continue
    print(f"  ✓ {len(results)} produtos via VTEX API")
    return results

# ─── PARSER SSR: GUANABARA ────────────────────────────────────────────────────
# A home do Guanabara renderiza no servidor blocos como:
#   <span class="product-name">Arroz Rei do Sul 5kg</span>
#   <span class="price">R$ 16,95</span>
# O parser coleta spans/divs com class hints de nome e preço em sequência.

class GuanabaraParser(HTMLParser):
    def __init__(self, base_url):
        super().__init__()
        self.products  = []
        self.base_url  = base_url
        self._buf      = []
        self._in_block = False
        self._cur_name = None
        self._skip     = 0
        self._SKIP_TAGS = {"script","style","head","noscript","svg"}
        self._NAME_CLS  = {"name","nome","product","produto","title","descri","item-name","shelf-item","product-name"}
        self._PRICE_CLS = {"price","preco","preço","valor","promocional","sale","offer","bestPrice","sellingPrice"}

    def _cls(self, attrs):
        return (dict(attrs).get("class") or "").lower()

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS: self._skip += 1; return
        if self._skip: return
        c = self._cls(attrs)
        if any(h in c for h in self._NAME_CLS):
            self._buf = []; self._in_block = "name"
        elif any(h in c for h in self._PRICE_CLS):
            self._buf = []; self._in_block = "price"

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS: self._skip = max(0,self._skip-1); return
        if self._skip or not self._in_block: return
        text = " ".join(self._buf).strip()
        self._buf = []
        if self._in_block == "name" and 3 < len(text) < 100:
            self._cur_name = text
        elif self._in_block == "price" and self._cur_name:
            m = PRICE_RE.search(text)
            if m:
                try:
                    p = float(m.group(1).replace(",","."))
                    if 0.5 < p < 3000:
                        self.products.append({
                            "product": self._cur_name[:80],
                            "price":   round(p, 2),
                            "unit":    "un",
                            "url":     self.base_url,
                            "promotion": True,
                        })
                        self._cur_name = None
                except ValueError: pass
        self._in_block = False

    def handle_data(self, data):
        if not self._skip and self._in_block:
            self._buf.append(data.strip())

# Fallback: varredura linear buscando padrão "NOME\nR$ PREÇO" no texto completo
def parse_ssr_linear(html, base_url):
    """
    Extrai todos os textos visíveis e faz uma varredura buscando padrão:
      texto_curto_sem_preço  →  texto_com_preço
    Usado como fallback quando o parser de classe falha.
    """
    # Remove tags, mantém texto
    clean = re.sub(r'<(script|style|noscript)[^>]*>.*?</\1>', '', html, flags=re.S|re.I)
    clean = re.sub(r'<[^>]+>', ' ', clean)
    lines = [l.strip() for l in clean.split('\n') if l.strip()]

    products = []
    seen = set()
    i = 0
    while i < len(lines):
        line = lines[i]
        pm = PRICE_RE.search(line)
        if pm:
            # Preço na mesma linha — tenta extrair nome
            before = line[:pm.start()].strip()
            if 3 < len(before) < 100 and not PRICE_RE.search(before):
                name = re.sub(r'\s+', ' ', before).strip()
                price = float(pm.group(1).replace(",","."))
                if 0.5 < price < 3000:
                    key = name.lower()[:40]
                    if key not in seen:
                        seen.add(key)
                        products.append({"product": name[:80], "price": round(price,2),
                                         "unit": "un", "url": base_url, "promotion": True})
            # Preço em linha separada — procura nome na linha anterior
            elif i > 0:
                prev = lines[i-1]
                if 3 < len(prev) < 100 and not PRICE_RE.search(prev):
                    name = re.sub(r'\s+', ' ', prev).strip()
                    price = float(pm.group(1).replace(",","."))
                    if 0.5 < price < 3000:
                        key = name.lower()[:40]
                        if key not in seen:
                            seen.add(key)
                            products.append({"product": name[:80], "price": round(price,2),
                                             "unit": "un", "url": base_url, "promotion": True})
        i += 1
    return products


def scrape_ssr(sm_name, url, ParserClass):
    html, status = fetch(url)
    if not html or status != 200:
        print(f"  ✗ SSR HTTP {status}")
        return []

    parser = ParserClass(url)
    try:
        parser.feed(html)
    except Exception:
        pass

    products = parser.products if hasattr(parser, "products") else []

    if len(products) < 5:
        print(f"  ~ Parser de classe: {len(products)} produtos — tentando varredura linear")
        products = parse_ssr_linear(html, url)

    print(f"  ✓ {len(products)} produtos via SSR")
    return products[:60]


# ─── PARSER SSR: MUNDIAL ─────────────────────────────────────────────────────
# Mundial renderiza produtos no servidor com estrutura:
#   <p class="offer-product-name">Leite Italac 1L</p>
#   <p class="offer-product-price">R$ 4,39 <span>cada</span></p>

class MundialParser(HTMLParser):
    def __init__(self, base_url):
        super().__init__()
        self.products  = []
        self.base_url  = base_url
        self._buf      = []
        self._in_block = False
        self._cur_name = None
        self._skip     = 0
        self._SKIP_TAGS = {"script","style","head","noscript","svg"}
        self._NAME_CLS  = {"product-name","offer-product-name","prod-name","item-name",
                           "name","nome","produto","description","desc","title"}
        self._PRICE_CLS = {"product-price","offer-product-price","price","preco","preço",
                           "best-price","selling-price","valor","oferta","promocional"}

    def _cls(self, attrs):
        return (dict(attrs).get("class") or "").lower()

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS: self._skip += 1; return
        if self._skip: return
        c = self._cls(attrs)
        if any(h in c for h in self._NAME_CLS):
            self._buf = []; self._in_block = "name"
        elif any(h in c for h in self._PRICE_CLS):
            self._buf = []; self._in_block = "price"

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS: self._skip = max(0,self._skip-1); return
        if self._skip or not self._in_block: return
        text = " ".join(self._buf).strip()
        self._buf = []
        if self._in_block == "name" and 3 < len(text) < 100:
            self._cur_name = text
        elif self._in_block == "price" and self._cur_name:
            m = PRICE_RE.search(text)
            if m:
                try:
                    p = float(m.group(1).replace(",","."))
                    if 0.5 < p < 3000:
                        self.products.append({
                            "product": self._cur_name[:80],
                            "price":   round(p, 2),
                            "unit":    "un",
                            "url":     self.base_url,
                            "promotion": True,
                        })
                        self._cur_name = None
                except ValueError: pass
        self._in_block = False

    def handle_data(self, data):
        if not self._skip and self._in_block:
            self._buf.append(data.strip())

# ─── PLAYWRIGHT (Supermarket) ─────────────────────────────────────────────────

def scrape_playwright(sm_name, url):
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        print("  ✗ Playwright não instalado")
        return []

    print(f"  → Abrindo browser Chromium: {url}")
    offers = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            ctx = browser.new_context(
                user_agent=UA,
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                viewport={"width": 1280, "height": 800},
            )
            # Mascara webdriver
            ctx.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = { runtime: {} };
            """)
            page = ctx.new_page()

            # Bloqueia recursos desnecessários para economizar tempo
            page.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,ico}", lambda r: r.abort())

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                # Aguarda aparecimento de preços na página
                try:
                    page.wait_for_selector("text=R$", timeout=15000)
                except PWTimeout:
                    pass
                # Scroll para carregar lazy-loaded content
                page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                page.wait_for_timeout(2000)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)
            except PWTimeout:
                print("  ⚠ Timeout carregando página")

            html = page.content()
            browser.close()

        # Extrai com varredura linear (SSR + JS renderizado)
        offers = parse_ssr_linear(html, url)

        # Se fallback não funcionou, tenta parser de classe genérico
        if len(offers) < 3:
            offers = parse_generic_class(html, url)

        print(f"  ✓ {len(offers)} produtos via Playwright")

    except Exception as e:
        print(f"  ✗ Playwright error: {e}")

    return offers[:60]


# ─── PARSER GENÉRICO DE CLASSE (fallback universal) ───────────────────────────

class _GenericParser(HTMLParser):
    def __init__(self, base_url):
        super().__init__()
        self.products = []
        self.base_url = base_url
        self._buf = []; self._in = False; self._cur = {}
        self._skip = 0; self._ST = {"script","style","head","noscript","svg"}
        self._PC = {"price","preco","preço","valor","oferta","promo","sale"}
        self._NC = {"name","nome","product","produto","title","item","descri"}

    def _cls(self, attrs): return (dict(attrs).get("class") or "").lower()

    def handle_starttag(self, tag, attrs):
        if tag in self._ST: self._skip += 1; return
        if self._skip: return
        c = self._cls(attrs)
        if any(h in c for h in self._PC): self._buf=[]; self._in="price"
        elif any(h in c for h in self._NC): self._buf=[]; self._in="name"

    def handle_endtag(self, tag):
        if tag in self._ST: self._skip=max(0,self._skip-1); return
        if self._skip or not self._in: return
        text = " ".join(self._buf).strip(); self._buf=[]
        if self._in == "name" and 3 < len(text) < 100:
            self._cur["name"] = text
        elif self._in == "price":
            m = PRICE_RE.search(text)
            if m and self._cur.get("name"):
                try:
                    p = float(m.group(1).replace(",","."))
                    if 0.5 < p < 3000:
                        self.products.append({"product": self._cur["name"][:80],
                            "price": round(p,2), "unit":"un",
                            "url": self.base_url, "promotion": True})
                        self._cur = {}
                except ValueError: pass
        self._in = False

    def handle_data(self, data):
        if not self._skip and self._in: self._buf.append(data.strip())


def parse_generic_class(html, base_url):
    p = _GenericParser(base_url)
    try: p.feed(html)
    except Exception: pass
    return p.products[:60]


# ─── ORQUESTRADOR ─────────────────────────────────────────────────────────────

def scrape(name, cfg):
    method = cfg["method"]
    url    = cfg["url"]
    site   = cfg["site"]

    if method == "vtex_api":
        return scrape_vtex(name, url, f"https://www.{site}/ofertas")

    elif method == "ssr_guanabara":
        return scrape_ssr(name, url, GuanabaraParser)

    elif method == "ssr_mundial":
        return scrape_ssr(name, url, MundialParser)

    elif method == "playwright":
        return scrape_playwright(name, url)

    return []


# ─── HASH / IO ────────────────────────────────────────────────────────────────

def chash(offers): return hashlib.md5(json.dumps(offers,sort_keys=True).encode()).hexdigest()[:8]

def load():
    if OUTPUT.exists():
        try: return json.loads(OUTPUT.read_text("utf-8"))
        except Exception: pass
    return {"updated_at": "", "supermarkets": {}}

def save(data):
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    print(f"✅ Salvo → {OUTPUT}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def run():
    print(f"\n🔍 Scraper — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")
    existing = load()
    sm_data  = existing.get("supermarkets", {})
    changed  = False

    for name, cfg in SUPERMARKETS.items():
        print(f"→ {name}")
        offers = scrape(name, cfg)

        if not offers:
            # Mantém dado anterior se a coleta falhou
            if name in sm_data:
                print(f"  ⚠ Sem novos dados — mantendo {len(sm_data[name].get('offers', []))} produtos anteriores")
            continue

        h = chash(offers)
        if h != sm_data.get(name, {}).get("hash", ""):
            print(f"  ★ {len(offers)} ofertas atualizadas")
            sm_data[name] = {
                "name":       name,
                "color":      cfg["color"],
                "light":      cfg["light"],
                "site":       cfg["site"],
                "offers_url": cfg["url"],
                "hash":       h,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "offers":     offers,
            }
            changed = True
        else:
            print(f"  – Sem mudança ({len(offers)} produtos)")

        time.sleep(random.uniform(3, 6))

    if changed or not existing.get("updated_at"):
        existing["updated_at"]   = datetime.now(timezone.utc).isoformat()
        existing["supermarkets"] = sm_data
        save(existing)
    else:
        print("\n⏩ Nenhuma mudança detectada")

    total = sum(len(v.get("offers", [])) for v in sm_data.values())
    print(f"\n✅ Concluído — {total} produtos indexados no total")


if __name__ == "__main__":
    run()
