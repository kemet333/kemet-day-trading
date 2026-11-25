#!/usr/bin/env python3
"""kemet-niveles · gamma.py: los niveles de gamma de las opciones en el precio del futuro: muro de calls, muro de puts, gamma 0 y
movimiento esperado hasta el próximo vencimiento.

    python3 gamma.py --mercado NQ                  # opciones de QQQ y del NDX, llevadas al precio del NQ
    python3 gamma.py --mercado ES --dias 14        # SPY y SPX, vencimientos de las dos próximas semanas
    python3 gamma.py --mercado TSLA                # una acción: sus propias opciones
    python3 gamma.py --mercado NQ --escribir --json

Cómo se calcula (el método es público; los números, de las cadenas de Yahoo):
  1. Por cada opción de los vencimientos que entran en --dias (sin las que vencen hoy, salvo con --con-0dte): interés abierto, volatilidad implícita y tiempo hasta el
     vencimiento (16:00 NY).
  2. Gamma de Black-Scholes y exposición en dólares por un 1 % de movimiento: interés abierto × gamma × 100 × precio² × 1 %.
     Calls en positivo y puts en negativo: el modelo de siempre, que supone que los dealers van largos de calls y cortos de
     puts. Es un supuesto, no un dato: nadie publica las posiciones de los dealers.
  3. Cada strike se lleva al precio del futuro con la relación futuro / subyacente de ahora, y se suma por filas.
  4. Muro de calls: la fila con más gamma de calls por encima del precio. Muro de puts: la de más gamma de puts por debajo. Gamma 0: el precio en el que la gamma
     total cambia de signo, recalculando todas las opciones en una rejilla de precios. Movimiento esperado: precio × volatilidad
     implícita at-the-money del vencimiento más cercano × √(tiempo hasta él).

Límites: el interés abierto es el del cierre anterior (la OCC lo publica una vez al día); Yahoo es gratis y va con retraso; no
incluye las opciones sobre futuros de la CME (son de pago). Código de salida: 0 con niveles, 2 si hay un error.
"""
import argparse
import datetime as dt
import gzip
import http.cookiejar
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

import comun
from comun import KemetError, pts

SUBYACENTES = {"NQ": ("QQQ", "^NDX"), "ES": ("SPY", "^SPX"), "RTY": ("IWM", "^RUT"), "YM": ("DIA",)}
FILA = {"NQ": 25.0, "ES": 5.0, "RTY": 5.0, "YM": 50.0}
MAX_VENCIMIENTOS = 15
INTERES = 0.04
RANGO_FLIP = 0.12            # la rejilla de la gamma 0: ±12 % del precio
FUENTE = "cadenas de opciones de Yahoo (gratis, con retraso; interés abierto del cierre anterior)"


# ---------------------------------------------------------------- Black-Scholes

def _phi(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def gamma_bs(S, K, iv, T, r=INTERES):
    if S <= 0 or K <= 0 or iv <= 0 or T <= 0:
        return 0.0
    v = iv * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * iv * iv) * T) / v
    return _phi(d1) / (S * v)


def gex(oi, g, S, mult=100):
    """Exposición en dólares por un 1 % de movimiento."""
    return oi * g * mult * S * S * 0.01


# ---------------------------------------------------------------- Yahoo con cookie y crumb

