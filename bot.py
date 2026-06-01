"""
Bot Albo Pretorio - Comune di Agrigento
Per cittadini pigri che non hanno tempo di leggere atti comunali.
"""

import os, json, hashlib, requests, re, time
from datetime import datetime
from bs4 import BeautifulSoup

TELEGRAM_TOKEN    = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID  = os.environ["TELEGRAM_CHAT_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

ALBO_URL  = "https://servizionline.comune.agrigento.it/ServiziOnLine/AlboPretorio/AlboPretorio"
SEEN_FILE = "seen_atti.json"

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)

def atto_id(a):
    return hashlib.md5(f"{a['numero']}_{a['tipo']}_{a['data']}".encode()).hexdigest()

def fetch_atti():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })

    try:
        session.get("https://servizionline.comune.agrigento.it/", timeout=20)
        time.sleep(2)
    except:
        pass

    try:
        resp = session.get(ALBO_URL, timeout=30)
        resp.raise_for_status()
        html = resp.text
        print(f"[INFO] Pagina scaricata: {len(html)} caratteri")
    except Exception as e:
        print(f"[ERRORE] Fetch: {e}")
        try:
            resp = session.get(
                "https://servizionline.comune.agrigento.it/Content/landingContent/?AlboPretorio=",
                timeout=30
            )
            html = resp.text
            print(f"[INFO] Pagina alternativa: {len(html)} caratteri")
        except Exception as e2:
            print(f"[ERRORE] Anche alternativa fallita: {e2}")
            return []

    soup = BeautifulSoup(html, "html.parser")
    testo = soup.get_text(separator="\n")
    print(f"[INFO] Testo estratto: {len(testo)} caratteri")
    print(f"[DEBUG] Prime 1000 righe:\n{testo[:1000]}")

    atti = []
    for line in testo.split("\n"):
        line = line.strip()
        m = re.search(
            r"(\d{3,5}/\d{4})\s+del\s+(\d{2}/\d{2}/\d{4})\s*[-–]\s*([^\-–\d][^\n\r]{3,80})",
            line
        )
        if not m:
            continue
        numero  = m.group(1).strip()
        data    = m.group(2).strip()
        tipo    = m.group(3).strip()
        oggetto = line[m.end():].strip()[:300]
        atto = {"numero": numero, "data": data, "tipo": tipo, "oggetto": oggetto, "link": ALBO_URL}
        uid = atto_id(atto)
        if not any(atto_id(a) == uid for a in atti):
            atti.append(atto)

    print(f"[INFO] Trovati {len(atti)} atti")
    return atti

def analizza_atto(atto):
    prompt = f"""Sei l'assistente del canale Telegram "Albo Pretorio Agrigento - Per cittadini pigri".
Il tuo tono è ironico, diretto, un po' sarcastico ma mai offensivo. Parli come un amico che spiega le cose al bar.

Hai ricevuto questo atto comunale:
- Tipo: {atto['tipo']}
- Numero: {atto['numero']}
- Data: {atto['data']}
- Oggetto: {atto['oggetto']}

Rispondi SOLO con un JSON valido, senza markdown, con questi campi:
{{
  "cosa_e_successo": "2-3 frasi ironiche che spiegano l'atto in modo semplice",
  "ti_cambia_vita": "1 frase su quanto impatta sul cittadino medio",
  "livello_scandalo": "uno tra: NESSUNO, TIENI_DOCCHIO, INTERESSANTE, SVEGLIATI, ALLERTA_MASSIMA",
  "emoji_scandalo": "uno tra: 🥱, 🤨, 😤, 🚨, 💥"
}}"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=15,
        )
        testo = resp.json()["content"][0]["text"].strip()
        # Pulizia JSON
        testo = re.sub(r"```json|```", "", testo).strip()
        return json.loads(testo)
    except Exception as e:
        print(f"[ERRORE] AI: {e}")
        return {
            "cosa_e_successo": atto['oggetto'][:200],
            "ti_cambia_vita": "Difficile dirlo senza leggere tutto.",
            "livello_scandalo": "NESSUNO",
            "emoji_scandalo": "🥱"
        }

SCANDALO_LABEL = {
    "NESSUNO":        "Nessuno",
    "TIENI_DOCCHIO":  "Tieni d'occhio",
    "INTERESSANTE":   "Interessante",
    "SVEGLIATI":      "Svegliati cittadino!",
    "ALLERTA_MASSIMA":"ALLERTA MASSIMA",
}

EMOJI_TIPO = {
    "determina": "📋",
    "delibera":  "🏛️",
    "ordinanza": "⚠️",
    "permesso":  "🏗️",
    "concorso":  "👔",
    "matrimonio":"💍",
    "avviso":    "📢",
}

def formato_msg(atto, analisi):
    tipo_lower = atto["tipo"].lower()
    emoji_tipo = next((v for k, v in EMOJI_TIPO.items() if k in tipo_lower), "📌")
    scandalo   = SCANDALO_LABEL.get(analisi["livello_scandalo"], "Nessuno")
    emoji_sc   = analisi["emoji_scandalo"]

    msg  = f"🏛️ *ALBO PRETORIO AGRIGENTO*\n"
    msg += f"_Per chi non ha tempo \\(né voglia\\) di leggere atti comunali_\n\n"
    msg += f"━━━━━━━━━━━━━━━━\n\n"
    msg += f"{emoji_tipo} *{atto['tipo']}* n\\. {atto['numero']}\n"
    msg += f"📅 {atto['data']}\n\n"
    msg += f"*Cosa è successo:*\n{analisi['cosa_e_successo']}\n\n"
    msg += f"*Ti cambia la vita?*\n{analisi['ti_cambia_vita']}\n\n"
    msg += f"*Livello di scandalo:* {emoji_sc} {scandalo}\n\n"
    msg += f"🔗 [Clicca qui se vuoi soffrire]({ALBO_URL})\n\n"
    msg += f"_Albo Pretorio Agrigento — perché qualcuno deve leggerlo, e quel qualcuno non sei tu_ 🫡"
    return msg

def invia_telegram(testo):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id":                  TELEGRAM_CHAT_ID,
                "text":                     testo,
                "parse_mode":               "MarkdownV2",
                "disable_web_page_preview": True
            },
            timeout=10
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[ERRORE] Telegram: {e}")
        return False

def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Avvio...")
    seen  = load_seen()
    atti  = fetch_atti()
    nuovi = [a for a in atti if atto_id(a) not in seen]
    print(f"[INFO] Atti nuovi: {len(nuovi)}")

    if not seen and nuovi:
        print("[INFO] Prima esecuzione — mando i primi 3 come test")
        nuovi = nuovi[:3]

    for atto in nuovi[:10]:
        print(f"[INFO] Processo: {atto['numero']} - {atto['tipo']}")
        analisi = analizza_atto(atto)
        msg     = formato_msg(atto, analisi)
        if invia_telegram(msg):
            seen.add(atto_id(atto))
            print(f"[OK] Inviato: {atto['numero']}")

    save_seen(seen)
    print(f"[FINE] Atti tracciati: {len(seen)}")

if __name__ == "__main__":
    main()
