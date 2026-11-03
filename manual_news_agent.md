# Manual de operación — News Agent

Guía de referencia para manejar el agente de noticias BTC + Pi Network corriendo en Oracle Cloud.

---

## 📌 Datos clave de tu setup

| Dato | Valor |
|---|---|
| **IP pública del servidor** | `64.181.162.229` |
| **Usuario del servidor** | `ubuntu` |
| **Ruta de la llave SSH** | `C:\Users\csusp\.ssh\oracle.key` |
| **Nombre del servicio** | `news-agent` |
| **Carpeta del proyecto** | `/home/ubuntu/news_agent/` |
| **Cloud provider** | Oracle Cloud Free Tier |
| **Sistema operativo** | Ubuntu 22.04 |

> Si pierdes la llave `oracle.key`, no se puede recuperar — hay que crear una VM nueva. **Haz backup en USB o Bitwarden.**

---

## 🚀 Cheat sheet — los comandos que vas a usar

### Conectarse al servidor (siempre el primer paso)

Abre PowerShell y pega:

```powershell
ssh -i C:\Users\csusp\.ssh\oracle.key ubuntu@64.181.162.229
```

Una vez dentro (verás el prompt `ubuntu@crypto-news:~$`), todo lo demás se hace ahí.

### Comandos básicos del agente

| Acción | Comando |
|---|---|
| **Ver si está corriendo** | `sudo systemctl status news-agent` |
| **Detener** | `sudo systemctl stop news-agent` |
| **Arrancar** | `sudo systemctl start news-agent` |
| **Reiniciar** (después de cambiar config) | `sudo systemctl restart news-agent` |
| **Ver logs en vivo** (Ctrl+C para salir) | `sudo journalctl -u news-agent -f` |
| **Ver últimas 100 líneas del log** | `tail -100 ~/news_agent/news_agent.log` |

### Salir del servidor

```bash
exit
```

Esto cierra la sesión SSH. **El agente sigue corriendo** — solo cierras tu conexión remota.

---

## 🟢 Cómo está configurado ahora

- **El agente arranca solo** cada vez que el servidor se reinicie
- **Se reinicia solo** si crashea (espera 30 segundos antes de reintentar)
- **Sigue corriendo** aunque cierres PowerShell, apagues tu PC, o te vayas de viaje
- **Los logs** se guardan en `/home/ubuntu/news_agent/news_agent.log`

---

## 📖 Operaciones detalladas

### 1. Conectarse al servidor

**Desde Windows (PowerShell):**

1. Tecla Windows + R → escribe `powershell` → Enter
2. Pega:
   ```powershell
   ssh -i C:\Users\csusp\.ssh\oracle.key ubuntu@64.181.162.229
   ```
3. Si es la primera vez en mucho tiempo y te pregunta "Are you sure you want to continue connecting?", escribe `yes` + Enter

**Desde el celular (Termius — opcional):**

1. Instalar Termius desde Play Store (Samsung S25)
2. Pasar la llave `oracle.key` al celular (vía Google Drive, USB, etc.)
3. En Termius: **+** (nuevo host)
   - Hostname/IP: `64.181.162.229`
   - Username: `ubuntu`
   - Key: importar `oracle.key`
4. Tap en el host para conectarse

---

### 2. Detener el agente

Una vez dentro del servidor por SSH:

```bash
sudo systemctl stop news-agent
```

Sin output = listo, está detenido. No llegarán más notificaciones.

**Verificar:**

```bash
sudo systemctl status news-agent
```

Verás `Active: inactive (dead)` en lugar de `active (running)`.

> Importante: detenerlo así es **temporal**. Si reinicias el servidor (cosa rara que pasa solo por mantenimiento de Oracle), va a arrancar solo de nuevo.

---

### 3. Arrancar el agente

```bash
sudo systemctl start news-agent
```

Sin output = arrancó. Verifica con `status` que diga `active (running)`.

---

### 4. Reiniciar el agente

Útil cuando cambias el `config.env` o subes una versión nueva del script. Reiniciar = stop + start automático.

```bash
sudo systemctl restart news-agent
```

---

### 5. Ver logs

**Modo "en vivo"** (ves cada línea nueva al instante):

```bash
sudo journalctl -u news-agent -f
```