class Yahoo:
    """Las cadenas de opciones de Yahoo piden una cookie y un «crumb» (lo mismo que hace su web). Sin claves."""

    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.crumb = None

    def _get(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": comun.UA, "Accept": "application/json,text/plain,*/*"})
        with self.op.open(req, timeout=20) as r:
            return r.read().decode("utf-8", "replace")

    def _crumb(self):
        try:
            self._get("https://fc.yahoo.com")
        except (urllib.error.URLError, OSError):
            pass                                    # responde 404, pero deja la cookie
        try:
            c = self._get("https://query1.finance.yahoo.com/v1/test/getcrumb").strip()
        except (urllib.error.URLError, OSError) as e:
            raise KemetError("Yahoo no da acceso a las opciones (%s): repite en un minuto" % e)
        if not c or "<" in c or len(c) > 40:
            raise KemetError("Yahoo no dio el permiso para las opciones: repite en un minuto")
        self.crumb = c

    def opciones(self, simbolo, fecha=None):
        if not self.crumb:
            self._crumb()
        q = urllib.parse.quote(simbolo)
        for intento in (0, 1):
            url = "https://query2.finance.yahoo.com/v7/finance/options/%s?crumb=%s%s" % (q, urllib.parse.quote(self.crumb), "&date=%d" % fecha if fecha else "")
            try:
                doc = json.loads(self._get(url))
                res = (doc.get("optionChain") or {}).get("result") or []
                if not res:
                    raise KemetError("Yahoo no tiene opciones de %s" % simbolo)
                comun._sleep(comun.PAUSE)
                return res[0]
            except urllib.error.HTTPError as e:
                if e.code == 401 and intento == 0:
                    self._crumb()
                    continue
                raise KemetError("Yahoo respondió HTTP %d con las opciones de %s" % (e.code, simbolo))
            except (urllib.error.URLError, OSError) as e:
                raise KemetError("sin conexión con Yahoo: %s" % e)
            except ValueError:
                raise KemetError("Yahoo devolvió algo que no es JSON con las opciones de %s" % simbolo)


def cadena(simbolo, dias, ahora_utc, yahoo=None, offline=None, con_0dte=False):
    """{"simbolo", "precio", "opciones": [(tipo, strike, oi, iv, vence_utc)]} con los vencimientos de los próximos `dias`."""
    if offline:
        nombre = simbolo.replace("^", "") + "-opciones.json"
        ruta = os.path.join(offline, nombre)
        abrir = open
        if not os.path.exists(ruta) and os.path.exists(ruta + ".gz"):
            ruta, abrir = ruta + ".gz", gzip.open
        if not os.path.exists(ruta):
            raise KemetError("sin %s en %s" % (nombre, offline))
        with abrir(ruta, "rt", encoding="utf-8") as fh:
            bloques = json.load(fh)
    else:
        yahoo = yahoo or Yahoo()
        primero = yahoo.opciones(simbolo)
        limite = comun.ts_de_utc(ahora_utc) + dias * 86400
        fechas = [d for d in primero.get("expirationDates") or [] if d <= limite][:MAX_VENCIMIENTOS]
        bloques = [primero] + [yahoo.opciones(simbolo, d) for d in fechas[1:]]
    precio = None
    ops = []
    for b in bloques:
        precio = precio or (b.get("quote") or {}).get("regularMarketPrice")
        for o in b.get("options") or []:
            fecha = dt.datetime.fromtimestamp(int(o["expirationDate"]), dt.timezone.utc).date()
            vence = comun.de_ny(dt.datetime.combine(fecha, dt.time(16, 0)))
            if vence <= ahora_utc or (vence - ahora_utc).days > dias:
                continue
            if not con_0dte and fecha <= comun.a_ny(ahora_utc).date():
                continue                            # lo que vence hoy: su gamma en el dinero lo tapa todo y no es un muro
            for tipo, lista in (("call", o.get("calls") or []), ("put", o.get("puts") or [])):
                for c in lista:
                    oi, iv, k = c.get("openInterest") or 0, c.get("impliedVolatility") or 0, c.get("strike")
                    if not k or oi <= 0 or not (0.01 <= iv <= 5):
                        continue
                    ops.append((tipo, float(k), int(oi), float(iv), vence))
    if not precio:
        raise KemetError("Yahoo no dio el precio de %s" % simbolo)
    return {"simbolo": simbolo, "precio": float(precio), "opciones": ops}


# ---------------------------------------------------------------- los niveles

def calcular(codigo, cadenas, precio_fut, ahora_utc, fila=None):
    """Pura: los niveles en el precio de `codigo` desde una o varias cadenas (cada una con su relación futuro/subyacente)."""
    paso = fila or FILA.get(codigo) or None
    filas = {}
    usadas = 0
    for ch in cadenas:
        S = ch["precio"]
        ratio = precio_fut / S
        for tipo, K, oi, iv, vence in ch["opciones"]:
            T = max((vence - ahora_utc).total_seconds() / (365.0 * 86400), 1.0 / (365 * 24))
            g = gex(oi, gamma_bs(S, K, iv, T), S) * (1 if tipo == "call" else -1)
            kf = K * ratio
            clave = round(kf / paso) * paso if paso else K
            f = filas.setdefault(clave, [0.0, 0.0])
            f[0 if tipo == "call" else 1] += g
            usadas += 1
    if not filas:
        raise KemetError("ninguna opción con interés abierto y volatilidad válidos en esos vencimientos")
    claves = sorted(filas)
    # los muros, a cada lado del precio: en el precio mismo manda la gamma de lo que vence hoy, y eso no es un muro
    sobre = [k for k in claves if k >= precio_fut] or claves
    bajo = [k for k in claves if k <= precio_fut] or claves
    muro_calls = max(sobre, key=lambda k: filas[k][0])
    muro_puts = min(bajo, key=lambda k: filas[k][1])
    total_ahora = sum(f[0] + f[1] for f in filas.values())

    # gamma 0: la gamma total recalculada en una rejilla de precios del futuro
    def total_en(pf):
        t = 0.0
        for ch in cadenas:
            S = ch["precio"] * pf / precio_fut
            for tipo, K, oi, iv, vence in ch["opciones"]:
                T = max((vence - ahora_utc).total_seconds() / (365.0 * 86400), 1.0 / (365 * 24))
                t += gex(oi, gamma_bs(S, K, iv, T), S) * (1 if tipo == "call" else -1)
        return t
    rejilla = [precio_fut * (1 - RANGO_FLIP + i * (2 * RANGO_FLIP / 120.0)) for i in range(121)]
    valores = [total_en(p) for p in rejilla]
    cruces = []
    for i in range(1, len(rejilla)):
        a, b = valores[i - 1], valores[i]
        if a == 0 or (a < 0) != (b < 0):
            x = rejilla[i - 1] + (rejilla[i] - rejilla[i - 1]) * (0 - a) / ((b - a) or 1)
            cruces.append(x)
    flip = min(cruces, key=lambda x: abs(x - precio_fut)) if cruces else None

    # movimiento esperado: volatilidad at-the-money del vencimiento más cercano de la primera cadena
    ch0 = cadenas[0]
    cercano = min((o[4] for o in ch0["opciones"]), default=None)
    atm = [o for o in ch0["opciones"] if o[4] == cercano]
    mov = None
    if atm:
        k_atm = min({o[1] for o in atm}, key=lambda k: abs(k - ch0["precio"]))
        ivs = [o[3] for o in atm if o[1] == k_atm]
        iv_atm = sum(ivs) / len(ivs)
        T = max((cercano - ahora_utc).total_seconds() / (365.0 * 86400), 1.0 / (365 * 24))
        mov = precio_fut * iv_atm * math.sqrt(T)                    # lo que descuenta el mercado hasta ese vencimiento
    tick = comun.tick_de(codigo, micro=False) if codigo in comun.CONTRATOS else 0.01
    al = lambda x: comun.al_tick(x, tick) if x is not None else None
    arriba = sorted([k for k in claves if k > precio_fut], key=lambda k: -filas[k][0])[:3]
    abajo = sorted([k for k in claves if k < precio_fut], key=lambda k: filas[k][1])[:3]
    return {
        "mercado": codigo, "precio": precio_fut, "subyacentes": [{"simbolo": c["simbolo"], "precio": c["precio"], "relacion": round(precio_fut / c["precio"], 6), "opciones": len(c["opciones"])} for c in cadenas],
        "fila": paso, "muro_calls": al(muro_calls), "muro_puts": al(muro_puts), "gamma_0": al(flip),
        "gamma_total_musd": round(total_ahora / 1e6, 1), "regimen": "positiva" if total_ahora > 0 else "negativa",
        "movimiento_esperado": round(mov, 2) if mov else None, "rango_esperado": [al(precio_fut - mov), al(precio_fut + mov)] if mov else None,
        "vencimiento_esperado": comun.a_ny(cercano).date().isoformat() if mov else None,
        "calls_arriba": [[al(k), round(filas[k][0] / 1e6, 1)] for k in arriba], "puts_abajo": [[al(k), round(filas[k][1] / 1e6, 1)] for k in abajo],
        "opciones_usadas": usadas, "fuente": FUENTE,
        "supuesto": "dealers largos de calls y cortos de puts (el modelo habitual; nadie publica sus posiciones)",
    }


def informe(doc, ahora_utc):
    sub = " + ".join("%s %s" % (s["simbolo"], pts(s["precio"])) for s in doc["subyacentes"])
    L = ["GAMMA · %s %s · %s · opciones de %s" % (doc["mercado"], pts(doc["precio"]), comun.hora_doble(ahora_utc), sub),
         "  Muro de calls   %s   (por encima: donde más gamma de calls hay; suele frenar las subidas)" % pts(doc["muro_calls"]),
         "  Muro de puts    %s   (por debajo: donde más gamma de puts hay; suele frenar las bajadas)" % pts(doc["muro_puts"]),
         "  Gamma 0         %s   %s" % (pts(doc["gamma_0"]) if doc["gamma_0"] else "no cruza en ±12 %",
                                       "(por encima los dealers frenan los movimientos; por debajo los aceleran)" if doc["gamma_0"] else ""),
         "  Gamma ahora     %s (%s M$ por un 1 %%)" % (doc["regimen"], comun.num(doc["gamma_total_musd"], 1))]
    if doc["movimiento_esperado"]:
        L.append("  Movimiento esperado hasta el vencimiento del %s: ±%s pts (%s – %s)" % (doc["vencimiento_esperado"], pts(doc["movimiento_esperado"]),
                 pts(doc["rango_esperado"][0]), pts(doc["rango_esperado"][1])))
    if doc["calls_arriba"]:
        L.append("  Calls por encima: " + " · ".join("%s (%s M$)" % (pts(k), comun.num(v, 1)) for k, v in doc["calls_arriba"]))
    if doc["puts_abajo"]:
        L.append("  Puts por debajo:  " + " · ".join("%s (%s M$)" % (pts(k), comun.num(v, 1)) for k, v in doc["puts_abajo"]))
    L.append("Supuesto: %s. Fuente: %s; no incluye las opciones sobre futuros de la CME. Son zonas de contexto, no señales."
             % (doc["supuesto"], doc["fuente"]))
    return "\n".join(L)


def precio_futuro(codigo, offline=None):
    ch = comun.velas(codigo, "5d", "5m", offline) if not offline else None
    if ch is None:
        for r in ("60d", "5d"):
            try:
                ch = comun.velas(codigo, r, "5m", offline)
                break
            except KemetError:
                continue
    if not ch or not ch["velas"]:
        raise KemetError("sin precio de %s: pásalo con --precio" % codigo)
    return ch["velas"][-1][4]


def main(argv=None):
    p = argparse.ArgumentParser(description="Niveles de gamma de las opciones en el precio del futuro (kemet-niveles).")
    p.add_argument("--mercado", help="NQ, ES, RTY, YM o un ticker de EE. UU.; por defecto el de kemet/config.json, y si no hay, NQ")
    p.add_argument("--dias", type=int, default=30, help="vencimientos de los próximos N días (30)")
    p.add_argument("--fila", type=float, help="ancho de fila en puntos del futuro (NQ 25, ES 5)")
    p.add_argument("--precio", type=float, help="precio del futuro (por defecto el último de Yahoo)")
    p.add_argument("--ahora", help='hora de Nueva York, "AAAA-MM-DD HH:MM"')
    p.add_argument("--offline", help="carpeta con <SIMBOLO>-opciones.json(.gz) guardados (y las velas, para el precio)")
    p.add_argument("--con-0dte", dest="con_0dte", action="store_true", help="incluye las opciones que vencen hoy (por defecto fuera)")
    p.add_argument("--escribir", action="store_true", help="guarda kemet/gamma.json")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    try:
        if a.dias < 1 or a.dias > 120:
            raise KemetError("--dias va de 1 a 120")
        ahora = comun.parse_ahora(a.ahora)
        cfg = comun.leer_json("config.json", obligatorio=False) or {}
        bruto = (a.mercado or cfg.get("mercado") or "NQ").upper()
        inst = comun.resolver(bruto)
        codigo = inst["codigo"]
        if inst["tipo"] == "accion":
            simbolos, fila = (codigo,), a.fila
        elif codigo in SUBYACENTES:
            simbolos, fila = SUBYACENTES[codigo], a.fila or FILA[codigo]
        else:
            raise KemetError("%s no tiene opciones gratis en Yahoo: las opciones sobre futuros de la CME son de pago. Hay de NQ, ES, RTY y YM (por sus índices y ETF) y de acciones" % codigo)
        yahoo = None if a.offline else Yahoo()
        cadenas = [cadena(s, a.dias, ahora, yahoo, a.offline, a.con_0dte) for s in simbolos]
        if inst["tipo"] == "accion":
            precio = a.precio or cadenas[0]["precio"]
        else:
            precio = a.precio or precio_futuro(codigo, a.offline)
        doc = calcular(codigo, cadenas, precio, ahora, fila)
        if a.escribir:
            comun.escribir_json("gamma.json", dict(doc, generado=comun.iso(ahora)))
        print(json.dumps(doc, ensure_ascii=False, indent=1) if a.json else informe(doc, ahora))
        return 0
    except KemetError as e:
        print("gamma.py: %s" % e, file=sys.stderr)
        return 2



if __name__ == "__main__":
    sys.exit(main())
