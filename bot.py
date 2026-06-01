"""
Bot Albo Pretorio - Comune di Agrigento
Usa Selenium per caricare la pagina JavaScript, analizza con AI e manda su Telegram.
"""

import os
import json
import hashlib
import requests
import time
from datetime import datetime
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ── Configurazione ──────────────────────────────────────────────
TELEGRAM_TOKEN    = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID  = os.environ["TELEGRAM_CHAT_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

ALBO_URL  = "https://servizionline.comune.agrigento.it/ServiziOnLine/AlboPretorio/AlboPretorio"
SEEN_FILE = "seen_atti.json"

# ── Persistenza atti già visti ───────────────────────────────────
def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()

def save_seen(seen: set):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)

def atto_id(atto: dict) -> str:
    key = f"{atto['numero']}_{atto['tipo']}_{atto['data']}"
    return hashlib.md5(key.encode()).hexdigest()

# ── Selenium scraping ─────────────────────────────────────────────
def fetch_atti() -> list[dict]:
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        driver.get(ALBO_URL)

        # Aspetta che la pagina carichi gli atti (max 15 secondi)
        time.sleep(8)

        html = driver.page_source
    except Exception as e:
        print(f"[ERRORE] Selenium: {e}")
        return []
    finally:
        if driver:
            driver.quit()

    soup = BeautifulSoup(html, "html.parser")
    atti = []
    import re

    # Cerca tutti i blocchi con pattern numero/anno
    testo_pagina = soup.get_text(separator="\n")
    
    for line in testo_pagina.split("\n"):
        line = line.strip()
        match = re.search(
            r"(\d{3,5}/\d{4})\s+del\s+(\d{2}/\d{2}/\d{4})\s*[-–]\s*([^\-–\d][^\n\r]{3,60})",
            line
        )
        if not match:
            continue

        numero = match.group(1).strip()
        data   = match.group(2).strip()
        tipo   = match.group(3).strip()
        oggetto = line[match.end():].strip()[:300]

        atto = {"numero": numero, "data": data, "tipo": tipo, "oggetto": oggetto, "link": ALBO_URL}
        uid  = atto_id(atto)
        if not any(atto_id(a) == uid for a in atti):
            atti.append(atto)

    print(f"[INFO] Trovati {len(atti)} atti")
    return atti

# ── Analisi AI ───────────────────────────────────────────────────
def spiega_atto(atto: dict) -> str:
    prompt = f"""Sei un assistente civico che spiega in modo semplice gli atti del Comune di Agrigento.

Atto pubblicato sull'Albo Pretorio:
- Numero: {atto['numero']}
- Data: {atto['data']}
- Tipo: {atto['tipo']}
- Oggetto: {atto['oggetto']}

Scrivi UNA spiegazione breve (2-3 frasi max) in italiano semplice, rivolta ai cittadini.
Spiega cosa significa questo atto concretamente. Niente burocrazia, niente tecnicismi.
Non iniziare con "Questo atto" o frasi simili. Vai diretto al punto."""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 200,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"].strip()
    except Exception as e:
        print(f"[ERRORE] AI: {e}")
        return ""

# ── Formattazione messaggio ──────────────────────────────────────
EMOJI = {
    "determina dirigenziale": "📋",
    "determina sindacale":    "📋",
    "delibera di consiglio":  "🏛️",
    "delibera di giunta":     "🏛️",
    "ordinanza":              "⚠️",
    "permesso edilizio":      "🏗️",
    "concorsi":               "👔",
    "matrimonio":             "💍",
    "avviso":                 "📢",
}

def formato_messaggio(atto: dict, spiegazione: str) -> str:
    tipo_lower = atto["tipo"].lower()
    emoji = next((v for k, v in EMOJI.items() if k in tipo_lower), "📌")

    msg  = f"{emoji} *{atto['tipo']}* — {atto['numero']}\n"
    msg += f"📅 {atto['data']}\n\n"
    if atto["oggetto"]:
        msg += f"_{atto['oggetto'][:200]}_\n\n"
    if spiegazione:
        msg += f"💬 {spiegazione}\n"
    msg += f"\n🔗 [Vai all'Albo Pretorio]({ALBO_URL})"
    msg += "\n\n_Comune di Agrigento — Albo Pretorio_"
    return msg

# ── Invio Telegram ───────────────────────────────────────────────
def invia_telegram(testo: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id":                  TELEGRAM_CHAT_ID,
            "text":                     testo,
            "parse_mode":               "Markdown",
            "disable_web_page_preview": True,
        }, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"[ERRORE] Telegram: {e}")
        return False

# ── Main ─────────────────────────────────────────────────────────
def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Avvio...")

    seen  = load_seen()
    atti  = fetch_atti()
    nuovi = [a for a in atti if atto_id(a) not in seen]

    print(f"[INFO] Atti nuovi: {len(nuovi)}")

    # Prima esecuzione: manda solo i primi 3 come test
    if not seen and nuovi:
        print("[INFO] Prima esecuzione — mando i primi 3 come test")
        nuovi = nuovi[:3]

    for atto in nuovi[:10]:
        print(f"[INFO] Processo: {atto['numero']} - {atto['tipo']}")
        spiegazione = spiega_atto(atto)
        messaggio   = formato_messaggio(atto, spiegazione)

        if invia_telegram(messaggio):
            seen.add(atto_id(atto))
            print(f"[OK] Inviato: {atto['numero']}")
        else:
            print(f"[ERRORE] Non inviato: {atto['numero']}")

    save_seen(seen)
    print(f"[FINE] Atti tracciati: {len(seen)}")

if __name__ == "__main__":
    main()