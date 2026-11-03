#!/usr/bin/env python3
"""
News Agent v1 — Monitoreo en vivo de noticias BTC + Pi Network
─────────────────────────────────────────────────────────────────
Notifica vía Discord webhook cuando aparecen noticias con potencial
impacto en precio. Filtra por keywords + pesos. Avisa antes y después
de eventos macro programados (FOMC, CPI, NFP, PCE, etc.).

Uso:
    python news_agent_v1.py            # loop continuo
    python news_agent_v1.py --once     # una sola pasada (debug)
    python news_agent_v1.py --test     # envía un mensaje de prueba a Discord
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
CRYPTOPANIC_TOKEN     = os.getenv("CRYPTOPANIC_TOKEN", "").strip()  # opcional

INTERVALO_SEGUNDOS    = 180        # cada 3 min revisa noticias
INTERVALO_EVENTOS_HRS = 6          # cada 6h refresca calendario macro
SCORE_MINIMO_ENVIAR   = 7          # umbral: solo notifica si score >= 7 (ALTO+)
MAX_NOTIS_POR_CICLO   = 8          # rate limit interno
DB_PATH               = BASE / "news_agent.db"

# Pre-alertas de eventos macro: en estas marcas (en minutos) antes del evento
PRE_ALERTAS_MIN       = [60 * 24, 60, 15]   # T-24h, T-1h, T-15min

# ══════════════════════════════════════════════════════════════════════════════
# FUENTES RSS
# ══════════════════════════════════════════════════════════════════════════════
RSS_FEEDS = [
    # Bitcoin / cripto general
    ("CoinDesk",        "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph",   "https://cointelegraph.com/rss"),
    ("Bitcoin Magazine","https://bitcoinmagazine.com/.rss/full/"),
    ("Decrypt",         "https://decrypt.co/feed"),
    ("BeInCrypto",      "https://beincrypto.com/feed/"),
    ("CryptoSlate",     "https://cryptoslate.com/feed/"),
    ("The Block",       "https://www.theblock.co/rss.xml"),
    # Pi Network — comunidad
    ("r/PiNetwork",     "https://www.reddit.com/r/PiNetwork/new/.rss"),
    ("Pi Blog",         "https://minepi.com/blog/feed/"),  # puede 404 — se ignora si falla
]

# ══════════════════════════════════════════════════════════════════════════════
# KEYWORDS Y PESOS — clasificación de impacto
# ══════════════════════════════════════════════════════════════════════════════
# Cada keyword suma su peso al score total de la noticia.
# Score final determina nivel: <4 BAJO, 4-6 MEDIO, 7-9 ALTO, >=10 CRÍTICO

KEYWORDS_BTC = {
    # CRÍTICO (peso alto: noticias movedoras de mercado)
    "etf approval":        12, "etf approved":      12, "etf rejected":       12,
    "etf denial":          12, "spot bitcoin etf":   8, "etf inflow":          5,
    "etf outflow":          5, "blackrock":          4, "fidelity":            3,
    "sec lawsuit":         10, "sec sues":          10, "sec settles":         8,
    "ban bitcoin":         12, "bitcoin banned":    12, "outlaw":              8,
    "hack":                10, "exploit":            8, "stolen":              7,
    "exchange collapse":   12, "bankruptcy":         9, "insolvent":           9,
    "halving":              6, "mt gox":             8, "satoshi":             6,
    "michael saylor":       4, "microstrategy buy":  6, "microstrategy sell":  8,
    "el salvador":          4, "strategic reserve":  9, "national reserve":    8,
    "trump bitcoin":        6, "biden bitcoin":      4,
    # ALTO
    "whale transfer":       5, "whale moved":        5, "large transfer":      4,
    "regulation":           5, "regulatory":         4, "lawsuit":             5,
    "approval":             4, "rejected":           4, "listing":             4,
    "delisting":            6, "exchange hack":      9, "bridge hack":         8,
    "all-time high":        4, "ath":                3, "new high":            3,
    "crash":                6, "plunge":             5, "surge":               4,
    # MEDIO
    "rally":                2, "pump":               1, "dump":                2,
    "analyst":              0, "prediction":         0, "forecast":            0,
    "adoption":             3, "institutional":      3, "bullish":             1,
    "bearish":              1, "support":            0, "resistance":          0,
    # MACRO — afectan BTC directamente
    "fomc":                 6, "fed minutes":        5, "fed meeting":         5,
    "rate cut":             7, "rate hike":          6, "rates unchanged":     4,
    "powell speech":        5, "powell testimony":   5, "jerome powell":       3,
    "cpi release":          5, "core cpi":           5, "inflation data":      4,
    "pce release":          5, "core pce":           5, "ppi release":         4,
    "non-farm payrolls":    4, "nfp report":         4, "jobs report":         3,
    "fed minutes":          4, "interest rate":      2, "monetary policy":     3,
    "yield curve":          3, "treasury yield":     2, "dollar index":        2,
    # Detectores de target (no aportan score, solo identifican target)
    "bitcoin":              0, "btc":                0,
}

KEYWORDS_PI = {
    # CRÍTICO para Pi
    "pi mainnet":          10, "open mainnet":      12, "mainnet launch":     12,
    "binance listing":     12, "coinbase listing":  12, "okx listing":        10,
    "bybit listing":       10, "kraken listing":    10, "kucoin listing":      8,
    "pi listing":           9, "pi listed":          9,
    "pi migration":         7, "kyc complete":       6, "pi delisting":      10,
    "pi network ban":      10, "pi banned":          9,
    # ALTO
    "pi day":               5, "pi network update": 4, "pi blockchain":       4,
    "pi node":              3, "pi browser":         2, "pi app":              2,
    "pi core team":         4, "nicolas kokkalis":   4, "chengdiao fan":       4,
    "pi partnership":       6, "pi roadmap":         5, "pi tokenomics":       5,
    "open network":         6, "enclosed network":   4,
    # General Pi (detectores de target — no aportan score solos)
    "pi network":           1, "pi coin":            1, "pi/usdt":             3,
    "minepi":               1, "$pi":                1,
}

# Eventos macro relevantes para BTC (calendar — ForexFactory JSON)
EVENTOS_MACRO_KEYS = [
    "FOMC", "Federal Funds", "Fed Chair", "Powell",
    "CPI", "Core CPI", "PCE", "Core PCE",
    "Non-Farm", "Unemployment", "NFP",
    "PPI", "GDP", "Retail Sales", "Consumer Confidence",
]

# ══════════════════════════════════════════════════════════════════════════════
# STORAGE — SQLite
# ══════════════════════════════════════════════════════════════════════════════
def db_init():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS seen_articles (
            url_hash TEXT PRIMARY KEY,
            title TEXT, source TEXT, url TEXT,
            score INTEGER, nivel TEXT, target TEXT,
            timestamp TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS event_alerts (
            event_id TEXT, alert_type TEXT,
            sent_at TEXT,
            PRIMARY KEY (event_id, alert_type)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS event_results (
            event_id TEXT PRIMARY KEY,
            title TEXT, country TEXT, scheduled_at TEXT,
            forecast TEXT, previous TEXT, actual TEXT,
            analyzed INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn

def url_hash(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()

def ya_visto(conn, url: str) -> bool:
    c = conn.cursor()
    c.execute("SELECT 1 FROM seen_articles WHERE url_hash = ?", (url_hash(url),))
    return c.fetchone() is not None

def marcar_visto(conn, url, title, source, score, nivel, target):
    c = conn.cursor()
    c.execute("""INSERT OR IGNORE INTO seen_articles
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
              (url_hash(url), title, source, url, score, nivel, target,
               datetime.now(timezone.utc).isoformat()))
    conn.commit()

