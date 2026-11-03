# Manual de operación — News Agent v2

Guía completa de manejo del agente de noticias BTC + Pi Network con análisis IA, corriendo en Oracle Cloud.

---

## 📌 Datos clave de tu setup

| Dato | Valor |
|---|---|
| **IP pública del servidor** | `64.181.162.229` |
| **Usuario del servidor (Linux)** | `ubuntu` |
| **Usuario en tu PC (Windows)** | `csusp` |
| **Ruta de la llave SSH** | `C:\Users\csusp\.ssh\oracle.key` |
| **Carpeta del proyecto en servidor** | `/home/ubuntu/news_agent/` |
| **Carpeta del proyecto en tu PC** | `C:\Users\csusp\OneDrive\Desktop\code todos\crypto news\` |
| **Nombre del servicio systemd** | `news-agent` |
| **Script en uso** | `news_agent_v2.py` |
| **Cloud provider** | Oracle Cloud Free Tier |
| **Sistema operativo del servidor** | Ubuntu 22.04 |
| **Modelo IA** | Claude Haiku 4.5 |

> ⚠️ **Backup obligatorio:** la llave `oracle.key`. Si la pierdes no se puede recuperar — tendrías que crear una VM nueva. Guárdala en USB o gestor de contraseñas (Bitwarden/1Password).

---

## ⚡ Quick Start — los 3 comandos que más vas a usar

### 1. Conectarte al servidor (siempre el primer paso)

Abre PowerShell (tecla Windows + R → `powershell` → Enter) y pega:

```powershell
ssh -i C:\Users\csusp\.ssh\oracle.key ubuntu@64.181.162.229
```

Si te pregunta "Are you sure...", escribe `yes` + Enter.

### 2. Verificar que está corriendo

```bash
sudo systemctl status news-agent
```

Buscas `Active: active (running)` en verde. `q` para salir.

### 3. Ver costos de la IA

```bash
cd ~/news_agent
source venv/bin/activate
python news_agent_v2.py --costs
```

Te muestra costo total acumulado, últimos 30 días, y distribución de direcciones predichas.

### Salir del servidor

```bash
exit
```

El agente sigue corriendo en Oracle aunque cierres PowerShell ✓.

---

## 🚀 Cheat sheet — comandos por categoría

### Operación del servicio (en SSH)

| Acción | Comando |
|---|---|
| Ver estado | `sudo systemctl status news-agent` |
| Detener | `sudo systemctl stop news-agent` |
| Arrancar | `sudo systemctl start news-agent` |
| Reiniciar | `sudo systemctl restart news-agent` |
| Desactivar arranque automático | `sudo systemctl disable news-agent` |
| Reactivar arranque automático | `sudo systemctl enable news-agent` |
| Ver últimos 50 eventos del servicio | `sudo journalctl -u news-agent -n 50 --no-pager` |
| Ver logs en vivo (Ctrl+C salir) | `sudo journalctl -u news-agent -f` |

### Logs del agente

| Acción | Comando |
|---|---|
| Últimas 100 líneas | `tail -100 ~/news_agent/news_agent.log` |
| Logs en vivo | `tail -f ~/news_agent/news_agent.log` |
| Buscar errores | `grep -i "error\|warning" ~/news_agent/news_agent.log \| tail -30` |
| Ver ciclos con notificaciones enviadas | `grep "→.*envíos" ~/news_agent/news_agent.log \| tail -30` |
| Vaciar log (sin borrar archivo) | `> ~/news_agent/news_agent.log` |

### Configuración

| Acción | Comando |
|---|---|
| Editar config (webhook, API key) | `nano ~/news_agent/config.env` |
| Ver config actual | `cat ~/news_agent/config.env` |
| Editar el script (umbrales, keywords) | `nano ~/news_agent/news_agent_v2.py` |
| Validar config sin afectar el servicio | `python ~/news_agent/news_agent_v2.py --once` (después de `source venv/bin/activate`) |

> 🔄 **Después de cualquier cambio en config o script**: `sudo systemctl restart news-agent`

### Test y diagnóstico

| Acción | Comando |
|---|---|
| Test de Discord | `python news_agent_v2.py --test` |
| Test de análisis IA con titular custom | `python news_agent_v2.py --analyze "tu titular aquí"` |
| Una pasada completa (debug) | `python news_agent_v2.py --once` |
| Ver costos IA acumulados | `python news_agent_v2.py --costs` |

> Todos requieren primero: `cd ~/news_agent && source venv/bin/activate`

### Comandos en PowerShell (en tu PC, NO en el servidor)

| Acción | Comando |
|---|---|
| Conectarse al servidor | `ssh -i C:\Users\csusp\.ssh\oracle.key ubuntu@64.181.162.229` |
| Subir archivo al servidor | `scp -i C:\Users\csusp\.ssh\oracle.key "C:\ruta\archivo.py" ubuntu@64.181.162.229:~/news_agent/` |
| Descargar archivo del servidor | `scp -i C:\Users\csusp\.ssh\oracle.key ubuntu@64.181.162.229:~/news_agent/archivo "C:\destino\"` |
| Backup de la base de datos | `scp -i C:\Users\csusp\.ssh\oracle.key ubuntu@64.181.162.229:~/news_agent/news_agent.db "C:\Users\csusp\OneDrive\Desktop\backup_news.db"` |

