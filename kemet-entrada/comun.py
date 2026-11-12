"""Lo que comparten las herramientas del pack Kemet Day Trading. Solo biblioteca estándar.

Cada carpeta de skill lleva una copia idéntica de este archivo (tests/test_repo.py lo comprueba), porque cada
skill se instala sola. Hora de Nueva York y de Madrid calculadas a mano (sin zoneinfo: funciona igual en Windows),
velas de Yahoo Finance (gratis, sin clave, unos 10 minutos de retraso en futuros), el día de negociación de CME
(empieza a las 18:00 NY del día anterior), contratos y micros, el reloj de Globex, y los archivos de `kemet/`.
"""
import datetime as _dt
import functools
import glob
import gzip
import json
import os
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (compatible; kemet-day-trading/1.0; +https://kemet-capital.com/skill)"
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
}
MICRO_A_CODIGO = {v["micro"]: k for k, v in CONTRATOS.items()}

# CME Globex (futuros de índices, energía y metales): abre el domingo a las 18:00 NY, cierra el viernes a las 17:00 NY,
# con una pausa diaria de 17:00 a 18:00 NY. Festivos con cierre completo o sesión recortada (cmegroup.com, leído el
# 2026-11-12; confirma siempre en el calendario de CME antes de un festivo).
CME_CERRADO = {
    "2026-04-03": "Viernes Santo", "2026-12-25": "Navidad",
    "2027-01-01": "Año Nuevo", "2027-03-26": "Viernes Santo", "2027-12-24": "Navidad (observado)",
}
CME_RECORTADO = {  # cierre anticipado de la sesión regular: 13:00 NY para índices
    "2026-01-19": "Martin Luther King", "2026-02-16": "Presidents Day", "2026-05-25": "Memorial Day", "2026-06-19": "Juneteenth",
    "2026-07-03": "Independence Day (observado)", "2026-09-07": "Labor Day", "2026-11-26": "Thanksgiving", "2026-11-27": "Día después de Thanksgiving",
    "2026-12-24": "Nochebuena", "2027-01-18": "Martin Luther King", "2027-02-15": "Presidents Day", "2027-05-31": "Memorial Day",
    "2027-06-18": "Juneteenth (observado)", "2027-07-05": "Independence Day (observado)", "2027-09-06": "Labor Day", "2027-11-25": "Thanksgiving", "2027-11-26": "Día después de Thanksgiving",
}
CALENDARIO = (2026, 2027)


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
    return _dt.datetime.utcnow().replace(microsecond=0)


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
    if _dt.time(17, 0) <= t < _dt.time(18, 0):
        return "pausa", "pausa diaria 17:00–18:00 NY"
    return "abierto", "sesión recortada: " + CME_RECORTADO[clave] if clave in CME_RECORTADO else "sesión normal"


@functools.lru_cache(maxsize=4096)
def sesion_regular(codigo, dia):
    """(apertura, cierre) UTC de la sesión regular de ese contrato ese día; cierre a las 13:00 NY en días recortados (índices)."""
    o, c = CONTRATOS[codigo]["rth"]
    o_t, c_t = parse_hhmm(o), parse_hhmm(c)
    if dia.isoformat() in CME_RECORTADO and codigo in ("ES", "NQ", "YM", "RTY"):
        c_t = _dt.time(13, 0)
    return de_ny(_dt.datetime.combine(dia, o_t)), de_ny(_dt.datetime.combine(dia, c_t))


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
    return "/v8/finance/chart/%s?range=%s&interval=%s" % (CONTRATOS[codigo]["yahoo"].replace("=", "%3D"), rango, intervalo)


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
        y = CONTRATOS[codigo]["yahoo"]
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
    if ch["simbolo"] and ch["simbolo"] != CONTRATOS[codigo]["yahoo"]:
        raise KemetError("el archivo es de %s, no de %s" % (ch["simbolo"], codigo))
    return ch


def velas_cerradas(ch, ahora_utc):
    """Solo las velas ya cerradas a esa hora: inicio + paso <= ahora. Yahoo tarda en completar la última; esperar es asunto del que llama."""
    lim = ts_de_utc(ahora_utc) - ch["paso"]
    return [b for b in ch["velas"] if b[0] <= lim]


def por_dia(velas_):
    """Agrupa velas por día de negociación de CME (18:00 NY a 17:00 NY), ordenado."""
    out = {}
    for b in velas_:
        out.setdefault(dia_negociacion(a_ny(utc_de_ts(b[0]))), []).append(b)
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
    return {"alto": hi, "bajo": lo, "ancho": round(hi - lo, 4), "velas": len(ib), "cierra": fin}


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
    return round(round(x / tick) * tick, 4)


# ---------------------------------------------------------------- formato español

def num(x, d=2):
    """1234.5 → 1.234,50 (formato español)."""
    s = "{:,.{}f}".format(x, d)
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def pts(x):
    """Puntos: sin decimales inútiles (12,00 → 12; 12,25 → 12,25)."""
    s = num(x, 2)
    return s[:-3] if s.endswith(",00") else s


def usd(x, d=0):
    return num(x, d) + " $"


# ---------------------------------------------------------------- archivos de kemet/

def ruta(nombre):
    return os.path.join(KEMET_DIR, nombre)


def leer_json(nombre, que=None, obligatorio=True):
    p = nombre if os.sep in nombre or nombre.endswith(".json") and os.path.exists(nombre) else ruta(nombre)
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
