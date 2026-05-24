#!/usr/bin/env python3
"""
Menor Preço RJ — Scraper de Encartes
Roda todo dia via GitHub Actions e atualiza data/encartes.json
"""

import json
import re
import time
import random
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError
from html.parser import HTMLParser

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
OUTPUT = DATA_DIR / "encartes.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

# ─── SUPERMERCADOS ────────────────────────────────────────────────────────────
# Cada entrada tem:
#   - name:    nome exibido no app
#   - color:   cor da marca
#   - light:   cor clara para fundo
#   - site:    domínio (para favicon)
#   - offers_url: URL da página de ofertas/encarte
#   - parser:  função de parse (definida abaixo)

SUPERMARKETS = [
    {
        "name": "Carrefour",
        "color": "#0057a8",
        "light": "#dbeafe",
        "site": "carrefour.com.br",
        "offers_url": "https://www.carrefour.com.br/ofertas",
    },
    {
        "name": "Guanabara",
        "color": "#c8102e",
        "light": "#fee2e2",
        "site": "supermercadosguanabara.com.br",
        "offers_url": "https://www.supermercadosguanabara.com.br/ofertas",
    },
    {
        "name": "Assaí",
        "color": "#e85d00",
        "light": "#ffedd5",
        "site": "assai.com.br",
        "offers_url": "https://www.assai.com.br/ofertas",
    },
    {
        "name": "Atacadão",
        "color": "#b91c1c",
        "light": "#fecaca",
        "site": "atacadao.com.br",
        "offers_url": "https://www.atacadao.com.br/ofertas",
    },
    {
        "name": "Prezunic",
        "color": "#15803d",
        "light": "#dcfce7",
        "site": "prezunic.com.br",
        "offers_url": "https://www.prezunic.com.br/ofertas",
    },
    {
        "name": "Mundial",
        "color": "#1d4ed8",
        "light": "#dbeafe",
        "site": "supermercadosmundial.com.br",
        "offers_url": "https://www.supermercadosmundial.com.br/ofertas",
    },
    {
        "name": "Supermarket",
        "color": "#7c3aed",
        "light": "#ede9fe",
        "site": "supermarket.com.br",
        "offers_url": "https://redesupermarket.com.br/ofertas/",
    },
    {
        "name": "Rede Economia",
        "color": "#b45309",
        "light": "#fef3c7",
        "site": "redeeconomia.com.br",
        "offers_url": "https://www.redeconomia.com.br/encartes/",
    },
]


# ─── HTML PARSER GENÉRICO ─────────────────────────────────────────────────────

class ProductParser(HTMLParser):
    """Parser genérico que tenta extrair produtos e preços de páginas de ofertas."""

    def __init__(self):
        super().__init__()
        self.products = []
        self._current = {}
        self._text_buf = []
        self._in_price = False
        self._in_name = False
        self._depth = 0
        self._price_re = re.compile(r"R?\$?\s*(\d{1,4}[.,]\d{2})")
        self._skip_tags = {"script", "style", "svg", "path", "head"}
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip += 1
            return
        if self._skip:
            return
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "") or ""
        # Heurística: detectar containers de produto
        price_hints = ["price", "preco", "preço", "valor", "oferta", "offer", "promo"]
        name_hints  = ["name", "nome", "title", "titulo", "produto", "product", "descri"]
        if any(h in cls.lower() for h in price_hints):
            self._in_price = True
        if any(h in cls.lower() for h in name_hints):
            self._in_name = True

    def handle_endtag(self, tag):
        if tag in self._skip_tags:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        text = " ".join(self._text_buf).strip()
        self._text_buf = []
        if not text:
            return
        m = self._price_re.search(text)
        if m:
            price_str = m.group(1).replace(".", "").replace(",", ".")
            try:
                price = float(price_str)
                if 0.5 < price < 5000:
                    if self._current.get("product"):
                        self.products.append({
                            "product": self._current["product"],
                            "price": price,
                            "unit": "un",
                            "promotion": True,
                        })
                        self._current = {}
            except ValueError:
                pass
        elif self._in_name and len(text) > 3:
            self._current["product"] = text[:80]
        self._in_price = False
        self._in_name = False

    def handle_data(self, data):
        if self._skip:
            return
        self._text_buf.append(data.strip())


