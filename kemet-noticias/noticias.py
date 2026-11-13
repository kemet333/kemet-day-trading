#!/usr/bin/env python3
"""Monitor de noticias de kemet-noticias. Solo biblioteca estándar.

Vigila los titulares y los filings de la SEC de las acciones que sigues o tienes, imprime solo lo nuevo desde la
última comprobación (lo más reciente primero, hora de Nueva York), cuánto se ha movido hoy cada una frente al cierre
de ayer y, si existe, la agenda macro del día de kemet/agenda.json: titulares y datos en la misma pantalla.

    python3 noticias.py                                      # los tickers de kemet/watchlist.json (y kemet/portfolio.json)
    python3 noticias.py --tickers TSLA,AAPL --horas 12
    python3 noticias.py --tickers TSLA --todo --horas 72     # todo lo de los últimos 3 días, visto o no
    python3 noticias.py --sin-edgar                          # solo titulares
    python3 noticias.py --tickers TSLA --escribir            # y guarda kemet/noticias.json

Fuentes, una petición por fuente y ticker:
  - RSS de titulares de Yahoo Finance:
    https://feeds.finance.yahoo.com/rss/2.0/headline?s=<TICKER>&region=US&lang=en-US
  - Atom de filings de EDGAR (8-K por defecto: resultados, cambios de dirección, acuerdos, reformulaciones):
    https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=<CIK>&type=8-K&count=10&output=atom
    La SEC pide un User-Agent con tu nombre y tu correo (`sec_user_agent` en kemet/config.json o la variable
    SEC_USER_AGENT, "Nombre correo@ejemplo.com"). Sin él, la parte de EDGAR se omite y el tool lo dice en una
    línea; los titulares siguen.
  - El movimiento: el gráfico de Yahoo (no oficial, con retraso), el último precio frente al cierre de ayer.
  - kemet/agenda.json: los datos macro del día (la escribe el usuario o `plan.py agenda`); solo si es de hoy.

Estado: kemet/estado/noticias.json recuerda lo ya enseñado (30 días) y el CIK de cada ticker, así una noticia sale
una vez. --todo las enseña todas; --sin-estado no toca el archivo. --offline CARPETA lee yahoo-<TICKER>.xml,
chart-<TICKER>.json, sec-<FORM>-<CIK>.xml y company_tickers.json de esa carpeta (los tests lo usan).

Los titulares son pistas, no hechos: abre la noticia antes de actuar, y nada de aquí es asesoramiento.
Código de salida 0 si hay algo nuevo, 1 si no, 2 ante un error (sin tickers, un archivo que falta).
"""
import argparse
import datetime as dt
import email.utils
import gzip
import http.client
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

import comun
from comun import KemetError

YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=US&lang=en-US"
SEC_FEED = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=%s&type=%s"
            "&dateb=&owner=include&count=%d&output=atom")
TAMBIEN_ACCION = {"CL", "ES", "HG", "NG", "SIL"}   # códigos de futuro que también son acciones o ETF: Colgate, Eversource, Hamilton, NovaGold, Global X Silver Miners
CIK_DIAS = 7                 # la lista de tickers de la SEC se renueva cada semana
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
MARCADORES = ("correo@ejemplo.com", "you@example.com")
GUARDAR_DIAS = 30
MOVIMIENTO_PCT = 3.0   # una acción tan lejos del cierre de ayer se marca como SE MUEVE
ESTADO = os.path.join("estado", "noticias.json")
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

