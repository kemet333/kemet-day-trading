#!/usr/bin/env python3
"""Niveles de sesión de futuros (ES, NQ, CL, GC...) y de acciones de EE. UU. (TSLA) con velas de 5 minutos de Yahoo
(gratis, sin clave). Solo biblioteca estándar.

    python3 niveles.py                              # el mercado de kemet/config.json (NQ si no hay)
    python3 niveles.py --mercado ES --escribir      # guarda kemet/niveles.json
    python3 niveles.py --todos                      # ES, NQ, CL y GC
    python3 niveles.py --ahora "2026-11-11 16:30" --offline tests/fixtures/yahoo --json
    python3 niveles.py --mercado TSLA               # una acción: sin noche, apertura y balance inicial de 15 minutos

Lo que un trader de futuros marca antes de abrir y nadie tuvo que teclear: máximo, mínimo y cierre de la sesión
regular anterior (el cierre de la última vela de 5 minutos hace de liquidación), el rango nocturno desde las 18:00 NY,
la apertura (primeros 15 minutos), el balance inicial (primera hora, solo cuando ya cerró), el máximo y el mínimo de
hoy, el rango medio de las últimas 20 sesiones regulares (contexto para dimensionar un stop) y dónde está el último
precio respecto a todo eso. Niveles, no señales: ni dirección, ni objetivos, ni filtros.

Puerto de `intelligence/app/levels.py` de Kemet a velas de 5 minutos. El día de negociación de CME empieza a las
18:00 NY de la víspera; la sesión regular es 09:30–16:00 en ES y NQ, 09:00–14:30 en CL y 08:20–13:30 en GC. Yahoo va
unos 10 minutos por detrás de CME: el «último» es el cierre de la última vela cerrada, nunca la cinta.

Una acción (--mercado TSLA): el día es la fecha de Nueva York, sin sesión nocturna (no hay ONH ni ONL), sesión regular
de 09:30 a 16:00 (13:00 en los días recortados de la NYSE), apertura y balance inicial de 15 minutos (--ib-minutos
para otro), niveles al céntimo y el rango medio en dólares por acción. Fin de semana y festivos de la NYSE: cerrado.

Código de salida 0 si hay niveles, 1 si no hay sesión anterior en el histórico, 2 si hay un error.
"""
import argparse
import datetime as dt
import os
import sys

import comun
from comun import KemetError

CODIGOS = ("ES", "NQ", "CL", "GC")
IB_FUTURO, IB_ACCION = 60, 15
RANGOS = ("60d", "5d")          # 60 días (los que Yahoo guarda en 5 min) para el rango medio de 20 sesiones; sin conexión vale uno de 5
DIAS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
ETIQUETAS = {"pdh": "máximo de ayer", "pdl": "mínimo de ayer", "pdc": "cierre de ayer", "onh": "máximo nocturno",
             "onl": "mínimo nocturno", "orh": "máximo de la apertura", "orl": "mínimo de la apertura",
             "ibh": "máximo del balance inicial", "ibl": "mínimo del balance inicial", "tdh": "máximo de hoy", "tdl": "mínimo de hoy"}
CLAVES = ("pdh", "pdl", "pdc", "onh", "onl", "orh", "orl", "ibh", "ibl", "tdh", "tdl")
FUENTE = "velas de 5 min de Yahoo (gratis, ~10 min de retraso)"
FUENTE_ACCION = "velas de 5 min de Yahoo (gratis, pueden ir con retraso)"


def es_accion(codigo):
    return comun.resolver(codigo)["tipo"] == "accion"


def dia_de(codigo, utc):
    """El día de negociación de CME en un futuro; la fecha de Nueva York en una acción."""
    ny = comun.a_ny(utc)
    return ny.date() if es_accion(codigo) else comun.dia_negociacion(ny)


def cerrado_hoy(codigo, utc):
    """(cerrado, motivo): Globex cerrado en un futuro; fin de semana o festivo de la NYSE en una acción."""
    if not es_accion(codigo):
        g, motivo = comun.estado_globex(utc)
        return g == "cerrado", motivo
    d = comun.a_ny(utc).date()
    if d.isoformat() in comun.NYSE_CERRADO:
        return True, comun.NYSE_CERRADO[d.isoformat()]
    if d.weekday() >= 5:
        return True, ("sábado", "domingo")[d.weekday() - 5]
    return False, None