---

## 🟢 Cómo está configurado tu agente

- ✅ **Arranca solo** cuando el servidor se reinicia
- ✅ **Se reinicia solo** si crashea (espera 30 segundos)
- ✅ **Sigue corriendo** aunque cierres PowerShell, apagues PC, viajes
- ✅ **Análisis IA activado** con Claude Haiku 4.5
- ✅ **Suprime NEUTRAL** con confianza ≥ 80% (no spamea con noticias irrelevantes)
- ✅ **Logs persistentes** en `~/news_agent/news_agent.log` y `journalctl`
- ✅ **Tracking de costos** automático en SQLite

**Ciclos:**
- Cada **3 minutos** revisa 9 fuentes RSS de cripto/Pi
- Cada **6 horas** revisa el calendario macro (FOMC, CPI, NFP, etc.)
- Solo analiza con IA noticias que pasen `score ≥ 7` (umbral de keywords)

---

## 📖 Operaciones detalladas

### 1. Conectarse al servidor

**Desde Windows (PowerShell):**

```powershell
ssh -i C:\Users\csusp\.ssh\oracle.key ubuntu@64.181.162.229
```

**Desde el celular Samsung (Termius — opcional):**

1. Instalar Termius desde Play Store
2. Pasar `oracle.key` al celular (Google Drive, USB, etc.)
3. Termius: **+** (nuevo host)
   - Hostname: `64.181.162.229`
   - Username: `ubuntu`
   - Key: importar `oracle.key`
4. Tap en el host para conectarse

---

### 2. Detener/arrancar/reiniciar

Una vez dentro del servidor por SSH:

```bash
sudo systemctl stop news-agent       # detener (no llegan más notis)
sudo systemctl start news-agent      # arrancar
sudo systemctl restart news-agent    # reiniciar (= stop + start)
```

`stop` es temporal — si el servidor se reinicia, el agente arranca solo de nuevo. Para apagarlo permanentemente:

```bash
sudo systemctl stop news-agent
sudo systemctl disable news-agent    # no arranca solo nunca más
```

Para reactivarlo:

```bash
sudo systemctl enable news-agent
sudo systemctl start news-agent
```

---

### 3. Ver logs

**Modo en vivo** (cada línea nueva al instante):

```bash
sudo journalctl -u news-agent -f
```

`Ctrl + C` para salir del modo live (no detiene el servicio).

**Snapshot de últimas líneas:**

```bash
tail -100 ~/news_agent/news_agent.log
```

**Buscar cosas específicas:**

```bash
# Errores y warnings
grep -i "error\|warning\|exception" ~/news_agent/news_agent.log | tail -30

# Ciclos con noticias enviadas
grep "→.*envíos" ~/news_agent/news_agent.log | tail -30

# Análisis hechos
grep "analizados" ~/news_agent/news_agent.log | tail -20

# Eventos macro detectados
grep "Próximo:" ~/news_agent/news_agent.log
```