ITEMS_8K = {
    "1.01": "acuerdo relevante", "1.02": "fin de un acuerdo", "1.03": "quiebra",
    "1.05": "incidente de ciberseguridad", "2.01": "compra o venta de activos",
    "2.02": "resultados", "2.03": "deuda nueva", "2.04": "aceleración de deuda",
    "2.05": "costes de reestructuración", "2.06": "deterioro de activos", "3.01": "aviso de exclusión de cotización",
    "3.02": "venta de acciones no registradas", "3.03": "cambio en los derechos de los accionistas",
    "4.01": "cambio de auditor", "4.02": "las cuentas pasadas ya no son fiables",
    "5.01": "cambio de control", "5.02": "cambio de consejero o directivo",
    "5.03": "cambio de estatutos o de ejercicio fiscal", "5.07": "resultado de la junta",
    "7.01": "información Regulation FD", "8.01": "otros hechos", "9.01": "anexos",
}
IMPORTANTES = {"1.03", "1.05", "2.02", "2.04", "2.06", "3.01", "4.02", "5.01", "5.02"}
ETIQUETAS = [
    ("resultados", r"\bearnings\b|\bresults\b|\bEPS\b|\bquarter(ly)?\b|\bresultados\b"),
    ("guía", r"\bguidance\b|\bforecast\b|\boutlook\b|\bguía\b|\bprevisi[oó]n"),
    ("analista", r"\bupgrade[sd]?\b|\bdowngrade[sd]?\b|price target|\boutperform\b|\bunderperform\b"),
    ("demanda", r"\blawsuit\b|\bsued\b|\bprobe\b|\binvestigation\b|\bSEC charges\b|\bantitrust\b|\bjudge\b|\bcourt\b|\bdemanda\b"),
    ("fusión", r"\bacqui(?:re|res|red|sition)\b|\bmerger\b|\bbuyout\b|\btakeover\b|\bdeal\b|\bfusi[oó]n\b"),
    ("dividendo", r"\bdividend\b|\bbuyback\b|\brepurchase\b|\bstock split\b|\boffering\b|\bdividendo\b"),
    ("dirección", r"\bCEO\b|\bCFO\b|\bresign|\bsteps down\b|\bappoint|\bconsejero delegado\b"),
    ("riesgo", r"\brecall\b|\bbankrupt|\bdefault\b|\bdelist|\bhack|\bbreach\b|\boutage\b|\bquiebra\b"),
    ("parada", r"\bhalt(?:s|ed)?\b|\btrading (?:pause|suspen)"),
    ("regulador", r"\bFDA\b|\bapproval\b|\bapproves\b|\bclinical\b|\bFTC\b|\bDOJ\b|\bregulador\b"),
    ("macro", r"\bFed\b|\bFOMC\b|\bCPI\b|\binflation\b|\bjobs report\b|\bpayrolls\b|\btariffs?\b|\bfutures\b|\bIPC\b"),
]
FUENTE_RSS = "Yahoo Finance"
FUENTE_SEC = "EDGAR"


# ---------------------------------------------------------------- horas

def fecha_es(d):
    return "%s %02d/%02d/%d" % (DIAS[d.weekday()], d.day, d.month, d.year)


def fecha_corta(d):
    return "%02d/%02d/%d" % (d.day, d.month, d.year)


def ny(utc):
    return comun.a_ny(utc)


def parse_tiempo(valor):
    """RFC 822 (RSS) o ISO 8601 (Atom) a UTC naive, o None."""
    valor = (valor or "").strip()
    if not valor:
        return None
    try:
        d = email.utils.parsedate_to_datetime(valor)
    except (TypeError, ValueError, IndexError):
        d = None
    if d is None:
        try:
            d = dt.datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is not None:
        d = d.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return d.replace(microsecond=0)


# ---------------------------------------------------------------- entradas