# ---------------------------------------------------------------- datos

_CACHE = {}


def cargar(codigo, offline=None):
    """Velas de 5 min: 60 días (los que Yahoo guarda) o, sin conexión, lo que haya en el archivo. Un archivo se lee una vez por proceso."""
    if not offline:
        return comun.velas(codigo, "60d", "5m")
    clave = (codigo, os.path.abspath(offline))
    if clave not in _CACHE:
        ultimo = None
        for r in RANGOS:
            try:
                _CACHE[clave] = comun.velas(codigo, r, "5m", offline)
                break
            except KemetError as e:
                ultimo = e
        else:
            raise ultimo
    return _CACHE[clave]


def fecha_es(d):
    return "%s %s" % (DIAS[d.weekday()], d.isoformat())


# ---------------------------------------------------------------- el cálculo

def calcular(codigo, ch, ahora_utc, ib_minutos=None):
    """Niveles de un instrumento (futuro o acción) a una hora dada. Devuelve el documento de kemet/niveles.json o None sin sesión anterior.
    `ib_minutos` None: 60 en un futuro, 15 en una acción."""
    inst = comun.resolver(codigo)
    codigo = inst["codigo"]
    accion = inst["tipo"] == "accion"
    ib_minutos = ib_minutos or (IB_ACCION if accion else IB_FUTURO)
    cerradas = comun.velas_cerradas(ch, ahora_utc)
    if not cerradas:
        return None
    dias = comun.por_dia(cerradas, codigo)
    hoy = dia_de(codigo, ahora_utc)
    previos = [d for d in dias if d < hoy and comun.regular(codigo, dias[d], d)]
    if not previos:
        return None
    ayer = previos[-1]
    rth_ayer = comun.regular(codigo, dias[ayer], ayer)
    ultima = cerradas[-1]
    doc = {"generado": comun.iso(ahora_utc), "mercado": codigo, "instrumento": inst["tipo"], "fecha": hoy.isoformat(), "sesion_anterior": ayer.isoformat(),
           "ultimo": ultima[4], "ultimo_hora": comun.hhmm(comun.a_ny(comun.utc_de_ts(ultima[0] + ch["paso"]))),
           "pdh": max(b[2] for b in rth_ayer), "pdl": min(b[3] for b in rth_ayer), "pdc": rth_ayer[-1][4]}
    apertura, cierre = comun.sesion_regular(codigo, hoy)
    t_ap = comun.ts_de_utc(apertura)
    velas_hoy = dias.get(hoy, [])
    noche = [b for b in velas_hoy if b[0] < t_ap] if not accion else []
    if noche:
        doc["onh"], doc["onl"] = comun.rango(noche)
    rth = comun.regular(codigo, velas_hoy, hoy)
    ahora_ts = comun.ts_de_utc(ahora_utc)
    if rth:
        apertura15 = [b for b in rth if b[0] < t_ap + 15 * 60]
        if ahora_ts >= t_ap + 15 * 60 and len(apertura15) >= 3:      # las tres velas de 5 minutos, no solo el reloj
            doc["orh"], doc["orl"] = comun.rango(apertura15)
        ib = comun.balance_inicial(codigo, velas_hoy, hoy, ib_minutos)
        if ib and ib.get("completo", True):
            doc["ibh"], doc["ibl"], doc["ib_ancho"], doc["ib_velas"] = ib["alto"], ib["bajo"], ib["ancho"], ib["velas"]
        doc["tdh"], doc["tdl"] = comun.rango(rth)
    doc["ib_minutos"] = ib_minutos
    cerrado, motivo = cerrado_hoy(codigo, ahora_utc)
    if cerrado:
        doc["sesion"], doc["mercado_cerrado"] = "cerrado", motivo
    elif apertura <= ahora_utc < cierre:
        doc["sesion"] = "rth"
    elif ahora_utc < apertura:
        doc["sesion"] = "nocturna" if not accion else "cerrado"
        if accion:
            doc["antes_apertura"] = True
    else:
        doc["sesion"] = "cerrado"
    o_ayer, c_ayer = comun.sesion_regular(codigo, ayer)
    if len(rth_ayer) < int((c_ayer - o_ayer).total_seconds() // ch["paso"]) - 2:
        doc["sesion_anterior_incompleta"] = len(rth_ayer)
    rangos = []
    for d in reversed(previos):                      # las últimas 20 sesiones regulares completas (una con huecos no cuenta)
        r = comun.rango_sesion(codigo, dias[d], d)
        if r:
            rangos.append(r)
        if len(rangos) == 20:
            break
    if rangos:
        doc["rango_medio_20"] = round(sum(rangos) / len(rangos), 2)
        doc["rango_medio_sesiones"] = len(rangos)
    tick = inst["tick"]
    for k in CLAVES + ("ultimo", "ib_ancho"):
        if k in doc:
            doc[k] = comun.al_tick(doc[k], tick)
    ultimo = doc["ultimo"]
    doc["posicion"] = {k: ("encima" if ultimo > doc[k] else "debajo" if ultimo < doc[k] else "en") for k in CLAVES if k in doc}
    return doc


# ---------------------------------------------------------------- texto

def lineas(doc, codigo, ahora_utc):
    c = comun.resolver(codigo)
    accion = c["tipo"] == "accion"
    sesion = {"rth": "sesión regular abierta", "nocturna": "sesión nocturna", "cerrado": "sesión regular cerrada"}[doc["sesion"]]
    if "mercado_cerrado" in doc:
        sesion = "mercado cerrado (%s)" % doc["mercado_cerrado"]
    elif doc.get("antes_apertura"):
        sesion = "antes de la apertura (09:30 NY)"
    out = ["%s · %s · %s · %s · %s" % (codigo, fecha_es(dt.date.fromisoformat(doc["fecha"])), comun.hora_doble(ahora_utc), FUENTE_ACCION if accion else FUENTE, sesion),
           "Último %s (cierre de la vela de las %s NY)" % (comun.num(doc["ultimo"], 2), doc["ultimo_hora"]),
           "  %-34s máximo %s   mínimo %s   cierre %s" % ("Ayer (sesión regular %s)" % doc["sesion_anterior"], comun.pts(doc["pdh"]), comun.pts(doc["pdl"]), comun.pts(doc["pdc"]))]
    if "sesion_anterior_incompleta" in doc:
        out[-1] += "   (sesión incompleta en los datos: %d velas, los niveles pueden cambiar)" % doc["sesion_anterior_incompleta"]
    if "onh" in doc:
        out.append("  %-34s máximo %s   mínimo %s" % ("Noche (desde 18:00 NY)", comun.pts(doc["onh"]), comun.pts(doc["onl"])))
    elif not accion:
        out.append("  %-34s sin velas todavía" % "Noche (desde 18:00 NY)")
    apertura = c["rth"][0]
    ib_min = doc.get("ib_minutos") or IB_FUTURO
    etiqueta_ib = "Balance inicial 1 h" if ib_min == 60 else "Balance inicial %d min" % ib_min
    if "orh" in doc:
        out.append("  %-34s máximo %s   mínimo %s" % ("Apertura 15 min", comun.pts(doc["orh"]), comun.pts(doc["orl"])))
    else:
        out.append("  %-34s %s" % ("Apertura 15 min", _pendiente(doc, apertura, 15)))
    if "ibh" in doc:
        out.append("  %-34s máximo %s   mínimo %s   ancho %s (%d velas)" % (etiqueta_ib, comun.pts(doc["ibh"]), comun.pts(doc["ibl"]), comun.pts(doc["ib_ancho"]), doc["ib_velas"]))
    else:
        out.append("  %-34s %s" % (etiqueta_ib, _pendiente(doc, apertura, ib_min)))
    if "tdh" in doc:
        out.append("  %-34s máximo %s   mínimo %s" % ("Hoy (sesión regular)", comun.pts(doc["tdh"]), comun.pts(doc["tdl"])))
    else:
        out.append("  %-34s sin sesión regular todavía" % "Hoy (sesión regular)")
    if "rango_medio_20" in doc:
        n = doc["rango_medio_sesiones"]
        out.append("  %-34s %s %s (media de máximo menos mínimo de %s, para dimensionar el stop)" % (
            "Rango medio de sesión", comun.num(doc["rango_medio_20"], 2), "$ por acción" if accion else "puntos",
            "las últimas 20 sesiones" if n >= 20 else ("1 sesión, la que hay" if n == 1 else "%d sesiones, las que hay" % n)))
    pos = doc["posicion"]
    partes = []
    for estado, palabra in (("encima", "por encima"), ("debajo", "por debajo"), ("en", "justo en")):
        ks = [k for k in CLAVES if pos.get(k) == estado]
        if ks:
            partes.append("%s %s" % (palabra, ", ".join(_corto(k) if estado != "en" else _corto(k).replace("del ", "el ", 1) for k in ks)))
    out.append("El precio está " + "; ".join(partes) + ".")
    return out


def _pendiente(doc, apertura, minutos):
    if doc["sesion"] == "rth":
        return "formándose, cierra a las %s" % _mas(apertura, minutos)
    if doc["sesion"] == "nocturna" or doc.get("antes_apertura"):
        return "a las %s NY" % _mas(apertura, minutos)
    return "no hay" + (" (%s)" % doc["mercado_cerrado"] if "mercado_cerrado" in doc else "")


def _mas(hhmm_, minutos):
    t = comun.parse_hhmm(hhmm_)
    return comun.hhmm((dt.datetime.combine(dt.date(2000, 1, 1), t) + dt.timedelta(minutes=minutos)).time())


def _corto(k):
    return {"pdh": "del máximo de ayer", "pdl": "del mínimo de ayer", "pdc": "del cierre de ayer", "onh": "del máximo nocturno",
            "onl": "del mínimo nocturno", "orh": "del máximo de la apertura", "orl": "del mínimo de la apertura",
            "ibh": "del máximo del IB", "ibl": "del mínimo del IB", "tdh": "del máximo de hoy", "tdl": "del mínimo de hoy"}[k]


# ---------------------------------------------------------------- main

def mercado_por_defecto():
    cfg = comun.leer_json("config.json", obligatorio=False) or {}
    try:
        return comun.resolver(cfg.get("mercado") or "NQ")["codigo"]
    except KemetError:
        return "NQ"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mercado", "--simbolo", dest="mercado", help="un futuro (ES, NQ, CL, GC...) o un ticker de EE. UU. (TSLA); por defecto el de kemet/config.json, y si no hay, NQ")
    p.add_argument("--todos", action="store_true", help="los cuatro contratos")
    p.add_argument("--ib-minutos", dest="ib_minutos", type=int, choices=(15, 30, 60), help="minutos del balance inicial (60 en futuros, 15 en acciones)")
    p.add_argument("--escribir", action="store_true", help="guarda kemet/niveles.json")
    p.add_argument("--ahora", help='hora de Nueva York, "AAAA-MM-DD HH:MM"')
    p.add_argument("--offline", help="archivo JSON de Yahoo (.json o .json.gz) o la carpeta tests/fixtures/yahoo")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    ahora = comun.parse_ahora(a.ahora)
    principal = comun.resolver(a.mercado or mercado_por_defecto())["codigo"]
    codigos = list(CODIGOS) if a.todos else [principal]
    if a.todos and principal not in codigos:
        codigos.insert(0, principal)
    docs, fallos = {}, {}
    for cod in codigos:
        try:
            doc = calcular(cod, cargar(cod, a.offline), ahora, a.ib_minutos if cod == principal else None)
        except KemetError as e:
            fallos[cod] = str(e)
            continue
        if doc:
            docs[cod] = doc
        else:
            fallos[cod] = "sin sesión anterior en el histórico"
    if a.json:
        salida = docs.get(principal) if not a.todos else {"generado": comun.iso(ahora), "mercados": docs, "faltan": fallos}
        print(comun.json.dumps(salida, ensure_ascii=False, indent=1))
    else:
        for i, cod in enumerate(codigos):
            if i:
                print()
            if cod in docs:
                print("\n".join(lineas(docs[cod], cod, ahora)))
            else:
                print("%s · %s · %s" % (cod, comun.hora_doble(ahora), fallos[cod]))
    if a.escribir:
        for cod, doc in docs.items():
            nombre = "niveles.json" if cod == principal else "niveles-%s.json" % cod
            ruta = comun.escribir_json(nombre, doc)
            if not a.json:
                print("Guardado %s" % ruta)
    return 0 if docs else 1


def run():
    try:
        sys.exit(main())
    except KemetError as e:
        print("Error: %s" % e, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    run()
