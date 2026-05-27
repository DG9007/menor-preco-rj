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