def tickers_de_archivos():
    """{ticker: nombre o None}: los aciertos del scanner (solo acciones) y las posiciones de kemet/portfolio.json."""
    out = {}
    def accion(sym):
        try:
            return comun.es_accion(sym)
        except KemetError:
            return False                      # un símbolo raro de un archivo no tumba la búsqueda de los demás
    wl = comun.leer_json("watchlist.json", obligatorio=False) or {}
    for h in wl.get("aciertos") or wl.get("hits") or []:
        sym = (h.get("simbolo") or h.get("symbol") or "").upper().replace("-", ".")
        if sym and accion(sym):
            out[sym] = h.get("nombre") or h.get("name")
    pf = comun.leer_json("portfolio.json", obligatorio=False) or {}
    for p in pf.get("posiciones") or pf.get("positions") or []:
        sym = (p.get("simbolo") or p.get("symbol") or p.get("ticker") or "").upper().replace("-", ".")
        if sym and accion(sym) and str(p.get("instrumento") or "") != "futuro":
            out[sym] = p.get("nombre") or out.get(sym)
    return out


def sec_user_agent(cli=None):
    """El User-Agent que pide la SEC: --user-agent, SEC_USER_AGENT o `sec_user_agent` de kemet/config.json. None si falta o es el marcador."""
    ua = (cli or os.environ.get("SEC_USER_AGENT") or "").strip()
    if not ua:
        cfg = comun.leer_json("config.json", obligatorio=False) or {}
        ua = str(cfg.get("sec_user_agent") or "").strip()
    if not ua or "@" not in ua or any(m in ua for m in MARCADORES):
        return None
    return ua


# ---------------------------------------------------------------- descarga

class Descarga(object):
    def __init__(self, sec_ua=None, offline=None, pausa=0.15):
        self.sec_ua = sec_ua
        self.offline = offline
        self.pausa = pausa
        self._ultima = 0.0

    def get(self, url, nombre, sec=False):
        if self.offline:
            ruta = os.path.join(self.offline, nombre)
            if not os.path.isfile(ruta):
                raise KemetError("offline: no hay archivo %s" % ruta)
            with open(ruta, "rb") as fh:
                return fh.read()
        if sec and not self.sec_ua:
            raise KemetError("sin User-Agent para la SEC")
        hueco = time.time() - self._ultima
        if hueco < self.pausa:
            time.sleep(self.pausa - hueco)
        self._ultima = time.time()
        cab = {"User-Agent": self.sec_ua if sec else comun.UA, "Accept-Encoding": "gzip"}
        req = urllib.request.Request(url, headers=cab)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                datos = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    datos = gzip.decompress(datos)
                return datos
        except urllib.error.HTTPError as e:
            raise KemetError("HTTP %s en %s" % (e.code, url))
        except urllib.error.URLError as e:
            raise KemetError("no se pudo llegar a %s: %s" % (url, e.reason))
        except (http.client.HTTPException, OSError) as e:      # conexión cortada, respuesta a medias, timeout
            raise KemetError("la conexión falló en %s: %s" % (url, e.__class__.__name__))


def simbolo_yahoo(ticker):
    return ticker.upper().replace(".", "-")


def mapa_cik(descarga, estado):
    """ticker a CIK de 10 dígitos, del company_tickers.json de la SEC (guardado en el estado)."""
    cache = estado.setdefault("ciks", {})
    fecha = comun.de_iso(estado.get("ciks_leidos"))
    if cache and fecha and (comun.utc_ahora() - fecha).days < CIK_DIAS:
        return cache
    datos = json.loads(descarga.get(TICKERS_URL, "company_tickers.json", sec=True).decode("utf-8"))
    cache.clear()                             # una salida a bolsa o un cambio de ticker entran al renovarla (cada CIK_DIAS días)
    for v in datos.values():
        cache.setdefault(v["ticker"].upper().replace("-", "."), str(v["cik_str"]).zfill(10))
    estado["ciks_leidos"] = comun.iso(comun.utc_ahora())
    return cache


# ---------------------------------------------------------------- parseo

def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _texto(el, nombre):
    for c in el.iter():
        if _local(c.tag) == nombre:
            return (c.text or "").strip()
    return ""


