#!/usr/bin/env python3
"""
News Agent v3 — Monitoreo BTC + Pi Network con fuentes primarias en tiempo real
─────────────────────────────────────────────────────────────────────────────────
Cambios vs v2:
  • Fuentes PRIMARIAS de máxima velocidad (T+10s a T+2min):
      - SEC EDGAR (filings 8-K/S-1 de BlackRock, MicroStrategy, etc.)
      - Federal Reserve (comunicados oficiales)
      - US Treasury (comunicados oficiales)
  • Fuentes SOCIALES vía Nitter (T+30s-2min, frágil):
      - EricBalchunas, JSeyff, WuBlockchain, DocumentingBTC, SECGov,
        whale_alert, saylor, etc.
  • Más subreddits: r/Bitcoin, r/CryptoCurrency, r/CryptoMarkets
  • Sistema de tiers: PRIMARY > SECONDARY > SOCIAL (con boost de score)
  • Intervalo bajado a 2 min con más fuentes

Uso:
    python news_agent_v3.py            # loop continuo
    python news_agent_v3.py --once     # una pasada (debug)
    python news_agent_v3.py --test     # mensaje prueba a Discord
    python news_agent_v3.py --analyze "titulo"   # test análisis IA
    python news_agent_v3.py --costs    # costos acumulados
    python news_agent_v3.py --sec      # debug fetch SEC
    python news_agent_v3.py --nitter   # debug fetch Nitter
"""

