"""Lo que comparten las herramientas del pack Kemet Day Trading. Solo biblioteca estándar.

Cada carpeta de skill lleva una copia idéntica de este archivo (tests/test_repo.py lo comprueba), porque cada
skill se instala sola. Hora de Nueva York y de Madrid calculadas a mano (sin zoneinfo: funciona igual en Windows),
velas de Yahoo Finance (gratis, sin clave, unos 10 minutos de retraso en futuros), el día de negociación de CME
(empieza a las 18:00 NY del día anterior), contratos y micros, acciones de EE. UU. por su ticker, el reloj de
Globex y el de la NYSE, y los archivos de `kemet/`.

Instrumentos: `resolver("NQ")` devuelve el contrato (mini y micro, tick, valor del punto, sesión regular);
`resolver("TSLA")` devuelve la acción (1 $ por punto y acción, tick 0,01, 09:30 a 16:00 NY, festivos NYSE).
Las funciones que reciben `codigo` aceptan cualquiera de los dos.
"""
import datetime as _dt
import functools
import glob
import gzip
import json
import os
import re
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (compatible; kemet-day-trading/2.0; +https://www.kemet-capital.com/skill/)"
PAUSE = 0.5       # segundos entre peticiones al endpoint gratuito
BACKOFF = 5.0     # segundos antes del único reintento tras un HTTP 429
HOSTS = ("query2", "query1")
BAR = {"1m": 60, "5m": 300, "15m": 900}
EPOCH = _dt.datetime(1970, 1, 1)
KEMET_DIR = os.environ.get("KEMET_DIR", "kemet")

# Contratos: símbolo de Yahoo, mini y micro, tick, valor del punto (mini, micro), sesión regular NY y hora de estar plano.
CONTRATOS = {
    "ES":  {"yahoo": "ES=F", "mini": "ES",  "micro": "MES", "tick": 0.25, "punto_mini": 50.0,   "punto_micro": 5.0,   "rth": ("09:30", "16:00"), "plano": "15:55", "nombre": "S&P 500"},
    "NQ":  {"yahoo": "NQ=F", "mini": "NQ",  "micro": "MNQ", "tick": 0.25, "punto_mini": 20.0,   "punto_micro": 2.0,   "rth": ("09:30", "16:00"), "plano": "15:55", "nombre": "Nasdaq 100"},
    "YM":  {"yahoo": "YM=F", "mini": "YM",  "micro": "MYM", "tick": 1.0,  "punto_mini": 5.0,    "punto_micro": 0.5,   "rth": ("09:30", "16:00"), "plano": "15:55", "nombre": "Dow Jones"},
    "RTY": {"yahoo": "RTY=F", "mini": "RTY", "micro": "M2K", "tick": 0.1, "punto_mini": 50.0,   "punto_micro": 5.0,   "rth": ("09:30", "16:00"), "plano": "15:55", "nombre": "Russell 2000"},
    "CL":  {"yahoo": "CL=F", "mini": "CL",  "micro": "MCL", "tick": 0.01, "punto_mini": 1000.0, "punto_micro": 100.0, "rth": ("09:00", "14:30"), "plano": "14:25", "nombre": "Crudo WTI"},
    "GC":  {"yahoo": "GC=F", "mini": "GC",  "micro": "MGC", "tick": 0.1,  "punto_mini": 100.0,  "punto_micro": 10.0,  "rth": ("08:20", "13:30"), "plano": "13:25", "nombre": "Oro"},
    "SI":  {"yahoo": "SI=F", "mini": "SI",  "micro": "SIL", "tick": 0.005, "punto_mini": 5000.0, "punto_micro": 1000.0, "rth": ("08:25", "13:25"), "plano": "13:20", "nombre": "Plata"},
    "HG":  {"yahoo": "HG=F", "mini": "HG",  "micro": "MHG", "tick": 0.0005, "punto_mini": 25000.0, "punto_micro": 2500.0, "rth": ("08:10", "13:00"), "plano": "12:55", "nombre": "Cobre"},
    "NG":  {"yahoo": "NG=F", "mini": "NG",  "micro": "MNG", "tick": 0.001, "punto_mini": 10000.0, "punto_micro": 1000.0, "rth": ("09:00", "14:30"), "plano": "14:25", "nombre": "Gas natural"},
    "6E":  {"yahoo": "6E=F", "mini": "6E",  "micro": "M6E", "tick": 0.0001,  "punto_mini": 125000.0, "punto_micro": 12500.0, "rth": ("08:20", "15:00"), "plano": "14:55", "nombre": "Euro"},
    "ZN":  {"yahoo": "ZN=F", "mini": "ZN",  "micro": "ZN",  "tick": 0.015625, "punto_mini": 1000.0, "punto_micro": 1000.0, "rth": ("08:20", "15:00"), "plano": "14:55", "nombre": "Bono 10 años"},
    "ZB":  {"yahoo": "ZB=F", "mini": "ZB",  "micro": "ZB",  "tick": 0.03125, "punto_mini": 1000.0, "punto_micro": 1000.0, "rth": ("08:20", "15:00"), "plano": "14:55", "nombre": "Bono 30 años"},
}
INDICES = ("ES", "NQ", "YM", "RTY")
# MNG son 1.000 MMBtu (1 $/tick). En 6E el tick es el del micro (0,0001): un precio a 0,0001 vale para 6E (0,00005) y M6E.
# ZN y ZB no tienen micro: su «micro» es el propio contrato y se cuenta con el tope de minis, nunca con el de micros.
MICRO_A_CODIGO = {v["micro"]: k for k, v in CONTRATOS.items() if v["micro"] != v["mini"]}


def sin_micro(codigo):
    """ZN, ZB: el contrato no tiene micro y cada unidad es un contrato entero."""
    c = CONTRATOS.get(codigo)
    return bool(c) and c["micro"] == c["mini"]

# CME Globex (futuros de índices, energía y metales): abre el domingo a las 18:00 NY, cierra el viernes a las 17:00 NY,
# con una pausa diaria de 17:00 a 18:00 NY. Festivos con cierre completo o sesión recortada (cmegroup.com, leído el
# 2026-11-12; confirma siempre en el calendario de CME antes de un festivo).
CME_CERRADO = {
    "2026-01-01": "Año Nuevo", "2026-04-03": "Viernes Santo", "2026-12-25": "Navidad",
    "2027-01-01": "Año Nuevo", "2027-03-26": "Viernes Santo", "2027-12-24": "Navidad (observado)",
}
CME_RECORTADO = {  # cierre anticipado de la sesión regular: 13:00 NY para índices
    "2026-01-19": "Martin Luther King", "2026-02-16": "Presidents Day", "2026-05-25": "Memorial Day", "2026-06-19": "Juneteenth",
    "2026-07-03": "Independence Day (observado)", "2026-09-07": "Labor Day", "2026-11-26": "Thanksgiving", "2026-11-27": "Día después de Thanksgiving",
    "2026-12-24": "Nochebuena", "2027-01-18": "Martin Luther King", "2027-02-15": "Presidents Day", "2027-05-31": "Memorial Day",
    "2027-06-18": "Juneteenth (observado)", "2027-07-05": "Independence Day (observado)", "2027-09-06": "Labor Day", "2027-11-25": "Thanksgiving", "2027-11-26": "Día después de Thanksgiving",
}
CALENDARIO = (2026, 2027)
CME_CORTE_RECORTADO = _dt.time(13, 0)   # en una sesión recortada los índices paran a las 13:00 NY (algunos días a las 13:15: aquí, el corte prudente)

# NYSE (acciones): cerrada y sesión recortada a las 13:00 NY (nyse.com/markets/hours-calendars, leído el 2026-10-13).
NYSE_CERRADO = {
    "2026-01-01": "Año Nuevo", "2026-01-19": "Martin Luther King", "2026-02-16": "Presidents Day", "2026-04-03": "Viernes Santo",
    "2026-05-25": "Memorial Day", "2026-06-19": "Juneteenth", "2026-07-03": "Independence Day (observado)", "2026-09-07": "Labor Day",
    "2026-11-26": "Thanksgiving", "2026-12-25": "Navidad",
    "2027-01-01": "Año Nuevo", "2027-01-18": "Martin Luther King", "2027-02-15": "Presidents Day", "2027-03-26": "Viernes Santo",
    "2027-05-31": "Memorial Day", "2027-06-18": "Juneteenth (observado)", "2027-07-05": "Independence Day (observado)", "2027-09-06": "Labor Day",
    "2027-11-25": "Thanksgiving", "2027-12-24": "Navidad (observado)",
}
NYSE_RECORTADO = {"2026-11-27": "Día después de Thanksgiving", "2026-12-24": "Nochebuena", "2027-11-26": "Día después de Thanksgiving"}
_TICKER = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


def resolver(simbolo):
    """Un futuro por su código (NQ), su mini o su micro (MNQ, MES), o una acción de EE. UU. por su ticker (TSLA, BRK.B).
    Devuelve un dict con `tipo` ("futuro" | "accion"), `codigo`, `yahoo`, `tick`, `punto_mini`, `punto_micro`, `mini`, `micro`,
    `rth`, `plano`, `nombre`. Para una acción, el punto vale 1 $ por acción y mini y micro son el propio ticker."""
    if isinstance(simbolo, dict):
        return simbolo
    s = str(simbolo or "").strip().upper()
    if s in CONTRATOS:
        return dict(CONTRATOS[s], tipo="futuro", codigo=s)
    if s in MICRO_A_CODIGO:
        c = MICRO_A_CODIGO[s]
        return dict(CONTRATOS[c], tipo="futuro", codigo=c)
    if s.endswith("=F") and s[:-2] in CONTRATOS:
        return dict(CONTRATOS[s[:-2]], tipo="futuro", codigo=s[:-2])
    if _TICKER.match(s):
        return {"tipo": "accion", "codigo": s, "yahoo": s.replace(".", "-"), "mini": s, "micro": s, "tick": 0.01, "punto_mini": 1.0, "punto_micro": 1.0,
                "rth": ("09:30", "16:00"), "plano": "15:55", "nombre": s}
    raise KemetError("no conozco el instrumento %r: un futuro (%s) o un ticker de EE. UU." % (simbolo, ", ".join(CONTRATOS)))


def es_accion(simbolo):
    return resolver(simbolo)["tipo"] == "accion"


class KemetError(Exception):
    """Un error que se cuenta al usuario en una línea, sin traza."""


# ---------------------------------------------------------------- horas

def _nth_sunday(year, month, n):
    d = _dt.date(year, month, 1)
    d += _dt.timedelta(days=(6 - d.weekday()) % 7)
    return d + _dt.timedelta(days=7 * (n - 1))


def _last_sunday(year, month):
    d = _dt.date(year, month + 1, 1) - _dt.timedelta(days=1) if month < 12 else _dt.date(year, 12, 31)
    return d - _dt.timedelta(days=(d.weekday() + 1) % 7)


@functools.lru_cache(maxsize=None)
def _verano_ny(y):
    return _dt.datetime.combine(_nth_sunday(y, 3, 2), _dt.time(7, 0)), _dt.datetime.combine(_nth_sunday(y, 11, 1), _dt.time(6, 0))   # 2:00 EST = 7:00 UTC; 2:00 EDT = 6:00 UTC


@functools.lru_cache(maxsize=None)
def _verano_madrid(y):
    return _dt.datetime.combine(_last_sunday(y, 3), _dt.time(1, 0)), _dt.datetime.combine(_last_sunday(y, 10), _dt.time(1, 0))


def ny_offset(utc):
    """Horas que Nueva York va por detrás de UTC: 4 en horario de verano (2.º domingo de marzo, 2:00, al 1.º de noviembre), 5 el resto."""
    start, end = _verano_ny(utc.year)
    return -4 if start <= utc < end else -5


def madrid_offset(utc):
    """Horas que Madrid va por delante de UTC: 2 en verano (último domingo de marzo, 1:00 UTC, al último de octubre), 1 el resto."""
    start, end = _verano_madrid(utc.year)
    return 2 if start <= utc < end else 1


def a_ny(utc):
    return utc + _dt.timedelta(hours=ny_offset(utc))


def a_madrid(utc):
    return utc + _dt.timedelta(hours=madrid_offset(utc))


def de_ny(local):
    """Hora de Nueva York (naive) a UTC (naive)."""
    guess = local + _dt.timedelta(hours=5)
    return local - _dt.timedelta(hours=ny_offset(guess))


def utc_ahora():
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None, microsecond=0)