def parse_rss(datos, ticker):
    """RSS de titulares de Yahoo a items."""
    try:
        raiz = ET.fromstring(datos)
    except ET.ParseError as e:
        raise KemetError("el RSS de %s no es XML válido: %s" % (ticker, e))
    out = []
    for it in raiz.iter("item"):
        titulo = _texto(it, "title")
        enlace = _texto(it, "link")
        guid = _texto(it, "guid") or enlace
        out.append({"id": "rss:" + guid, "fuente": FUENTE_RSS, "tipo": "titular", "ticker": ticker, "titulo": titulo,
                    "resumen": _texto(it, "description"), "enlace": enlace, "hora": parse_tiempo(_texto(it, "pubDate"))})
    return out


def parse_sec_atom(datos, ticker):
    """Atom de filings de EDGAR a items."""
    try:
        raiz = ET.fromstring(datos)
    except ET.ParseError as e:
        raise KemetError("el feed de la SEC de %s no es XML válido: %s" % (ticker, e))
    empresa = ""
    for el in raiz.iter():
        if _local(el.tag) == "conformed-name":
            empresa = (el.text or "").strip()
            break
    out = []
    for entry in raiz.iter():
        if _local(entry.tag) != "entry":
            continue
        form = _texto(entry, "filing-type")
        acc = _texto(entry, "accession-number")
        items = re.findall(r"\d+\.\d+", _texto(entry, "items-desc"))
        etiquetas = [ITEMS_8K.get(i, "punto " + i) for i in items if i != "9.01"]
        enlace = ""
        for c in entry.iter():
            if _local(c.tag) == "link":
                enlace = c.get("href", "")
        titulo = "%s presentó un %s" % (empresa or ticker, form)
        if etiquetas:
            titulo += ": " + ", ".join(etiquetas)
        out.append({"id": "sec:" + acc, "fuente": FUENTE_SEC, "tipo": "filing", "formulario": form, "ticker": ticker,
                    "titulo": titulo, "resumen": _texto(entry, "form-name"), "items": items,
                    "importante": bool(set(items) & IMPORTANTES), "enlace": enlace, "hora": parse_tiempo(_texto(entry, "updated"))})
    return out


