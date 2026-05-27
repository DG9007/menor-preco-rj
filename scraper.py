#!/usr/bin/env python3
"""
Menor Preço RJ — Scraper v5.1 (Playwright Total com Fallback Seguro)
Coleta ofertas reais e atualizadas de 4 supermercados do RJ.
"""

import json, re, time, random, hashlib
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
OUTPUT   = DATA_DIR / "encartes.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

SUPERMARKETS = {
    "Guanabara": {
        "color": "#c8102e", "light": "#fee2e2",
        "site":  "supermercadosguanabara.com.br",
        "url":   "https://www.supermercadosguanabara.com.br/",
    },
    "Prezunic": {
        "color": "#15803d", "light": "#dcfce7",
        "site":  "prezunic.com.br",
        # URL da API VTEX corrigida: Busca geral filtrando pelas maiores promoções/descontos
        "url":   "https://www.prezunic.com.br/api/catalog_system/pub/products/search?fq=O:OrderByBestDiscountDESC&_from=0&_to=49",
    },
    "Mundial": {
        "color": "#1d4ed8", "light": "#dbeafe",
        "site":  "supermercadosmundial.com.br",
        "url":   "https://www.supermercadosmundial.com.br/ofertas",
    },
    "Supermarket": {
        "color": "#7c3aed", "light": "#ede9fe",
        "site":  "redesupermarket.com.br",
        "url":   "https://redesupermarket.com.br/ofertas/",
    },
}