def utc_de_ts(ts):
    return EPOCH + _dt.timedelta(seconds=int(ts))


def ts_de_utc(utc):
    return int((utc - EPOCH).total_seconds())


def parse_ahora(text):
    """`--ahora "2026-11-11 10:35"` en hora de Nueva York (o `2026-11-11T10:35`). Vacío: ahora."""
    if not text:
        return utc_ahora()
    t = text.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return de_ny(_dt.datetime.strptime(t, fmt))
        except ValueError:
            pass
    raise KemetError("no entiendo la hora %r: usa AAAA-MM-DD HH:MM en hora de Nueva York" % text)


def parse_hhmm(text, que="la hora"):
    try:
        h, m = text.strip().split(":")
        t = _dt.time(int(h), int(m))
        return t
    except Exception:
        raise KemetError("%s tiene que ser HH:MM, no %r" % (que, text))


def hhmm(t):
    return "%02d:%02d" % (t.hour, t.minute)


def hora_doble(utc):
    """`15:30 Madrid / 09:30 NY` para cabeceras."""
    return "%s Madrid / %s NY" % (hhmm(a_madrid(utc)), hhmm(a_ny(utc)))


# ---------------------------------------------------------------- el día de negociación y el reloj de CME

def dia_negociacion(ny):
    """Un día de CME empieza a las 18:00 NY de la víspera: una vela pertenece al día de (hora + 6 h)."""
    return (ny + _dt.timedelta(hours=6)).date()