def parse_chart(datos, ticker):
    """JSON del gráfico de Yahoo a {"ticker", "precio", "cierre_ayer", "pct", "hora"} o KemetError."""
    try:
        doc = json.loads(datos.decode("utf-8") if isinstance(datos, bytes) else datos)
        meta = doc["chart"]["result"][0]["meta"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise KemetError("el gráfico de %s no sirve" % ticker)
    precio = meta.get("regularMarketPrice")
    ayer = meta.get("chartPreviousClose") or meta.get("previousClose")
    if not precio or not ayer:
        raise KemetError("el gráfico de %s no trae precio" % ticker)
    cuando = meta.get("regularMarketTime")
    return {"ticker": ticker, "precio": round(float(precio), 2), "cierre_ayer": round(float(ayer), 2),
            "pct": round((float(precio) / float(ayer) - 1) * 100, 2), "hora": comun.utc_de_ts(cuando) if cuando else None}


def movimientos(descarga, tickers, errores=None):
    errores = [] if errores is None else errores
    out = []
    for t in sorted(tickers):
        nombre = "chart-%s.json" % t
        try:
            ruta = ("/v8/finance/chart/%s?range=1d&interval=5m" % simbolo_yahoo(t)) if t in TAMBIEN_ACCION else comun.chart_path(t, "1d", "5m")
            datos = descarga.get("https://query2.finance.yahoo.com" + ruta, nombre)   # CL es la acción de Colgate, no el crudo
            out.append(parse_chart(datos, t))
        except KemetError as e:
            if not (descarga.offline and "no hay archivo" in str(e)):
                errores.append("precio de %s: %s" % (t, e))
    return out


# ---------------------------------------------------------------- etiquetas y duplicados

def patrones_mencion(tickers):
    pats = {}
    for t, nombre in tickers.items():
        alts = [r"\(%s\)" % re.escape(t), r"\$%s\b" % re.escape(t), r"\b(?:NYSE|NASDAQ|Nasdaq)\s*:\s*%s\b" % re.escape(t)]
        if nombre and len(nombre) >= 4:
            alts.append(r"\b%s\b" % re.escape(nombre).replace(r"\ ", r"[\s-]"))
        pats[t] = re.compile("|".join(alts))
    return pats


def etiquetar(items, tickers):
    """A qué tickers toca cada item y sus etiquetas."""
    pats = patrones_mencion(tickers)
    for it in items:
        pajar = "%s %s" % (it["titulo"], it.get("resumen") or "")
        toca = {it["ticker"]} if it["ticker"] in tickers else set()
        for t, rx in pats.items():
            if rx.search(pajar):
                toca.add(t)
        it["toca"] = sorted(toca)
        it["etiquetas"] = [e for e, rx in ETIQUETAS if re.search(rx, pajar, re.I)]
        if it["tipo"] == "filing" and "2.02" in it.get("items", []) and "resultados" not in it["etiquetas"]:
            it["etiquetas"].insert(0, "resultados")
    return items


def sin_duplicados(items):
    """Un item por historia: mismo id, mismo enlace o mismo título el mismo día."""
    vistos, out = {}, []
    for it in items:
        claves = [it["id"], it["enlace"],
                  "%s|%s" % (re.sub(r"\W+", " ", it["titulo"].lower()).strip(), it["hora"].date() if it["hora"] else "")]
        ya = next((vistos[k] for k in claves if k and k in vistos), None)
        if ya is not None:
            for t in it.get("toca", []):
                if t not in ya["toca"]:
                    ya["toca"].append(t)
            ya["toca"].sort()
            continue
        for k in claves:
            if k:
                vistos[k] = it
        out.append(it)
    return out


def huella(it):
    return hashlib.sha1(it["id"].encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- la comprobación

def recoger(descarga, tickers, estado, sec=True, formularios=("8-K",), cuantos=10, errores=None):
    errores = [] if errores is None else errores
    items = []
    for t in sorted(tickers):
        try:
            items += parse_rss(descarga.get(YAHOO_RSS % simbolo_yahoo(t), "yahoo-%s.xml" % t), t)
        except KemetError as e:
            errores.append("titulares de %s: %s" % (t, e))
    if sec:
        try:
            ciks = mapa_cik(descarga, estado)
        except KemetError as e:
            errores.append("lista de tickers de la SEC: %s" % e)
            ciks = {}
        for t in sorted(tickers):
            cik = ciks.get(t)
            if not cik:
                if ciks:
                    errores.append("sin CIK en la SEC para %s" % t)
                continue
            for form in formularios:
                try:
                    datos = descarga.get(SEC_FEED % (cik, form, cuantos), "sec-%s-%s.xml" % (form, cik), sec=True)
                    items += parse_sec_atom(datos, t)
                except KemetError as e:
                    errores.append("EDGAR %s de %s: %s" % (form, t, e))
    return items


def seleccionar(items, estado, ahora, horas=12, todo=False):
    """Los items dentro de la ventana; solo los no vistos salvo con --todo. Los más recientes primero."""
    vistos = estado.setdefault("vistos", {})
    corte = ahora - dt.timedelta(hours=horas)
    tope = ahora + dt.timedelta(minutes=10)   # con --ahora fijado no sale nada de después
    out = []
    for it in items:
        if it["hora"] is not None and (it["hora"] < corte or it["hora"] > tope):
            continue
        it["nuevo"] = huella(it) not in vistos
        if it["nuevo"] or todo:
            out.append(it)
    out.sort(key=lambda i: (i["hora"] or ahora), reverse=True)
    return out


def recordar(items, estado, ahora):
    vistos = estado.setdefault("vistos", {})
    sello = comun.iso(ahora)
    for it in items:
        vistos.setdefault(huella(it), sello)
    corte = comun.iso(ahora - dt.timedelta(days=GUARDAR_DIAS))
    estado["vistos"] = {k: v for k, v in vistos.items() if v >= corte}
    estado["ultima_comprobacion"] = sello


# ---------------------------------------------------------------- la agenda macro

def agenda_de_hoy(ahora, mercados=None):
    """(datos de hoy o None, aviso). Los datos de kemet/agenda.json con su hora, si es de hoy; cada uno con `pasado` y `ventana`."""
    doc = comun.leer_json("agenda.json", obligatorio=False)
    hoy = ny(ahora).date()
    if not doc:
        return None, "sin kemet/agenda.json: no conozco los datos macro de hoy (escríbela con `plan.py agenda`)"
    if doc.get("fecha") != hoy.isoformat():
        return None, "kemet/agenda.json es del %s, no de hoy: no la enseño" % doc.get("fecha")
    t_ny = ny(ahora)
    out = []
    for d in doc.get("datos") or []:
        if not d.get("hora"):
            raise KemetError("un dato de la agenda no tiene hora: %r" % (d,))
        h = comun.parse_hhmm(d["hora"], "la hora de %s" % d.get("nombre", "un dato"))
        cuando = dt.datetime.combine(hoy, h)
        margen = 20 if d.get("fuerte") else 10
        falta = int((cuando - t_ny).total_seconds() // 60)
        out.append({"hora": comun.hhmm(h), "nombre": d.get("nombre", "dato"), "fuerte": bool(d.get("fuerte")),
                    "mercados": d.get("mercados") or [], "ventana": "%s a %s" % (comun.hhmm((cuando - dt.timedelta(minutes=margen)).time()),
                                                                                comun.hhmm((cuando + dt.timedelta(minutes=margen)).time())),
                    "pasado": falta < -margen, "minutos": falta})
    out.sort(key=lambda x: x["hora"])
    return out, None


def lineas_agenda(datos):
    out = ["Agenda macro de hoy (kemet/agenda.json), hora de Nueva York:"]
    for d in datos:
        margen = 20 if d["fuerte"] else 10
        if d["pasado"]:
            cuando = "pasado"
        elif d["minutos"] <= margen:
            cuando = "ahora, dentro de la ventana" + (" (el dato sale dentro de %d min)" % d["minutos"] if d["minutos"] > 0 else "")
        elif d["minutos"] < 60:
            cuando = "dentro de %d min" % d["minutos"]
        else:
            cuando = "dentro de %d h %02d min" % divmod(d["minutos"], 60)
        extra = []
        if d["fuerte"]:
            extra.append("fuerte")
        if d["mercados"]:
            extra.append("solo " + ", ".join(d["mercados"]))
        out.append("  %s  %-28s %s  ventana sin operar %s  (%s)" % (d["hora"], d["nombre"], ", ".join(extra).ljust(12), d["ventana"], cuando))
    return out


# ---------------------------------------------------------------- salida

def lineas_movimientos(movs, pct=MOVIMIENTO_PCT):
    out = []
    for m in movs:
        marca = "  SE MUEVE" if abs(m["pct"]) >= pct else ""
        cuando = (", a las %s NY" % comun.hhmm(ny(m["hora"]))) if m.get("hora") else ""
        out.append("  %-6s %s  %s%s %% (cierre de ayer %s%s)%s" % (m["ticker"], comun.usd(m["precio"], 2), "+" if m["pct"] >= 0 else "",
                                                                   comun.num(m["pct"]), comun.usd(m["cierre_ayer"], 2), cuando, marca))
    return out


def render(items, errores, ahora, tickers, horas, movs=None, agenda=None, pct=MOVIMIENTO_PCT):
    t = ny(ahora)
    out = ["Noticias de %s, %s, %s · últimas %s horas, titulares de Yahoo Finance, 8-K de EDGAR y movimiento de hoy"
           % (", ".join(sorted(tickers)) if tickers else "la agenda", fecha_es(t.date()), comun.hora_doble(ahora), comun.num(horas, 0) if horas == int(horas) else comun.num(horas, 1))]
    if movs:
        abierto = comun.estado_nyse(ahora)[0] == "abierto"
        recientes = [m for m in movs if m.get("hora") and ny(m["hora"]).date() == t.date()]
        out.append("Movimiento de hoy frente al cierre de ayer:" if abierto or recientes else
                   "La bolsa aún no ha abierto hoy: esto es el movimiento de la última sesión, no el de hoy (sin datos de premercado):")
        out += lineas_movimientos(movs, pct)
    if agenda:
        out += lineas_agenda(agenda)
    if tickers:
        out.append("Lo nuevo, lo más reciente primero:" if items else "Nada nuevo en las últimas %s horas." % comun.num(horas, 0))
    for it in items:
        cuando = ny(it["hora"]) if it["hora"] else None
        sello = "%s %s" % (fecha_corta(cuando.date()), comun.hhmm(cuando)) if cuando else "hora desconocida"
        marca = "!" if it.get("importante") else " "
        quien = ",".join(it["toca"]) or it["ticker"]
        out.append("%s %s  %-11s %-13s %s" % (marca, sello, quien, it["fuente"], it["titulo"]))
        extra = []
        if it["etiquetas"]:
            extra.append("etiquetas: " + ", ".join(it["etiquetas"]))
        extra.append(it["enlace"])
        out.append("      " + "  ".join(extra))
    for e in errores:
        out.append("Nota: %s" % e)
    out.append("Comprobado a las %s NY. Los titulares son pistas, no hechos: abre la noticia antes de actuar. No es asesoramiento financiero." % comun.hhmm(t))
    return "\n".join(out) + "\n"


def _json_listo(items):
    out = []
    for it in items:
        d = dict(it)
        d["hora"] = comun.iso(it["hora"]) if it["hora"] else None
        d["hora_ny"] = comun.hhmm(ny(it["hora"])) if it["hora"] else None
        out.append(d)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Monitor de noticias (kemet-noticias): titulares, 8-K, movimiento de hoy y la agenda macro.")
    ap.add_argument("--tickers", nargs="*", help="TSLA,AAPL o TSLA AAPL; por defecto los de kemet/watchlist.json")
    ap.add_argument("--horas", type=float, default=12, help="ignora lo más antiguo que esto (12)")
    ap.add_argument("--todo", action="store_true", help="enseña también lo ya visto")
    ap.add_argument("--formularios", default="8-K", help="formularios de la SEC, separados por comas (8-K)")
    ap.add_argument("--sin-edgar", dest="sin_edgar", action="store_true", help="solo titulares")
    ap.add_argument("--sin-movimiento", dest="sin_movimiento", action="store_true", help="sin la línea de precio por ticker")
    ap.add_argument("--movimiento-pct", dest="movimiento_pct", type=float, default=MOVIMIENTO_PCT, help="marca SE MUEVE desde este %% (3)")
    ap.add_argument("--user-agent", dest="user_agent", help="User-Agent para la SEC: \"Nombre correo@ejemplo.com\"")
    ap.add_argument("--offline", metavar="CARPETA")
    ap.add_argument("--ahora", help='fija el reloj ("2026-10-19 10:15", hora de Nueva York)')
    ap.add_argument("--sin-estado", dest="sin_estado", action="store_true", help="no toca kemet/estado/noticias.json")
    ap.add_argument("--escribir", action="store_true", help="guarda kemet/noticias.json")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        return correr(a)
    except KemetError as e:
        print("noticias.py: %s" % e, file=sys.stderr)
        return 2


def correr(a):
    ahora = comun.parse_ahora(a.ahora)
    pedidos, avisos_tickers = [], []
    for x in a.tickers or []:
        pedidos += [s for s in re.split(r"[,\s]+", x.upper()) if s]
    conocidos = tickers_de_archivos()
    if pedidos:
        tickers = {}
        for t in pedidos:
            t = t.replace("-", ".")
            if t in TAMBIEN_ACCION:
                # CL es Colgate, ES Eversource, HG Hamilton: aquí se pide por ticker, así que es la acción
                avisos_tickers.append("%s también es un futuro; busco las noticias de la acción %s (los futuros no tienen titulares por ticker: mira la agenda)" % (t, t))
            elif not comun.es_accion(t):
                raise KemetError("%s no es un ticker de acciones de EE. UU.; los futuros no tienen titulares por ticker, mira la agenda y kemet-niveles" % t)
            tickers[t] = conocidos.get(t)
    else:
        tickers = conocidos
    agenda, aviso_agenda = agenda_de_hoy(ahora)
    if not tickers and not agenda:
        raise KemetError("sin tickers: pasa --tickers TSLA,AAPL o lanza kemet-scanner antes (escribe kemet/watchlist.json)")
    estado = (comun.leer_json(comun.ruta(ESTADO), obligatorio=False) if not a.sin_estado else None) or {}
    errores = list(avisos_tickers)
    if aviso_agenda:
        errores.append(aviso_agenda)
    ua = sec_user_agent(a.user_agent)
    sec = not a.sin_edgar
    if sec and not ua and not a.offline:
        errores.append("EDGAR omitido: pon sec_user_agent en kemet/config.json o la variable SEC_USER_AGENT (\"Nombre correo@ejemplo.com\") para incluir los 8-K")
        sec = False
    descarga = Descarga(ua, offline=a.offline)
    formularios = [f.strip().upper() for f in a.formularios.split(",") if f.strip()]
    items = recoger(descarga, tickers, estado, sec=sec, formularios=formularios, errores=errores) if tickers else []
    items = sin_duplicados(etiquetar(items, tickers))
    mostrados = seleccionar(items, estado, ahora, horas=a.horas, todo=a.todo)
    movs = [] if a.sin_movimiento or not tickers else movimientos(descarga, tickers, errores)
    doc = {"generado": comun.iso(ahora), "fuente": "RSS de Yahoo Finance, Atom de EDGAR, gráfico de Yahoo, kemet/agenda.json",
           "tickers": sorted(tickers), "horas": a.horas,
           "movimientos": [dict(m, hora=comun.iso(m["hora"]) if m.get("hora") else None, se_mueve=abs(m["pct"]) >= a.movimiento_pct) for m in movs],
           "agenda": agenda, "items": _json_listo(mostrados), "notas": errores}
    if a.escribir:
        doc["escrito"] = comun.escribir_json("noticias.json", doc)
    if a.json:
        print(json.dumps(doc, indent=1, ensure_ascii=False))
    else:
        sys.stdout.write(render(mostrados, errores, ahora, tickers, a.horas, movs, agenda, a.movimiento_pct))
        if a.escribir:
            print("Escrito %s." % doc["escrito"])
    if not a.sin_estado:
        recordar(mostrados, estado, ahora)        # solo lo enseñado: lo que quedó fuera de la ventana sigue siendo nuevo
        comun.escribir_json(comun.ruta(ESTADO), estado)
    if tickers and not items and not movs and errores and all(_es_fallo_de_red(e) for e in errores if e not in avisos_tickers and e != aviso_agenda):
        print("Sin conexión con las fuentes: lo de arriba no significa «no hay noticias». Repite en unos minutos.", file=sys.stderr)
        return 2
    return 0 if any(i["nuevo"] for i in mostrados) or (not tickers and agenda) else 1


def _es_fallo_de_red(texto):
    return any(x in texto for x in ("no se pudo llegar", "la conexión falló", "HTTP 5", "HTTP 429"))


if __name__ == "__main__":
    sys.exit(main())
