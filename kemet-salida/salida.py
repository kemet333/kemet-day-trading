#!/usr/bin/env python3
"""kemet-salida: el stop y el objetivo antes de la entrada, para la ruptura del balance inicial de kemet-entrada.
Solo biblioteca estándar. Nunca envía una orden.

    python3 salida.py plan                                    # desde kemet/entrada.json: stop en el medio del IB, objetivo 1R
    python3 salida.py plan --escribir                         # y guarda kemet/plan.json
    python3 salida.py plan --stop ib-opuesto --objetivo R:2
    python3 salida.py plan --stop atr:1.5 --offline tests/fixtures/yahoo
    python3 salida.py plan --entrada 28429.75 --lado largo --ib-alto 28426 --ib-bajo 28199 --hora 10:45
    python3 salida.py show                                    # el kemet/plan.json actual
    python3 salida.py plan --mercado TSLA                     # una acción: el riesgo va en dólares por acción

Stops (todo redondeado al tick del contrato):
  ib-medio    el punto medio del IB (por defecto): donde la ruptura ha dejado de serlo
  ib-opuesto  el lado opuesto del IB: IB bajo para un largo, IB alto para un corto (más ancho, menos contratos)
  pts:X       X puntos detrás de la entrada
  precio:X    tu precio
  atr:K       K veces el ATR de 14 velas de la sesión regular hasta la vela de la entrada (con menos de 14 velas
              promedia las que hay y lo dice); necesita velas: --offline o Yahoo

Objetivos:
  R:X         X veces el riesgo desde la entrada (R:1 por defecto, R:2)
  precio:X    tu precio

Rechaza con motivo (código 1): stop del lado equivocado, objetivo detrás de la entrada, riesgo menor de 4 ticks,
entrada después de sin_entradas_despues (15:00) o a la hora de estar plano o después, y un entrada.json sin disparo
(salvo que des --entrada PRECIO --lado largo|corto, con --ib-alto y --ib-bajo si hace falta el IB).

plano_a: --plano-a, si no el de kemet/config.json, si no el del contrato (15:55 en índices, 14:25 CL, 13:25 GC).
Nunca después de la hora límite de la firma menos 5 minutos (hora_limite y hora_limite_tz del config) ni del
cierre de una sesión recortada menos 5 minutos.

Riesgo en puntos y en dólares por micro, y por mini cuando la cuenta permite minis (max_mini en config) o no hay config.
En una acción de EE. UU. (--mercado TSLA, o el entrada.json de una acción) todo va en dólares por acción: tick 0,01,
plano a las 15:55 (13:00 menos 5 minutos en un día recortado de la NYSE), sin hora límite de firma, sin micros ni minis.
Nunca imprime un P&L ni una rentabilidad esperada. Un stop es un plan, no una garantía.

Códigos de salida: plan 0 = plan, 1 = rechazado; show 0 = hay plan, 1 = no hay; 2 = error (una línea, sin traza).
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

import comun
from comun import (CME_RECORTADO, KemetError, NYSE_RECORTADO, a_ny, al_tick, de_ny, dia_negociacion, escribir_json, hhmm,
                   hora_doble, iso, leer_json, madrid_offset, num, ny_offset, parse_ahora, parse_hhmm, pts, resolver, sesion_regular,
                   ts_de_utc, usd, utc_ahora, velas, velas_cerradas)

POR_DEFECTO = {"sin_entradas_despues": "15:00"}
ATR_VELAS = 14
MIN_TICKS = 4
STOP_DEFECTO = "ib-medio"
OBJETIVO_DEFECTO = "R:1"
MARGEN_LIMITE = 5                 # minutos antes de la hora límite de la firma
NOTA_STOP = "Un stop es un plan, no una garantía: un hueco o un mercado rápido lo pueden llenar más allá."
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


class Rechazo(Exception):
    """Un plan que no se puede hacer, con el motivo. Código de salida 1."""


# ---------------------------------------------------------------- utilidades

def fecha_es(d):
    return "%s %02d/%02d/%d" % (DIAS[d.weekday()], d.day, d.month, d.year)


def nf(x):
    """1,5 / 2 / 0,5: un número sin ceros inútiles, en formato español."""
    s = num(x, 2)
    return s[:-3] if s.endswith(",00") else (s[:-1] if s.endswith("0") else s)


def dinero(x):
    """454,50 $ / 4.545 $"""
    s = usd(x, 2)
    return s.replace(",00 $", " $")


def veces(x):
    return "%s %s" % (nf(x), "vez" if abs(x - 1) < 1e-9 else "veces")


def leer_config():
    return leer_json(comun.ruta("config.json"), obligatorio=False)


def mercado_de(flag, cfg, doc=None):
    """El código del instrumento: un futuro (NQ, MNQ...) o un ticker de acciones de EE. UU. (TSLA)."""
    return resolver(flag or (doc or {}).get("mercado") or (cfg or {}).get("mercado") or "NQ")["codigo"]


def es_accion(inst):
    return inst["tipo"] == "accion"


def unidad(inst):
    """Puntos del contrato en un futuro, dólares por acción en una acción."""
    return "$" if es_accion(inst) else "puntos"


def dia_de(inst, ny):
    """El día de negociación de CME en un futuro; la fecha de Nueva York en una acción."""
    return ny.date() if es_accion(inst) else dia_negociacion(ny)


def velas_al_tick(ch, inst):
    """Una acción: los precios de Yahoo (float32) redondeados al céntimo. Un futuro queda tal cual."""
    if not es_accion(inst):
        return ch
    t = inst["tick"]
    return dict(ch, velas=[(b[0], al_tick(b[1], t), al_tick(b[2], t), al_tick(b[3], t), al_tick(b[4], t), b[5]) for b in ch["velas"]])


def numero(texto, que):
    """1.5, 1,5 o 28.426,25 (formato español) a float."""
    t = str(texto).strip()
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        raise KemetError("%s no es un número: %r" % (que, texto))


def parse_stop(texto):
    t = str(texto).strip().lower()
    if t in ("ib-medio", "ib_medio", "medio"):
        return "ib-medio", None
    if t in ("ib-opuesto", "ib_opuesto", "opuesto"):
        return "ib-opuesto", None
    m = re.match(r"^(pts|precio|atr):\s*([0-9][0-9.,]*)$", t)
    if not m:
        raise KemetError("--stop es ib-medio, ib-opuesto, pts:X, precio:X o atr:K (no %r)" % texto)
    v = numero(m.group(2), "--stop")
    if v <= 0:
        raise KemetError("--stop %s necesita un número mayor que 0" % m.group(1))
    return m.group(1), v


def parse_objetivo(texto):
    t = str(texto).strip()
    m = re.match(r"^(r|precio):\s*([0-9][0-9.,]*)$", t.lower())
    if not m:
        raise KemetError("--objetivo es R:1, R:2 o precio:X (no %r)" % texto)
    v = numero(m.group(2), "--objetivo")
    if v <= 0:
        raise KemetError("--objetivo %s necesita un número mayor que 0" % m.group(1))
    return ("R" if m.group(1) == "r" else m.group(1)), v


def hora_a_ny(hhmm_txt, zona, dia):
    """Una hora de la firma en su zona (America/Chicago, America/New_York, Europe/Madrid) pasada a hora de Nueva York."""
    t = parse_hhmm(hhmm_txt, "hora_limite")
    z = (zona or "America/New_York")
    if z in ("America/New_York", "US/Eastern", "EST", "EDT"):
        return t, None
    if z in ("America/Chicago", "US/Central", "CST", "CDT"):
        return (dt.datetime.combine(dia, t) + dt.timedelta(hours=1)).time(), None
    if z in ("Europe/Madrid", "CET", "CEST"):
        mediodia = dt.datetime.combine(dia, dt.time(12, 0)) + dt.timedelta(hours=5)
        salto = madrid_offset(mediodia) - ny_offset(mediodia)
        return (dt.datetime.combine(dia, t) - dt.timedelta(hours=salto)).time(), None
    return t, "hora_limite_tz %r no la conozco: tomo %s como hora de Nueva York" % (z, hhmm_txt)


def resolver_plano(codigo, dia, explicito, cfg, hora_entrada=None):
    """(HH:MM NY, notas). --plano-a, si no plano_a del config, si no el del contrato; nunca después de la hora límite de la
    firma menos 5 minutos ni del cierre de una sesión recortada menos 5 minutos. Rechaza una entrada a esa hora o después."""
    notas = []
    cfg = cfg or {}
    inst = resolver(codigo)
    if explicito:
        t, origen = parse_hhmm(explicito, "--plano-a"), "--plano-a"
    elif cfg.get("plano_a"):
        t, origen = parse_hhmm(cfg["plano_a"], "plano_a"), "config"
    else:
        t, origen = parse_hhmm(inst["plano"], "plano"), "accion" if es_accion(inst) else "contrato"
    o, c = sesion_regular(codigo, dia)
    cierre = a_ny(c).time()
    tope_cierre = (dt.datetime.combine(dia, cierre) - dt.timedelta(minutes=MARGEN_LIMITE)).time()
    if t > tope_cierre:
        recortados = NYSE_RECORTADO if es_accion(inst) else CME_RECORTADO
        notas.append("plano adelantado a las %s: la sesión regular cierra a las %s%s" % (
            hhmm(tope_cierre), hhmm(cierre), " (%s)" % recortados[dia.isoformat()] if dia.isoformat() in recortados else ""))
        t = tope_cierre
    if cfg.get("hora_limite") and not es_accion(inst):
        lim, aviso = hora_a_ny(cfg["hora_limite"], cfg.get("hora_limite_tz"), dia)
        if aviso:
            notas.append(aviso)
        tope = (dt.datetime.combine(dia, lim) - dt.timedelta(minutes=MARGEN_LIMITE)).time()
        if t > tope:
            notas.append("plano adelantado a las %s: la firma (%s) obliga a estar plano a las %s NY y dejamos %d minutos" % (
                hhmm(tope), cfg.get("firma") or "config", hhmm(lim), MARGEN_LIMITE))
            t = tope
    if hora_entrada and hora_entrada >= t:
        raise Rechazo("la entrada de las %s es a la hora de estar plano (%s) o después: no queda tiempo para la operación" % (
            hhmm(hora_entrada), hhmm(t)))
    return t, origen, notas


# ---------------------------------------------------------------- ATR

def atr_de(velas_, n=ATR_VELAS):
    """ATR de las últimas n velas (todas si hay menos). La primera vela de la sesión usa su propio rango."""
    trs, prev = [], None
    for b in velas_:
        tr = b[2] - b[3]
        if prev is not None:
            tr = max(tr, abs(b[2] - prev), abs(b[3] - prev))
        trs.append(tr)
        prev = b[4]
    usar = trs[-n:]
    return sum(usar) / len(usar), len(usar)


def velas_hasta_entrada(codigo, dia, barra, hora, offline, ahora_utc):
    """Las velas de la sesión regular de `dia` hasta la vela de la entrada (barra desde 1), o hasta `hora`, o las cerradas a `ahora`.
    Filtra por hora directamente en vez de pasar por comun.por_dia/regular (tardan segundos con 60 días de velas)."""
    try:
        try:
            ch = velas(codigo, "60d", "5m", offline)
        except KemetError:
            if not offline:
                raise
            ch = velas(codigo, "5d", "5m", offline)        # los fixtures de CL y GC son de 5 días
    except OSError as e:
        raise KemetError("no pude leer las velas de %s: %s" % (offline or "Yahoo", e))
    ch = velas_al_tick(ch, resolver(codigo))
    cerradas = velas_cerradas(ch, ahora_utc) if ahora_utc else ch["velas"]
    o, c = sesion_regular(codigo, dia)
    ots, cts = ts_de_utc(o), ts_de_utc(c)
    rth = [b for b in cerradas if ots <= b[0] < cts]
    if barra:
        rth = [b for b in rth if (b[0] - ots) // 300 + 1 <= barra]
    elif hora:
        fin = ts_de_utc(de_ny(dt.datetime.combine(dia, hora)))
        rth = [b for b in rth if b[0] + 300 <= fin]
    return rth


# ---------------------------------------------------------------- el cálculo

def calcular(codigo, lado, entrada, regla_stop, param_stop, regla_obj, param_obj, ib_alto=None, ib_bajo=None, atr=None, atr_n=None):
    """Stop, objetivo y riesgo al tick. Lanza Rechazo con el motivo. `codigo` es un futuro o un ticker de acciones."""
    con = resolver(codigo)
    tick = con["tick"]
    if lado not in ("largo", "corto"):
        raise KemetError("--lado es largo o corto")
    e = al_tick(entrada, tick)
    if e <= 0:
        raise Rechazo("la entrada tiene que ser un precio mayor que 0")
    signo = 1 if lado == "largo" else -1
    ib_ok = ib_alto is not None and ib_bajo is not None
    if ib_ok and ib_alto <= ib_bajo:
        raise Rechazo("el IB alto %s tiene que estar por encima del IB bajo %s" % (pts(ib_alto), pts(ib_bajo)))
    ancho = round(ib_alto - ib_bajo, 4) if ib_ok else None
    detalle = ""
    if regla_stop in ("ib-medio", "ib-opuesto") and not ib_ok:
        raise KemetError("el stop %s necesita el IB: --ib-alto y --ib-bajo, o un entrada.json con IB" % regla_stop)
    if regla_stop == "ib-medio":
        bruto = (ib_alto + ib_bajo) / 2.0
        etiqueta = "punto medio del IB"
        detalle = "(%s + %s) / 2" % (pts(ib_alto), pts(ib_bajo))
    elif regla_stop == "ib-opuesto":
        bruto = ib_bajo if lado == "largo" else ib_alto
        etiqueta = "lado opuesto del IB (%s)" % ("IB bajo" if lado == "largo" else "IB alto")
    elif regla_stop == "pts":
        bruto = e - signo * param_stop
        etiqueta = "%s %s %s de la entrada" % (pts(param_stop), unidad(con), "debajo" if lado == "largo" else "encima")
    elif regla_stop == "precio":
        bruto = param_stop
        etiqueta = "tu precio"
    elif regla_stop == "atr":
        if atr is None:
            raise KemetError("el stop atr:K necesita las velas de la sesión (--offline o Yahoo)")
        bruto = e - signo * param_stop * atr
        etiqueta = "%s x ATR(%d) %s de la entrada" % (nf(param_stop), atr_n, "debajo" if lado == "largo" else "encima")
        detalle = "ATR %s %s sobre las %d velas hasta la entrada%s" % (
            pts(round(atr, 2)), unidad(con), atr_n, " (menos de %d)" % ATR_VELAS if atr_n < ATR_VELAS else "")
    else:
        raise KemetError("regla de stop desconocida %r" % regla_stop)
    stop = al_tick(bruto, tick)
    if abs(stop - bruto) > 1e-9:
        detalle = (detalle + ", " if detalle else "") + "%s redondeado al tick" % pts(bruto)
    if (lado == "largo" and stop >= e) or (lado == "corto" and stop <= e):
        raise Rechazo("el stop %s (%s) está %s de la entrada %s: el stop de un %s va %s" % (
            pts(stop), etiqueta, "encima o al nivel" if lado == "largo" else "debajo o al nivel", pts(e), lado,
            "debajo" if lado == "largo" else "encima"))
    riesgo = round(abs(e - stop), 4)
    if riesgo < MIN_TICKS * tick - 1e-9:
        raise Rechazo("el stop está a %s %s de la entrada, menos de %d ticks (%s): demasiado pegado para el ruido normal, ánchalo" % (
            pts(riesgo), unidad(con), MIN_TICKS, pts(MIN_TICKS * tick)))
    if regla_obj == "R":
        bruto_obj = e + signo * param_obj * riesgo
        etiqueta_obj = "%s R (%s el riesgo)" % (nf(param_obj), veces(param_obj))
        detalle_obj = "%s %s %s x %s" % (pts(e), "+" if lado == "largo" else "-", nf(param_obj), pts(riesgo))
    elif regla_obj == "precio":
        bruto_obj = param_obj
        etiqueta_obj = "tu precio"
        detalle_obj = ""
    else:
        raise KemetError("regla de objetivo desconocida %r" % regla_obj)
    objetivo = al_tick(bruto_obj, tick)
    if (lado == "largo" and objetivo <= e) or (lado == "corto" and objetivo >= e):
        raise Rechazo("el objetivo %s está %s de la entrada %s: el objetivo de un %s va %s" % (
            pts(objetivo), "debajo o al nivel" if lado == "largo" else "encima o al nivel", pts(e), lado,
            "encima" if lado == "largo" else "debajo"))
    recorrido = round(abs(objetivo - e), 4)
    rr = round(recorrido / riesgo, 2)
    return {"entrada": e, "stop": stop, "etiqueta_stop": etiqueta, "detalle_stop": detalle, "objetivo": objetivo,
            "etiqueta_objetivo": etiqueta_obj, "detalle_objetivo": detalle_obj, "riesgo_pts": riesgo, "recorrido_pts": recorrido,
            "rr": rr, "riesgo_usd_micro": round(riesgo * con["punto_micro"], 2), "riesgo_usd_mini": round(riesgo * con["punto_mini"], 2),
            "riesgo_usd_accion": round(riesgo, 2) if es_accion(con) else None,
            "ib": {"alto": ib_alto, "bajo": ib_bajo, "ancho": ancho} if ib_ok else None}


# ---------------------------------------------------------------- reunir los datos de la entrada

def reunir(a, cfg):
    """Los hechos de la entrada: de kemet/entrada.json o de los flags. Devuelve (codigo, info)."""
    doc = None
    manual = a.entrada is not None
    ruta_in = comun.dada(a.de) or comun.ruta("entrada.json")
    if not manual or a.lado is None or a.ib_alto is None or a.ib_bajo is None:
        doc = leer_json(ruta_in, "ejecuta antes kemet-entrada (entrada.py check --escribir) o da --entrada, --lado, --ib-alto y --ib-bajo",
                        obligatorio=not manual)
    codigo = mercado_de(a.mercado, cfg, doc)
    ib = (doc or {}).get("ib") or {}
    if doc is not None and not manual:
        if doc.get("estado") != "disparado":
            raise Rechazo("%s dice %s (%s): planifica cuando dispare, o da --entrada PRECIO --lado largo|corto para planificar por adelantado" % (
                ruta_in, doc.get("estado") or "sin estado", doc.get("motivo") or "sin motivo"))
        if doc.get("precio") is None or doc.get("lado") not in ("largo", "corto"):
            raise KemetError("%s no tiene precio o lado" % ruta_in)
    lado = a.lado or ((doc or {}).get("lado") if not manual else None)
    if manual and lado is None:
        raise KemetError("--entrada necesita --lado largo|corto")
    if lado not in ("largo", "corto"):
        raise KemetError("--lado es largo o corto")
    entrada = a.entrada if manual else doc["precio"]
    fecha = a.fecha or (doc or {}).get("fecha")
    hora = a.hora or ((doc or {}).get("hora") if not manual else None)
    barra = a.barra if a.barra is not None else ((doc or {}).get("barra") if not manual else None)
    ib_alto = a.ib_alto if a.ib_alto is not None else ib.get("alto")
    ib_bajo = a.ib_bajo if a.ib_bajo is not None else ib.get("bajo")
    return codigo, {"lado": lado, "entrada": float(entrada), "fecha": fecha, "hora": hora, "barra": barra, "ib_alto": ib_alto,
                    "ib_bajo": ib_bajo, "ib_minutos": ib.get("minutos"), "origen": "flags" if manual else ruta_in}


def construir(a, ahora_utc):
    cfg = leer_config()
    codigo, info = reunir(a, cfg)
    regla_stop, param_stop = parse_stop(a.stop or STOP_DEFECTO)
    regla_obj, param_obj = parse_objetivo(a.objetivo or OBJETIVO_DEFECTO)
    if info["fecha"]:
        try:
            dia = dt.date.fromisoformat(str(info["fecha"]))
        except ValueError:
            raise KemetError("la fecha tiene que ser AAAA-MM-DD, no %r" % info["fecha"])
    else:
        dia = dia_de(resolver(codigo), a_ny(ahora_utc))
    hora = parse_hhmm(info["hora"], "la hora de la entrada") if info["hora"] else None
    corte = parse_hhmm((cfg or {}).get("sin_entradas_despues") or POR_DEFECTO["sin_entradas_despues"], "sin_entradas_despues")
    if hora and hora > corte:
        raise Rechazo("la entrada de las %s es posterior a las %s, la última hora para una entrada nueva (sin_entradas_despues)" % (hhmm(hora), hhmm(corte)))
    atr = atr_n = None
    if regla_stop == "atr":
        vs = velas_hasta_entrada(codigo, dia, info["barra"], hora, a.offline, ahora_utc if a.ahora else None)
        if len(vs) < 3:
            raise Rechazo("el stop atr:K necesita al menos 3 velas cerradas de la sesión regular de %s hasta la entrada y hay %d" % (dia.isoformat(), len(vs)))
        atr, atr_n = atr_de(vs)
    c = calcular(codigo, info["lado"], info["entrada"], regla_stop, param_stop, regla_obj, param_obj, info["ib_alto"], info["ib_bajo"], atr, atr_n)
    plano, origen_plano, notas = resolver_plano(codigo, dia, a.plano_a, cfg, hora)
    con = resolver(codigo)
    regla_stop_txt = regla_stop if param_stop is None else "%s:%s" % (regla_stop, nf(param_stop).replace(".", "").replace(",", "."))
    regla_obj_txt = "%s:%s" % (regla_obj, nf(param_obj).replace(".", "").replace(",", "."))
    plan = {"generado": iso(ahora_utc), "mercado": codigo, "instrumento": con["tipo"], "micro": con["micro"], "mini": con["mini"], "fecha": dia.isoformat(),
            "sistema": "ruptura-ib", "ib_minutos": info["ib_minutos"], "lado": info["lado"], "entrada": c["entrada"], "hora_entrada": hhmm(hora) if hora else None,
            "barra": info["barra"], "stop": c["stop"], "regla_stop": regla_stop_txt, "etiqueta_stop": c["etiqueta_stop"],
            "detalle_stop": c["detalle_stop"], "objetivo": c["objetivo"], "regla_objetivo": regla_obj_txt,
            "etiqueta_objetivo": c["etiqueta_objetivo"], "detalle_objetivo": c["detalle_objetivo"], "riesgo_pts": c["riesgo_pts"],
            "recorrido_pts": c["recorrido_pts"], "riesgo_usd_micro": c["riesgo_usd_micro"], "riesgo_usd_mini": c["riesgo_usd_mini"],
            "rr": c["rr"], "plano_a": hhmm(plano), "plano_a_origen": origen_plano, "sin_entradas_despues": hhmm(corte),
            "ib": c["ib"], "origen": info["origen"], "notas": notas, "nota": NOTA_STOP}
    if es_accion(con):
        plan["riesgo_usd_accion"] = c["riesgo_usd_accion"]
    if atr is not None:
        plan["atr"] = round(atr, 4)
        plan["atr_velas"] = atr_n
    hoy = dia_de(con, a_ny(ahora_utc))
    if dia != hoy:
        plan["notas"].append("este plan es del %s, no de hoy (%s)" % (fecha_es(dia), fecha_es(hoy)))
    plan["_mostrar_mini"] = (cfg is None or (cfg.get("max_mini") or 0) >= 1) and not es_accion(con)
    plan["_sin_config"] = cfg is None
    return plan


# ---------------------------------------------------------------- palabras

def describir(plan, mostrar_mini=True):
    dia = dt.date.fromisoformat(plan["fecha"])
    con = resolver(plan["mercado"])
    accion = es_accion(con)
    u = unidad(con)
    out = ["Plan de salida: %s %s, %s, ruptura del IB%s sobre velas de 5 minutos" % (
        plan["mercado"], plan["lado"], fecha_es(dia), " de %d minutos" % plan["ib_minutos"] if plan.get("ib_minutos") else "")]
    cuando = ""
    if plan.get("hora_entrada"):
        cuando = " a las %s NY" % plan["hora_entrada"]
        if plan.get("barra") is not None:
            cuando += " (barra %d)" % plan["barra"]
    out.append("  Entrada   %s%s" % (pts(plan["entrada"]), cuando))
    out.append("  Stop      %s  %s%s" % (pts(plan["stop"]), plan.get("etiqueta_stop", ""), (": " + plan["detalle_stop"]) if plan.get("detalle_stop") else ""))
    out.append("  Objetivo  %s  %s%s" % (pts(plan["objetivo"]), plan.get("etiqueta_objetivo", ""), (": " + plan["detalle_objetivo"]) if plan.get("detalle_objetivo") else ""))
    if accion:
        riesgo = "  Riesgo    %s por acción (el riesgo en dólares es ese por el número de acciones)" % dinero(plan["riesgo_pts"])
    else:
        riesgo = "  Riesgo    %s puntos, %s por micro (%s)" % (pts(plan["riesgo_pts"]), dinero(plan["riesgo_usd_micro"]), con["micro"])
        if mostrar_mini:
            riesgo += ", %s por mini (%s)" % (dinero(plan["riesgo_usd_mini"]), con["mini"])
    out.append(riesgo)
    out.append("  Recorrido %s %s hasta el objetivo, %s el riesgo" % (pts(plan.get("recorrido_pts", abs(plan["objetivo"] - plan["entrada"]))), u, veces(plan["rr"])))
    plano_utc = de_ny(dt.datetime.combine(dia, parse_hhmm(plan["plano_a"])))
    out.append("  Plano a las %s, gane o pierda: nada se queda abierto" % hora_doble(plano_utc))
    if plan.get("ib"):
        ib = plan["ib"]
        out.append("  IB        %s a %s, %s %s" % (pts(ib["bajo"]), pts(ib["alto"]), pts(ib["ancho"]), u))
    out.append("Stop y objetivo van puestos antes de la entrada. Si el precio toca el stop, fuera; el stop nunca se aleja.")
    out.append(NOTA_STOP)
    return out


def cmd_plan(a):
    ahora = parse_ahora(a.ahora) if a.ahora else utc_ahora()
    try:
        plan = construir(a, ahora)
    except Rechazo as e:
        if a.json:
            print(json.dumps({"rechazado": True, "motivo": str(e)}, ensure_ascii=False, indent=1))
        else:
            print("RECHAZADO  %s." % e)
            print("No hay plan y no se ha enviado ninguna orden. Corrige la regla, no la fuerces.")
        return 1
    mostrar_mini = plan.pop("_mostrar_mini")
    sin_config = plan.pop("_sin_config")
    ruta_out = escribir_json("plan.json", plan) if a.escribir else None
    if a.json:
        print(json.dumps(plan, ensure_ascii=False, indent=1))
        return 0
    for l in describir(plan, mostrar_mini):
        print(l)
    for n in plan["notas"]:
        print("Nota: %s." % n)
    accion = plan.get("instrumento") == "accion"
    if sin_config:
        if accion:
            print("Sin kemet/config.json: plano a las %s (una acción no tiene hora límite de firma)." % plan["plano_a"])
        else:
            print("Sin kemet/config.json: plano a las %s del contrato y sin hora límite de firma." % plan["plano_a"])
    if ruta_out:
        print("Escrito %s." % ruta_out)
    print("Siguiente: kemet-maquina lo repite sobre sesiones pasadas y kemet-tamano lo convierte en %s. No se ha enviado ninguna orden." % (
        "acciones enteras" if accion else "contratos"))
    return 0


def cmd_show(a):
    plan = leer_json(comun.ruta("plan.json"), obligatorio=False)
    if plan is None:
        print("No hay %s todavía. Hazlo con salida.py plan --escribir." % comun.ruta("plan.json"))
        return 1
    for k in ("mercado", "fecha", "lado", "entrada", "stop", "objetivo", "riesgo_pts", "rr", "plano_a"):
        if plan.get(k) is None:
            raise KemetError("a %s le falta %r: haz un plan nuevo con salida.py plan --escribir" % (comun.ruta("plan.json"), k))
    if a.json:
        print(json.dumps(plan, ensure_ascii=False, indent=1))
        return 0
    cfg = leer_config()
    for l in describir(plan, cfg is None or (cfg.get("max_mini") or 0) >= 1):
        print(l)
    hoy = dia_de(resolver(plan["mercado"]), a_ny(parse_ahora(a.ahora) if a.ahora else utc_ahora()))
    if plan["fecha"] != hoy.isoformat():
        print("Nota: este plan es del %s, no de hoy (%s)." % (fecha_es(dt.date.fromisoformat(plan["fecha"])), fecha_es(hoy)))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="kemet-salida: el stop y el objetivo antes de la entrada.")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("plan", help="calcula stop y objetivo")
    p.add_argument("--de", metavar="RUTA", help="entrada.json del que partir (por defecto kemet/entrada.json)")
    p.add_argument("--mercado", "--simbolo", dest="mercado", help="un futuro (ES, NQ, CL, GC...) o un ticker de EE. UU. (TSLA); por defecto el del entrada.json o del config, si no NQ")
    p.add_argument("--entrada", type=float, help="precio de entrada, para planificar sin entrada.json o por adelantado")
    p.add_argument("--lado", choices=["largo", "corto"])
    p.add_argument("--ib-alto", type=float, dest="ib_alto")
    p.add_argument("--ib-bajo", type=float, dest="ib_bajo")
    p.add_argument("--fecha", help="AAAA-MM-DD (por defecto la del entrada.json, o el día de negociación de hoy)")
    p.add_argument("--hora", help="hora de la entrada HH:MM NY (por defecto la del entrada.json)")
    p.add_argument("--barra", type=int, help="barra de la entrada desde las 09:30 contando desde 1 (para el ATR)")
    p.add_argument("--stop", help="ib-opuesto (por defecto), pts:X, precio:X, atr:K")
    p.add_argument("--objetivo", help="ib:0.5 (por defecto), R:1, R:2, precio:X")
    p.add_argument("--plano-a", dest="plano_a", help="HH:MM NY (por defecto plano_a del config o el del contrato)")
    p.add_argument("--offline", metavar="RUTA", help="JSON de Yahoo guardado o la carpeta tests/fixtures/yahoo, para atr:K")
    p.add_argument("--ahora", help='hora de Nueva York, por ejemplo "2026-11-11 10:45"')
    p.add_argument("--escribir", action="store_true", help="guarda kemet/plan.json")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("show", help="el plan actual")
    p.add_argument("--ahora")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"plan": cmd_plan, "show": cmd_show}[a.cmd](a)
    except KemetError as e:
        print("salida.py: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