---

### 4. Cambiar configuración

#### 4a. Cambiar webhook de Discord

```bash
nano ~/news_agent/config.env
```

Edita la línea `DISCORD_WEBHOOK_URL=...` con la nueva URL. Guarda con `Ctrl+O` → Enter → `Ctrl+X`.

```bash
sudo systemctl restart news-agent
```

#### 4b. Cambiar API key de Anthropic

Mismo flujo, edita `ANTHROPIC_API_KEY=sk-ant-...` y reinicia.

#### 4c. Desactivar IA temporalmente (para ahorrar costos)

```bash
nano ~/news_agent/config.env
```

Comenta la línea con `#` al inicio:

```
#ANTHROPIC_API_KEY=sk-ant-...
```

Reinicia. El agente vuelve a comportarse como v1 (sin análisis), pero sigue notificando por keywords.

Para reactivar: descomentar la línea (quitarle el `#`) y reiniciar.

#### 4d. Cambiar umbral de notificación

```bash
nano ~/news_agent/news_agent_v2.py
```

Busca la línea (cerca del inicio):
```python
SCORE_MINIMO_ENVIAR   = 7
```

- Quieres **más notis** (incluye MEDIO) → cambia a `5`
- Quieres **menos notis** (solo CRÍTICO) → cambia a `10`

Guarda y reinicia.

#### 4e. Otros parámetros editables en el script

| Variable | Default | Qué hace |
|---|---|---|
| `INTERVALO_SEGUNDOS` | 180 | Cada cuánto revisa noticias (3 min) |
| `INTERVALO_EVENTOS_HRS` | 6 | Cada cuánto revisa calendario macro |
| `SCORE_MINIMO_ENVIAR` | 7 | Umbral de keywords para notificar |
| `MAX_NOTIS_POR_CICLO` | 8 | Tope de notis por ciclo (anti-spam) |
| `SUPRIMIR_NEUTRAL` | True | Si IA dice NEUTRAL con confianza ≥80, no notifica |
| `MODELO_CLAUDE` | claude-haiku-4-5-20251001 | Modelo de Anthropic |

---

### 5. Análisis IA con Claude Haiku

#### 5a. Probar la IA con un titular cualquiera

```bash
cd ~/news_agent
source venv/bin/activate
python news_agent_v2.py --analyze "BlackRock files for spot Bitcoin ETF amendment"
```

Output esperado:
```json
{
  "direccion": "BULLISH",
  "confianza": 75,
  "magnitud": "MEDIANO",
  "horizonte": "DÍAS",
  "explicacion": "...",
  "input_tokens": 451,
  "output_tokens": 110,
  "costo_usd": 0.001001
}
```

#### 5b. Ver costos acumulados

```bash
python news_agent_v2.py --costs
```

Te muestra: análisis totales, tokens consumidos, costo total y de últimos 30 días, distribución BULLISH/BEARISH/NEUTRAL de los últimos 7 días.

#### 5c. Costo real esperado

Con el setup default (umbral 7, suprimiendo NEUTRAL alta confianza):
- ~5-15 noticias notificables por día
- ~$0.001 por análisis
- **Costo mensual estimado: $0.15 - $0.50 USD**

Si ves costos disparados:
- Sube `SCORE_MINIMO_ENVIAR` a 9 o 10
- Baja `MAX_NOTIS_POR_CICLO` a 5
- O desactiva la IA (sección 4c)

---

### 6. Base de datos — inspeccionar qué ha visto el agente

#### 6a. Instalar SQLite client (solo primera vez)

```bash
sudo apt install -y sqlite3
```

#### 6b. Abrir consola SQL

```bash
sqlite3 ~/news_agent/news_agent.db
```

Te abre prompt `sqlite>`. Para salir: `.quit` o `Ctrl+D`.

#### 6c. Queries útiles