# ─── FETCH E PARSE ────────────────────────────────────────────────────────────

def fetch_html(url: str, timeout: int = 15) -> str | None:
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=timeout) as r:
            raw = r.read()
            enc = r.headers.get_content_charset("utf-8")
            return raw.decode(enc, errors="replace")
    except URLError as e:
        print(f"  ⚠ Erro ao buscar {url}: {e}")
        return None
    except Exception as e:
        print(f"  ⚠ Erro inesperado {url}: {e}")
        return None


def parse_offers(html: str, sm_name: str, base_url: str) -> list[dict]:
    """Extrai ofertas de um HTML. Tenta JSON-LD primeiro, depois parser HTML."""
    offers = []

    # 1) Tenta JSON-LD (mais confiável quando disponível)
    price_re = re.compile(r'"price"\s*:\s*"?([\d.,]+)"?')
    name_re  = re.compile(r'"name"\s*:\s*"([^"]{3,80})"')
    url_re   = re.compile(r'"url"\s*:\s*"(https?://[^"]+)"')

    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S):
        prices = price_re.findall(block)
        names  = name_re.findall(block)
        urls   = url_re.findall(block)
        for i, (n, p) in enumerate(zip(names, prices)):
            try:
                price = float(p.replace(".", "").replace(",", "."))
                if 0.5 < price < 5000:
                    offers.append({
                        "product":   n.strip(),
                        "price":     price,
                        "unit":      "un",
                        "url":       urls[i] if i < len(urls) else base_url,
                        "promotion": True,
                    })
            except ValueError:
                pass

    # 2) Fallback: parser HTML genérico
    if not offers:
        parser = ProductParser()
        try:
            parser.feed(html)
            offers = [{"url": base_url, **p} for p in parser.products[:40]]
        except Exception:
            pass

    # 3) Fallback final: ao menos registra que o site foi verificado
    if not offers:
        offers = [{
            "product": f"Encarte {sm_name} (acesse o site para ver ofertas)",
            "price": 0,
            "unit": "",
            "url": base_url,
            "promotion": False,
        }]

    return offers[:40]


def content_hash(offers: list) -> str:
    s = json.dumps(offers, sort_keys=True)
    return hashlib.md5(s.encode()).hexdigest()[:8]


# ─── CARGA / SALVA JSON ───────────────────────────────────────────────────────

def load_existing() -> dict:
    if OUTPUT.exists():
        try:
            return json.loads(OUTPUT.read_text("utf-8"))
        except Exception:
            pass
    return {"updated_at": "", "supermarkets": {}}


def save(data: dict):
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    print(f"✅ Salvo em {OUTPUT}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def run():
    print(f"🔍 Scraper iniciado — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    existing = load_existing()
    sm_data  = existing.get("supermarkets", {})
    changed  = False

    for sm in SUPERMARKETS:
        name = sm["name"]
        url  = sm["offers_url"]
        print(f"\n→ {name} ({url})")

        html = fetch_html(url)
        if not html:
            print(f"  ✗ Sem resposta, mantendo dados anteriores")
            continue

        offers = parse_offers(html, name, url)
        new_hash = content_hash(offers)
        old_hash = sm_data.get(name, {}).get("hash", "")

        if new_hash != old_hash:
            print(f"  ✓ {len(offers)} oferta(s) — NOVO conteúdo detectado")
            sm_data[name] = {
                "name":       name,
                "color":      sm["color"],
                "light":      sm["light"],
                "site":       sm["site"],
                "offers_url": url,
                "hash":       new_hash,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "offers":     offers,
            }
            changed = True
        else:
            print(f"  – {len(offers)} oferta(s) — sem mudança")

        # Pausa educada entre requisições
        time.sleep(random.uniform(2, 5))

    if changed or not existing.get("updated_at"):
        existing["updated_at"]    = datetime.now(timezone.utc).isoformat()
        existing["supermarkets"]  = sm_data
        save(existing)
    else:
        print("\n⏩ Nenhuma mudança detectada, JSON não atualizado.")

    print("\n✅ Concluído.")


if __name__ == "__main__":
    run()