def estado_globex(utc):
    """abierto | pausa (17:00–18:00 NY entre semana) | cerrado (fin de semana, festivo). Devuelve (estado, motivo)."""
    ny = a_ny(utc)
    d, t = ny.date(), ny.time()
    clave = d.isoformat()
    if clave in CME_CERRADO:
        return "cerrado", CME_CERRADO[clave]
    wd = d.weekday()  # lunes 0 … domingo 6
    if wd == 5:
        return "cerrado", "sábado"
    if wd == 6:
        return ("abierto", "sesión del domingo noche") if t >= _dt.time(18, 0) else ("cerrado", "domingo, abre a las 18:00 NY")
    if wd == 4 and t >= _dt.time(17, 0):
        return "cerrado", "viernes, cierre semanal a las 17:00 NY"
    manana = (d + _dt.timedelta(days=1)).isoformat()
    if manana in CME_CERRADO and t >= _dt.time(17, 0):
        return "cerrado", "víspera de %s: no hay sesión esta noche" % CME_CERRADO[manana]
    if clave in CME_RECORTADO and CME_CORTE_RECORTADO <= t < _dt.time(18, 0):
        return ("cerrado" if wd == 4 else "pausa"), "sesión recortada (%s): para a las %s NY" % (CME_RECORTADO[clave], CME_CORTE_RECORTADO.strftime("%H:%M"))
    if _dt.time(17, 0) <= t < _dt.time(18, 0):
        return "pausa", "pausa diaria 17:00–18:00 NY"
    return "abierto", "sesión recortada: " + CME_RECORTADO[clave] if clave in CME_RECORTADO else "sesión normal"