def alerta_ya_enviada(conn, event_id, alert_type) -> bool:
    c = conn.cursor()
    c.execute("SELECT 1 FROM event_alerts WHERE event_id=? AND alert_type=?",
              (event_id, alert_type))
    return c.fetchone() is not None

def marcar_alerta(conn, event_id, alert_type):
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO event_alerts VALUES (?, ?, ?)",
              (event_id, alert_type, datetime.now(timezone.utc).isoformat()))
    conn.commit()

# ══════════════════════════════════════════════════════════════════════════════
# DISCORD NOTIFIER
# ══════════════════════════════════════════════════════════════════════════════
COLORES = {
    "CRÍTICO": 0xE74C3C,   # rojo
    "ALTO":    0xE67E22,   # naranja
    "MEDIO":   0x3498DB,   # azul
    "BAJO":    0x95A5A6,   # gris
    "EVENTO":  0x9B59B6,   # morado
    "ANÁLISIS":0x2ECC71,   # verde
}
EMOJIS = {
    "CRÍTICO": "🚨", "ALTO": "⚠️", "MEDIO": "📰", "BAJO": "💬",
    "EVENTO":  "📅", "ANÁLISIS": "🧠",
}

def discord_send(titulo, descripcion, nivel="MEDIO",
                 url=None, fuente=None, extra_fields=None):
    if not DISCORD_WEBHOOK_URL:
        log.warning("Sin DISCORD_WEBHOOK_URL configurado — no se envía")
        return False
    emoji = EMOJIS.get(nivel, "📰")
    embed = {
        "title": f"{emoji} {titulo}"[:256],
        "description": (descripcion or "")[:4000],
        "color": COLORES.get(nivel, 0x95A5A6),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [],
    }
    if url:
        embed["url"] = url
    if fuente:
        embed["footer"] = {"text": fuente}
    if extra_fields:
        for name, value in extra_fields.items():
            embed["fields"].append({"name": str(name)[:256],
                                    "value": str(value)[:1024],
                                    "inline": True})
    payload = {"embeds": [embed]}
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        if r.status_code == 429:
            retry = r.json().get("retry_after", 2)
            time.sleep(float(retry) + 0.5)
            r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        if 200 <= r.status_code < 300:
            return True
        log.warning(f"Discord respondió {r.status_code}: {r.text[:200]}")
        return False
    except Exception as e:
        log.error(f"Error enviando a Discord: {e}")
        return False