import os, sys, json, time, hashlib, logging, sqlite3, re
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(BASE / "news_agent.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("news_agent")

try:
    import requests
    import feedparser
    from dotenv import load_dotenv
except ImportError:
    log.error("Faltan dependencias: pip install requests feedparser python-dotenv")
    sys.exit(1)

load_dotenv(BASE / "config.env")

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════════════
DISCORD_WEBHOOK_URL   = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
CRYPTOPANIC_TOKEN     = os.getenv("CRYPTOPANIC_TOKEN", "").strip()
ANTHROPIC_API_KEY     = os.getenv("ANTHROPIC_API_KEY", "").strip()
USER_AGENT_SEC        = os.getenv("USER_AGENT_SEC",
                                  "NewsAgent contact@newsagent.local").strip()

USAR_CLAUDE_API       = bool(ANTHROPIC_API_KEY)
MODELO_CLAUDE         = "claude-haiku-4-5-20251001"
SUPRIMIR_NEUTRAL      = True

INTERVALO_SEGUNDOS    = 120
INTERVALO_EVENTOS_HRS = 6
SCORE_MINIMO_ENVIAR   = 7
MAX_NOTIS_POR_CICLO   = 8
DB_PATH               = BASE / "news_agent.db"

PRE_ALERTAS_MIN       = [60 * 24, 60, 15]
PRECIO_HAIKU_INPUT    = 1.00
PRECIO_HAIKU_OUTPUT   = 5.00

# ══════════════════════════════════════════════════════════════════════════════
# FUENTES PRIMARIAS — SEC EDGAR (compañías que mueven BTC con sus filings)
# ══════════════════════════════════════════════════════════════════════════════
SEC_COMPANIES = {
    "BlackRock":          "0001364742",
    "MicroStrategy":      "0001050446",
    "Coinbase":           "0001679788",
    "Marathon Digital":   "0001507605",
    "Riot Platforms":     "0001167419",
    "Grayscale":          "0001588489",
    "Tesla":              "0001318605",
    "Block Inc":          "0001512673",
    "Robinhood":          "0001783879",
    "Galaxy Digital":     "0001805222",
    "Hut 8":              "0001964333",
    "CleanSpark":         "0000827054",
}
SEC_FORMS_RELEVANTES = ["8-K", "S-1", "S-1/A", "424B5", "13F-HR"]

# ══════════════════════════════════════════════════════════════════════════════
# FUENTES PRIMARIAS — Fed / Treasury
# ══════════════════════════════════════════════════════════════════════════════
RSS_PRIMARIOS = [
    ("Fed Press",     "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("Fed Speeches",  "https://www.federalreserve.gov/feeds/speeches.xml"),
    ("Treasury",      "https://home.treasury.gov/news/press-releases/feed"),
]

# ══════════════════════════════════════════════════════════════════════════════
# FUENTES SECUNDARIAS — Medios cripto
# ══════════════════════════════════════════════════════════════════════════════
RSS_SECUNDARIOS = [
    ("CoinDesk",        "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph",   "https://cointelegraph.com/rss"),
    ("Bitcoin Magazine","https://bitcoinmagazine.com/.rss/full/"),
    ("Decrypt",         "https://decrypt.co/feed"),
    ("BeInCrypto",      "https://beincrypto.com/feed/"),
    ("CryptoSlate",     "https://cryptoslate.com/feed/"),
    ("The Block",       "https://www.theblock.co/rss.xml"),
    ("Pi Blog",         "https://minepi.com/blog/feed/"),
]

# ══════════════════════════════════════════════════════════════════════════════
# FUENTES SOCIALES — Reddit + Nitter (Twitter sin API)
# ══════════════════════════════════════════════════════════════════════════════
RSS_REDDIT = [
    ("r/PiNetwork",       "https://www.reddit.com/r/PiNetwork/new/.rss"),
    ("r/Bitcoin",         "https://www.reddit.com/r/Bitcoin/new/.rss"),
    ("r/CryptoCurrency",  "https://www.reddit.com/r/CryptoCurrency/new/.rss"),
    ("r/CryptoMarkets",   "https://www.reddit.com/r/CryptoMarkets/new/.rss"),
]

CUENTAS_X = [
    "EricBalchunas", "JSeyff", "WuBlockchain",
    "DocumentingBTC", "SECGov", "whale_alert",
    "saylor", "elonmusk", "BitcoinMagazine", "CoinDesk",
]

NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.cz",
    "https://nitter.adminforge.de",
    "https://nitter.moomoo.me",
    "https://lightbrd.com",
]

# ══════════════════════════════════════════════════════════════════════════════
# KEYWORDS
# ══════════════════════════════════════════════════════════════════════════════
KEYWORDS_BTC = {
    "etf approval":12, "etf approved":12, "etf rejected":12, "etf denial":12,
    "spot bitcoin etf":8, "etf inflow":5, "etf outflow":5,
    "blackrock":4, "fidelity":3,
    "sec lawsuit":10, "sec sues":10, "sec settles":8,
    "ban bitcoin":12, "bitcoin banned":12, "outlaw":8,
    "hack":10, "exploit":8, "stolen":7,
    "exchange collapse":12, "bankruptcy":9, "insolvent":9,
    "halving":6, "mt gox":8, "satoshi":6,
    "michael saylor":4, "microstrategy buy":6, "microstrategy sell":8,
    "el salvador":4, "strategic reserve":9, "national reserve":8,
    "trump bitcoin":6, "biden bitcoin":4,
    "whale transfer":5, "whale moved":5, "large transfer":4,
    "regulation":5, "regulatory":4, "lawsuit":5,
    "approval":4, "rejected":4, "listing":4, "delisting":6,
    "exchange hack":9, "bridge hack":8,
    "all-time high":4, "ath":3, "new high":3,
    "crash":6, "plunge":5, "surge":4,
    "rally":2, "pump":1, "dump":2,
    "analyst":0, "prediction":0, "forecast":0,
    "adoption":3, "institutional":3, "bullish":1, "bearish":1,
    "support":0, "resistance":0,
    "fomc":6, "fed minutes":5, "fed meeting":5,
    "rate cut":7, "rate hike":6, "rates unchanged":4,
    "powell speech":5, "powell testimony":5, "jerome powell":3,
    "cpi release":5, "core cpi":5, "inflation data":4,
    "pce release":5, "core pce":5, "ppi release":4,
    "non-farm payrolls":4, "nfp report":4, "jobs report":3,
    "interest rate":2, "monetary policy":3,
    "yield curve":3, "treasury yield":2, "dollar index":2,
    "8-k":3, "form 8-k":4, "current report":2,
    "s-1 amendment":5, "form s-1":4, "registration statement":3,
    "13f":2, "13f filing":3,
    "bitcoin":0, "btc":0,
}

KEYWORDS_PI = {
    "pi mainnet":10, "open mainnet":12, "mainnet launch":12,
    "binance listing":12, "coinbase listing":12, "okx listing":10,
    "bybit listing":10, "kraken listing":10, "kucoin listing":8,
    "pi listing":9, "pi listed":9,
    "pi migration":7, "kyc complete":6, "pi delisting":10,
    "pi network ban":10, "pi banned":9,
    "pi day":5, "pi network update":4, "pi blockchain":4,
    "pi node":3, "pi browser":2, "pi app":2,
    "pi core team":4, "nicolas kokkalis":4, "chengdiao fan":4,
    "pi partnership":6, "pi roadmap":5, "pi tokenomics":5,
    "open network":6, "enclosed network":4,
    "pi network":1, "pi coin":1, "pi/usdt":3, "minepi":1, "$pi":1,
}

EVENTOS_MACRO_KEYS = [
    "FOMC", "Federal Funds", "Fed Chair", "Powell",
    "CPI", "Core CPI", "PCE", "Core PCE",
    "Non-Farm", "Unemployment", "NFP",
    "PPI", "GDP", "Retail Sales", "Consumer Confidence",
]

BOOST_TIER = {"PRIMARY": 5, "SOCIAL": 3, "SECONDARY": 0, "REDDIT": -1}

# ══════════════════════════════════════════════════════════════════════════════
# STORAGE
# ══════════════════════════════════════════════════════════════════════════════
def db_init():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS seen_articles (
        url_hash TEXT PRIMARY KEY, title TEXT, source TEXT, url TEXT,
        score INTEGER, nivel TEXT, target TEXT, timestamp TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS event_alerts (
        event_id TEXT, alert_type TEXT, sent_at TEXT,
        PRIMARY KEY (event_id, alert_type))""")
    c.execute("""CREATE TABLE IF NOT EXISTS event_results (
        event_id TEXT PRIMARY KEY, title TEXT, country TEXT, scheduled_at TEXT,
        forecast TEXT, previous TEXT, actual TEXT, analyzed INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS ai_analysis (
        url_hash TEXT PRIMARY KEY, direccion TEXT, confianza INTEGER,
        magnitud TEXT, horizonte TEXT, explicacion TEXT,
        input_tokens INTEGER, output_tokens INTEGER, costo_usd REAL,
        timestamp TEXT)""")
    cols = [r[1] for r in c.execute("PRAGMA table_info(seen_articles)").fetchall()]
    for col, typ in [("direccion","TEXT"),("confianza","INTEGER"),
                     ("tier","TEXT"),("published_at","TEXT")]:
        if col not in cols:
            c.execute(f"ALTER TABLE seen_articles ADD COLUMN {col} {typ}")
    conn.commit()
    return conn

def url_hash(url): return hashlib.md5(url.encode("utf-8")).hexdigest()

def ya_visto(conn, url):
    c = conn.cursor()
    c.execute("SELECT 1 FROM seen_articles WHERE url_hash=?", (url_hash(url),))
    return c.fetchone() is not None

def marcar_visto(conn, url, title, source, score, nivel, target,
                 direccion=None, confianza=None, tier=None, published_at=None):
    c = conn.cursor()
    c.execute("""INSERT OR IGNORE INTO seen_articles
        (url_hash,title,source,url,score,nivel,target,timestamp,
         direccion,confianza,tier,published_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (url_hash(url), title, source, url, score, nivel, target,
         datetime.now(timezone.utc).isoformat(),
         direccion, confianza, tier, published_at))
    conn.commit()

def alerta_ya_enviada(conn, eid, atype):
    c = conn.cursor()
    c.execute("SELECT 1 FROM event_alerts WHERE event_id=? AND alert_type=?", (eid, atype))
    return c.fetchone() is not None

def marcar_alerta(conn, eid, atype):
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO event_alerts VALUES (?,?,?)",
              (eid, atype, datetime.now(timezone.utc).isoformat()))
    conn.commit()

def guardar_analisis(conn, url, a):
    c = conn.cursor()
    c.execute("""INSERT OR REPLACE INTO ai_analysis VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (url_hash(url), a.get("direccion"), a.get("confianza"),
         a.get("magnitud"), a.get("horizonte"), a.get("explicacion"),
         a.get("input_tokens",0), a.get("output_tokens",0),
         a.get("costo_usd",0.0), datetime.now(timezone.utc).isoformat()))
    conn.commit()

# ══════════════════════════════════════════════════════════════════════════════
# CLAUDE HAIKU
# ══════════════════════════════════════════════════════════════════════════════
PROMPT_ANALISIS = """Eres analista cripto experto. Lee esta noticia y predice su impacto en el precio de {target}.

TÍTULO: {titulo}
RESUMEN: {resumen}
FUENTE: {fuente} (tipo: {tier})

Contexto: {contexto_target}

Responde SOLO con JSON válido, sin markdown:
{{
  "direccion": "BULLISH" | "BEARISH" | "NEUTRAL",
  "confianza": <0-100>,
  "magnitud": "PEQUEÑO" | "MEDIANO" | "GRANDE",
  "horizonte": "HORAS" | "DÍAS" | "SEMANAS",
  "explicacion": "<1-2 frases en español, máx 280 chars>"
}}

Reglas:
- BULLISH=sube. BEARISH=baja. NEUTRAL=sin impacto claro o ya descontado.
- Confianza alta (>70) SOLO si la noticia es clara y movedora.
- Magnitud: PEQUEÑO (<2%), MEDIANO (2-5%), GRANDE (>5%).
- PRIMARY (SEC/Fed/Treasury) es oficial — más confiable.
- SOCIAL (Twitter) requiere cautela — verificar si es info original.
- En español, directo, sin disclaimers."""

CONTEXTO_BTC = ("Bitcoin reacciona a: ETFs, FOMC, whales, regulación, hacks, "
                "compras institucionales, eventos macro USA.")
CONTEXTO_PI = ("Pi Network está en fase pre-listing en mainnets mayores. "
               "Reacciona a listings, anuncios del Core Team, hitos de mainnet. "
               "Macro tradicional la afecta poco.")
CONTEXTO_MACRO = ("Macro USA afecta BTC vía expectativas de tasas. CPI/PCE alto → "
                  "Fed hawkish → bearish BTC. Tasas a la baja → bullish BTC.")

def analizar_con_claude(titulo, resumen, target, fuente="", tier="SECONDARY"):
    if not USAR_CLAUDE_API: return None
    contexto = {"BTC":CONTEXTO_BTC,"PI":CONTEXTO_PI,
                "MACRO":CONTEXTO_MACRO}.get(target, CONTEXTO_BTC)
    prompt = PROMPT_ANALISIS.format(
        target=target, titulo=titulo[:300],
        resumen=(resumen or titulo)[:800],
        fuente=fuente, tier=tier, contexto_target=contexto)
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": MODELO_CLAUDE, "max_tokens": 300,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=30)
        if r.status_code == 429:
            time.sleep(5); return None
        if r.status_code != 200:
            log.warning(f"Anthropic {r.status_code}: {r.text[:200]}")
            return None
        data = r.json()
        texto = data["content"][0]["text"].strip()
        m = re.search(r"\{.*\}", texto, re.DOTALL)
        if not m: return None
        a = json.loads(m.group())
        if a.get("direccion") not in ("BULLISH","BEARISH","NEUTRAL"): return None
        u = data.get("usage", {})
        i_t, o_t = u.get("input_tokens",0), u.get("output_tokens",0)
        a["input_tokens"]  = i_t
        a["output_tokens"] = o_t
        a["costo_usd"]     = (i_t * PRECIO_HAIKU_INPUT + o_t * PRECIO_HAIKU_OUTPUT) / 1_000_000
        return a
    except Exception as e:
        log.warning(f"Error Claude: {e}")
        return None

# ══════════════════════════════════════════════════════════════════════════════
# DISCORD
# ══════════════════════════════════════════════════════════════════════════════
COLORES = {"CRÍTICO":0xE74C3C,"ALTO":0xE67E22,"MEDIO":0x3498DB,"BAJO":0x95A5A6,
           "EVENTO":0x9B59B6,"ANÁLISIS":0x2ECC71}
EMOJIS = {"CRÍTICO":"🚨","ALTO":"⚠️","MEDIO":"📰","BAJO":"💬",
          "EVENTO":"📅","ANÁLISIS":"🧠"}
DIR_EMOJI = {"BULLISH":"🟢⬆️","BEARISH":"🔴⬇️","NEUTRAL":"⚪➡️"}
TIER_EMOJI = {"PRIMARY":"⚡","SECONDARY":"📰","SOCIAL":"💬","REDDIT":"👥"}

def barra_confianza(c, ancho=10):
    if c is None: return "—"
    llenos = round(c * ancho / 100)
    return "▓" * llenos + "░" * (ancho - llenos) + f" {c}%"

def discord_send(titulo, descripcion, nivel="MEDIO",
                 url=None, fuente=None, extra_fields=None, tier=None):
    if not DISCORD_WEBHOOK_URL: return False
    emoji = EMOJIS.get(nivel, "📰")
    tit = f"{emoji} {titulo}"
    if tier: tit = f"{TIER_EMOJI.get(tier,'')} {tit}"
    embed = {"title": tit[:256],
             "description": (descripcion or "")[:4000],
             "color": COLORES.get(nivel, 0x95A5A6),
             "timestamp": datetime.now(timezone.utc).isoformat(),
             "fields": []}
    if url: embed["url"] = url
    if fuente: embed["footer"] = {"text": fuente}
    if extra_fields:
        for k, v in extra_fields.items():
            embed["fields"].append({"name": str(k)[:256], "value": str(v)[:1024],
                                    "inline": True})
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json={"embeds":[embed]}, timeout=15)
        if r.status_code == 429:
            retry = r.json().get("retry_after", 2)
            time.sleep(float(retry) + 0.5)
            r = requests.post(DISCORD_WEBHOOK_URL, json={"embeds":[embed]}, timeout=15)
        return 200 <= r.status_code < 300
    except Exception as e:
        log.error(f"Error Discord: {e}")
        return False

# ══════════════════════════════════════════════════════════════════════════════
# SCORING
# ══════════════════════════════════════════════════════════════════════════════
def score_texto(texto):
    t = texto.lower()
    score_btc = sum(p for kw, p in KEYWORDS_BTC.items() if kw in t)
    score_pi  = sum(p for kw, p in KEYWORDS_PI.items()  if kw in t)
    hits_btc  = [kw for kw in KEYWORDS_BTC if kw in t and KEYWORDS_BTC[kw] > 0]
    hits_pi   = [kw for kw in KEYWORDS_PI  if kw in t and KEYWORDS_PI[kw]  > 0]
    menciona_pi  = any(k in t for k in (
        "pi network","pinetwork","pi coin","minepi","$pi",
        "pi/usdt","pi day","pi mainnet","pi blockchain"))
    menciona_btc = any(k in t for k in ("bitcoin","btc"," btc ","btc/","satoshi"))
    if menciona_pi and score_pi > 0:
        return score_pi, "PI", hits_pi
    if menciona_btc and score_btc > 0:
        return score_btc, "BTC", hits_btc
    if score_btc > 0:
        return score_btc, "MACRO", hits_btc
    return 0, "GENERAL", []

def nivel_de_score(score):
    if score >= 10: return "CRÍTICO"
    if score >= 7:  return "ALTO"
    if score >= 4:  return "MEDIO"
    return "BAJO"

# ══════════════════════════════════════════════════════════════════════════════
# FETCHERS
# ══════════════════════════════════════════════════════════════════════════════
def fetch_rss(nombre, url, tier="SECONDARY"):
    try:
        feed = feedparser.parse(url, request_headers={
            "User-Agent": "Mozilla/5.0 (NewsAgent/3.0)"})
        if feed.bozo and not feed.entries: return []
        items = []
        for e in feed.entries[:30]:
            published = getattr(e, "published", "") or getattr(e, "updated", "")
            items.append({
                "title":     getattr(e, "title", "(sin título)"),
                "url":       getattr(e, "link", ""),
                "summary":   getattr(e, "summary", "")[:500],
                "source":    nombre,
                "tier":      tier,
                "published": published,
            })
        return items
    except Exception as ex:
        log.warning(f"  {nombre}: {ex}")
        return []

def fetch_sec_company(name, cik):
    try:
        r = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json",
                         timeout=15, headers={"User-Agent": USER_AGENT_SEC})
        if r.status_code != 200:
            log.debug(f"  SEC {name}: HTTP {r.status_code}")
            return []
        data = r.json()
        recent = data.get("filings", {}).get("recent", {})
        forms       = recent.get("form", [])
        dates       = recent.get("filingDate", [])
        accessions  = recent.get("accessionNumber", [])
        primaryDocs = recent.get("primaryDocument", [])
        items = []
        ahora = datetime.now(timezone.utc)
        for i, form in enumerate(forms[:20]):
            if form not in SEC_FORMS_RELEVANTES: continue
            if i >= len(dates) or i >= len(accessions): break
            try:
                fecha = datetime.strptime(dates[i], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if (ahora - fecha).total_seconds() > 2 * 86400: continue
            adsh = accessions[i].replace("-", "")
            doc  = primaryDocs[i] if i < len(primaryDocs) else ""
            url_filing = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{adsh}/{doc}"
            items.append({
                "title":     f"SEC {form} — {name}",
                "url":       url_filing,
                "summary":   (f"{name} presentó filing {form} ante la SEC. "
                              f"8-K = eventos materiales. Fecha: {dates[i]}."),
                "source":    f"SEC EDGAR · {name}",
                "tier":      "PRIMARY",
                "published": dates[i],
            })
        return items
    except Exception as ex:
        log.debug(f"  SEC {name}: {ex}")
        return []

def fetch_todas_sec():
    todos = []
    for name, cik in SEC_COMPANIES.items():
        items = fetch_sec_company(name, cik)
        todos.extend(items)
        time.sleep(0.15)
    return todos

_nitter_actual = None

def encontrar_nitter_activo():
    global _nitter_actual
    if _nitter_actual:
        try:
            r = requests.get(_nitter_actual + "/EricBalchunas/rss", timeout=8,
                             headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200 and "rss" in r.text[:200].lower():
                return _nitter_actual
        except Exception:
            pass
        _nitter_actual = None
    for inst in NITTER_INSTANCES:
        try:
            r = requests.get(inst + "/EricBalchunas/rss", timeout=8,
                             headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200 and "rss" in r.text[:200].lower():
                _nitter_actual = inst
                log.info(f"  Nitter: usando {inst}")
                return inst
        except Exception:
            continue
    log.warning("  Nitter: ninguna instancia disponible")
    return None

def fetch_twitter_user(username, instance):
    try:
        feed = feedparser.parse(f"{instance}/{username}/rss",
                                request_headers={"User-Agent": "Mozilla/5.0 (NewsAgent/3.0)"})
        if feed.bozo and not feed.entries: return []
        items = []
        for e in feed.entries[:10]:
            title = getattr(e, "title", "")
            if title.startswith("RT @"): continue
            items.append({
                "title":     f"@{username}: {title[:200]}",
                "url":       getattr(e, "link", ""),
                "summary":   getattr(e, "summary", "")[:500],
                "source":    f"X · @{username}",
                "tier":      "SOCIAL",
                "published": getattr(e, "published", ""),
            })
        return items
    except Exception:
        return []

def fetch_todas_x():
    instance = encontrar_nitter_activo()
    if not instance: return []
    todos = []
    for user in CUENTAS_X:
        items = fetch_twitter_user(user, instance)
        todos.extend(items)
        time.sleep(0.3)
    return todos

def fetch_cryptopanic():
    if not CRYPTOPANIC_TOKEN: return []
    url = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTOPANIC_TOKEN}&filter=hot&kind=news"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200: return []
        return [{
            "title":     p.get("title", ""),
            "url":       p.get("url", ""),
            "summary":   p.get("title", ""),
            "source":    f"CryptoPanic ({p.get('source',{}).get('title','?')})",
            "tier":      "SECONDARY",
            "published": p.get("published_at", ""),
        } for p in r.json().get("results", [])]
    except Exception:
        return []

# ══════════════════════════════════════════════════════════════════════════════
# CALENDARIO MACRO
# ══════════════════════════════════════════════════════════════════════════════
FOREXFACTORY_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

def fetch_calendario_macro():
    try:
        r = requests.get(FOREXFACTORY_URL, timeout=20,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200: return []
        eventos = []
        for ev in r.json():
            if ev.get("country") != "USD": continue
            if ev.get("impact","").lower() not in ("high","medium"): continue
            title = ev.get("title", "")
            if not any(k.lower() in title.lower() for k in EVENTOS_MACRO_KEYS): continue
            try:
                dt = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
            except Exception:
                continue
            eventos.append({"id": f"{title}_{ev['date']}", "title": title,
                            "scheduled": dt, "impact": ev["impact"].upper(),
                            "forecast": ev.get("forecast",""),
                            "previous": ev.get("previous",""),
                            "actual":   ev.get("actual","")})
        return eventos
    except Exception:
        return []

def parsear_numero(s):
    if not s: return None
    m = re.search(r"-?\d+\.?\d*", str(s).replace(",", ""))
    return float(m.group()) if m else None

def analizar_evento_macro(title, forecast, previous, actual):
    f, p, a = parsear_numero(forecast), parsear_numero(previous), parsear_numero(actual)
    t = title.lower()
    if a is None: return None
    msg, direccion = [], "NEUTRAL"
    if any(k in t for k in ["cpi","pce","ppi"]):
        if f is not None:
            if a > f + 0.05:
                direccion = "BEARISH BTC"
                msg.append(f"Inflación SOBRE forecast ({a} vs {f}) → Fed hawkish, "
                           f"BTC suele caer 1-3%.")
            elif a < f - 0.05:
                direccion = "BULLISH BTC"
                msg.append(f"Inflación BAJO forecast ({a} vs {f}) → Fed dovish. "
                           f"BTC suele rebotar 1-4%.")
            else:
                msg.append(f"Inflación EN LÍNEA ({a} vs {f}) → impacto limitado.")
    elif "fomc" in t or "federal funds" in t:
        if p is not None:
            if a < p:
                direccion = "BULLISH BTC"
                msg.append(f"Recorte tasa ({a}% desde {p}%) → BTC suele subir 3-8%.")
            elif a > p:
                direccion = "BEARISH BTC"
                msg.append(f"Subida tasa ({a}% desde {p}%) → BTC suele caer 2-5%.")
            else:
                msg.append(f"Tasa SIN CAMBIO ({a}%) — depende del tono del comunicado.")
    elif "non-farm" in t or "nfp" in t:
        if f is not None:
            if a > f * 1.15:
                direccion = "MIXTO — BEARISH inicial"
                msg.append(f"NFP MUY SOBRE forecast ({a}K vs {f}K) → BTC -1-3%.")
            elif a < f * 0.85:
                direccion = "BULLISH BTC"
                msg.append(f"NFP MUY BAJO forecast ({a}K vs {f}K) → BTC +2-4%.")
    msg.append("\nNota: Pi reacciona poco a macro tradicional.")
    return f"**Dirección esperada: {direccion}**\n\n" + "\n".join(msg)

# ══════════════════════════════════════════════════════════════════════════════
# CICLO NOTICIAS
# ══════════════════════════════════════════════════════════════════════════════
def construir_descripcion(summary, analisis, tier=None):
    bloques = []
    tier_label = {"PRIMARY":   "⚡ FUENTE PRIMARIA (oficial — alta velocidad)",
                  "SECONDARY": "📰 Fuente secundaria",
                  "SOCIAL":    "💬 Fuente social (X/Twitter)",
                  "REDDIT":    "👥 Reddit (alto ruido)"}.get(tier, "")
    if tier_label: bloques.append(f"_{tier_label}_")
    if analisis:
        de = DIR_EMOJI.get(analisis["direccion"], "❓")
        bloques.append(
            f"**{de} {analisis['direccion']}**  ·  Magnitud **{analisis.get('magnitud','—')}**  ·  "
            f"Horizonte **{analisis.get('horizonte','—')}**\n"
            f"Confianza: `{barra_confianza(analisis.get('confianza',0))}`\n\n"
            f"**Análisis:** {analisis.get('explicacion','')}"
        )
    if summary: bloques.append(f"_Resumen:_ {summary[:300]}")
    return "\n\n".join(bloques)

def ciclo_noticias(conn):
    log.info("─── Ciclo noticias ───")
    todos = []
    cont = {"PRIMARY":0, "SECONDARY":0, "SOCIAL":0, "REDDIT":0}

    log.info("  ▼ PRIMARIAS")
    for nombre, url in RSS_PRIMARIOS:
        items = fetch_rss(nombre, url, tier="PRIMARY")
        log.info(f"    {nombre}: {len(items)}")
        todos.extend(items)
        cont["PRIMARY"] += len(items)
        time.sleep(0.3)

    sec_items = fetch_todas_sec()
    log.info(f"    SEC EDGAR: {len(sec_items)} filings recientes")
    todos.extend(sec_items)
    cont["PRIMARY"] += len(sec_items)

    log.info("  ▼ SECUNDARIAS")
    for nombre, url in RSS_SECUNDARIOS:
        items = fetch_rss(nombre, url, tier="SECONDARY")
        log.info(f"    {nombre}: {len(items)}")
        todos.extend(items)
        cont["SECONDARY"] += len(items)
        time.sleep(0.3)

    cp = fetch_cryptopanic()
    if cp:
        log.info(f"    CryptoPanic: {len(cp)}")
        todos.extend(cp)
        cont["SECONDARY"] += len(cp)

    log.info("  ▼ Reddit")
    for nombre, url in RSS_REDDIT:
        items = fetch_rss(nombre, url, tier="REDDIT")
        log.info(f"    {nombre}: {len(items)}")
        todos.extend(items)
        cont["REDDIT"] += len(items)
        time.sleep(0.3)

    log.info("  ▼ X/Twitter (Nitter)")
    x_items = fetch_todas_x()
    log.info(f"    X: {len(x_items)} tweets")
    todos.extend(x_items)
    cont["SOCIAL"] += len(x_items)

    log.info(f"  TOTAL: {len(todos)} (P={cont['PRIMARY']} "
             f"S={cont['SECONDARY']} R={cont['REDDIT']} X={cont['SOCIAL']})")

    enviados, analizados, costo = 0, 0, 0.0
    for it in todos:
        if not it.get("url") or not it.get("title"): continue
        if ya_visto(conn, it["url"]): continue

        tier = it.get("tier", "SECONDARY")
        boost = BOOST_TIER.get(tier, 0)
        texto = f"{it['title']} {it.get('summary','')}"
        score, target, hits = score_texto(texto)
        score_final = score + boost
        nivel = nivel_de_score(score_final)

        if score_final < SCORE_MINIMO_ENVIAR:
            marcar_visto(conn, it["url"], it["title"], it["source"],
                         score_final, nivel, target, tier=tier,
                         published_at=it.get("published"))
            continue

        if enviados >= MAX_NOTIS_POR_CICLO:
            marcar_visto(conn, it["url"], it["title"], it["source"],
                         score_final, nivel, target, tier=tier,
                         published_at=it.get("published"))
            continue

        analisis = None
        if USAR_CLAUDE_API:
            analisis = analizar_con_claude(it["title"], it.get("summary",""),
                                           target, it["source"], tier)
            if analisis:
                analizados += 1
                costo += analisis.get("costo_usd", 0.0)
                guardar_analisis(conn, it["url"], analisis)
                if (SUPRIMIR_NEUTRAL and analisis["direccion"] == "NEUTRAL"
                    and analisis.get("confianza", 0) >= 80):
                    log.info(f"  [SUPRIMIDA] {it['title'][:65]}")
                    marcar_visto(conn, it["url"], it["title"], it["source"],
                                 score_final, nivel, target,
                                 direccion="NEUTRAL",
                                 confianza=analisis.get("confianza"),
                                 tier=tier, published_at=it.get("published"))
                    continue

        log.info(f"  [{nivel}/{target}/{tier}/{score_final}] "
                 f"{(analisis['direccion'] if analisis else '?'):>8} → "
                 f"{it['title'][:60]}")

        descripcion = construir_descripcion(it.get("summary",""), analisis, tier)
        extra = {"Keywords": ", ".join(hits[:5]) or "—", "Tier": tier}
        if analisis: extra["Costo IA"] = f"${analisis.get('costo_usd',0):.5f}"

        ok = discord_send(
            titulo=it["title"], descripcion=descripcion, nivel=nivel,
            url=it["url"],
            fuente=f"{it['source']} · {target} · score={score_final}",
            extra_fields=extra, tier=tier,
        )
        if ok:
            enviados += 1
            marcar_visto(conn, it["url"], it["title"], it["source"],
                         score_final, nivel, target,
                         direccion=analisis["direccion"] if analisis else None,
                         confianza=analisis.get("confianza") if analisis else None,
                         tier=tier, published_at=it.get("published"))
            time.sleep(1.2)

    log.info(f"  → {enviados} envíos · {analizados} IA · costo: ${costo:.4f}")

# ══════════════════════════════════════════════════════════════════════════════
# CICLO EVENTOS
# ══════════════════════════════════════════════════════════════════════════════
def ciclo_eventos(conn):
    log.info("─── Calendario macro ───")
    eventos = fetch_calendario_macro()
    log.info(f"  {len(eventos)} eventos")
    ahora = datetime.now(timezone.utc)
    for ev in eventos:
        delta = (ev["scheduled"] - ahora).total_seconds() / 60.0
        for marca in PRE_ALERTAS_MIN:
            tol = INTERVALO_EVENTOS_HRS * 60 / 2 + 5
            if abs(delta - marca) <= tol and delta > 0:
                aid = f"pre_{marca}"
                if not alerta_ya_enviada(conn, ev["id"], aid):
                    cuando = (f"en {marca//60}h {marca%60}min" if marca >= 60
                              else f"en {marca}min")
                    discord_send(
                        titulo=f"Próximo: {ev['title']}",
                        descripcion=(f"Evento macro **{cuando}** "
                                     f"({ev['scheduled'].strftime('%Y-%m-%d %H:%M UTC')})\n\n"
                                     f"**Impacto:** {ev['impact']}\n"
                                     f"**Forecast:** {ev['forecast'] or '—'}\n"
                                     f"**Anterior:** {ev['previous'] or '—'}\n\n"
                                     f"Prepárate."),
                        nivel="EVENTO",
                        fuente="Calendario macro · ForexFactory")
                    marcar_alerta(conn, ev["id"], aid)
        if delta < 0 and abs(delta) < 60 * 24:
            if ev.get("actual") and not alerta_ya_enviada(conn, ev["id"], "post"):
                analisis_rb = analizar_evento_macro(
                    ev["title"], ev["forecast"], ev["previous"], ev["actual"])
                if analisis_rb:
                    discord_send(
                        titulo=f"Resultado: {ev['title']}",
                        descripcion=analisis_rb, nivel="ANÁLISIS",
                        fuente="Análisis automático · rule-based",
                        extra_fields={"Actual": ev["actual"],
                                      "Forecast": ev["forecast"] or "—",
                                      "Anterior": ev["previous"] or "—"})
                    marcar_alerta(conn, ev["id"], "post")

# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════
def test_envio():
    log.info("Test Discord...")
    ok = discord_send(
        titulo="News Agent v3 funcionando",
        descripcion=("Si ves esto, todo conecta.\n"
                     f"IA: {'ACTIVADO' if USAR_CLAUDE_API else 'OFF'}\n"
                     f"Tiers: PRIMARY/SECONDARY/SOCIAL/REDDIT"),
        nivel="ALTO",
        fuente=f"v3 · {len(SEC_COMPANIES)} cías SEC · {len(CUENTAS_X)} cuentas X",
        extra_fields={"Hora": datetime.now().strftime("%H:%M:%S"),
                      "Modelo": MODELO_CLAUDE if USAR_CLAUDE_API else "—"})
    log.info("✓ OK" if ok else "✗ FALLÓ")

def test_analisis(titulo):
    if not USAR_CLAUDE_API:
        log.error("Sin ANTHROPIC_API_KEY"); return
    score, target, _ = score_texto(titulo)
    if target == "GENERAL": target = "BTC"
    a = analizar_con_claude(titulo, "", target, "test", "PRIMARY")
    print(json.dumps(a, indent=2, ensure_ascii=False) if a else "Falló")

def mostrar_costos():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    n, in_t, out_t, costo = c.execute(
        "SELECT COUNT(*), SUM(input_tokens), SUM(output_tokens), SUM(costo_usd) "
        "FROM ai_analysis").fetchone()
    print(f"Análisis IA: {n}  ·  Tokens: {in_t or 0:,} in / {out_t or 0:,} out")
    print(f"Costo total: ${costo or 0:.4f}")
    r30 = c.execute("SELECT SUM(costo_usd) FROM ai_analysis "
                    "WHERE timestamp > datetime('now','-30 days')").fetchone()
    print(f"Últimos 30d: ${r30[0] or 0:.4f}")
    print("\nTier de notificaciones (últimos 7 días):")
    for t, n in c.execute("""SELECT tier, COUNT(*) FROM seen_articles
                             WHERE direccion IS NOT NULL
                               AND timestamp > datetime('now','-7 days')
                             GROUP BY tier""").fetchall():
        print(f"  {t}: {n}")
    conn.close()

def debug_sec():
    print("=== Test SEC EDGAR ===")
    print(f"User-Agent: {USER_AGENT_SEC}")
    for name, cik in list(SEC_COMPANIES.items())[:5]:
        items = fetch_sec_company(name, cik)
        print(f"\n{name} (CIK {cik}): {len(items)} filings recientes")
        for it in items[:3]:
            print(f"  {it['title']}")
            print(f"  {it['url']}")

def debug_nitter():
    print("=== Test Nitter ===")
    inst = encontrar_nitter_activo()
    if not inst:
        print("Ninguna instancia activa. Las instancias de Nitter mueren con frecuencia.")
        print("Lista de instancias actuales: https://github.com/zedeus/nitter/wiki/Instances")
        return
    print(f"Activa: {inst}\n")
    for user in CUENTAS_X[:5]:
        items = fetch_twitter_user(user, inst)
        print(f"@{user}: {len(items)} tweets")
        for it in items[:2]:
            print(f"  {it['title'][:100]}")

def main():
    if "--test" in sys.argv:    test_envio(); return
    if "--costs" in sys.argv:   mostrar_costos(); return
    if "--sec" in sys.argv:     debug_sec(); return
    if "--nitter" in sys.argv:  debug_nitter(); return
    if "--analyze" in sys.argv:
        idx = sys.argv.index("--analyze")
        if idx + 1 < len(sys.argv):
            test_analisis(sys.argv[idx + 1])
        return

    if not DISCORD_WEBHOOK_URL:
        log.error("Falta DISCORD_WEBHOOK_URL"); sys.exit(1)

    conn = db_init()
    log.info("═══ News Agent v3 iniciado ═══")
    log.info(f"IA:               {'ACTIVADO ('+MODELO_CLAUDE+')' if USAR_CLAUDE_API else 'OFF'}")
    log.info(f"Suprimir NEUTRAL: {SUPRIMIR_NEUTRAL}")
    log.info(f"Score mín:        {SCORE_MINIMO_ENVIAR} (+boost por tier)")
    log.info(f"Intervalo:        {INTERVALO_SEGUNDOS}s")
    log.info(f"SEC companies:    {len(SEC_COMPANIES)}")
    log.info(f"X accounts:       {len(CUENTAS_X)}")

    if "--once" in sys.argv:
        ciclo_noticias(conn); ciclo_eventos(conn); return

    ult = 0
    while True:
        try:
            ciclo_noticias(conn)
            if time.time() - ult > INTERVALO_EVENTOS_HRS * 3600:
                ciclo_eventos(conn); ult = time.time()
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.exception(f"Error: {e}")
        time.sleep(INTERVALO_SEGUNDOS)

if __name__ == "__main__":
    main()