```sql
-- Últimas 20 noticias procesadas (incluye nivel y dirección IA)
SELECT timestamp, nivel, target, score, direccion, confianza, title
FROM seen_articles
ORDER BY timestamp DESC LIMIT 20;

-- Solo noticias CRÍTICAS de los últimos 7 días
SELECT timestamp, target, score, direccion, confianza, title
FROM seen_articles
WHERE nivel = 'CRÍTICO' AND timestamp > datetime('now', '-7 days')
ORDER BY timestamp DESC;

-- Distribución por nivel
SELECT nivel, COUNT(*) as cantidad
FROM seen_articles
GROUP BY nivel
ORDER BY cantidad DESC;

-- Análisis IA de los últimos 7 días por dirección
SELECT direccion, COUNT(*) as n, AVG(confianza) as conf_promedio,
       SUM(costo_usd) as costo
FROM ai_analysis
WHERE timestamp > datetime('now', '-7 days')
GROUP BY direccion;

-- Top 10 noticias BULLISH con mayor confianza
SELECT a.timestamp, s.target, a.confianza, a.magnitud, s.title
FROM ai_analysis a JOIN seen_articles s ON a.url_hash = s.url_hash
WHERE a.direccion = 'BULLISH'
ORDER BY a.confianza DESC LIMIT 10;

-- Eventos macro alertados
SELECT * FROM event_alerts ORDER BY sent_at DESC LIMIT 30;

-- Costo por día (últimos 30 días)
SELECT date(timestamp) as dia, COUNT(*) as analisis, SUM(costo_usd) as costo
FROM ai_analysis
WHERE timestamp > datetime('now', '-30 days')
GROUP BY dia
ORDER BY dia DESC;
```

#### 6d. Queries directas sin abrir consola SQL

```bash
sqlite3 ~/news_agent/news_agent.db "SELECT direccion, COUNT(*), AVG(confianza) FROM ai_analysis WHERE timestamp > datetime('now', '-7 days') GROUP BY direccion;"
```

---

### 7. Actualizar el script (cuando saquemos v3 o ajustes)

#### Flujo típico desde tu PC:

**Paso 1**: Edita el script en local con VS Code (o cualquier editor) en
`C:\Users\csusp\OneDrive\Desktop\code todos\crypto news\news_agent_v2.py`.

**Paso 2**: Súbelo al servidor desde PowerShell:

```powershell
scp -i C:\Users\csusp\.ssh\oracle.key "C:\Users\csusp\OneDrive\Desktop\code todos\crypto news\news_agent_v2.py" ubuntu@64.181.162.229:~/news_agent/
```

> ⚠️ Cuidado: si tu cliente convierte `.py` en hipervínculo `[v2.py](http://v2.py)`, escribe el nombre a mano antes de Enter.

**Paso 3**: Conéctate por SSH y reinicia:

```powershell
ssh -i C:\Users\csusp\.ssh\oracle.key ubuntu@64.181.162.229
```
```bash
sudo systemctl restart news-agent
sudo systemctl status news-agent  # verificar que arrancó OK
```

**Paso 4**: Verifica que el log no muestra errores:

```bash
sudo journalctl -u news-agent -n 30 --no-pager
```

#### Editar directamente en el servidor (alternativa rápida)

Para cambios pequeños (un umbral, un keyword), es más rápido editar directo:

```bash
nano ~/news_agent/news_agent_v2.py
sudo systemctl restart news-agent
```

Pero **siempre actualiza también la copia local** para mantenerlas sincronizadas.

---

### 8. Backup

#### 8a. Backup de la base de datos

Desde PowerShell en tu PC:

```powershell
scp -i C:\Users\csusp\.ssh\oracle.key ubuntu@64.181.162.229:~/news_agent/news_agent.db "C:\Users\csusp\OneDrive\Desktop\backup_news_$(Get-Date -Format 'yyyyMMdd').db"
```

Recomendado: hacerlo cada 1-2 semanas.

#### 8b. Backup completo del proyecto