@functools.lru_cache(maxsize=4096)
def estado_nyse(utc):
    """abierto | cerrado para acciones: 09:30 a 16:00 NY entre semana, sin festivos; 13:00 en días recortados. Devuelve (estado, motivo)."""
    ny = a_ny(utc)
    d, t = ny.date(), ny.time()
    clave = d.isoformat()
    if clave in NYSE_CERRADO:
        return "cerrado", NYSE_CERRADO[clave]
    if d.weekday() >= 5:
        return "cerrado", "fin de semana"
    cierre = _dt.time(13, 0) if clave in NYSE_RECORTADO else _dt.time(16, 0)
    if t < _dt.time(9, 30):
        return "cerrado", "antes de la apertura (09:30 NY)"
    if t >= cierre:
        return "cerrado", "después del cierre (%s NY)" % hhmm(cierre)
    return "abierto", ("sesión recortada: " + NYSE_RECORTADO[clave]) if clave in NYSE_RECORTADO else "sesión regular"


def estado_mercado(simbolo, utc):
    """El reloj que toca: Globex para un futuro, la NYSE para una acción."""
    return estado_nyse(utc) if es_accion(simbolo) else estado_globex(utc)


@functools.lru_cache(maxsize=8192)
def _sesion_regular(codigo, dia):
    inst = resolver(codigo)
    o, c = inst["rth"]
    o_t, c_t = parse_hhmm(o), parse_hhmm(c)
    clave = dia.isoformat()
    if inst["tipo"] == "accion":
        if clave in NYSE_RECORTADO:
            c_t = _dt.time(13, 0)
    elif clave in CME_RECORTADO and inst["codigo"] in INDICES:
        c_t = _dt.time(13, 0)
    return de_ny(_dt.datetime.combine(dia, o_t)), de_ny(_dt.datetime.combine(dia, c_t))