# ══════════════════════════════════════════════════════════════════════════════
# SCORING
# ══════════════════════════════════════════════════════════════════════════════
def score_texto(texto: str):
    """Devuelve (score_total, target, hits) para un texto dado.

    Target se detecta por presencia de menciones (Pi tiene prioridad si aparece).
    Score solo suma keywords semánticas, no detectores de target.
    """
    t = texto.lower()
    score_btc = sum(p for kw, p in KEYWORDS_BTC.items() if kw in t)
    score_pi  = sum(p for kw, p in KEYWORDS_PI.items()  if kw in t)
    hits_btc  = [kw for kw in KEYWORDS_BTC if kw in t and KEYWORDS_BTC[kw] > 0]
    hits_pi   = [kw for kw in KEYWORDS_PI  if kw in t and KEYWORDS_PI[kw]  > 0]

    # Detectar target por presencia explícita
    menciona_pi  = any(k in t for k in (
        "pi network", "pinetwork", "pi coin", "minepi", "$pi",
        "pi/usdt", "pi day", "pi mainnet", "pi blockchain",
    ))
    menciona_btc = any(k in t for k in ("bitcoin", "btc", " btc ", "btc/", "satoshi"))

    # Pi tiene prioridad si se menciona — ecosistema más pequeño, menos cobertura
    if menciona_pi and score_pi > 0:
        target, score, hits = "PI", score_pi, hits_pi
    elif menciona_btc and score_btc > 0:
        target, score, hits = "BTC", score_btc, hits_btc
    elif score_btc > 0:  # noticia macro sin BTC explícito pero con keywords macro
        target, score, hits = "MACRO", score_btc, hits_btc
    else:
        target, score, hits = "GENERAL", 0, []
    return score, target, hits

def nivel_de_score(score: int) -> str:
    if score >= 10: return "CRÍTICO"
    if score >= 7:  return "ALTO"
    if score >= 4:  return "MEDIO"
    return "BAJO"

# ══════════════════════════════════════════════════════════════════════════════
# FUENTES — RSS
# ══════════════════════════════════════════════════════════════════════════════
def fetch_rss(nombre, url):
    """Devuelve lista de dicts {title, url, summary, published, source}."""
    try:
        feed = feedparser.parse(url, request_headers={
            "User-Agent": "Mozilla/5.0 (NewsAgent/1.0)"
        })
        if feed.bozo and not feed.entries:
            log.debug(f"  {nombre}: feed vacío o malformado")
            return []
        items = []
        for e in feed.entries[:30]:
            items.append({
                "title":   getattr(e, "title", "(sin título)"),
                "url":     getattr(e, "link", ""),
                "summary": getattr(e, "summary", "")[:500],
                "source":  nombre,
            })
        return items
    except Exception as ex:
        log.warning(f"  {nombre}: error fetch RSS — {ex}")
        return []