Salir con **Ctrl + C**.

**Últimas 100 líneas** (snapshot rápido):

```bash
tail -100 ~/news_agent/news_agent.log
```

**Buscar errores:**

```bash
grep -i "error\|warning\|exception" ~/news_agent/news_agent.log | tail -50
```

**Buscar noticias enviadas hoy:**

```bash
grep "→.*notificaciones enviadas" ~/news_agent/news_agent.log | tail -20
```

---

### 6. Cambiar configuración (webhook, umbral, keywords)

**6a. Cambiar el webhook de Discord o agregar token de CryptoPanic:**

```bash
nano ~/news_agent/config.env
```

Edita lo que necesites con las flechas. Guardar y salir: `Ctrl+O` → Enter → `Ctrl+X`.

Luego reinicia el servicio:

```bash
sudo systemctl restart news-agent
```

**6b. Cambiar el umbral de notificación (`SCORE_MINIMO_ENVIAR`) o keywords:**

```bash
nano ~/news_agent/news_agent_v1.py
```

Edita las variables al inicio del archivo (línea ~40 aprox). Mismo guardar/salir/restart.

> Tip: si quieres recibir más notis (incluyendo MEDIO), cambia `SCORE_MINIMO_ENVIAR = 7` a `5`. Si quieres menos noise (solo CRÍTICO), súbelo a `10`.

---

### 7. Apagar para vacaciones largas (no se reactiva solo)

Si te vas un mes y no quieres ni que arranque solo en caso de reinicio:

```bash
sudo systemctl stop news-agent
sudo systemctl disable news-agent
```

Para reactivar después:

```bash
sudo systemctl enable news-agent
sudo systemctl start news-agent
```

---

### 8. Subir archivos nuevos al servidor (actualizaciones)

Cuando saquemos `news_agent_v2.py` o cualquier ajuste, en una **PowerShell de tu PC** (no en el SSH):

```powershell
scp -i C:\Users\csusp\.ssh\oracle.key "C:\ruta\completa\al\archivo.py" ubuntu@64.181.162.229:~/news_agent/
```

⚠️ **Cuidado con los nombres**: si tu cliente transforma `.py` en hipervínculo y al pegar el comando aparece algo tipo `archivo_[v1.py](http://v1.py)`, escribe el nombre a mano antes de mandarlo.

Después en el SSH:

```bash
sudo systemctl restart news-agent
```

---

### 9. Backup de la base de datos

La DB `news_agent.db` guarda noticias vistas y eventos. Si quieres hacer backup ocasional:

```powershell
scp -i C:\Users\csusp\.ssh\oracle.key ubuntu@64.181.162.229:~/news_agent/news_agent.db "C:\Users\csusp\OneDrive\Desktop\backup_news_agent.db"
```

---

### 10. Inspeccionar la base de datos (lo que ha visto el agente)

Desde el SSH:

```bash
sudo apt install -y sqlite3   # solo la primera vez
sqlite3 ~/news_agent/news_agent.db
```

Te abre un prompt `sqlite>`. Algunas queries útiles:

```sql
-- Últimas 20 noticias procesadas
SELECT nivel, target, score, title, timestamp 
FROM seen_articles 
ORDER BY timestamp DESC 
LIMIT 20;

-- Cuántas noticias ha procesado por nivel
SELECT nivel, COUNT(*) FROM seen_articles GROUP BY nivel;

-- Noticias CRÍTICAS de los últimos 7 días
SELECT title, source, score, timestamp 
FROM seen_articles 
WHERE nivel = 'CRÍTICO' AND timestamp > datetime('now', '-7 days') 
ORDER BY timestamp DESC;

-- Eventos macro alertados
SELECT * FROM event_alerts ORDER BY sent_at DESC LIMIT 30;
```

Salir de sqlite con `.quit` o `Ctrl+D`.

---

## 🆘 Problemas comunes

### "Permission denied (publickey)" al hacer SSH

Permisos de la llave mal configurados. En PowerShell:

```powershell
icacls C:\Users\csusp\.ssh\oracle.key /inheritance:r
icacls C:\Users\csusp\.ssh\oracle.key /grant:r "csusp:(R)"
```

### "Connection timed out" al hacer SSH

