#!/usr/bin/env python3
"""
News Agent v2 — Monitoreo BTC + Pi Network con análisis de impacto IA
─────────────────────────────────────────────────────────────────────
Cambios vs v1:
  • Analiza cada noticia notificable con Claude Haiku
  • Determina dirección (BULLISH/BEARISH/NEUTRAL), confianza,
    magnitud esperada y horizonte temporal
  • Incluye explicación en lenguaje natural
  • Tracking de costos de API en SQLite
  • Migración automática de DB del v1 (no pierdes histórico)

Uso:
    python news_agent_v2.py            # loop continuo
    python news_agent_v2.py --once     # una sola pasada (debug)
    python news_agent_v2.py --test     # mensaje de prueba a Discord
    python news_agent_v2.py --analyze "titulo"   # test de análisis IA
    python news_agent_v2.py --costs    # muestra costo acumulado de la API
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
ANTHROPIC_API_KEY     = os.getenv("ANTHROPIC_API_KEY", "").strip()

USAR_CLAUDE_API       = bool(ANTHROPIC_API_KEY)        # True si hay key
MODELO_CLAUDE         = "claude-haiku-4-5-20251001"
SUPRIMIR_NEUTRAL      = True       # si Claude dice NEUTRAL con confianza ≥80, no notifica

INTERVALO_SEGUNDOS    = 180        # 3 min
INTERVALO_EVENTOS_HRS = 6          # 6h
SCORE_MINIMO_ENVIAR   = 7          # umbral de keywords para enviar/analizar
MAX_NOTIS_POR_CICLO   = 8
DB_PATH               = BASE / "news_agent.db"

PRE_ALERTAS_MIN       = [60 * 24, 60, 15]   # T-24h, T-1h, T-15min

# Precios Haiku 4.5 (USD por millón de tokens) — actualizar si cambian
PRECIO_HAIKU_INPUT    = 1.00
PRECIO_HAIKU_OUTPUT   = 5.00

# ══════════════════════════════════════════════════════════════════════════════
# FUENTES RSS
# ══════════════════════════════════════════════════════════════════════════════
RSS_FEEDS = [
    ("CoinDesk",        "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph",   "https://cointelegraph.com/rss"),
    ("Bitcoin Magazine","https://bitcoinmagazine.com/.rss/full/"),
    ("Decrypt",         "https://decrypt.co/feed"),
    ("BeInCrypto",      "https://beincrypto.com/feed/"),
    ("CryptoSlate",     "https://cryptoslate.com/feed/"),
    ("The Block",       "https://www.theblock.co/rss.xml"),
    ("r/PiNetwork",     "https://www.reddit.com/r/PiNetwork/new/.rss"),
    ("Pi Blog",         "https://minepi.com/blog/feed/"),
]

# ══════════════════════════════════════════════════════════════════════════════
# KEYWORDS — clasificación inicial por score
# ══════════════════════════════════════════════════════════════════════════════
KEYWORDS_BTC = {
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
    "whale transfer":       5, "whale moved":        5, "large transfer":      4,
    "regulation":           5, "regulatory":         4, "lawsuit":             5,
    "approval":             4, "rejected":           4, "listing":             4,
    "delisting":            6, "exchange hack":      9, "bridge hack":         8,
    "all-time high":        4, "ath":                3, "new high":            3,
    "crash":                6, "plunge":             5, "surge":               4,
    "rally":                2, "pump":               1, "dump":                2,
    "analyst":              0, "prediction":         0, "forecast":            0,
    "adoption":             3, "institutional":      3, "bullish":             1,
    "bearish":              1, "support":            0, "resistance":          0,
    # MACRO
    "fomc":                 6, "fed minutes":        5, "fed meeting":         5,
    "rate cut":             7, "rate hike":          6, "rates unchanged":     4,
    "powell speech":        5, "powell testimony":   5, "jerome powell":       3,
    "cpi release":          5, "core cpi":           5, "inflation data":      4,
    "pce release":          5, "core pce":           5, "ppi release":         4,
    "non-farm payrolls":    4, "nfp report":         4, "jobs report":         3,
    "interest rate":        2, "monetary policy":    3,
    "yield curve":          3, "treasury yield":     2, "dollar index":        2,
    "bitcoin":              0, "btc":                0,
}

KEYWORDS_PI = {
    "pi mainnet":          10, "open mainnet":      12, "mainnet launch":     12,
    "binance listing":     12, "coinbase listing":  12, "okx listing":        10,
    "bybit listing":       10, "kraken listing":    10, "kucoin listing":      8,
    "pi listing":           9, "pi listed":          9,
    "pi migration":         7, "kyc complete":       6, "pi delisting":      10,
    "pi network ban":      10, "pi banned":          9,
    "pi day":               5, "pi network update": 4, "pi blockchain":       4,
    "pi node":              3, "pi browser":         2, "pi app":              2,
    "pi core team":         4, "nicolas kokkalis":   4, "chengdiao fan":       4,
    "pi partnership":       6, "pi roadmap":         5, "pi tokenomics":       5,
    "open network":         6, "enclosed network":   4,
    "pi network":           1, "pi coin":            1, "pi/usdt":             3,
    "minepi":               1, "$pi":                1,
}

EVENTOS_MACRO_KEYS = [
    "FOMC", "Federal Funds", "Fed Chair", "Powell",
    "CPI", "Core CPI", "PCE", "Core PCE",
    "Non-Farm", "Unemployment", "NFP",
    "PPI", "GDP", "Retail Sales", "Consumer Confidence",
]

# ══════════════════════════════════════════════════════════════════════════════
# STORAGE — SQLite con migración desde v1
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
    # Tabla nueva v2: análisis IA + tracking de costos
    c.execute("""
        CREATE TABLE IF NOT EXISTS ai_analysis (
            url_hash TEXT PRIMARY KEY,
            direccion TEXT, confianza INTEGER,
            magnitud TEXT, horizonte TEXT,
            explicacion TEXT,
            input_tokens INTEGER, output_tokens INTEGER,
            costo_usd REAL,
            timestamp TEXT
        )
    """)
    # Migración: agregar columnas a seen_articles si no existen
    cols = [r[1] for r in c.execute("PRAGMA table_info(seen_articles)").fetchall()]
    if "direccion" not in cols:
        c.execute("ALTER TABLE seen_articles ADD COLUMN direccion TEXT")
    if "confianza" not in cols:
        c.execute("ALTER TABLE seen_articles ADD COLUMN confianza INTEGER")

    conn.commit()
    return conn

def url_hash(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()

def ya_visto(conn, url: str) -> bool:
    c = conn.cursor()
    c.execute("SELECT 1 FROM seen_articles WHERE url_hash = ?", (url_hash(url),))
    return c.fetchone() is not None

def marcar_visto(conn, url, title, source, score, nivel, target,
                 direccion=None, confianza=None):
    c = conn.cursor()
    c.execute("""INSERT OR IGNORE INTO seen_articles
                 (url_hash, title, source, url, score, nivel, target,
                  timestamp, direccion, confianza)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (url_hash(url), title, source, url, score, nivel, target,
               datetime.now(timezone.utc).isoformat(),
               direccion, confianza))
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