# ─── EXTRAÇÃO PREZUNIC (API VTEX) ─────────────────────────────────────────────
def scrape_prezunic_api(url):
    import urllib.request
    print("  → Acessando API VTEX do Prezunic...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode('utf-8'))
            results = []
            for item in data:
                name = item.get("productName", "").strip()
                sellers = item.get("items", [{}])[0].get("sellers", [{}])
                price = sellers[0].get("commertialOffer", {}).get("Price", 0)
                if name and price > 0:
                    results.append({
                        "product": name[:80],
                        "price": round(float(price), 2),
                        "unit": "un",
                        "url": item.get("link", "https://www.prezunic.com.br"),
                        "promotion": True
                    })
            return results
    except Exception as e:
        print(f"  ✗ Erro Prezunic API: {e}")
        return []

# ─── EXTRAÇÃO VIA PLAYWRIGHT (MUNDIAL, SUPERMARKET, GUANABARA) ────────────────
def scrape_with_playwright():
    from playwright.sync_api import sync_playwright
    
    scraped_data = { "Guanabara": [], "Mundial": [], "Supermarket": [] }
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, locale="pt-BR")
        page = ctx.new_page()
        
        # --- 1. MUNDIAL ---
        print("  → Abrindo Mundial...")
        try:
            page.goto(SUPERMARKETS["Mundial"]["url"], timeout=45000, wait_until="networkidle")
            cards = page.query_selector_all(".product-card, .item-oferta, .showcase-item")
            for card in cards:
                name_el = card.query_selector(".product-name, .title, h3")
                price_el = card.query_selector(".product-price, .price, .valor")
                if name_el and price_el:
                    name = name_el.inner_text().strip()
                    price_text = price_el.inner_text()
                    match = re.search(r"(\d{1,4}[.,]\d{2})", price_text)
                    if match:
                        price = float(match.group(1).replace(",", "."))
                        scraped_data["Mundial"].append({
                            "product": name[:80], "price": price, "unit": "un",
                            "url": SUPERMARKETS["Mundial"]["url"], "promotion": True
                        })
        except Exception as e:
            print(f"  ✗ Erro ao raspar Mundial: {e}")

        # --- 2. SUPERMARKET ---
        print("  → Abrindo Supermarket...")
        try:
            page.goto(SUPERMARKETS["Supermarket"]["url"], timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            items = page.query_selector_all(".oferta-item, .product-item, div[class*='oferta']")
            for item in items:
                name_el = item.query_selector(".nome, .title, h4")
                price_el = item.query_selector(".preco, .price, [class*='preco']")
                if name_el and price_el:
                    name = name_el.inner_text().strip()
                    price_text = price_el.inner_text()
                    match = re.search(r"(\d{1,4}[.,]\d{2})", price_text)
                    if match:
                        price = float(match.group(1).replace(",", "."))
                        scraped_data["Supermarket"].append({
                            "product": name[:80], "price": price, "unit": "un",
                            "url": SUPERMARKETS["Supermarket"]["url"], "promotion": True
                        })
        except Exception as e:
            print(f"  ✗ Erro ao raspar Supermarket: {e}")

        # --- 3. GUANABARA ---
        print("  → Abrindo Guanabara...")
        try:
            page.goto(SUPERMARKETS["Guanabara"]["url"], timeout=45000, wait_until="networkidle")
            encarte_img = page.query_selector("img[src*='encarte'], .banner-encarte img, #encarte")
            if encarte_img:
                src = encarte_img.get_attribute("src")
                scraped_data["Guanabara"].append({
                    "product": "Encarte Digital Completo (Veja no Link)",
                    "price": 0.0,
                    "unit": "link",
                    "url": src if src.startswith("http") else f"https://www.supermercadosguanabara.com.br{src}",
                    "promotion": True
                })
        except Exception as e:
            print(f"  ✗ Erro ao raspar Guanabara: {e}")
            
        browser.close()
    return scraped_data

# ─── AUXILIARES E SALVAMENTO ──────────────────────────────────────────────────
def chash(offers): 
    return hashlib.md5(json.dumps(offers, sort_keys=True).encode()).hexdigest()[:8]

def load_existing():
    if OUTPUT.exists():
        try: return json.loads(OUTPUT.read_text("utf-8"))
        except Exception: pass
    return {"updated_at": "", "supermarkets": {}}

# ─── FLUXO PRINCIPAL ──────────────────────────────────────────────────────────
def run():
    print(f"\n🔍 Iniciando o Novo Orquestrador de Encartes — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")
    
    existing = load_existing()
    sm_data = existing.get("supermarkets", {})
    changed = False

    # Estrutura base de resultados caso o Playwright falte
    pw_results = { "Guanabara": [], "Mundial": [], "Supermarket": [] }
    
    # Bloco seguro de verificação do Playwright
    try:
        from playwright.sync_api import sync_playwright
        pw_results = scrape_with_playwright()
    except ImportError:
        print("  ⚠ Playwright não está instalado no ambiente. Pulando Guanabara, Mundial e Supermarket temporariamente.")
    except Exception as e:
        print(f"  ✗ Erro inesperado ao iniciar Playwright: {e}")
    
    # Executa a API do Prezunic de forma nativa e independente
    pw_results["Prezunic"] = scrape_prezunic_api(SUPERMARKETS["Prezunic"]["url"])

    # Consolida os dados e atualiza o arquivo JSON
    for name, offers in pw_results.items():
        cfg = SUPERMARKETS[name]
        if not offers:
            if name in sm_data:
                print(f"  ⚠ {name}: Sem novos dados capturados — mantendo cache anterior.")
            continue
            
        h = chash(offers)
        if h != sm_data.get(name, {}).get("hash", ""):
            print(f"  ★ {name}: {len(offers)} ofertas atualizadas com sucesso!")
            sm_data[name] = {
                "name": name,
                "color": cfg["color"],
                "light": cfg["light"],
                "site": cfg["site"],
                "offers_url": cfg["url"],
                "hash": h,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "offers": offers,
            }
            changed = True
        else:
            print(f"  – {name}: Sem alterações detectadas no encarte.")

    if changed or not existing.get("updated_at"):
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()
        existing["supermarkets"] = sm_data
        OUTPUT.write_text(json.dumps(existing, ensure_ascii=False, indent=2), "utf-8")
        print(f"\n✅ Banco de dados atualizado com sucesso em: {OUTPUT}")
    else:
        print("\n⏩ Nenhuma alteração global detectada nos encartes.")

if __name__ == "__main__":
    run()