- Verifica que estás escribiendo bien la IP: `64.181.162.229`
- Verifica que la VM esté **RUNNING** en Oracle (cloud.oracle.com → Compute → Instances)
- Si la VM está running pero igual da timeout: hay que abrir el puerto 22 en Oracle (Networking → tu VCN → Security Lists → Add Ingress Rule)

### El servicio dice "failed" en `status`

Ver el error específico:

```bash
sudo journalctl -u news-agent -n 50 --no-pager
```

Las causas más comunes:
- Webhook de Discord inválido (regéneralo en Discord → editar canal → integraciones → webhooks)
- Error de Python por algún cambio que rompió el script (revertir a versión anterior)

### No me llegan notificaciones a Discord aunque el agente está corriendo

1. **Samsung Battery Optimization** desactivada para Discord (Configuración → Apps → Discord → Batería → "Sin restricciones")
2. **Discord cerrado en PC** o estado **Invisible** (Discord no manda push si te ve activo en otra parte)
3. **Notificaciones del canal en "Todos los mensajes"** (mantener pulsado el servidor en celular → Configuración de notificaciones)
4. Verifica que el agente realmente esté enviando: en el SSH ejecuta `tail -50 ~/news_agent/news_agent.log` y busca `→ X notificaciones enviadas`

### El servicio se reinicia constantemente

```bash
sudo systemctl status news-agent
```

Si ves `Restart=always` activándose seguido es porque el script crashea y systemd lo levanta de nuevo. Revisa `tail -100 ~/news_agent/news_agent.log` para ver el traceback y mándamelo.

### Probar que el webhook funciona aislado del servicio

```bash
cd ~/news_agent
source venv/bin/activate
python news_agent_v1.py --test
```

Te debería llegar el mensaje "⚠️ News Agent funcionando" a Discord.

---

## 💰 Costos

- **Oracle Cloud Free Tier**: gratis siempre (cumpliendo el shape Always Free de la VM)
- Solo te cobrarían si:
  - Cambias a un shape pago (no lo hicimos)
  - Excedes el tráfico de salida mensual gratis (10 TB/mes — imposible llegar con este script)
  - No usas la cuenta por meses y te la marcan inactiva (basta con loguearte 1 vez al mes para evitarlo)

---

## 📝 Mantenimiento periódico recomendado

| Cada cuánto | Qué hacer |
|---|---|
| **Semanalmente (5 min)** | `sudo systemctl status news-agent` → confirmar que sigue activo. Glance al log. |
| **Mensualmente** | Loguearte a `cloud.oracle.com` para evitar que marquen la cuenta inactiva. Revisar la base de datos para ver si hay patrones de ruido en las notis y ajustar pesos de keywords. |
| **Cada 3-6 meses** | Actualizar paquetes del servidor: `sudo apt update && sudo apt upgrade -y` (no rompe nada normalmente). |
| **Cuando llegue v2** | Hacer backup de `news_agent.db`, subir el script nuevo, `sudo systemctl restart news-agent`. |

---

## 🔐 Seguridad — lo que **NO** debes hacer nunca

- ❌ Compartir o subir a internet la llave privada (`oracle.key`)
- ❌ Subir el `config.env` a GitHub o cualquier sitio público (contiene la URL del webhook)
- ❌ Pegar la URL del webhook en chats públicos, foros, screenshots compartidos, etc.
- ❌ Exponer puertos adicionales en Oracle Security Lists sin saber para qué sirven
- ❌ Instalar paquetes random sin saber qué hacen (`sudo apt install` con cosas que no entiendes)

Si crees que el webhook se filtró: ve a Discord → editar canal → integraciones → webhooks → eliminar y crear uno nuevo, actualiza `config.env` y reinicia el servicio.

---

## 📞 Cuándo llamarme (a Claude)

Pégame el output del comando y te ayudo a debuggear:

- "Active: failed" o "inactive (dead)" sin tú haberlo detenido
- Errores en `tail -100 ~/news_agent/news_agent.log`
- Notificaciones que se sienten irrelevantes (ruido) o que crees que se están perdiendo (falsos negativos)
- Idea de feature nueva (más fuentes, más cripto monitoreadas, otro canal de notificación, etc.)

---

*Generado para Carlos · Setup del 28-04-2026*