def fetch_cryptopanic():
    """Opcional: requiere token gratis en cryptopanic.com"""
    if not CRYPTOPANIC_TOKEN:
        return []
    url = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTOPANIC_TOKEN}&filter=hot&kind=news"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        items = []
        for p in data.get("results", []):
            items.append({
                "title":   p.get("title", ""),
                "url":     p.get("url", ""),
                "summary": p.get("title", ""),
                "source":  f"CryptoPanic ({p.get('source',{}).get('title','?')})",
            })
        return items
    except Exception as ex:
        log.warning(f"CryptoPanic error: {ex}")
        return []

# ══════════════════════════════════════════════════════════════════════════════
# CALENDARIO MACRO — ForexFactory JSON público
# ══════════════════════════════════════════════════════════════════════════════
FOREXFACTORY_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

def fetch_calendario_macro():
    """Lista de eventos US de impacto medio/alto que matcheen EVENTOS_MACRO_KEYS."""
    try:
        r = requests.get(FOREXFACTORY_URL, timeout=20,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            log.warning(f"ForexFactory respondió {r.status_code}")
            return []
        data = r.json()
        eventos = []
        for ev in data:
            if ev.get("country") != "USD":
                continue
            impact = ev.get("impact", "").lower()
            if impact not in ("high", "medium"):
                continue
            title = ev.get("title", "")
            if not any(k.lower() in title.lower() for k in EVENTOS_MACRO_KEYS):
                continue
            # Parse fecha — formato ISO con timezone
            try:
                dt = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
            except Exception:
                continue
            eventos.append({
                "id":        f"{title}_{ev['date']}",
                "title":     title,
                "scheduled": dt,
                "impact":    impact.upper(),
                "forecast":  ev.get("forecast", ""),
                "previous":  ev.get("previous", ""),
                "actual":    ev.get("actual", ""),
            })
        return eventos
    except Exception as ex:
        log.warning(f"Error fetching calendario macro: {ex}")
        return []

# ══════════════════════════════════════════════════════════════════════════════
# ANÁLISIS DE IMPACTO POST-EVENTO (rule-based)
# ══════════════════════════════════════════════════════════════════════════════
def parsear_numero(s):
    """Extrae el primer número de un string como '3.2%' → 3.2"""
    if not s: return None
    m = re.search(r"-?\d+\.?\d*", str(s).replace(",", ""))
    return float(m.group()) if m else None

def analizar_impacto(title: str, forecast, previous, actual):
    """Análisis rule-based del impacto esperado en BTC."""
    f = parsear_numero(forecast)
    p = parsear_numero(previous)
    a = parsear_numero(actual)
    t = title.lower()

    if a is None:
        return None  # no hay dato actual aún

    msg = []
    direccion = "NEUTRAL"

    # CPI / PCE / PPI: inflación
    if any(k in t for k in ["cpi", "pce", "ppi"]):
        if f is not None:
            if a > f + 0.05:
                direccion = "BEARISH BTC"
                msg.append(f"Inflación SOBRE forecast ({a} vs {f}) → Fed más hawkish, "
                           f"presión bajista en BTC corto plazo. Históricamente BTC cae 1-3% intradía.")
            elif a < f - 0.05:
                direccion = "BULLISH BTC"
                msg.append(f"Inflación BAJO forecast ({a} vs {f}) → Fed más dovish, "
                           f"alivio para activos de riesgo. BTC suele rebotar 1-4%.")
            else:
                direccion = "NEUTRAL"
                msg.append(f"Inflación EN LÍNEA ({a} vs forecast {f}) → impacto limitado, "
                           f"mercado ya descontaba este nivel.")

    # FOMC / tasas
    elif "fomc" in t or "federal funds" in t:
        if p is not None:
            if a < p:
                direccion = "BULLISH BTC"
                msg.append(f"Recorte de tasa ({a}% desde {p}%) → muy bullish para BTC. "
                           f"Liquidez al alza, históricamente BTC sube 3-8% en sesiones siguientes.")
            elif a > p:
                direccion = "BEARISH BTC"
                msg.append(f"Subida de tasa ({a}% desde {p}%) → bearish corto plazo. "
                           f"BTC suele caer 2-5% pero tiende a recuperar si era esperado.")
            else:
                direccion = "NEUTRAL → depende del comunicado"
                msg.append(f"Tasa SIN CAMBIO ({a}%). El impacto vendrá del lenguaje del FOMC "
                           f"y la rueda de prensa de Powell — ojo a 'higher for longer' (bearish) "
                           f"o señales de cortes (bullish).")

    # NFP / Empleo
    elif "non-farm" in t or "nfp" in t:
        if f is not None:
            if a > f * 1.15:
                direccion = "MIXTO — BEARISH inicial"
                msg.append(f"NFP MUY SOBRE forecast ({a}K vs {f}K) → economía fuerte, "
                           f"Fed mantiene tasas altas. BTC suele caer 1-3% por dólar fuerte.")
            elif a < f * 0.85:
                direccion = "BULLISH BTC"
                msg.append(f"NFP MUY BAJO forecast ({a}K vs {f}K) → debilidad económica, "
                           f"acelera expectativa de cortes. BTC suele subir 2-4%.")
            else:
                direccion = "NEUTRAL"
                msg.append(f"NFP en línea ({a}K vs {f}K).")

    # Unemployment
    elif "unemployment" in t:
        if f is not None:
            if a > f:
                direccion = "BULLISH BTC"
                msg.append(f"Desempleo SOBRE forecast ({a}% vs {f}%) → Fed presionada a "
                           f"recortar. Bullish moderado para BTC.")
            elif a < f:
                direccion = "BEARISH BTC"
                msg.append(f"Desempleo BAJO forecast ({a}% vs {f}%) → mercado laboral fuerte, "
                           f"Fed mantiene línea dura. Bearish moderado para BTC.")

    # GDP
    elif "gdp" in t:
        if f is not None:
            if a > f:
                direccion = "MIXTO"
                msg.append(f"GDP fuerte ({a}% vs {f}%): bueno para risk-on en general "
                           f"pero refuerza Fed hawkish — neto suele ser bearish BTC corto.")
            else:
                direccion = "BULLISH BTC"
                msg.append(f"GDP débil ({a}% vs {f}%) → expectativa de cortes sube, "
                           f"bullish para BTC.")

    # Pi Network: estos eventos macro afectan poco a Pi (pre-listing en mainnets mayores)
    msg.append("\nNota: Pi Network reacciona menos a macro tradicional, "
               "más a hitos propios (listings, mainnet, migración).")

    return f"**Dirección esperada: {direccion}**\n\n" + "\n".join(msg)

# ══════════════════════════════════════════════════════════════════════════════
# CICLO DE NOTICIAS
# ══════════════════════════════════════════════════════════════════════════════
def ciclo_noticias(conn):
    log.info("─── Ciclo de noticias ───")
    todos = []

    for nombre, url in RSS_FEEDS:
        items = fetch_rss(nombre, url)
        log.info(f"  {nombre}: {len(items)} items")
        todos.extend(items)
        time.sleep(0.5)  # cortesía con servidores

    cp_items = fetch_cryptopanic()
    if cp_items:
        log.info(f"  CryptoPanic: {len(cp_items)} items")
        todos.extend(cp_items)

    # Procesar
    enviados = 0
    for it in todos:
        if not it.get("url") or not it.get("title"):
            continue
        if ya_visto(conn, it["url"]):
            continue

        # Score con title + summary
        texto = f"{it['title']} {it.get('summary','')}"
        score, target, hits = score_texto(texto)
        nivel = nivel_de_score(score)

        marcar_visto(conn, it["url"], it["title"], it["source"],
                     score, nivel, target)

        log.info(f"  [{nivel}/{target}/{score}] {it['title'][:80]}")

        if score >= SCORE_MINIMO_ENVIAR and enviados < MAX_NOTIS_POR_CICLO:
            descripcion = it.get("summary", "")[:600]
            ok = discord_send(
                titulo      = it["title"],
                descripcion = descripcion,
                nivel       = nivel,
                url         = it["url"],
                fuente      = f"{it['source']} · {target} · score={score}",
                extra_fields= {"Keywords": ", ".join(hits[:6]) or "—"},
            )
            if ok:
                enviados += 1
                time.sleep(1.2)  # rate limit cortesía Discord

    log.info(f"  → {enviados} notificaciones enviadas este ciclo")

# ══════════════════════════════════════════════════════════════════════════════
# CICLO DE EVENTOS MACRO
# ══════════════════════════════════════════════════════════════════════════════
def ciclo_eventos(conn):
    log.info("─── Ciclo de calendario macro ───")
    eventos = fetch_calendario_macro()
    log.info(f"  {len(eventos)} eventos relevantes esta semana")

    ahora = datetime.now(timezone.utc)

    for ev in eventos:
        delta = ev["scheduled"] - ahora
        delta_min = delta.total_seconds() / 60.0

        # Pre-alertas
        for marca in PRE_ALERTAS_MIN:
            # Ventana de tolerancia: si estamos a ±(intervalo/2) de la marca
            tolerancia = INTERVALO_EVENTOS_HRS * 60 / 2 + 5
            if abs(delta_min - marca) <= tolerancia and delta_min > 0:
                alert_id = f"pre_{marca}"
                if not alerta_ya_enviada(conn, ev["id"], alert_id):
                    cuando = (f"en {marca//60}h {marca%60}min" if marca >= 60
                              else f"en {marca}min")
                    discord_send(
                        titulo      = f"Próximo: {ev['title']}",
                        descripcion = (
                            f"Evento macro **{cuando}** "
                            f"({ev['scheduled'].strftime('%Y-%m-%d %H:%M UTC')})\n\n"
                            f"**Impacto esperado:** {ev['impact']}\n"
                            f"**Forecast:** {ev['forecast'] or '—'}\n"
                            f"**Anterior:** {ev['previous'] or '—'}\n\n"
                            f"Prepárate. BTC suele moverse en torno a estos releases. "
                            f"Pi reacciona poco, salvo correlación con sentimiento general."
                        ),
                        nivel       = "EVENTO",
                        fuente      = "Calendario macro · ForexFactory",
                    )
                    marcar_alerta(conn, ev["id"], alert_id)

        # Post-evento: si pasó hace <24h y tiene 'actual', y no se ha analizado
        if delta_min < 0 and abs(delta_min) < 60 * 24:
            if ev.get("actual") and not alerta_ya_enviada(conn, ev["id"], "post"):
                analisis = analizar_impacto(
                    ev["title"], ev["forecast"], ev["previous"], ev["actual"]
                )
                if analisis:
                    discord_send(
                        titulo      = f"Resultado: {ev['title']}",
                        descripcion = analisis,
                        nivel       = "ANÁLISIS",
                        fuente      = "Análisis automático · rule-based",
                        extra_fields= {
                            "Actual":   ev["actual"],
                            "Forecast": ev["forecast"] or "—",
                            "Anterior": ev["previous"] or "—",
                        },
                    )
                    marcar_alerta(conn, ev["id"], "post")

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def test_envio():
    log.info("Enviando mensaje de prueba a Discord...")
    ok = discord_send(
        titulo      = "News Agent funcionando",
        descripcion = "Si ves esto, el webhook está bien configurado y "
                      "las notificaciones llegan a tu celular.",
        nivel       = "ALTO",
        fuente      = "News Agent v1 · test",
        extra_fields= {"Hora local": datetime.now().strftime("%H:%M:%S")},
    )
    log.info("✓ OK" if ok else "✗ FALLÓ — revisa DISCORD_WEBHOOK_URL")
    return ok

def main():
    if "--test" in sys.argv:
        test_envio()
        return

    if not DISCORD_WEBHOOK_URL:
        log.error("Falta DISCORD_WEBHOOK_URL en config.env")
        log.error("Crea config.env junto al script con la línea:")
        log.error("DISCORD_WEBHOOK_URL=https://TU_WEBHOOK_DE_DISCORD_AQUI")
        sys.exit(1)

    conn = db_init()
    log.info("═══ News Agent v1 iniciado ═══")
    log.info(f"Score mínimo para notificar: {SCORE_MINIMO_ENVIAR}")
    log.info(f"Intervalo noticias: {INTERVALO_SEGUNDOS}s")
    log.info(f"Intervalo eventos:  {INTERVALO_EVENTOS_HRS}h")

    if "--once" in sys.argv:
        ciclo_noticias(conn)
        ciclo_eventos(conn)
        return

    ultima_eventos = 0
    while True:
        try:
            ciclo_noticias(conn)
            if time.time() - ultima_eventos > INTERVALO_EVENTOS_HRS * 3600:
                ciclo_eventos(conn)
                ultima_eventos = time.time()
        except KeyboardInterrupt:
            log.info("Detenido por usuario")
            break
        except Exception as e:
            log.exception(f"Error en loop principal: {e}")
        time.sleep(INTERVALO_SEGUNDOS)

if __name__ == "__main__":
    main()