def guardar_analisis(conn, url, analisis):
    c = conn.cursor()
    c.execute("""INSERT OR REPLACE INTO ai_analysis
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (url_hash(url),
               analisis.get("direccion"),
               analisis.get("confianza"),
               analisis.get("magnitud"),
               analisis.get("horizonte"),
               analisis.get("explicacion"),
               analisis.get("input_tokens", 0),
               analisis.get("output_tokens", 0),
               analisis.get("costo_usd", 0.0),
               datetime.now(timezone.utc).isoformat()))
    conn.commit()

# ══════════════════════════════════════════════════════════════════════════════
# CLAUDE HAIKU — análisis de impacto
# ══════════════════════════════════════════════════════════════════════════════
PROMPT_ANALISIS = """Eres analista cripto experto. Lee esta noticia y predice su impacto en el precio de {target}.

TÍTULO: {titulo}
RESUMEN: {resumen}
FUENTE: {fuente}

Contexto: {contexto_target}

Responde SOLO con un objeto JSON válido, sin texto adicional, sin markdown, sin ```:
{{
  "direccion": "BULLISH" | "BEARISH" | "NEUTRAL",
  "confianza": <entero 0-100>,
  "magnitud": "PEQUEÑO" | "MEDIANO" | "GRANDE",
  "horizonte": "HORAS" | "DÍAS" | "SEMANAS",
  "explicacion": "<1-2 frases concisas en español, máximo 280 caracteres>"
}}

Reglas:
- direccion BULLISH = sube precio. BEARISH = baja precio. NEUTRAL = sin impacto claro o ya descontado.
- confianza alta (>70) SOLO si la noticia es clara, verificada y movedora. Rumores o ambigüedades → confianza baja.
- magnitud: PEQUEÑO (<2%), MEDIANO (2-5%), GRANDE (>5%).
- Si es repetición de algo ya conocido o noticia vieja, NEUTRAL con confianza alta.
- Si la fuente es Reddit/comunidad, baja la confianza ~20 puntos (no es periodismo verificado).
- En español. Sé directo, sin disclaimers."""

CONTEXTO_BTC = ("Bitcoin reacciona fuerte a: aprobación/rechazo de ETFs, decisiones FOMC, "
                "movimientos de whales grandes, regulación, hacks de exchanges, "
                "compras institucionales (MicroStrategy, BlackRock), eventos macro USA.")

CONTEXTO_PI = ("Pi Network está en fase pre-listing en mainnets mayores (Binance, Coinbase). "
               "Reacciona a: listings nuevos, anuncios del Core Team, hitos de mainnet, "
               "migraciones, KYC. Macro tradicional la afecta poco. Mucha info de comunidad "
               "tiende a ser especulativa/fanática.")

CONTEXTO_MACRO = ("Datos macro USA afectan BTC vía expectativas de tasas. CPI/PCE alto → Fed "
                  "hawkish → bearish BTC. Tasas a la baja → bullish BTC. NFP fuerte → bearish "
                  "(Fed mantiene línea dura). Pi reacciona poco a estos datos directamente.")

def analizar_con_claude(titulo: str, resumen: str, target: str, fuente: str = ""):
    """Devuelve dict con análisis o None si falla."""
    if not USAR_CLAUDE_API:
        return None

    contexto = {"BTC": CONTEXTO_BTC, "PI": CONTEXTO_PI,
                "MACRO": CONTEXTO_MACRO}.get(target, CONTEXTO_BTC)

    prompt = PROMPT_ANALISIS.format(
        target = target,
        titulo = titulo[:300],
        resumen = (resumen or titulo)[:800],
        fuente = fuente,
        contexto_target = contexto,
    )

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers = {
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json = {
                "model": MODELO_CLAUDE,
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout = 30,
        )

        if r.status_code == 429:
            log.warning("Anthropic rate limit — esperando 5s")
            time.sleep(5)
            return None
        if r.status_code != 200:
            log.warning(f"Anthropic respondió {r.status_code}: {r.text[:200]}")
            return None

        data = r.json()
        texto = data["content"][0]["text"].strip()

        # Extraer JSON aunque venga con markdown (por si las moscas)
        m = re.search(r"\{.*\}", texto, re.DOTALL)
        if not m:
            log.warning(f"No JSON en respuesta de Claude: {texto[:200]}")
            return None

        analisis = json.loads(m.group())

        # Validación básica
        if analisis.get("direccion") not in ("BULLISH", "BEARISH", "NEUTRAL"):
            log.warning(f"Dirección inválida: {analisis.get('direccion')}")
            return None

        # Tracking de costos
        usage = data.get("usage", {})
        in_tok = usage.get("input_tokens", 0)
        out_tok = usage.get("output_tokens", 0)
        costo = (in_tok * PRECIO_HAIKU_INPUT + out_tok * PRECIO_HAIKU_OUTPUT) / 1_000_000

        analisis["input_tokens"]  = in_tok
        analisis["output_tokens"] = out_tok
        analisis["costo_usd"]     = costo

        return analisis

    except json.JSONDecodeError as e:
        log.warning(f"JSON parse error de Claude: {e}")
        return None
    except Exception as e:
        log.warning(f"Error análisis Claude: {e}")
        return None

# ══════════════════════════════════════════════════════════════════════════════
# DISCORD NOTIFIER
# ══════════════════════════════════════════════════════════════════════════════
COLORES = {
    "CRÍTICO": 0xE74C3C, "ALTO": 0xE67E22, "MEDIO": 0x3498DB, "BAJO": 0x95A5A6,
    "EVENTO": 0x9B59B6, "ANÁLISIS": 0x2ECC71,
}
EMOJIS = {
    "CRÍTICO": "🚨", "ALTO": "⚠️", "MEDIO": "📰", "BAJO": "💬",
    "EVENTO": "📅", "ANÁLISIS": "🧠",
}
DIR_EMOJI = {"BULLISH": "🟢⬆️", "BEARISH": "🔴⬇️", "NEUTRAL": "⚪➡️"}

def barra_confianza(c: int, ancho=10) -> str:
    """Renderiza barra ASCII tipo ▓▓▓░░░░░░░ 30%"""
    if c is None: return "—"
    llenos = round(c * ancho / 100)
    return "▓" * llenos + "░" * (ancho - llenos) + f" {c}%"

def discord_send(titulo, descripcion, nivel="MEDIO",
                 url=None, fuente=None, extra_fields=None):
    if not DISCORD_WEBHOOK_URL:
        log.warning("Sin DISCORD_WEBHOOK_URL — no se envía")
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
        log.warning(f"Discord {r.status_code}: {r.text[:200]}")
        return False
    except Exception as e:
        log.error(f"Error enviando Discord: {e}")
        return False

# ══════════════════════════════════════════════════════════════════════════════
# SCORING
# ══════════════════════════════════════════════════════════════════════════════
def score_texto(texto: str):
    t = texto.lower()
    score_btc = sum(p for kw, p in KEYWORDS_BTC.items() if kw in t)
    score_pi  = sum(p for kw, p in KEYWORDS_PI.items()  if kw in t)
    hits_btc  = [kw for kw in KEYWORDS_BTC if kw in t and KEYWORDS_BTC[kw] > 0]
    hits_pi   = [kw for kw in KEYWORDS_PI  if kw in t and KEYWORDS_PI[kw]  > 0]

    menciona_pi  = any(k in t for k in (
        "pi network", "pinetwork", "pi coin", "minepi", "$pi",
        "pi/usdt", "pi day", "pi mainnet", "pi blockchain",
    ))
    menciona_btc = any(k in t for k in ("bitcoin", "btc", " btc ", "btc/", "satoshi"))

    if menciona_pi and score_pi > 0:
        target, score, hits = "PI", score_pi, hits_pi
    elif menciona_btc and score_btc > 0:
        target, score, hits = "BTC", score_btc, hits_btc
    elif score_btc > 0:
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
# FUENTES
# ══════════════════════════════════════════════════════════════════════════════
def fetch_rss(nombre, url):
    try:
        feed = feedparser.parse(url, request_headers={
            "User-Agent": "Mozilla/5.0 (NewsAgent/2.0)"
        })
        if feed.bozo and not feed.entries:
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
        log.warning(f"  {nombre}: error fetch — {ex}")
        return []

def fetch_cryptopanic():
    if not CRYPTOPANIC_TOKEN:
        return []
    url = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTOPANIC_TOKEN}&filter=hot&kind=news"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        return [{
            "title":   p.get("title", ""),
            "url":     p.get("url", ""),
            "summary": p.get("title", ""),
            "source":  f"CryptoPanic ({p.get('source',{}).get('title','?')})",
        } for p in data.get("results", [])]
    except Exception as ex:
        log.warning(f"CryptoPanic error: {ex}")
        return []

# ══════════════════════════════════════════════════════════════════════════════
# CALENDARIO MACRO
# ══════════════════════════════════════════════════════════════════════════════
FOREXFACTORY_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

def fetch_calendario_macro():
    try:
        r = requests.get(FOREXFACTORY_URL, timeout=20,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            log.warning(f"ForexFactory {r.status_code}")
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
        log.warning(f"Error calendario: {ex}")
        return []

# ══════════════════════════════════════════════════════════════════════════════
# ANÁLISIS RULE-BASED POST-EVENTO MACRO (sin Claude — para events ya conocidos)
# ══════════════════════════════════════════════════════════════════════════════
def parsear_numero(s):
    if not s: return None
    m = re.search(r"-?\d+\.?\d*", str(s).replace(",", ""))
    return float(m.group()) if m else None

def analizar_evento_macro(title, forecast, previous, actual):
    f = parsear_numero(forecast)
    p = parsear_numero(previous)
    a = parsear_numero(actual)
    t = title.lower()
    if a is None: return None

    msg, direccion = [], "NEUTRAL"

    if any(k in t for k in ["cpi", "pce", "ppi"]):
        if f is not None:
            if a > f + 0.05:
                direccion = "BEARISH BTC"
                msg.append(f"Inflación SOBRE forecast ({a} vs {f}) → Fed más hawkish, "
                           f"presión bajista BTC. Históricamente cae 1-3% intradía.")
            elif a < f - 0.05:
                direccion = "BULLISH BTC"
                msg.append(f"Inflación BAJO forecast ({a} vs {f}) → Fed más dovish. "
                           f"BTC suele rebotar 1-4%.")
            else:
                msg.append(f"Inflación EN LÍNEA ({a} vs {f}) → impacto limitado.")
    elif "fomc" in t or "federal funds" in t:
        if p is not None:
            if a < p:
                direccion = "BULLISH BTC"
                msg.append(f"Recorte de tasa ({a}% desde {p}%) → muy bullish BTC. "
                           f"BTC suele subir 3-8% en sesiones siguientes.")
            elif a > p:
                direccion = "BEARISH BTC"
                msg.append(f"Subida de tasa ({a}% desde {p}%) → bearish corto plazo. "
                           f"BTC suele caer 2-5%.")
            else:
                direccion = "NEUTRAL → depende del tono"
                msg.append(f"Tasa SIN CAMBIO ({a}%). Impacto vendrá del comunicado FOMC y "
                           f"rueda de Powell — 'higher for longer' (bearish), señales de "
                           f"cortes (bullish).")
    elif "non-farm" in t or "nfp" in t:
        if f is not None:
            if a > f * 1.15:
                direccion = "MIXTO — BEARISH inicial"
                msg.append(f"NFP MUY SOBRE forecast ({a}K vs {f}K) → Fed mantiene tasas "
                           f"altas. BTC suele caer 1-3%.")
            elif a < f * 0.85:
                direccion = "BULLISH BTC"
                msg.append(f"NFP MUY BAJO forecast ({a}K vs {f}K) → expectativa de cortes "
                           f"sube. BTC suele subir 2-4%.")
            else:
                msg.append(f"NFP en línea ({a}K vs {f}K).")
    elif "unemployment" in t:
        if f is not None:
            if a > f:
                direccion = "BULLISH BTC"
                msg.append(f"Desempleo SOBRE forecast ({a}% vs {f}%) → Fed presionada a "
                           f"recortar. Bullish moderado.")
            elif a < f:
                direccion = "BEARISH BTC"
                msg.append(f"Desempleo BAJO forecast ({a}% vs {f}%) → mercado laboral "
                           f"fuerte. Bearish moderado.")
    elif "gdp" in t:
        if f is not None:
            if a > f:
                direccion = "MIXTO"
                msg.append(f"GDP fuerte ({a}% vs {f}%) — refuerza Fed hawkish. "
                           f"Neto suele ser bearish BTC.")
            else:
                direccion = "BULLISH BTC"
                msg.append(f"GDP débil ({a}% vs {f}%) → expectativa de cortes sube.")

    msg.append("\nNota: Pi Network reacciona poco a macro tradicional, "
               "más a hitos propios.")

    return f"**Dirección esperada: {direccion}**\n\n" + "\n".join(msg)

# ══════════════════════════════════════════════════════════════════════════════
# CICLO DE NOTICIAS
# ══════════════════════════════════════════════════════════════════════════════
def construir_descripcion_con_analisis(summary: str, analisis: dict) -> str:
    """Embellece el embed con el análisis IA."""
    if not analisis:
        return (summary or "")[:600]

    dir_emoji = DIR_EMOJI.get(analisis["direccion"], "❓")
    direccion = analisis["direccion"]
    confianza = analisis.get("confianza", 0)
    magnitud  = analisis.get("magnitud", "—")
    horizonte = analisis.get("horizonte", "—")
    expl      = analisis.get("explicacion", "")

    return (
        f"**{dir_emoji} {direccion}**  ·  Magnitud **{magnitud}**  ·  "
        f"Horizonte **{horizonte}**\n"
        f"Confianza: `{barra_confianza(confianza)}`\n\n"
        f"**Análisis:** {expl}\n\n"
        f"_Resumen:_ {(summary or '')[:300]}"
    )

def ciclo_noticias(conn):
    log.info("─── Ciclo noticias ───")
    todos = []

    for nombre, url in RSS_FEEDS:
        items = fetch_rss(nombre, url)
        log.info(f"  {nombre}: {len(items)} items")
        todos.extend(items)
        time.sleep(0.5)

    cp_items = fetch_cryptopanic()
    if cp_items:
        log.info(f"  CryptoPanic: {len(cp_items)} items")
        todos.extend(cp_items)

    enviados = 0
    analizados = 0
    costo_ciclo = 0.0

    for it in todos:
        if not it.get("url") or not it.get("title"):
            continue
        if ya_visto(conn, it["url"]):
            continue

        texto = f"{it['title']} {it.get('summary','')}"
        score, target, hits = score_texto(texto)
        nivel = nivel_de_score(score)

        # Si no llega al umbral, marca como visto y sigue (no analizar, ahorra API)
        if score < SCORE_MINIMO_ENVIAR:
            marcar_visto(conn, it["url"], it["title"], it["source"],
                         score, nivel, target)
            log.debug(f"  [{nivel}/{target}/{score}] {it['title'][:80]}")
            continue

        if enviados >= MAX_NOTIS_POR_CICLO:
            # marcar visto pero sin enviar para no spamear
            marcar_visto(conn, it["url"], it["title"], it["source"],
                         score, nivel, target)
            continue

        # Analizar con Claude (si está activado)
        analisis = None
        if USAR_CLAUDE_API:
            analisis = analizar_con_claude(
                titulo  = it["title"],
                resumen = it.get("summary", ""),
                target  = target,
                fuente  = it["source"],
            )
            if analisis:
                analizados += 1
                costo_ciclo += analisis.get("costo_usd", 0.0)
                guardar_analisis(conn, it["url"], analisis)
                # Suprimir si NEUTRAL con alta confianza
                if (SUPRIMIR_NEUTRAL
                    and analisis["direccion"] == "NEUTRAL"
                    and analisis.get("confianza", 0) >= 80):
                    log.info(f"  [{nivel}/{target}/{score}] SUPRIMIDA (neutral 80+): "
                             f"{it['title'][:80]}")
                    marcar_visto(conn, it["url"], it["title"], it["source"],
                                 score, nivel, target,
                                 direccion="NEUTRAL",
                                 confianza=analisis.get("confianza"))
                    continue

        log.info(f"  [{nivel}/{target}/{score}] "
                 f"{(analisis['direccion'] if analisis else '?'):>8} → "
                 f"{it['title'][:75]}")

        descripcion = construir_descripcion_con_analisis(it.get("summary", ""), analisis)

        extra = {"Keywords": ", ".join(hits[:5]) or "—"}
        if analisis:
            extra["Costo IA"] = f"${analisis.get('costo_usd', 0):.5f}"

        ok = discord_send(
            titulo      = it["title"],
            descripcion = descripcion,
            nivel       = nivel,
            url         = it["url"],
            fuente      = f"{it['source']} · {target} · score={score}",
            extra_fields= extra,
        )
        if ok:
            enviados += 1
            marcar_visto(conn, it["url"], it["title"], it["source"],
                         score, nivel, target,
                         direccion = analisis["direccion"] if analisis else None,
                         confianza = analisis.get("confianza") if analisis else None)
            time.sleep(1.2)

    log.info(f"  → {enviados} envíos · {analizados} analizados · "
             f"costo ciclo: ${costo_ciclo:.4f}")

# ══════════════════════════════════════════════════════════════════════════════
# CICLO DE EVENTOS MACRO
# ══════════════════════════════════════════════════════════════════════════════
def ciclo_eventos(conn):
    log.info("─── Ciclo calendario macro ───")
    eventos = fetch_calendario_macro()
    log.info(f"  {len(eventos)} eventos relevantes esta semana")
    ahora = datetime.now(timezone.utc)

    for ev in eventos:
        delta = ev["scheduled"] - ahora
        delta_min = delta.total_seconds() / 60.0

        for marca in PRE_ALERTAS_MIN:
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
                            f"Prepárate. BTC suele moverse en torno a estos releases."
                        ),
                        nivel       = "EVENTO",
                        fuente      = "Calendario macro · ForexFactory",
                    )
                    marcar_alerta(conn, ev["id"], alert_id)

        if delta_min < 0 and abs(delta_min) < 60 * 24:
            if ev.get("actual") and not alerta_ya_enviada(conn, ev["id"], "post"):
                analisis_rb = analizar_evento_macro(
                    ev["title"], ev["forecast"], ev["previous"], ev["actual"]
                )
                if analisis_rb:
                    discord_send(
                        titulo      = f"Resultado: {ev['title']}",
                        descripcion = analisis_rb,
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
# COMANDOS CLI
# ══════════════════════════════════════════════════════════════════════════════
def test_envio():
    log.info("Test Discord...")
    ok = discord_send(
        titulo      = "News Agent v2 funcionando",
        descripcion = "Si ves esto, todo conecta. Análisis IA: "
                      + ("ACTIVADO ✓" if USAR_CLAUDE_API else "DESACTIVADO (sin API key)"),
        nivel       = "ALTO",
        fuente      = f"News Agent v2 · {'con IA' if USAR_CLAUDE_API else 'sin IA'}",
        extra_fields= {"Hora local": datetime.now().strftime("%H:%M:%S"),
                       "Modelo IA": MODELO_CLAUDE if USAR_CLAUDE_API else "—"},
    )
    log.info("✓ OK" if ok else "✗ FALLÓ")

def test_analisis(titulo: str):
    if not USAR_CLAUDE_API:
        log.error("Sin ANTHROPIC_API_KEY en config.env")
        return
    log.info(f"Analizando: {titulo}")
    score, target, _ = score_texto(titulo)
    if target == "GENERAL": target = "BTC"
    a = analizar_con_claude(titulo, "", target, "test")
    if a:
        print(json.dumps(a, indent=2, ensure_ascii=False))
    else:
        log.error("Análisis falló")

def mostrar_costos():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute("""
        SELECT
            COUNT(*) as n,
            SUM(input_tokens) as in_tok,
            SUM(output_tokens) as out_tok,
            SUM(costo_usd) as costo
        FROM ai_analysis
    """).fetchone()
    n, in_tok, out_tok, costo = rows
    print(f"Análisis IA totales: {n}")
    print(f"Input tokens:  {in_tok or 0:,}")
    print(f"Output tokens: {out_tok or 0:,}")
    print(f"Costo total:   ${costo or 0:.4f} USD")

    rows30 = c.execute("""
        SELECT SUM(costo_usd) FROM ai_analysis
        WHERE timestamp > datetime('now', '-30 days')
    """).fetchone()
    print(f"Costo últimos 30 días: ${rows30[0] or 0:.4f} USD")

    rows7 = c.execute("""
        SELECT direccion, COUNT(*), AVG(confianza) FROM ai_analysis
        WHERE timestamp > datetime('now', '-7 days')
        GROUP BY direccion
    """).fetchall()
    if rows7:
        print(f"\nÚltimos 7 días por dirección:")
        for d, n, conf in rows7:
            print(f"  {d}: {n} noticias · confianza media {conf:.0f}")
    conn.close()

def main():
    if "--test" in sys.argv:
        test_envio()
        return
    if "--costs" in sys.argv:
        mostrar_costos()
        return
    if "--analyze" in sys.argv:
        idx = sys.argv.index("--analyze")
        if idx + 1 < len(sys.argv):
            test_analisis(sys.argv[idx + 1])
        else:
            log.error("Uso: --analyze \"titulo a analizar\"")
        return

    if not DISCORD_WEBHOOK_URL:
        log.error("Falta DISCORD_WEBHOOK_URL en config.env")
        sys.exit(1)

    conn = db_init()
    log.info("═══ News Agent v2 iniciado ═══")
    log.info(f"Análisis IA:        {'ACTIVADO ('+MODELO_CLAUDE+')' if USAR_CLAUDE_API else 'DESACTIVADO'}")
    log.info(f"Suprimir NEUTRAL:   {SUPRIMIR_NEUTRAL}")
    log.info(f"Score mín. enviar:  {SCORE_MINIMO_ENVIAR}")
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
            log.info("Detenido")
            break
        except Exception as e:
            log.exception(f"Error loop: {e}")
        time.sleep(INTERVALO_SEGUNDOS)

if __name__ == "__main__":
    main()
