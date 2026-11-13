#!/usr/bin/env python3
"""Escáner de gráficos de kemet-scanner: miles de acciones de EE. UU. y los doce futuros de CME. Solo biblioteca estándar.

    python3 scanner.py universo                              # listas de Nasdaq Trader -> kemet/universo.txt
    python3 scanner.py diario                                # antes de la apertura: reglas diarias -> kemet/watchlist.json
    python3 scanner.py diario --simbolos TSLA,NVDA,AMD       # o --watchlist ARCHIVO, o --limite 200
    python3 scanner.py orb                                   # desde las 09:50 NY: rupturas del rango de apertura hasta ahora
    python3 scanner.py orb --a 10:15 --rango-minutos 15      # corta el reloj a las 10:15 NY
    python3 scanner.py futuros                               # los doce contratos: balance inicial, máximo y mínimo de ayer, rango
    python3 scanner.py orb --offline pared.json.gz --ahora "2026-10-19 10:15" --min-precio 0

universo  Baja los directorios de símbolos de Nasdaq Trader (nasdaqlisted.txt y otherlisted.txt) y se queda con las
          acciones ordinarias, las acciones comunes y los ADR cotizados en EE. UU. La regla, en orden:
            1. no es un valor de prueba, ni un ETF, ni NextShares
            2. ticker llano: de 1 a 5 letras, o de 1 a 4 letras más una letra de clase tras un punto (BRK.B); fuera
               los sufijos .U / .W / .R (unidades, warrants, derechos) y las preferentes con $
            3. fuera, diga lo que diga el nombre: warrants; unidades y derechos de SPAC ("Units, each consisting of",
               "Rights to receive"); notas, ETN, obligaciones; un cupón con %; "Depositary Shares" que no sean
               American ni Global (llevan una preferente)
            4. dentro: el nombre dice common stock / shares / units, ordinary shares, shares of beneficial interest,
               ADS / ADR / American o Global depositary shares, o partnership / trust units
            5. fuera: el nombre aún dice unit, right, bond, preferred o preference
            6. dentro: todo lo demás (nombres llanos como "AMETEK, Inc.")

diario    Escaneo de CIERRES diarios antes de la apertura (spark de Yahoo: 20 símbolos por petición, 3 meses de velas
          de 1 día, solo cierres). Liquidez con el meta del spark: regularMarketPrice >= --min-precio (5) y
          regularMarketVolume >= --min-volumen (1.000.000). Reglas, solo sobre cierres:
            ruptura-20d         el último cierre está por encima de los 20 cierres anteriores
            bandera             sube más del 10 % en las 10 sesiones anteriores a las últimas 5, y los últimos 5
                                cierres caben en un 5 %
            recupera-media-20   cerró bajo la media de 20 días y después cerró encima
            sobreventa          RSI 14 (Wilder) por debajo de 30
            rebote              el RSI 14 estaba bajo 30 ayer y hoy cerró arriba
          La vela diaria de hoy no cuenta hasta el cierre de la sesión.

orb       Rupturas del rango de apertura sobre velas de 5 minutos. El rango son los primeros --rango-minutos (15) de
          la sesión. Fase 1: cierres del spark para todos los símbolos (1 día de velas de 5 minutos, 20 por petición);
          un gráfico sigue solo si una vela cerrada después del rango cerró en o por encima del cierre más alto del
          rango (condición necesaria). Fase 2: el gráfico v8 de cada candidato (máximos y mínimos reales): máximo del
          rango = el máximo más alto de sus velas; acierto = la primera vela cerrada que CIERRA por encima, a la hora
          de su cierre. La fase 2 pide como mucho --max-confirmar (200) gráficos, los más negociados primero (precio
          por volumen hasta ese momento), y lo dice cuando se queda corta. Un gráfico vale solo si están todas las
          velas de 5 minutos desde las 09:30 hasta el corte (una vela que falta es una parada o un valor sin
          operaciones). Suelos: --min-precio 5 (último cierre), --min-volumen 0.

futuros   Los doce contratos de comun.CONTRATOS (ES, NQ, YM, RTY, CL, GC, SI, HG, NG, 6E, ZN, ZB), uno por uno:
          quién cerró fuera del balance inicial de --ib-minutos (60) de su sesión regular y cuándo, quién está por
          encima del máximo de ayer o por debajo del mínimo de ayer, y el rango de hoy frente al medio de las
          últimas --sesiones (20) sesiones regulares. Reglas: ib-arriba, ib-abajo, sobre-pdh, bajo-pdl. El rango
          frente al medio es contexto, no una regla. --simbolos NQ,ES limita los contratos.

Velas: se descartan los cierres nulos, las velas fuera de la rejilla de 5 minutos (el tick en vivo de Yahoo, como
10:49:45) y las velas que aún no han cerrado (inicio + 5 minutos <= reloj). Horas de Nueva York. --ahora fija el
reloj ("2026-10-19 10:15", hora de Nueva York) y permite repetir un día.

Los endpoints de Yahoo son gratuitos, no oficiales y van con retraso (unos 10 minutos en futuros). query2 primero,
query1 ante un 429 o un 5xx, un reintento tras una pausa en un 429. Una pausa educada entre peticiones (--pausa, 0,3 s).
Los resultados parciales se dicen como parciales.

--offline RUTA lee archivos en vez de la red: universo quiere una carpeta con nasdaqlisted.txt y otherlisted.txt;
diario y orb una carpeta de archivos <TICKER>.json (gráficos v8) o respuestas del spark, o un solo archivo que sea
un spark, un v8 o un paquete {"TSLA": <v8>, ...}; futuros la carpeta tests/fixtures/yahoo (o cualquiera con
<CODIGO>=F-*-5m.json.gz). .json.gz vale.

Un escaneo es una lista de gráficos que cumplen una regla, no una lista de valores que comprar.
Código de salida 0 si encontró algo, 1 si no encontró nada o no había sesión que escanear, 2 ante un error
(un archivo que falta, un flag mal puesto, Yahoo caído).
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

import comun
from comun import KemetError

NASDAQ_ARCHIVOS = ("nasdaqlisted.txt", "otherlisted.txt")
NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/"
SPARK_MAX = 20          # el spark de Yahoo responde 400 por encima de 20 símbolos
PAUSA = 0.3             # segundos entre peticiones: educado con los endpoints gratuitos
DORMIR = time.sleep     # los tests lo cambian
VELA_MIN = 5
MAX_CONFIRMAR = 200     # gráficos v8 de la fase 2 por escaneo orb, los más negociados primero
MIN_VELAS_DIARIAS = 30
SESIONES = 20
UNIVERSO = "universo.txt"
WATCHLIST = "watchlist.json"
CORTE_FALLOS = 5               # lotes seguidos con error antes de dejar de pedir a Yahoo
NOTA = "Un escaneo es una lista de gráficos que cumplen una regla, no una lista de valores que comprar."
APERTURA = dt.time(9, 30)
CIERRE = dt.time(16, 0)
RECORTADO = dt.time(13, 0)
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

REGLAS_DIARIO = [
    ("ruptura-20d", "ruptura del máximo de cierre de 20 días"),
    ("bandera", "bandera alcista"),
    ("recupera-media-20", "recupera la media de 20 días"),
    ("sobreventa", "sobreventa (RSI 14 bajo 30)"),
    ("rebote", "rebote desde sobreventa"),
]
REGLAS_FUTUROS = [
    ("ib-arriba", "cierre por encima del balance inicial"),
    ("ib-abajo", "cierre por debajo del balance inicial"),
    ("sobre-pdh", "por encima del máximo de ayer"),
    ("bajo-pdl", "por debajo del mínimo de ayer"),
]
ETIQUETA = dict(REGLAS_DIARIO + REGLAS_FUTUROS + [("orb", "ruptura del rango de apertura")])


# ---------------------------------------------------------------- horas y sesión de la bolsa

def ny_de_ts(ts):
    """Segundos Unix a hora de Nueva York (naive), con la regla de comun, nunca con la zona de la máquina."""
    return comun.a_ny(comun.utc_de_ts(ts))


def fecha_es(d):
    return "%s %02d/%02d/%d" % (DIAS[d.weekday()], d.day, d.month, d.year)


def dia_de_bolsa(d):
    """(hay sesión, motivo) para acciones: fines de semana y festivos de la NYSE de comun."""
    if d.weekday() >= 5:
        return False, "fin de semana"
    nombre = comun.NYSE_CERRADO.get(d.isoformat())
    if nombre:
        return False, "festivo de la NYSE: " + nombre
    return True, ""


def sesion_bolsa(d):
    """(apertura, cierre) en hora de Nueva York, o None si ese día no hay sesión."""
    ok, _ = dia_de_bolsa(d)
    if not ok:
        return None
    return APERTURA, (RECORTADO if d.isoformat() in comun.NYSE_RECORTADO else CIERRE)


def hueco(dia, k):
    """El inicio de la vela k (desde 0) de 5 minutos de la sesión de ese día."""
    return dt.datetime.combine(dia, APERTURA) + dt.timedelta(minutes=VELA_MIN * k)


# ---------------------------------------------------------------- red

def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": comun.UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def a_yahoo(sym):
    return sym.upper().replace(".", "-")


def spark_path(simbolos, rango, intervalo):
    return "/v7/finance/spark?symbols=%s&range=%s&interval=%s" % (",".join(a_yahoo(s) for s in simbolos), rango, intervalo)


def chart_path(sym, rango, intervalo):
    return "/v8/finance/chart/%s?range=%s&interval=%s" % (a_yahoo(sym), rango, intervalo)


# ---------------------------------------------------------------- parseo

def serie_de_resultado(res):
    """Un resultado de gráfico de Yahoo (v8 o una respuesta del spark) a listas llanas."""
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0] or {}
    t = res.get("timestamp") or []
    n = len(t)

    def col(k):
        v = q.get(k)
        return list(v) + [None] * (n - len(v)) if isinstance(v, list) else None
    return {"t": list(t), "c": col("close") or [None] * n, "o": col("open"), "h": col("high"),
            "l": col("low"), "v": col("volume"), "meta": res.get("meta") or {}}


def parse_spark(texto_o_doc, pedidos=None):
    """JSON del spark a {SIMBOLO: serie}. Los símbolos que Yahoo no conoce simplemente no vienen.
    `pedidos` traduce los símbolos de Yahoo a los nuestros (BRK-B a BRK.B)."""
    doc = json.loads(texto_o_doc) if isinstance(texto_o_doc, str) else texto_o_doc
    sp = (doc or {}).get("spark") if isinstance(doc, dict) else None
    if not isinstance(sp, dict):
        raise KemetError("la respuesta del spark de Yahoo no tiene la forma que conozco")
    err = sp.get("error")
    out = {}
    for item in sp.get("result") or []:
        resp = item.get("response") or []
        if not resp:
            continue
        ysym = item.get("symbol") or (resp[0].get("meta") or {}).get("symbol") or ""
        sym = (pedidos or {}).get(ysym.upper(), ysym.upper().replace("-", "."))
        out[sym] = serie_de_resultado(resp[0])
    if err and not out:
        raise KemetError("spark de Yahoo: %s" % (err.get("description") or err.get("code") or err))
    return out


def parse_chart(texto_o_doc, sym=""):
    """JSON v8 a serie. KemetError cuando Yahoo dice que no hay datos."""
    try:
        doc = json.loads(texto_o_doc) if isinstance(texto_o_doc, str) else texto_o_doc
        chart = doc["chart"]
    except (ValueError, KeyError, TypeError):
        raise KemetError("Yahoo devolvió algo inesperado para %s" % sym)
    res = chart.get("result")
    if not res:
        err = chart.get("error") or {}
        raise KemetError("sin datos de %s: %s" % (sym, err.get("description", "ticker desconocido")))
    return serie_de_resultado(res[0])


def _raiz(nombre):
    for ext in (".json.gz", ".json"):
        if nombre.endswith(ext):
            return nombre[:-len(ext)]
    return nombre


def _absorber(doc, pista, datos, errores):
    """Un JSON offline ya parseado a datos / errores."""
    if isinstance(doc, dict) and "spark" in doc:
        datos.update(parse_spark(doc))
    elif isinstance(doc, dict) and "chart" in doc:
        sym = pista
        if not sym:
            try:
                sym = (doc["chart"].get("result") or [{}])[0]["meta"]["symbol"]
            except (AttributeError, KeyError, TypeError, IndexError):
                raise KemetError("un gráfico v8 offline sin símbolo: llama al archivo <TICKER>.json")
        sym = sym.upper().replace("-", ".")
        try:
            datos[sym] = parse_chart(doc, sym)
        except KemetError as e:
            errores[sym] = str(e)
    elif isinstance(doc, dict):
        for k, v in doc.items():
            _absorber(v, k, datos, errores)
    else:
        raise KemetError("el archivo offline %s no es un spark, un gráfico v8 ni un paquete" % pista)


def cargar_offline(ruta):
    """Una carpeta de archivos <TICKER>.json(.gz) o un solo archivo a ({SIMBOLO: serie}, {SIMBOLO: error})."""
    datos, errores = {}, {}
    if os.path.isdir(ruta):
        nombres = sorted(f for f in os.listdir(ruta) if f.endswith((".json", ".json.gz")))
        if not nombres:
            raise KemetError("no hay archivos .json en %s" % ruta)
        for f in nombres:
            try:
                doc = json.loads(comun.leer_texto(os.path.join(ruta, f)))
            except ValueError as e:
                raise KemetError("%s no es JSON válido: %s" % (f, e))
            if isinstance(doc, dict) and ("chart" in doc or "spark" in doc):
                _absorber(doc, "" if "spark" in doc else _raiz(f), datos, errores)
            else:
                _absorber(doc, "", datos, errores)
    elif os.path.isfile(ruta):
        try:
            doc = json.loads(comun.leer_texto(ruta))
        except ValueError as e:
            raise KemetError("%s no es JSON válido: %s" % (ruta, e))
        _absorber(doc, "", datos, errores)
    else:
        raise KemetError("no hay archivo ni carpeta offline en %s" % ruta)
    return datos, errores


# ---------------------------------------------------------------- el universo

TICKER = re.compile(r"^[A-Z]{1,5}$|^[A-Z]{1,4}\.[A-Z]$")
SIEMPRE_FUERA = [
    ("warrant", re.compile(r"\bwarrants?\b")),
    ("unidad o derecho", re.compile(r"\b(units?|rights?),? (each|that|entitling)\b|(?<!the )\brights? to\b")),
    ("nota", re.compile(r"\b(notes?|etns?|debentures?)\b")),
    ("cupón", re.compile(r"%")),
    ("depositary", re.compile(r"(?<!american )(?<!global )\bdepositary shares?\b")),
]
COMUN = re.compile(
    r"\bcommon (stock|shares?|units?)\b|\bord(inary)? shares?\b|\bshares? of beneficial interest\b"
    r"|\b(american|global) deposit[ao]ry\b|\bads[s]?\b|\badrs?\b"
    r"|\b(limited partnership|partnership|trust) units?\b|\bl\.?p\.? units?\b"
    r"|\bunits? (of|representing)\b.*\b(limited partner|partnership|beneficial interest|limited liability)")
FUERA_SI_DICE = [
    ("unidad", re.compile(r"\bunits?\b")),
    ("derecho", re.compile(r"\brights?\b")),
    ("bono", re.compile(r"\bbonds?\b")),
    ("preferente", re.compile(r"\bpreferred\b|\bpreference\b")),
]


def clasificar(fila):
    """Una fila del directorio de símbolos a 'dentro' o la regla que la deja fuera."""
    sym = (fila.get("Symbol") or fila.get("ACT Symbol") or "").strip()
    if (fila.get("Test Issue") or "").strip() != "N":
        return "valor de prueba"
    if (fila.get("ETF") or "").strip() != "N":
        return "ETF"
    if (fila.get("NextShares") or "N").strip() != "N":
        return "NextShares"
    if not TICKER.match(sym):
        return "ticker no llano"
    if re.search(r"\.[UWR]$", sym):
        return "sufijo de unidad / warrant / derecho"
    nombre = " ".join((fila.get("Security Name") or "").lower().split())
    for tag, rx in SIEMPRE_FUERA:
        if rx.search(nombre):
            return tag
    if COMUN.search(nombre):
        return "dentro"
    for tag, rx in FUERA_SI_DICE:
        if rx.search(nombre):
            return tag
    return "dentro"


def parse_symdir(texto):
    """Archivo con barras de Nasdaq Trader a (filas, fecha de creación). La última línea es 'File Creation Time: ...'."""
    lineas = [ln for ln in texto.replace("\r", "").split("\n") if ln.strip()]
    if not lineas or "|" not in lineas[0]:
        raise KemetError("no es un directorio de símbolos de Nasdaq Trader")
    cab = [h.strip() for h in lineas[0].split("|")]
    if "Security Name" not in cab or not ({"Symbol", "ACT Symbol"} & set(cab)):
        raise KemetError("no es un directorio de símbolos de Nasdaq Trader (cabecera %s)" % lineas[0][:60])
    filas, creado = [], None
    for ln in lineas[1:]:
        if ln.startswith("File Creation Time"):
            m = re.search(r"(\d{2})(\d{2})(\d{4})(\d{2}):(\d{2})", ln)
            if m:
                creado = "%s-%s-%s %s:%s" % (m.group(3), m.group(1), m.group(2), m.group(4), m.group(5))
            continue
        filas.append(dict(zip(cab, ln.split("|"))))
    return filas, creado


def construir_universo(textos):
    """{archivo: texto} a (dentro [(SIMBOLO, nombre)], recuento, creado)."""
    dentro, recuento, creado = {}, {}, None
    for nombre in NASDAQ_ARCHIVOS:
        if nombre not in textos:
            raise KemetError("falta %s" % nombre)
        filas, c = parse_symdir(textos[nombre])
        creado = creado or c
        recuento["filas"] = recuento.get("filas", 0) + len(filas)
        for f in filas:
            por_que = clasificar(f)
            recuento[por_que] = recuento.get(por_que, 0) + 1
            if por_que == "dentro":
                sym = (f.get("Symbol") or f.get("ACT Symbol")).strip()
                dentro[sym] = " ".join((f.get("Security Name") or "").split())
    return sorted(dentro.items()), recuento, creado


# ---------------------------------------------------------------- reglas diarias

def rsi(cierres, n=14):
    """RSI de Wilder sobre cierres."""
    if len(cierres) < n + 1:
        return None
    g = [max(0.0, cierres[i] - cierres[i - 1]) for i in range(1, len(cierres))]
    p = [max(0.0, cierres[i - 1] - cierres[i]) for i in range(1, len(cierres))]
    mg, mp = sum(g[:n]) / n, sum(p[:n]) / n
    for i in range(n, len(g)):
        mg = (mg * (n - 1) + g[i]) / n
        mp = (mp * (n - 1) + p[i]) / n
    return 100 - 100 / (1 + mg / mp) if mp else 100.0


def cierres_diarios(serie, ahora_utc):
    """[(fecha, cierre)] de velas diarias COMPLETAS: fuera los cierres nulos, fuera la vela de hoy hasta que
    cierre la sesión, fuera lo fechado después del reloj."""
    ny = comun.a_ny(ahora_utc)
    hoy = ny.date()
    s = sesion_bolsa(hoy)
    hoy_cerrado = s is None or ny.time() >= s[1]
    out = {}
    for ts, c in zip(serie["t"], serie["c"]):
        if c is None:
            continue
        d = ny_de_ts(ts).date()
        if d > hoy or (d == hoy and not hoy_cerrado):
            continue
        out[d] = float(c)   # una vela por día: un duplicado tardío (el tick en vivo) gana
    return sorted(out.items())


def reglas_diarias(cierres):
    """cierres (del más antiguo al último, 30 o más) a (reglas, cifras)."""
    c = cierres
    ultimo = c[-1]
    max20 = max(c[-21:-1])
    media20 = sum(c[-20:]) / 20.0
    media20_ant = sum(c[-21:-1]) / 20.0
    tramo = c[-6] / c[-16] - 1
    rango5 = (max(c[-5:]) - min(c[-5:])) / ultimo
    r = rsi(c)
    r_ant = rsi(c[:-1])
    reglas = []
    if ultimo > max20:
        reglas.append("ruptura-20d")
    if tramo > 0.10 and rango5 < 0.05:
        reglas.append("bandera")
    if c[-2] < media20_ant and ultimo > media20:
        reglas.append("recupera-media-20")
    if r is not None and r < 30:
        reglas.append("sobreventa")
    if r_ant is not None and r_ant < 30 and ultimo > c[-2]:
        reglas.append("rebote")
    return reglas, {"rsi": r, "rsi_ant": r_ant, "max20": max20, "media20": media20,
                    "tramo_pct": tramo * 100, "rango5_pct": rango5 * 100}


def detalle_diario(reglas, n):
    partes = []
    for r in reglas:
        if r == "ruptura-20d":
            partes.append("cierre por encima del máximo de cierre de 20 días (%s)" % comun.num(n["max20"]))
        elif r == "bandera":
            partes.append("sube %s %% en 10 sesiones y los últimos 5 cierres caben en un %s %%" % (comun.num(n["tramo_pct"], 1), comun.num(n["rango5_pct"], 1)))
        elif r == "recupera-media-20":
            partes.append("cierre por encima de la media de 20 días (%s) tras cerrar debajo" % comun.num(n["media20"]))
        elif r == "sobreventa":
            partes.append("RSI 14 en %s" % comun.num(n["rsi"], 1))
        elif r == "rebote":
            partes.append("RSI 14 ayer en %s, hoy cierre al alza" % comun.num(n["rsi_ant"], 1))
    return "; ".join(partes)


def escanear_diario(datos, simbolos, ahora_utc, min_precio, min_volumen):
    """Puro. datos = {SIMBOLO: serie}. Devuelve (aciertos, recuento, última fecha)."""
    aciertos, fechas = [], {}
    recuento = {"pedidos": len(simbolos), "recibidos": 0, "sin_liquidez": 0, "cortos": 0, "escaneados": 0}
    for sym in simbolos:
        s = datos.get(sym)
        if not s:
            continue
        recuento["recibidos"] += 1
        velas = cierres_diarios(s, ahora_utc)
        meta = s.get("meta") or {}
        precio = meta.get("regularMarketPrice")
        if precio is None and velas:
            precio = velas[-1][1]
        vol = meta.get("regularMarketVolume")
        if precio is None or precio < min_precio or (min_volumen > 0 and (vol is None or vol < min_volumen)):
            recuento["sin_liquidez"] += 1
            continue
        if len(velas) < MIN_VELAS_DIARIAS:
            recuento["cortos"] += 1
            continue
        recuento["escaneados"] += 1
        f = velas[-1][0]
        fechas[f] = fechas.get(f, 0) + 1
        cierres = [c for _, c in velas]
        reglas, n = reglas_diarias(cierres)
        if reglas:
            aciertos.append({"simbolo": sym, "regla": " + ".join(reglas), "reglas": reglas, "precio": round(cierres[-1], 2),
                             "hora": "cierre " + f.isoformat(), "detalle": detalle_diario(reglas, n),
                             "rsi": round(n["rsi"], 1), "volumen": int(vol) if vol is not None else None})
    aciertos.sort(key=lambda h: (-(h["precio"] * (h["volumen"] or 0)), h["simbolo"]))   # los más negociados primero
    ultima = max(fechas, key=lambda d: (fechas[d], d)) if fechas else None
    recuento["aciertos"] = len(aciertos)
    return aciertos, recuento, ultima


# ---------------------------------------------------------------- ruptura del rango de apertura

def velas_sesion(serie, dia, corte):
    """Velas de 5 minutos de `dia` cerradas a `corte` (hora NY naive), en la rejilla, con cierre. Ordenadas, una por hueco."""
    s = sesion_bolsa(dia)
    cierre_t = s[1] if s else CIERRE
    out = {}
    hs, ls = serie.get("h"), serie.get("l")
    for i, ts in enumerate(serie["t"]):
        c = serie["c"][i]
        if c is None:
            continue
        ny = ny_de_ts(ts)
        if ny.date() != dia or ny.second or ny.minute % VELA_MIN:
            continue   # otro día, o el tick en vivo fuera de la rejilla
        if ny.time() < APERTURA or ny.time() >= cierre_t:
            continue   # premercado, after hours, la impresión de cierre de las 16:00
        if ny + dt.timedelta(minutes=VELA_MIN) > corte:
            continue   # aún no ha cerrado al corte
        v = serie.get("v")
        out[ny] = {"inicio": ny, "c": float(c),
                   "h": None if not hs or hs[i] is None else float(hs[i]),
                   "l": None if not ls or ls[i] is None else float(ls[i]),
                   "v": (v[i] or 0) if v else 0}
    return [out[k] for k in sorted(out)]


def utilizable(velas, dia, corte, n_rango):
    """Están todas las velas desde las 09:30 hasta el corte, y al menos las del rango."""
    quiero = int((corte - hueco(dia, 0)).total_seconds() // (VELA_MIN * 60))
    s = sesion_bolsa(dia)
    if s:
        quiero = min(quiero, int((dt.datetime.combine(dia, s[1]) - hueco(dia, 0)).total_seconds() // (VELA_MIN * 60)))
    if quiero < n_rango or len(velas) != quiero:
        return False
    return all(b["inicio"] == hueco(dia, k) for k, b in enumerate(velas))


def candidato_orb(velas, n_rango):
    """Fase 1, solo cierres: alguna vela cerrada después del rango cerró en o por encima del cierre más alto del rango."""
    tope = max(b["c"] for b in velas[:n_rango])
    return any(b["c"] >= tope for b in velas[n_rango:])


def acierto_orb(velas, n_rango):
    """Fase 2, máximos y mínimos reales: la primera vela cerrada que CIERRA por encima del máximo del rango."""
    rng = velas[:n_rango]
    if any(b["h"] is None or b["l"] is None for b in rng):
        return None
    alto = max(b["h"] for b in rng)
    bajo = min(b["l"] for b in rng)
    for k in range(n_rango, len(velas)):
        b = velas[k]
        if b["c"] > alto:
            cierra = b["inicio"] + dt.timedelta(minutes=VELA_MIN)
            pct = (b["c"] / alto - 1) * 100
            return {"precio": round(b["c"], 2), "hora": comun.hhmm(cierra), "vela": b["inicio"].strftime("%H:%M"),
                    "barra": k + 1, "rango_alto": round(alto, 2), "rango_bajo": round(bajo, 2), "pct_encima": round(pct, 2),
                    "detalle": "la vela de %s (barra %d) cerró en %s, un %s %% por encima del máximo del rango %s a %s"
                               % (b["inicio"].strftime("%H:%M"), k + 1, comun.num(b["c"]), comun.num(pct), comun.num(bajo), comun.num(alto)),
                    "_t": cierra}
    return None


class SinSesion(Exception):
    """No hay nada que escanear a esta hora: una línea y código 1, no es un error."""


def ventana_orb(ahora_utc, a, rango_minutos, hasta, dia_explicito=None):
    """-> (día, corte NY naive) o SinSesion con el mensaje llano."""
    ny = comun.a_ny(ahora_utc)
    dia = dia_explicito or ny.date()
    if rango_minutos < VELA_MIN or rango_minutos % VELA_MIN or rango_minutos > 120:
        raise KemetError("--rango-minutos quiere un múltiplo de 5 entre 5 y 120 (15 es el clásico)")
    ok, por_que = dia_de_bolsa(dia)
    if not ok:
        raise SinSesion("Sin sesión el %s (%s): la bolsa está cerrada. Lanza orb un día de sesión después del rango de apertura, "
                        "o repite un día pasado con --offline." % (fecha_es(dia), por_que))
    s = sesion_bolsa(dia)
    fin_rango = hueco(dia, rango_minutos // VELA_MIN)
    primer_cierre = fin_rango + dt.timedelta(minutes=VELA_MIN)
    cierre_dt = dt.datetime.combine(dia, s[1])
    if a is not None:
        corte = dt.datetime.combine(dia, a)
        if dia_explicito is None and corte > ny + dt.timedelta(seconds=59):
            raise SinSesion("--a %s es más tarde que ahora (%s NY)." % (comun.hhmm(a), comun.hhmm(ny)))
        if corte > cierre_dt:
            raise SinSesion("--a %s es después del cierre de las %s del %s." % (comun.hhmm(a), comun.hhmm(cierre_dt), fecha_es(dia)))
    else:
        corte = ny.replace(second=0, microsecond=0)
        if corte >= cierre_dt:
            raise SinSesion("La bolsa cerró a las %s NY el %s. Repite la sesión con --a 10:15." % (comun.hhmm(cierre_dt), fecha_es(dia)))
    if corte < primer_cierre:
        raise SinSesion("Son las %s NY: el rango de apertura de %d minutos va de 09:30 a %s y la primera vela después cierra a las %s. "
                        "Vuelve a lanzar orb a partir de las %s." % (comun.hhmm(corte), rango_minutos, comun.hhmm(fin_rango),
                                                                       comun.hhmm(primer_cierre), comun.hhmm(primer_cierre)))
    if hasta is not None and corte.time() > hasta:
        raise SinSesion("Son las %s NY, después de las %s, tu última hora para entradas nuevas (sin_entradas_despues): una ruptura del "
                        "rango de apertura encontrada ahora está caducada. Lanza orb mañana a partir de las %s, o repite hoy con --a 10:15."
                        % (comun.hhmm(corte), comun.hhmm(hasta), comun.hhmm(primer_cierre)))
    return dia, corte


def escanear_orb(fase1, simbolos, dia, corte, rango_minutos, min_precio=0.0, min_volumen=0, confirmar=None, max_confirmar=None):
    """fase1 = {SIMBOLO: serie} con cierres (spark o v8). confirmar(sym) -> serie con máximos y mínimos (None = la de la fase 1).
    Con confirmar y max_confirmar solo se confirman los max_confirmar candidatos más negociados (precio por volumen hasta el
    corte); el resto se cuentan como sin confirmar. Devuelve (aciertos, recuento, fallidos {sym: por qué})."""
    n_rango = rango_minutos // VELA_MIN
    recuento = {"pedidos": len(simbolos), "recibidos": 0, "inutilizables": 0, "sin_liquidez": 0, "escaneados": 0,
                "candidatos": 0, "confirmados": 0, "sin_confirmar": 0}
    aciertos, fallidos, cands = [], {}, []
    for sym in simbolos:
        s = fase1.get(sym)
        if not s:
            continue
        recuento["recibidos"] += 1
        velas = velas_sesion(s, dia, corte)
        if not utilizable(velas, dia, corte, n_rango):
            recuento["inutilizables"] += 1
            continue
        vol = sum(b["v"] for b in velas) if s.get("v") else (s.get("meta") or {}).get("regularMarketVolume") or 0
        if velas[-1]["c"] < min_precio or vol < min_volumen:
            recuento["sin_liquidez"] += 1
            continue
        recuento["escaneados"] += 1
        if candidato_orb(velas, n_rango):
            cands.append((sym, velas, velas[-1]["c"] * vol))
    recuento["candidatos"] = len(cands)
    if confirmar is not None and max_confirmar and len(cands) > max_confirmar:
        cands.sort(key=lambda x: -x[2])
        recuento["sin_confirmar"] = len(cands) - max_confirmar
        cands = cands[:max_confirmar]
    for sym, velas, _ in cands:
        completas = velas
        if confirmar is not None:
            try:
                s2 = confirmar(sym)
            except KemetError as e:
                fallidos[sym] = str(e)
                continue
            completas = velas_sesion(s2, dia, corte)
            if not utilizable(completas, dia, corte, n_rango):
                fallidos[sym] = "al gráfico v8 le falta una vela"
                continue
        recuento["confirmados"] += 1
        h = acierto_orb(completas, n_rango)
        if h:
            aciertos.append(dict({"simbolo": sym, "regla": "orb", "reglas": ["orb"]}, **h))
    aciertos.sort(key=lambda x: (x["_t"], x["simbolo"]))
    for h in aciertos:
        del h["_t"]
    recuento["aciertos"] = len(aciertos)
    return aciertos, recuento, fallidos


# ---------------------------------------------------------------- futuros

def analizar_contrato(codigo, dias, hoy, ib_minutos=60, sesiones=SESIONES):
    """Un contrato con sus velas cerradas agrupadas por día de negociación a una fila: último, IB y si cerró fuera,
    máximo y mínimo de ayer y dónde está el último cierre, rango de hoy frente al medio de las últimas sesiones."""
    inst = comun.resolver(codigo)
    fila = {"simbolo": codigo, "nombre": inst["nombre"], "reglas": [], "notas": []}
    velas_hoy = dias.get(hoy, [])
    if not velas_hoy:
        fila["notas"].append("sin velas de hoy")
        return fila
    u = velas_hoy[-1]
    fila["ultimo"] = u[4]
    fila["hora_ultimo"] = comun.hhmm(comun.a_ny(comun.utc_de_ts(u[0] + 300)))
    rth = comun.regular(codigo, velas_hoy, hoy)
    apertura_utc, _ = comun.sesion_regular(codigo, hoy)
    # el balance inicial y la primera vela que cierra fuera
    ib = comun.balance_inicial(codigo, velas_hoy, hoy, ib_minutos)
    if ib:
        fila["ib"] = {"alto": ib["alto"], "bajo": ib["bajo"], "ancho": ib["ancho"], "velas": ib["velas"], "minutos": ib_minutos}
        for b in rth:
            if b[0] < ib["cierra"]:
                continue
            if b[4] > ib["alto"] or b[4] < ib["bajo"]:
                lado = "ib-arriba" if b[4] > ib["alto"] else "ib-abajo"
                fila["reglas"].append(lado)
                fila["ruptura"] = {"lado": "arriba" if lado == "ib-arriba" else "abajo", "precio": b[4],
                                   "hora": comun.hhmm(comun.a_ny(comun.utc_de_ts(b[0] + 300))),
                                   "vela": comun.hhmm(comun.a_ny(comun.utc_de_ts(b[0])))}
                break
    elif rth:
        fila["notas"].append("balance inicial de %d minutos aún abierto" % ib_minutos)
    else:
        fila["notas"].append("sesión regular sin abrir (%s NY)" % comun.hhmm(comun.a_ny(apertura_utc)))
    # ayer: la última sesión regular anterior con velas
    anteriores = [d for d in dias if d < hoy]
    for d in reversed(anteriores):
        r = comun.regular(codigo, dias[d], d)
        if r:
            hi, lo = comun.rango(r)
            fila["ayer"] = {"fecha": d.isoformat(), "pdh": hi, "pdl": lo, "pdc": r[-1][4]}
            if u[4] > hi:
                fila["reglas"].append("sobre-pdh")
                fila["posicion_ayer"] = "por encima del máximo de ayer"
            elif u[4] < lo:
                fila["reglas"].append("bajo-pdl")
                fila["posicion_ayer"] = "por debajo del mínimo de ayer"
            else:
                fila["posicion_ayer"] = "dentro del rango de ayer"
            break
    else:
        fila["notas"].append("sin sesión de ayer en los datos")
    # el rango de hoy frente al medio de las últimas sesiones regulares completas
    rangos = []
    for d in reversed(anteriores):
        x = comun.rango_sesion(codigo, dias[d], d)
        if x is not None:
            rangos.append(x)
        if len(rangos) >= sesiones:
            break
    if rth:
        hi, lo = comun.rango(rth)
        fila["rango_hoy"] = round(hi - lo, 4)
        fila["rango_hoy_de"] = "regular"
    else:
        hi, lo = comun.rango(velas_hoy)
        fila["rango_hoy"] = round(hi - lo, 4)
        fila["rango_hoy_de"] = "nocturna"
    if rangos:
        fila["rango_medio"] = round(sum(rangos) / len(rangos), 4)
        fila["rango_sesiones"] = len(rangos)
        fila["rango_pct"] = round(fila["rango_hoy"] / fila["rango_medio"] * 100, 1) if fila["rango_medio"] else None
    else:
        fila["notas"].append("sin sesiones anteriores completas para el rango medio")
    return fila


def acierto_futuro(fila):
    """La fila de un contrato con reglas a un acierto de la watchlist (precio y hora de la ruptura del IB si la hubo)."""
    if not fila["reglas"]:
        return None
    r = fila.get("ruptura")
    partes = []
    if r:
        partes.append("la vela de %s cerró en %s, por %s del balance inicial %s a %s (%s puntos)"
                      % (r["vela"], comun.pts(r["precio"]), "encima" if r["lado"] == "arriba" else "debajo",
                         comun.pts(fila["ib"]["bajo"]), comun.pts(fila["ib"]["alto"]), comun.pts(fila["ib"]["ancho"])))
    if fila.get("ayer"):
        partes.append("%s (%s a %s)" % (fila["posicion_ayer"], comun.pts(fila["ayer"]["pdl"]), comun.pts(fila["ayer"]["pdh"])))
    if fila.get("rango_medio") is not None:
        partes.append("rango de hoy %s puntos, el %s %% del medio de %d sesiones (%s)"
                      % (comun.pts(fila["rango_hoy"]), comun.num(fila["rango_pct"], 0), fila["rango_sesiones"], comun.pts(fila["rango_medio"])))
    return {"simbolo": fila["simbolo"], "regla": " + ".join(fila["reglas"]), "reglas": list(fila["reglas"]),
            "precio": r["precio"] if r else fila["ultimo"], "hora": r["hora"] if r else fila["hora_ultimo"],
            "detalle": "; ".join(partes)}


def escanear_futuros(codigos, ahora_utc, offline, ib_minutos=60, sesiones=SESIONES, pausa=PAUSA, rango="1mo"):
    """Devuelve (filas, fallidos). Una petición por contrato (o un archivo por contrato con --offline)."""
    hoy = comun.dia_negociacion(comun.a_ny(ahora_utc))
    filas, fallidos = [], {}
    for k, codigo in enumerate(codigos):
        if not offline and k and pausa:
            DORMIR(pausa)
        try:
            ch = comun.velas(codigo, rango, "5m", offline)
        except KemetError as e:
            fallidos[codigo] = str(e)
            continue
        dias = comun.por_dia(comun.velas_cerradas(ch, ahora_utc), codigo)
        filas.append(analizar_contrato(codigo, dias, hoy, ib_minutos, sesiones))
    return filas, fallidos


def linea_futuro(f):
    """Dos líneas por contrato para la salida llana."""
    if "ultimo" not in f:
        return ["  %-4s %s" % (f["simbolo"], "; ".join(f["notas"]))]
    a = "  %-4s último %s (%s)" % (f["simbolo"], comun.pts(f["ultimo"]), f["hora_ultimo"])
    if f.get("ib"):
        a += "   IB %s a %s, %s pts" % (comun.pts(f["ib"]["bajo"]), comun.pts(f["ib"]["alto"]), comun.pts(f["ib"]["ancho"]))
        r = f.get("ruptura")
        if r:
            a += ": CIERRE POR %s a las %s en %s" % ("ENCIMA" if r["lado"] == "arriba" else "DEBAJO", r["hora"], comun.pts(r["precio"]))
        else:
            a += ": sin cierre fuera"
    b = "      "
    if f.get("ayer"):
        b += "ayer %s a %s: %s" % (comun.pts(f["ayer"]["pdl"]), comun.pts(f["ayer"]["pdh"]), f["posicion_ayer"])
    if f.get("rango_hoy") is not None:
        b += ". Rango de hoy %s pts%s" % (comun.pts(f["rango_hoy"]), " (nocturna)" if f["rango_hoy_de"] == "nocturna" else "")
        if f.get("rango_medio") is not None:
            b += ", el %s %% del medio de %d sesiones (%s)" % (comun.num(f["rango_pct"], 0), f["rango_sesiones"], comun.pts(f["rango_medio"]))
    if f["notas"]:
        b += ". " + "; ".join(f["notas"])
    return [a, b.rstrip()]


# ---------------------------------------------------------------- descarga

def progreso(a, msg):
    if not getattr(a, "json", False) and not getattr(a, "silencio", False):
        print(msg, file=sys.stderr)


def bajar_spark(simbolos, rango, intervalo, pausa, a=None):
    """Lotes de 20. -> ({SIMBOLO: serie}, {SIMBOLO: error})."""
    datos, fallidos = {}, {}
    lotes = [simbolos[i:i + SPARK_MAX] for i in range(0, len(simbolos), SPARK_MAX)]
    seguidos = 0
    for k, lote in enumerate(lotes):
        if k and pausa:
            DORMIR(pausa)
        pedidos = {a_yahoo(s): s for s in lote}
        try:
            got = parse_spark(comun.yahoo_get(spark_path(lote, rango, intervalo)), pedidos)
            seguidos = 0
        except (KemetError, ValueError) as e:
            for s in lote:
                fallidos[s] = str(e)
            seguidos += 1
            if seguidos >= CORTE_FALLOS:
                # Yahoo limita (429) o no hay red: seguir son cientos de peticiones y minutos para acabar sin nada
                for resto in lotes[k + 1:]:
                    for s in resto:
                        fallidos[s] = "sin pedir: %d lotes seguidos fallaron (%s)" % (CORTE_FALLOS, str(e)[:80])
                if a is not None:
                    progreso(a, "  %d lotes seguidos fallaron: paro aquí (%s)" % (CORTE_FALLOS, str(e)[:80]))
                break
            continue
        for s in lote:
            if s in got:
                datos[s] = got[s]
            else:
                fallidos[s] = "Yahoo no devolvió datos"
        if a is not None and len(lotes) > 25 and (k + 1) % 50 == 0:
            progreso(a, "  spark %d de %d peticiones" % (k + 1, len(lotes)))
    return datos, fallidos


def simbolos_de_archivo(ruta):
    """Una watchlist.json (aciertos[].simbolo, o hits[].symbol del pack de referencia) o un texto SIMBOLO|Nombre."""
    if not os.path.exists(ruta):
        raise KemetError("no existe el archivo %s" % ruta)
    with open(ruta, encoding="utf-8") as fh:
        texto = fh.read()
    if texto.lstrip().startswith(("{", "[")):
        try:
            doc = json.loads(texto)
        except ValueError as e:
            raise KemetError("%s no es JSON válido: %s" % (ruta, e))
        items = (doc.get("aciertos") or doc.get("hits") or []) if isinstance(doc, dict) else doc
        return [str(x.get("simbolo") or x.get("symbol") if isinstance(x, dict) else x).upper() for x in items if x]
    out = []
    for ln in texto.splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            out.append(ln.split("|")[0].strip().upper())
    return out


def leer_simbolos(a, offline_syms=None):
    if a.simbolos:
        syms = [s for s in re.split(r"[,\s]+", a.simbolos.upper()) if s]
    elif a.watchlist:
        syms = simbolos_de_archivo(a.watchlist)
    elif offline_syms is not None and not a.universo:
        syms = sorted(offline_syms)   # offline: todos los gráficos del archivo, salvo que haya lista
    else:
        ruta = a.universo or comun.ruta(UNIVERSO)
        if not os.path.exists(ruta):
            raise KemetError("aún no hay %s: lanza `scanner.py universo` primero, o pasa --simbolos" % ruta)
        syms = simbolos_de_archivo(ruta)
    out = []
    for s in syms:
        if s not in out:
            out.append(s)
    if a.limite:
        out = out[:a.limite]
    if not out:
        raise KemetError("no hay símbolos que escanear")
    return out


def config_sin_entradas_despues():
    cfg = comun.leer_json("config.json", obligatorio=False) or {}
    return cfg.get("sin_entradas_despues") or "15:00"


def sin_datos(recibidos, total, fallidos=None):
    """Si Yahoo no ha devuelto nada, error (código 2) y kemet/watchlist.json se queda como estaba: «0 aciertos» por una caída
    de Yahoo se leía como «no hay nada»."""
    if total and not recibidos:
        motivo = ""
        if isinstance(fallidos, dict) and fallidos:
            motivo = ": %s" % sorted(set(fallidos.values()))[0][:120]
        raise KemetError("Yahoo no ha devuelto datos de ninguno de los %d símbolos%s. No toco kemet/watchlist.json; repite en unos minutos" % (total, motivo))


def documento(modo, ahora_utc, simbolos, recuento, fallidos, aciertos, a, **extra):
    doc = {"modo": modo, "generado": comun.iso(ahora_utc), "universo": len(simbolos), "escaneados": recuento.get("escaneados", 0),
           "fallidos": fallidos, "fuente": "yahoo", "nota": NOTA}
    doc.update(extra)
    doc["aciertos"] = aciertos
    if getattr(a, "offline", None):
        doc["offline"] = os.path.basename(a.offline.rstrip("/"))
    return doc


def guardar(a, doc):
    if a.sin_escribir:
        return None
    ruta = a.salida or comun.ruta(WATCHLIST)
    return comun.escribir_json(ruta, doc)


def _n(x):
    x = float(x)
    return comun.num(x, 0) if x == int(x) else comun.num(x, 2)


def plural(n, uno, varios):
    return uno if n == 1 else varios


# ---------------------------------------------------------------- comandos

def cmd_universo(a):
    t0 = time.time()
    textos = {}
    for k, nombre in enumerate(NASDAQ_ARCHIVOS):
        if a.offline:
            p = os.path.join(a.offline, nombre)
            if not os.path.exists(p):
                raise KemetError("no hay %s en %s" % (nombre, a.offline))
            with open(p, encoding="utf-8", errors="replace") as fh:
                textos[nombre] = fh.read()
        else:
            if k and a.pausa:
                DORMIR(a.pausa)
            try:
                textos[nombre] = http_get(NASDAQ_URL + nombre, timeout=60)
            except urllib.error.HTTPError as e:
                raise KemetError("nasdaqtrader.com respondió HTTP %d para %s" % (e.code, nombre))
            except (urllib.error.URLError, OSError) as e:
                raise KemetError("no se pudo llegar a nasdaqtrader.com: %s" % getattr(e, "reason", e))
    dentro, recuento, creado = construir_universo(textos)
    ruta = a.salida or comun.ruta(UNIVERSO)
    if not a.sin_escribir:
        os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as fh:
            for sym, nombre in dentro:
                fh.write("%s|%s\n" % (sym, nombre))
    fuera = {k: v for k, v in recuento.items() if k not in ("dentro", "filas")}
    if a.json:
        print(json.dumps({"total": len(dentro), "filas": recuento.get("filas", 0), "archivos_creados": creado, "fuera": fuera,
                          "salida": None if a.sin_escribir else ruta, "segundos": round(time.time() - t0, 1)}, indent=1, ensure_ascii=False))
    else:
        print("Directorios de símbolos de Nasdaq Trader%s: %s filas." % ((", archivos de las %s NY" % creado) if creado else "", comun.num(recuento.get("filas", 0), 0)))
        print("Dentro %s acciones ordinarias, comunes y ADR cotizados en EE. UU." % comun.num(len(dentro), 0))
        print("Fuera: " + ", ".join("%s %s" % (comun.num(v, 0), k) for k, v in sorted(fuera.items(), key=lambda kv: -kv[1])) + ".")
        if not a.sin_escribir:
            print("Escrito %s (un SIMBOLO|Nombre por línea)." % ruta)
    return 0 if dentro else 1


def cmd_diario(a):
    t0 = time.time()
    ahora = comun.parse_ahora(a.ahora)
    offline_syms = None
    if a.offline:
        datos, fallidos = cargar_offline(a.offline)
        offline_syms = sorted(set(datos) | set(fallidos))
    simbolos = leer_simbolos(a, offline_syms)
    if not a.offline:
        progreso(a, "Bajando cierres diarios de %s símbolos (%d peticiones al spark)..."
                 % (comun.num(len(simbolos), 0), (len(simbolos) + SPARK_MAX - 1) // SPARK_MAX))
        datos, fallidos = bajar_spark(simbolos, "3mo", "1d", a.pausa, a)
    aciertos, recuento, ultima = escanear_diario(datos, simbolos, ahora, a.min_precio, a.min_volumen)
    nfallidos = len(simbolos) - recuento["recibidos"]
    sin_datos(recuento["recibidos"], len(simbolos), fallidos)
    doc = documento("diario", ahora, simbolos, recuento, nfallidos, aciertos, a,
                    datos_hasta=("cierre del %s" % ultima.isoformat()) if ultima else None,
                    filtros={"min_precio": a.min_precio, "min_volumen": a.min_volumen})
    ruta = guardar(a, doc)
    if a.json:
        print(json.dumps(dict(doc, recuento=recuento, segundos=round(time.time() - t0, 1)), indent=1, ensure_ascii=False))
        return 0 if aciertos else 1
    ny = comun.a_ny(ahora)
    print("Escaneo diario, %s, %s · cierres hasta el %s (spark de Yahoo, solo cierres diarios)"
          % (fecha_es(ny.date()), comun.hora_doble(ahora), ultima.isoformat() if ultima else "ninguno"))
    print("Recibidos %s de %s gráficos%s. %s pasan el filtro de liquidez (%s $ o más y %s acciones o más)%s; %s escaneados."
          % (comun.num(recuento["recibidos"], 0), comun.num(len(simbolos), 0),
             (" (%s fallaron o sin datos)" % comun.num(nfallidos, 0)) if nfallidos else "",
             comun.num(recuento["recibidos"] - recuento["sin_liquidez"], 0), _n(a.min_precio), comun.num(a.min_volumen, 0),
             (", %d con menos de %d días" % (recuento["cortos"], MIN_VELAS_DIARIAS)) if recuento["cortos"] else "",
             comun.num(recuento["escaneados"], 0)))
    if aciertos:
        por = [(k, sum(1 for h in aciertos if k in h["reglas"])) for k, _ in REGLAS_DIARIO]
        print("%d %s una regla: %s." % (len(aciertos), plural(len(aciertos), "gráfico cumple", "gráficos cumplen"),
                                        ", ".join("%d %s" % (n, ETIQUETA[k]) for k, n in por if n)))
        print("Los más negociados primero (precio por volumen):")
    else:
        print("Ningún gráfico cumple una regla.")
    for h in aciertos[:a.mostrar]:
        print("  %-6s %12s  RSI %5s  %s" % (h["simbolo"], comun.usd(h["precio"], 2), comun.num(h["rsi"], 1),
                                            ", ".join(ETIQUETA[t] for t in h["reglas"])))
    if len(aciertos) > a.mostrar:
        print("  ... y %d más en la watchlist (--mostrar N para ver más)." % (len(aciertos) - a.mostrar))
    if ruta:
        print("Escrito %s (modo diario, %d %s)." % (ruta, len(aciertos), plural(len(aciertos), "acierto", "aciertos")))
    print(NOTA + " Siguiente: elige un gráfico y pásalo a kemet-noticias.")
    return 0 if aciertos else 1


def cmd_orb(a):
    t0 = time.time()
    ahora = comun.parse_ahora(a.ahora)
    corte_a = comun.parse_hhmm(a.a, "--a") if a.a else None
    hasta = comun.parse_hhmm(a.hasta or config_sin_entradas_despues(), "--hasta")
    datos = fallidos = None
    dia_explicito = None
    offline_syms = None
    if a.offline:
        datos, fallidos = cargar_offline(a.offline)
        offline_syms = sorted(set(datos) | set(fallidos))
        if not a.ahora:
            dias = [ny_de_ts(s["t"][-1]).date() for s in datos.values() if s["t"]]
            if dias:
                dia_explicito = max(dias)
                if corte_a is None:
                    raise KemetError("repetición offline: da --a HH:MM o --ahora \"AAAA-MM-DD HH:MM\"")
    try:
        dia, corte = ventana_orb(ahora, corte_a, a.rango_minutos, hasta, dia_explicito)
    except SinSesion as e:
        print(str(e))
        return 1
    simbolos = leer_simbolos(a, offline_syms)
    confirmar = None
    if not a.offline:
        hoy = comun.a_ny(comun.utc_ahora()).date()
        if (hoy - dia).days > 6:
            raise KemetError("el histórico gratuito de 5 minutos de Yahoo es corto: repite el %s con --offline" % dia.isoformat())
        rango = "1d" if dia == hoy else "5d"
        progreso(a, "Fase 1: cierres de 5 minutos de %s símbolos (%d peticiones al spark)..."
                 % (comun.num(len(simbolos), 0), (len(simbolos) + SPARK_MAX - 1) // SPARK_MAX))
        datos, fallidos = bajar_spark(simbolos, rango, "%dm" % VELA_MIN, a.pausa, a)
        hechos = []

        def confirmar(sym):
            if a.pausa:
                DORMIR(a.pausa)
            hechos.append(sym)
            if len(hechos) % 50 == 0:
                progreso(a, "  fase 2: %d gráficos v8 hasta ahora" % len(hechos))
            return parse_chart(comun.yahoo_get(chart_path(sym, rango, "%dm" % VELA_MIN)), sym)
    aciertos, recuento, fallidos2 = escanear_orb(datos, simbolos, dia, corte, a.rango_minutos, a.min_precio, a.min_volumen,
                                                 confirmar, a.max_confirmar)
    fallidos = dict(fallidos or {})
    fallidos.update(fallidos2)
    nfallidos = len([s for s in simbolos if s in fallidos])
    sin_datos(recuento["recibidos"], len(simbolos), fallidos)
    doc = documento("orb", ahora, simbolos, recuento, nfallidos, aciertos, a,
                    datos_hasta="%s %s NY" % (dia.isoformat(), comun.hhmm(corte)), sin_confirmar=recuento["sin_confirmar"],
                    rango_minutos=a.rango_minutos, intervalo="%dm" % VELA_MIN,
                    filtros={"min_precio": a.min_precio, "min_volumen": a.min_volumen})
    ruta = guardar(a, doc)
    if a.json:
        print(json.dumps(dict(doc, recuento=recuento, segundos=round(time.time() - t0, 1)), indent=1, ensure_ascii=False))
        return 0 if aciertos else 1
    print("Ruptura del rango de apertura, %s, %s NY · rango de %d minutos (09:30 a %s), velas de 5 minutos de Yahoo"
          % (fecha_es(dia), comun.hhmm(corte), a.rango_minutos, comun.hhmm(hueco(dia, a.rango_minutos // VELA_MIN))))
    print("Recibidos %s de %s gráficos%s; %s utilizables%s; %s candidatos, %s confirmados con máximos y mínimos reales."
          % (comun.num(recuento["recibidos"], 0), comun.num(len(simbolos), 0),
             (" (%s fallaron o sin datos)" % comun.num(nfallidos, 0)) if nfallidos else "",
             comun.num(recuento["escaneados"], 0),
             (" (%s bajo el suelo de precio o volumen)" % comun.num(recuento["sin_liquidez"], 0)) if recuento["sin_liquidez"] else "",
             comun.num(recuento["candidatos"], 0), comun.num(recuento["confirmados"], 0)))
    if recuento["sin_confirmar"]:
        print("PARCIAL: %s candidatos más no se comprobaron (solo los %s más negociados; --max-confirmar 0 los comprueba todos)."
              % (comun.num(recuento["sin_confirmar"], 0), comun.num(a.max_confirmar, 0)))
    if aciertos:
        print("%d de %s gráficos cerraron por encima del máximo de su rango de apertura a las %s:"
              % (len(aciertos), ("los %s comprobados" % comun.num(recuento["confirmados"], 0)) if recuento["sin_confirmar"]
                 else comun.num(recuento["escaneados"], 0), comun.hhmm(corte)))
        for h in aciertos[:a.mostrar]:
            print("  %s  %-6s %12s  rango %s a %s  +%s %% por encima" % (
                h["hora"], h["simbolo"], comun.usd(h["precio"], 2), comun.num(h["rango_bajo"]), comun.num(h["rango_alto"]), comun.num(h["pct_encima"])))
        if len(aciertos) > a.mostrar:
            print("  ... y %d más en la watchlist (--mostrar N para ver más)." % (len(aciertos) - a.mostrar))
    else:
        print("Ningún gráfico cerró por encima del máximo de su rango de apertura a las %s." % comun.hhmm(corte))
    if ruta:
        print("Escrito %s (modo orb, %d %s)." % (ruta, len(aciertos), plural(len(aciertos), "acierto", "aciertos")))
    print(NOTA + " Siguiente: elige un gráfico, kemet-noticias y después kemet-entrada.")
    return 0 if aciertos else 1


def ultima_sesion(ahora_utc):
    """Las 16:55 NY del último día con sesión de Globex antes de ahora (el viernes, en fin de semana)."""
    ny = comun.a_ny(ahora_utc)
    for atras in range(0, 10):
        d = ny.date() - dt.timedelta(days=atras)
        cand = comun.de_ny(dt.datetime.combine(d, dt.time(16, 55)))
        if cand <= ahora_utc and comun.estado_globex(cand)[0] == "abierto":
            return cand
    return ahora_utc


def cmd_futuros(a):
    t0 = time.time()
    ahora = comun.parse_ahora(a.ahora)
    if a.simbolos:
        codigos = []
        for s in re.split(r"[,\s]+", a.simbolos.upper()):
            if not s:
                continue
            inst = comun.resolver(s)
            if inst["tipo"] != "futuro":
                raise KemetError("futuros solo acepta contratos (%s), no %s; para una acción usa diario u orb" % (", ".join(comun.CONTRATOS), s))
            codigos.append(inst["codigo"])
    else:
        codigos = list(comun.CONTRATOS)
    if a.ib_minutos < VELA_MIN or a.ib_minutos % VELA_MIN or a.ib_minutos > 120:
        raise KemetError("--ib-minutos quiere un múltiplo de 5 entre 5 y 120 (60 es el del pack)")
    if not a.offline:
        progreso(a, "Bajando velas de 5 minutos de %d contratos (una petición por contrato)..." % len(codigos))
    real = ahora
    if comun.estado_globex(ahora)[0] == "cerrado":
        ahora = ultima_sesion(ahora)          # fin de semana o festivo: el escaneo de la última sesión, no «sin velas de hoy»
    filas, fallidos = escanear_futuros(codigos, ahora, a.offline, a.ib_minutos, a.sesiones, a.pausa)
    aciertos = [h for h in (acierto_futuro(f) for f in filas) if h]
    recuento = {"pedidos": len(codigos), "recibidos": len(filas), "escaneados": len([f for f in filas if "ultimo" in f]),
                "aciertos": len(aciertos)}
    ny = comun.a_ny(ahora)
    hoy = comun.dia_negociacion(ny)
    sin_datos(len(filas), len(codigos), fallidos)
    doc = documento("futuros", ahora, codigos, recuento, len(fallidos), aciertos, a,
                    datos_hasta="%s %s NY" % (hoy.isoformat(), comun.hhmm(ny)), ib_minutos=a.ib_minutos, sesiones=a.sesiones,
                    contratos=filas, sin_datos=fallidos)
    ruta = guardar(a, doc)
    if a.json:
        print(json.dumps(dict(doc, recuento=recuento, segundos=round(time.time() - t0, 1)), indent=1, ensure_ascii=False))
        return 0 if aciertos else 1
    estado, motivo = comun.estado_globex(real)
    if real != ahora:
        print("Globex %s (%s): este es el escaneo de la última sesión, hasta las %s." % (estado, motivo, comun.hora_doble(ahora)))
        estado = "abierto"
    print("Futuros, %s, %s · balance inicial de %d minutos, máximo y mínimo de ayer, rango frente al medio de %d sesiones (velas de 5 minutos de Yahoo, unos 10 minutos de retraso)"
          % (fecha_es(hoy), comun.hora_doble(ahora), a.ib_minutos, a.sesiones))
    if estado != "abierto":
        print("Globex %s (%s): los últimos cierres son los de antes del cierre." % (estado, motivo))
    linea = "%d de %d contratos con datos" % (len(filas), len(codigos))
    if fallidos:
        linea += " (%d sin datos: %s). PARCIAL." % (len(fallidos), ", ".join(fallidos))
    else:
        linea += "."
    print(linea)
    for f in filas:
        for ln in linea_futuro(f):
            print(ln)
    if aciertos:
        print("%d %s una regla: %s." % (len(aciertos), plural(len(aciertos), "contrato cumple", "contratos cumplen"),
                                        "; ".join("%s %s" % (h["simbolo"], ", ".join(ETIQUETA[r] for r in h["reglas"])) for h in aciertos)))
    else:
        print("Ningún contrato cumple una regla a esta hora.")
    if ruta:
        print("Escrito %s (modo futuros, %d %s)." % (ruta, len(aciertos), plural(len(aciertos), "acierto", "aciertos")))
    print(NOTA + " Siguiente: niveles y plan del contrato elegido (kemet-niveles, kemet-plan), la entrada vela a vela con kemet-entrada.")
    return 0 if aciertos else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Escáner de gráficos (kemet-scanner): reglas diarias, rupturas del rango de apertura y los doce futuros.")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("universo", help="baja las listas de Nasdaq Trader -> kemet/universo.txt")
    p.add_argument("--salida", help="ruta del archivo (por defecto kemet/universo.txt)")
    p.add_argument("--offline", metavar="CARPETA", help="una carpeta con nasdaqlisted.txt y otherlisted.txt")
    p.add_argument("--sin-escribir", dest="sin_escribir", action="store_true")
    p.add_argument("--pausa", type=float, default=PAUSA)
    p.add_argument("--json", action="store_true")

    def comunes(p, min_precio, min_volumen, con_universo=True):
        g = p.add_mutually_exclusive_group()
        g.add_argument("--simbolos", help="tickers separados por comas en vez del universo")
        if con_universo:
            g.add_argument("--watchlist", metavar="ARCHIVO", help="una watchlist.json (aciertos) o un texto de tickers")
            p.add_argument("--universo", help="lista de símbolos, un SIMBOLO|Nombre por línea (por defecto kemet/universo.txt)")
            p.add_argument("--limite", type=int, help="escanea solo los N primeros símbolos")
            p.add_argument("--min-precio", dest="min_precio", type=float, default=min_precio)
            p.add_argument("--min-volumen", dest="min_volumen", type=int, default=min_volumen)
        p.add_argument("--offline", metavar="RUTA", help="carpeta o archivo de fixtures en vez de la red")
        p.add_argument("--ahora", help='fija el reloj ("2026-10-19 10:15", hora de Nueva York)')
        p.add_argument("--salida", help="ruta de la watchlist (por defecto kemet/watchlist.json)")
        p.add_argument("--sin-escribir", dest="sin_escribir", action="store_true")
        p.add_argument("--pausa", type=float, default=PAUSA, help="segundos entre peticiones (%.1f)" % PAUSA)
        p.add_argument("--mostrar", type=int, default=50, help="aciertos que se imprimen (se escriben todos)")
        p.add_argument("--silencio", action="store_true")
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("diario", help="reglas de antes de la apertura sobre cierres diarios")
    comunes(p, 5.0, 1000000)
    p = sub.add_parser("orb", help="rupturas del rango de apertura hasta ahora")
    comunes(p, 5.0, 0)
    p.add_argument("--rango-minutos", dest="rango_minutos", type=int, default=15)
    p.add_argument("--max-confirmar", dest="max_confirmar", type=int, default=MAX_CONFIRMAR,
                   help="gráficos v8 que pide la fase 2, los más negociados primero (%d; 0 = todos)" % MAX_CONFIRMAR)
    p.add_argument("--a", help="corta el reloj a esta hora de Nueva York, HH:MM")
    p.add_argument("--hasta", help="sin entradas nuevas después de HH:MM (por defecto sin_entradas_despues de kemet/config.json, 15:00)")
    p = sub.add_parser("futuros", help="los doce contratos: balance inicial, máximo y mínimo de ayer, rango frente al medio")
    comunes(p, 0.0, 0, con_universo=False)
    p.add_argument("--ib-minutos", dest="ib_minutos", type=int, default=60)
    p.add_argument("--sesiones", type=int, default=SESIONES, help="sesiones para el rango medio (%d)" % SESIONES)
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    for k in ("watchlist", "universo", "limite", "min_precio", "min_volumen"):
        if not hasattr(a, k):
            setattr(a, k, None if k != "min_precio" else 0.0)
    try:
        return {"universo": cmd_universo, "diario": cmd_diario, "orb": cmd_orb, "futuros": cmd_futuros}[a.cmd](a)
    except KemetError as e:
        print("scanner.py: %s" % e, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("scanner.py: parado", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