```powershell
scp -i C:\Users\csusp\.ssh\oracle.key -r ubuntu@64.181.162.229:~/news_agent/ "C:\Users\csusp\OneDrive\Desktop\backup_news_full"
```

(El `-r` baja toda la carpeta — incluye config.env, script, db, logs.)

---

## 🆘 Solución de problemas

### El agente no envía notificaciones

**Verifica en orden:**

1. ¿Servicio activo?
   ```bash
   sudo systemctl status news-agent
   ```
   Si no, `sudo systemctl start news-agent`.

2. ¿Procesó noticias en último ciclo?
   ```bash
   tail -50 ~/news_agent/news_agent.log
   ```
   Debe haber líneas tipo `CoinDesk: 30 items` etc. Si todos los feeds dicen 0, hay problema de red.

3. ¿Llegan al umbral?
   Si ves `→ 0 envíos · 0 analizados`, simplemente no hay noticias importantes — es comportamiento normal. Si pasan días sin envíos y crees que sí debería haber, baja `SCORE_MINIMO_ENVIAR` temporalmente.

4. ¿Webhook funciona?
   ```bash
   cd ~/news_agent && source venv/bin/activate
   python news_agent_v2.py --test
   ```

5. ¿Notificaciones del celular activadas?
   - Samsung: **Configuración → Apps → Discord → Batería → "Sin restricciones"** (este es el #1)
   - Discord cerrado en PC o estado **Invisible**
   - Notificaciones del canal en "Todos los mensajes"

### El servicio dice "failed"

```bash
sudo journalctl -u news-agent -n 50 --no-pager
```

Causas comunes:
- API key de Anthropic inválida o sin saldo → revisa en console.anthropic.com
- Webhook de Discord inválido → regéneralo
- Error de Python en el script → revisa el traceback y revertir cambios

### Logs duplicados (cada línea aparece 2 veces)

El service file tiene `StandardOutput=append:` redundante. Edita:

```bash
sudo nano /etc/systemd/system/news-agent.service
```

Borra estas dos líneas si están:
```
StandardOutput=append:/home/ubuntu/news_agent/news_agent.log
StandardError=append:/home/ubuntu/news_agent/news_agent.log
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart news-agent
```

### "Permission denied (publickey)" al hacer SSH

En PowerShell:
```powershell
icacls C:\Users\csusp\.ssh\oracle.key /inheritance:r
icacls C:\Users\csusp\.ssh\oracle.key /grant:r "csusp:(R)"
```

### "Connection timed out" al hacer SSH

- Verifica IP: `64.181.162.229`
- Verifica VM RUNNING en cloud.oracle.com → Compute → Instances
- Si todo OK, abrir puerto 22 en Oracle Networking → tu VCN → Security Lists → Add Ingress Rule

### Costos IA disparados

```bash
python news_agent_v2.py --costs
```

Si ves más de $1/día:
- Sube `SCORE_MINIMO_ENVIAR` en el script
- Baja `MAX_NOTIS_POR_CICLO`
- Setea spend limit en console.anthropic.com → Billing

### CoinDesk siempre devuelve 0 items

Cambiaron la URL del feed. No es crítico (tienes 8 fuentes más). Si quieres arreglarlo, busca otra URL del RSS de CoinDesk y reemplaza en el script:

```bash
nano ~/news_agent/news_agent_v2.py
# busca la línea: ("CoinDesk", "https://...")
# reemplaza la URL
```

### Verificar que la IA está funcionando

```bash
cd ~/news_agent && source venv/bin/activate
python news_agent_v2.py --analyze "Federal Reserve cuts interest rates by 50bps emergency meeting"
```

Si te devuelve JSON válido → IA funciona. Si dice error o no devuelve nada, revisa API key.

---

## 📅 Mantenimiento periódico

| Frecuencia | Acción |
|---|---|
| **Diario** (30 segundos) | `sudo systemctl status news-agent \| head -3` para ver que sigue activo |
| **Semanal** (5 min) | Revisar `--costs` y query SQL de noticias CRÍTICAS de la semana para ver si los análisis fueron acertados |
| **Mensual** | Loguearte a console.anthropic.com (verifica saldo) y cloud.oracle.com (evita marca de inactiva). Backup de la DB. |
| **Cada 3-6 meses** | Actualizar paquetes: `sudo apt update && sudo apt upgrade -y` |
| **Cuando saquemos versión nueva** | Backup DB → subir nuevo script → reiniciar servicio |

---

## 💰 Costos esperados

### Oracle Cloud (servidor)
- **$0/mes** indefinidamente, mientras la VM use shape Always Free Eligible (`VM.Standard.E2.1.Micro`)
- Solo se cobra si: cambias a shape pago, excedes 10 TB/mes de tráfico saliente (imposible con este script), o no usas la cuenta por meses (logéate al menos 1x/mes)

### Anthropic API (IA)
- **~$0.15 - $0.50 USD/mes** con tu uso típico
- **~$0.001 USD por análisis**
- Con $5 USD de saldo te alcanza para **~5000 análisis** o **10+ meses**

### Discord
- $0/mes (gratis siempre)

**Total mensual: $0.15 - $0.50 USD** — esencialmente gratis.

---

## 🔐 Seguridad — qué NO hacer nunca

- ❌ Compartir o subir la llave privada `oracle.key` (NUNCA a GitHub, Telegram, etc.)
- ❌ Subir `config.env` a GitHub o sitio público (contiene webhook + API key)
- ❌ Pegar la URL del webhook en chats, foros, screenshots compartidos
- ❌ Pegar la API key de Anthropic en cualquier lado fuera del servidor
- ❌ Exponer puertos adicionales en Oracle sin saber qué hacen
- ❌ Instalar paquetes random (`sudo apt install` con cosas que no entiendes)
- ❌ Compartir credenciales con nadie, ni siquiera "para que ayude a debuggear"

### Si algo se filtra:

- **Webhook Discord filtrado**: Discord → editar canal → integraciones → webhooks → eliminar y crear nuevo. Actualiza `config.env` y reinicia.
- **API key filtrada**: console.anthropic.com → API Keys → revoke. Crea una nueva. Actualiza `config.env` y reinicia.
- **Llave SSH filtrada**: en Oracle, edita la VM y agrega una nueva llave SSH. Quita la vieja del archivo `~/.ssh/authorized_keys` en el servidor.

---

## 📞 Cuándo escribirme (a Claude)

Pégame el contexto y debuggeamos:

- Servicio en `failed` o `inactive` sin que lo hayas detenido
- Errores en `tail -100 ~/news_agent/news_agent.log`
- Notificaciones que sienten irrelevantes (mucho ruido) o que crees que se están perdiendo
- Costos de IA disparados sin explicación
- Idea de feature nueva (más cripto monitoreadas, más fuentes, otro canal de notificación, alertas de precio, etc.)
- Subir a v3 con mejoras

---

## 📂 Estructura final de archivos

### En tu PC (Windows):
```
C:\Users\csusp\OneDrive\Desktop\code todos\crypto news\
├── news_agent_v1.py             ← histórico, ya no se usa
├── news_agent_v2.py             ← actual
├── config.env.ejemplo           ← plantilla
├── manual_news_agent_v2.md      ← este archivo
└── iniciar_news_agent.bat       ← histórico, ya no se usa (v2 corre en cloud)

C:\Users\csusp\.ssh\
├── oracle.key                   ← llave privada SSH
└── oracle.key.pub               ← llave pública (opcional)
```

### En el servidor (Oracle):
```
/home/ubuntu/news_agent/
├── news_agent_v2.py             ← script ejecutándose
├── config.env                   ← webhook + API key
├── news_agent.db                ← base de datos (histórico de noticias y análisis)
├── news_agent.log               ← log de Python
└── venv/                        ← entorno aislado de Python

/etc/systemd/system/
└── news-agent.service           ← configuración del servicio 24/7
```

---

*Manual actualizado para v2 · Setup de Carlos · 28-04-2026*
*Versión del script: news_agent_v2.py · Modelo IA: claude-haiku-4-5-20251001*