def sesion_regular(codigo, dia):
    """(apertura, cierre) UTC de la sesión regular de ese instrumento ese día; 13:00 NY en días recortados (índices y acciones)."""
    return _sesion_regular(resolver(codigo)["codigo"], dia)


# ---------------------------------------------------------------- Yahoo

def _open_url(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _sleep(seconds):
    time.sleep(seconds)


def yahoo_get(path):
    """GET a Yahoo: query2 primero, query1 si responde 429 o 5xx; un reintento tras BACKOFF en un 429."""
    last = "sin respuesta"
    for host in HOSTS:
        url = "https://%s.finance.yahoo.com%s" % (host, path)
        for attempt in (0, 1):
            try:
                return _open_url(url)
            except urllib.error.HTTPError as e:
                code = e.code
                try:
                    body = e.read().decode("utf-8", "replace") if code == 404 else None
                except Exception:
                    body = None
                finally:
                    e.close()
                if code == 404:
                    if body:
                        return body
                    raise KemetError("Yahoo no tiene gráfico en %s (HTTP 404)" % url.split("?")[0])
                last = "HTTP %d" % code
                if code == 429 and attempt == 0:
                    _sleep(BACKOFF)
                    continue
                if code == 429 or code >= 500:
                    break
                raise KemetError("Yahoo respondió HTTP %d en %s" % (code, url.split("?")[0]))
            except urllib.error.URLError as e:
                last = "sin conexión: %s" % (e.reason,)
                break
            except OSError as e:
                last = "error de red: %s" % (e,)
                break
    raise KemetError("Yahoo no responde (%s en query2 y query1): espera un minuto y repite" % last)


def chart_path(codigo, rango="5d", intervalo="5m"):
    return "/v8/finance/chart/%s?range=%s&interval=%s" % (resolver(codigo)["yahoo"].replace("=", "%3D"), rango, intervalo)


def leer_texto(path):
    if path.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def parse_chart(text, codigo=None):
    """JSON v8 de Yahoo → {"simbolo", "zona", "ts_mercado", "velas": [(ts_utc, o, h, l, c, v)…]} con las velas nulas fuera y en orden.
    Una vela fuera de la rejilla del intervalo (el tick en vivo de Yahoo) se descarta."""
    try:
        doc = json.loads(text)
    except ValueError:
        raise KemetError("Yahoo devolvió algo que no es JSON")
    chart = doc.get("chart") or {}
    if chart.get("error"):
        raise KemetError("Yahoo: %s" % (chart["error"].get("description") or chart["error"]))
    res = (chart.get("result") or [None])[0]
    if not res:
        raise KemetError("Yahoo no devolvió datos" + (" para %s" % codigo if codigo else ""))
    meta = res.get("meta") or {}
    gran = meta.get("dataGranularity", "5m")
    paso = BAR.get(gran, 300)
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    ts = res.get("timestamp") or []
    velas = []
    for i, t in enumerate(ts):
        try:
            o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
            v = (q.get("volume") or [None] * len(ts))[i]
        except (KeyError, IndexError):
            continue
        if None in (o, h, l, c) or int(t) % paso:
            continue
        velas.append((int(t), float(o), float(h), float(l), float(c), int(v or 0)))
    velas.sort()
    return {"simbolo": meta.get("symbol"), "zona": meta.get("exchangeTimezoneName"), "ts_mercado": meta.get("regularMarketTime"),
            "intervalo": gran, "paso": paso, "velas": velas}


def velas(codigo, rango="5d", intervalo="5m", offline=None):
    """Velas de un contrato: de un archivo guardado (`--offline`, .json o .json.gz) o de Yahoo."""
    if offline:
        y = resolver(codigo)["yahoo"]
        if os.path.isdir(offline):
            exactos = ["%s-%s-%s.json.gz" % (y, rango, intervalo), "%s-%s-%s.json" % (y, rango, intervalo), "%s.json.gz" % y, "%s.json" % y, "%s.json" % codigo]
            rutas = [os.path.join(offline, n) for n in exactos if os.path.exists(os.path.join(offline, n))]
            # el mismo intervalo con otro rango vale (los fixtures de CL y GC son de 5 días)
            rutas += sorted(glob.glob(os.path.join(offline, "%s-*-%s.json*" % (y, intervalo))))
            if not rutas:
                raise KemetError("no hay un archivo de %s en %s" % (codigo, offline))
            offline = rutas[0]
        if not os.path.exists(offline):
            raise KemetError("no existe el archivo %s" % offline)
        ch = parse_chart(leer_texto(offline), codigo)
    else:
        ch = parse_chart(yahoo_get(chart_path(codigo, rango, intervalo)), codigo)
    if ch["simbolo"] and ch["simbolo"] != resolver(codigo)["yahoo"]:
        raise KemetError("el archivo es de %s, no de %s" % (ch["simbolo"], codigo))
    return ch


def velas_cerradas(ch, ahora_utc):
    """Solo las velas ya cerradas a esa hora: inicio + paso <= ahora y, además, <= hasta donde llegan los datos de Yahoo
    (regularMarketTime). Yahoo va unos minutos tarde y publica la vela en curso con su marca de 5 minutos: sin este tope,
    una vela a medio formar contaba como cerrada (un disparo falso que después desaparecía)."""
    lim = ts_de_utc(ahora_utc) - ch["paso"]
    if ch.get("ts_mercado"):
        lim = min(lim, int(ch["ts_mercado"]) - ch["paso"])
    return [b for b in ch["velas"] if b[0] <= lim]


def por_dia(velas_, codigo=None):
    """Agrupa velas por día de negociación: el de CME (18:00 NY a 17:00 NY) para futuros, la fecha NY para acciones."""
    accion = bool(codigo) and es_accion(codigo)
    out = {}
    for b in velas_:
        ny = a_ny(utc_de_ts(b[0]))
        out.setdefault(ny.date() if accion else dia_negociacion(ny), []).append(b)
    return dict(sorted(out.items()))


def en_regular(codigo, b, dia=None):
    """¿La vela está dentro de la sesión regular del contrato?"""
    t = utc_de_ts(b[0])
    o, c = sesion_regular(codigo, dia or dia_negociacion(a_ny(t)))
    return o <= t < c


def regular(codigo, velas_dia, dia):
    return [b for b in velas_dia if en_regular(codigo, b, dia)]


def rango(velas_):
    """(máximo, mínimo) de una lista de velas, o None."""
    if not velas_:
        return None
    return max(b[2] for b in velas_), min(b[3] for b in velas_)


def balance_inicial(codigo, velas_dia, dia, minutos=60):
    """Máximo y mínimo de los primeros `minutos` de la sesión regular, solo si esa hora ya está completa en las velas.
    Devuelve {"alto", "bajo", "ancho", "velas", "cierra": ts_utc} o None."""
    o, _ = sesion_regular(codigo, dia)
    fin = ts_de_utc(o) + minutos * 60
    rth = regular(codigo, velas_dia, dia)
    ib = [b for b in rth if b[0] < fin]
    if not ib or ib[-1][0] + 300 < fin:   # falta la última vela de la hora
        return None
    hi, lo = rango(ib)
    esperadas = minutos // 5
    return {"alto": hi, "bajo": lo, "ancho": round(hi - lo, 4), "velas": len(ib), "cierra": fin, "esperadas": esperadas,
            "completo": len(ib) >= esperadas}


def rango_sesion(codigo, velas_dia, dia):
    """Máximo menos mínimo de la sesión regular completa de un día (None si la sesión tiene huecos)."""
    rth = regular(codigo, velas_dia, dia)
    o, c = sesion_regular(codigo, dia)
    esperadas = int((c - o).total_seconds() // 300)
    if len(rth) < esperadas - 2:          # una sesión con huecos no sirve
        return None
    hi, lo = rango(rth)
    return round(hi - lo, 4)


def mediana(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def al_tick(x, tick):
    return round(round(x / tick) * tick, 8)


# ---------------------------------------------------------------- formato español

def num(x, d=2):
    """1234.5 → 1.234,50 (formato español)."""
    s = "{:,.{}f}".format(x, d)
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def pts(x):
    """Puntos: sin decimales inútiles (12,00 → 12; 12,25 → 12,25) y, por debajo de 10, los que haga falta (6E 1,11235)."""
    d = 2
    while abs(x) < 10 and d < 5 and abs(round(x, d) - x) > 2e-5:   # 6E, HG, NG: los decimales del tick; 2e-5 absorbe el ruido de float32 de Yahoo
        d += 1
    s = num(x, d)
    if d == 2 and s.endswith(",00"):
        return s[:-3]
    return s


def usd(x, d=0):
    return num(x, d) + " $"


# ---------------------------------------------------------------- archivos de kemet/

def ruta(nombre):
    return os.path.join(KEMET_DIR, nombre)


def dada(path):
    """Una ruta que da el usuario en la línea de comandos (--plan, --orden…): relativa al directorio de trabajo."""
    return os.path.abspath(path) if path else path


def leer_json(nombre, que=None, obligatorio=True):
    # Un nombre suelto («config.json») es siempre kemet/<nombre>; solo una ruta con carpeta (o la de dada()) se lee tal cual.
    # Antes, un config.json o agenda.json cualquiera del directorio de trabajo tapaba en silencio al de kemet/.
    p = nombre if (os.sep in nombre or (os.altsep and os.altsep in nombre) or os.path.isabs(nombre)) else ruta(nombre)
    if not os.path.exists(p):
        if obligatorio:
            raise KemetError("falta %s%s" % (p, (": " + que) if que else ""))
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as e:
        raise KemetError("%s no es JSON válido: %s" % (p, e))


def escribir_json(nombre, doc):
    p = nombre if os.sep in nombre else ruta(nombre)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    return p


def iso(utc):
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def de_iso(texto):
    """"2026-11-13T15:04:05Z" -> datetime UTC naive; None si no se entiende."""
    try:
        return _dt.datetime.strptime(str(texto), "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None


def huella_dia(doc):
    """Huella de kemet/estado/dia.json: si cambia (otra operación, un resultado), un PASS anterior ya no vale para el bróker."""
    import hashlib
    ops = doc.get("operaciones") if isinstance(doc, dict) else None
    blob = json.dumps([doc.get("fecha") if isinstance(doc, dict) else None, ops or []], sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]
