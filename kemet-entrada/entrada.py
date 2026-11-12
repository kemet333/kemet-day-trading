#!/usr/bin/env python3
"""kemet-entrada: la ruptura del balance inicial vela a vela, con el momento de la entrada. Solo biblioteca
estándar. Nunca envía una orden.

    python3 entrada.py check                                  # NQ (o el mercado de kemet/config.json), ahora
    python3 entrada.py check --mercado ES --ib-minutos 30 --escribir     # y guarda kemet/entrada.json
    python3 entrada.py check --ahora "2026-11-11 10:45" --offline tests/fixtures/yahoo
    python3 entrada.py watch --hasta 15:00 --cada 30          # una línea por vela cerrada, para en el disparo
    python3 entrada.py watch --ahora "2026-11-11 10:20" --offline tests/fixtures/yahoo --escribir
    python3 entrada.py check --mercado TSLA                   # una acción de EE. UU.: IB de 15 minutos, reloj de la NYSE
    python3 entrada.py watchlist --offline tests/fixtures/yahoo   # una línea por símbolo de kemet/watchlist.json

La regla (ruptura del balance inicial, versión didáctica):
  1. Balance inicial (IB): máximo y mínimo de los primeros --ib-minutos de la sesión regular (60 por defecto en
     futuros: 09:30 a 10:30 NY en índices; 15 por defecto en acciones, 09:30 a 09:45; también 30).
  2. Disparo: la primera vela de 5 minutos CERRADA después del IB que cierra por encima del IB alto (largo) o por
     debajo del IB bajo (corto). Una mecha no dispara. Un cierre exacto en el nivel no dispara. El precio de entrada es
     el cierre de esa vela y la hora, la de su cierre. Una operación al día: la primera.
  3. Sin entradas antes de sin_entradas_antes (09:45) ni después de sin_entradas_despues (15:00), de kemet/config.json.
  4. Stop y objetivo los pone kemet-salida (medio IB y 1R por defecto). Plano a plano_a (15:55 en índices).

Estados: cerrado (Globex cerrado), formando (antes de que cierre el IB), esperando (IB cerrado, ningún cierre fuera),
disparado (lado, hora de cierre de la vela, barra desde la apertura contando desde 1, precio de cierre), caducado
(sin_entradas_despues sin disparo). Solo cuentan velas cerradas: inicio + 5 min <= ahora. Igual en ES, NQ, CL y GC.

Acciones de EE. UU. (--mercado TSLA, o --simbolo): el día es la fecha de Nueva York (sin sesión nocturna), la sesión
regular va de 09:30 a 16:00 (13:00 en los días recortados de la NYSE), el reloj es el de la NYSE (fin de semana y
festivos), las distancias van en dólares por acción y los precios de Yahoo se redondean al céntimo. El resto de la
regla es la misma. `watchlist` recorre los símbolos de kemet/watchlist.json (kemet-scanner) y da una línea por cada uno.

Datos: velas de 5 minutos de Yahoo Finance (gratis, sin clave, unos 10 minutos de retraso en futuros).
--offline RUTA lee un archivo guardado o la carpeta tests/fixtures/yahoo. Sin --ahora, un archivo offline se lee a la
hora de su propio reloj (meta.regularMarketTime).

Códigos de salida: check 0 = disparado, 1 = cualquier otro estado; watch 0 = disparó, 1 = paró sin disparo;
2 = error (una línea, sin traza).
"""
import argparse
import datetime as dt
import json
import sys
import time

import comun
from comun import (CME_RECORTADO, INDICES, KemetError, NYSE_CERRADO, NYSE_RECORTADO, a_ny, al_tick, de_ny, dia_negociacion,
                   escribir_json, estado_globex, estado_nyse, hhmm, hora_doble, iso, leer_json, parse_ahora, parse_hhmm, pts,
                   resolver, sesion_regular, ts_de_utc, utc_ahora, utc_de_ts, velas, velas_cerradas)

POR_DEFECTO = {"sin_entradas_antes": "09:45", "sin_entradas_despues": "15:00"}
IB_MINUTOS = (15, 30, 60)
IB_FUTURO = 60               # minutos del IB por defecto en un futuro
IB_ACCION = 15               # y en una acción (la ruptura del rango de apertura de 15 minutos)
ESPERA_YAHOO = 60            # segundos que una vela cerrada puede tardar en llegar a Yahoo
GRACIA = 2                   # segundos después del cierre de una vela antes de pedirla
PASO = 300
SISTEMA = "ruptura-ib"
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


# ---------------------------------------------------------------- utilidades

def fecha_es(d):
    """miércoles 11/11/2026"""
    return "%s %02d/%02d/%d" % (DIAS[d.weekday()], d.day, d.month, d.year)


def leer_config():
    """kemet/config.json si existe (lo escribe tamano.py config); si no, None y cada tool usa sus valores."""
    return leer_json(comun.ruta("config.json"), obligatorio=False)


def mercado_de(flag, cfg):
    """El código del instrumento: un futuro (NQ, MNQ, ES...) o un ticker de acciones de EE. UU. (TSLA, BRK.B)."""
    return resolver(flag or (cfg or {}).get("mercado") or "NQ")["codigo"]


def es_accion(inst):
    return inst["tipo"] == "accion"


def unidad(inst):
    """Las distancias van en puntos del contrato o en dólares por acción."""
    return "$" if es_accion(inst) else "puntos"


def dia_de(inst, ny):
    """El día al que pertenece una hora de Nueva York: el de negociación de CME en un futuro, la fecha en una acción."""
    return ny.date() if es_accion(inst) else dia_negociacion(ny)


def velas_al_tick(ch, inst):
    """Una acción: Yahoo manda los precios como float32 (391,1700134...): se redondean al céntimo, que es el tick.
    Un futuro se queda tal cual (sus precios ya vienen en el tick)."""
    if not es_accion(inst):
        return ch
    t = inst["tick"]
    return dict(ch, velas=[(b[0], al_tick(b[1], t), al_tick(b[2], t), al_tick(b[3], t), al_tick(b[4], t), b[5]) for b in ch["velas"]])


def mercado_cerrado(inst, utc):
    """(cerrado, motivo). Un futuro: Globex cerrado (fin de semana, festivo). Una acción: fin de semana o festivo de la
    NYSE; fuera de 09:30 a 16:00 no está «cerrado» para esta regla, está antes o después de la sesión."""
    if es_accion(inst):
        d = a_ny(utc).date()
        clave = d.isoformat()
        if clave in NYSE_CERRADO:
            return True, NYSE_CERRADO[clave]
        if d.weekday() >= 5:
            return True, DIAS[d.weekday()]
        return False, ("sesión recortada: " + NYSE_RECORTADO[clave]) if clave in NYSE_RECORTADO else "día de sesión de la NYSE"
    eg, motivo = estado_globex(utc)
    return eg == "cerrado", motivo


def hora_cfg(cfg, clave):
    v = (cfg or {}).get(clave) or POR_DEFECTO[clave]
    return parse_hhmm(v, clave)


def proxima_apertura(utc, inst=None):
    """La próxima apertura después de `utc`, en hora de Nueva York (texto): Globex en un futuro, las 09:30 de la NYSE en una acción."""
    if inst is not None and es_accion(inst):
        ny = a_ny(utc)
        for i in range(0, 12):
            d = (ny + dt.timedelta(days=i)).date()
            cand = de_ny(dt.datetime.combine(d, dt.time(9, 30)))
            if cand > utc and estado_nyse(cand)[0] == "abierto":
                return "%s 09:30" % fecha_es(d)
        return None
    t = utc
    for _ in range(24 * 10):
        t += dt.timedelta(hours=1)
        if estado_globex(t)[0] == "abierto":
            ny = a_ny(t).replace(minute=0)
            return "%s %s" % (fecha_es(ny.date()), hhmm(ny))
    return None


def minutos_entre(a, b):
    return int(max(0, (b - a).total_seconds()) // 60)


def velas_del_dia(cerradas, o, c):
    """Las velas de la sesión regular (o <= inicio < c) sin pasar por comun.por_dia, que tarda segundos con 60 días."""
    ots, cts = ts_de_utc(o), ts_de_utc(c)
    return [b for b in cerradas if ots <= b[0] < cts]


# ---------------------------------------------------------------- la regla

def lado_de_vela(b, ib_alto, ib_bajo):
    """El lado que dispara una vela cerrada, por su CIERRE: largo si cierra por encima del IB alto, corto si cierra por
    debajo del IB bajo, None si cierra dentro o justo en un nivel. Una mecha fuera no cuenta."""
    if b[4] > ib_alto:
        return "largo"
    if b[4] < ib_bajo:
        return "corto"
    return None


def seguimiento(velas_, desde_ts, lado, stop, objetivo):
    """Qué pasó desde la vela siguiente al disparo: máximo, mínimo, último cierre y si se tocó antes el stop o el objetivo.
    El stop gana al objetivo en la misma vela."""
    tramo = [b for b in velas_ if b[0] > desde_ts]
    if not tramo:
        return None
    out = {"maximo": max(b[2] for b in tramo), "minimo": min(b[3] for b in tramo), "ultimo": tramo[-1][4],
           "ultima_vela": hhmm(a_ny(utc_de_ts(tramo[-1][0]))), "velas": len(tramo), "stop_tocado": None,
           "objetivo_tocado": None}
    for b in tramo:
        fin = hhmm(a_ny(utc_de_ts(b[0] + PASO)))
        if lado == "largo":
            if b[3] <= stop:
                out["stop_tocado"] = fin
                break
            if b[2] >= objetivo:
                out["objetivo_tocado"] = fin
                break
        else:
            if b[2] >= stop:
                out["stop_tocado"] = fin
                break
            if b[3] <= objetivo:
                out["objetivo_tocado"] = fin
                break
    return out


def evaluar(codigo, ch, ahora_utc, cfg=None, ib_minutos=None):
    """Función pura: el estado de la ruptura del IB de `codigo` (futuro o acción) a la hora `ahora_utc` con las velas de `ch`.
    `ib_minutos` None toma el del instrumento: 60 en un futuro, 15 en una acción."""
    cfg = cfg or {}
    inst = resolver(codigo)
    codigo = inst["codigo"]
    accion = es_accion(inst)
    if ib_minutos is None:
        ib_minutos = IB_ACCION if accion else IB_FUTURO
    if ib_minutos not in IB_MINUTOS:
        raise KemetError("--ib-minutos es 15, 30 o 60")
    tick = inst["tick"]
    ch = velas_al_tick(ch, inst)
    ny = a_ny(ahora_utc)
    dia = dia_de(inst, ny)
    res = {"mercado": codigo, "instrumento": inst["tipo"], "micro": inst["micro"], "unidad": unidad(inst), "fecha": dia.isoformat(),
           "sistema": SISTEMA, "ib_minutos": ib_minutos,
           "ahora": ny.strftime("%Y-%m-%d %H:%M"), "ahora_utc": iso(ahora_utc), "estado": "esperando", "motivo": "",
           "lado": None, "hora": None, "barra": None, "precio": None, "ib": None, "ultimo": None, "despues": None,
           "avisos": [], "retraso": None, "_velas": []}
    cerrado, motivo_g = mercado_cerrado(inst, ahora_utc)
    if cerrado:
        res.update(estado="cerrado", motivo="%s (%s)" % ("NYSE cerrada" if accion else "Globex cerrado", motivo_g),
                   proxima_apertura=proxima_apertura(ahora_utc, inst))
        return res
    o, c = sesion_regular(codigo, dia)
    cierre_ib = o + dt.timedelta(minutes=ib_minutos)
    desde = de_ny(dt.datetime.combine(dia, hora_cfg(cfg, "sin_entradas_antes")))
    corte = de_ny(dt.datetime.combine(dia, hora_cfg(cfg, "sin_entradas_despues")))
    if accion:
        recortado = NYSE_RECORTADO.get(dia.isoformat())
    else:
        recortado = CME_RECORTADO.get(dia.isoformat()) if codigo in INDICES else None
    if corte > c - dt.timedelta(minutes=5):
        corte = c - dt.timedelta(minutes=5)
    res.update(apertura=hhmm(a_ny(o)), cierre=hhmm(a_ny(c)), cierre_ib=hhmm(a_ny(cierre_ib)),
               sin_entradas_antes=hhmm(a_ny(desde)), sin_entradas_despues=hhmm(a_ny(corte)), recortado=recortado, reloj=motivo_g)
    if not accion:
        res["globex"] = motivo_g

    cerradas = velas_cerradas(ch, ahora_utc)
    rth = velas_del_dia(cerradas, o, c)
    res["_velas"] = rth
    res["velas_cerradas"] = len(rth)
    ots = ts_de_utc(o)

    # ¿La última vela que el reloj da por cerrada ha llegado ya a Yahoo?
    if ahora_utc >= o + dt.timedelta(seconds=PASO):
        n_cerradas = min(int((ahora_utc - o).total_seconds()) // PASO, int((c - o).total_seconds()) // PASO)
        inicio_esperado = ots + (n_cerradas - 1) * PASO
        if not rth or rth[-1][0] < inicio_esperado:
            seg = int((ahora_utc - utc_de_ts(inicio_esperado + PASO)).total_seconds())
            res["retraso"] = {"vela": hhmm(a_ny(utc_de_ts(inicio_esperado))), "segundos": seg,
                              "pendiente": seg < ESPERA_YAHOO, "cierra_ts": inicio_esperado + PASO}

    if ahora_utc < o:
        res.update(estado="formando", motivo="la sesión regular abre a las %s NY y el IB de %d minutos se cierra a las %s (faltan %d minutos para la apertura)"
                   % (hhmm(a_ny(o)), ib_minutos, hhmm(a_ny(cierre_ib)), minutos_entre(ahora_utc, o)))
        return res

    ib = comun.balance_inicial(codigo, rth, dia, ib_minutos)
    n_ib = ib_minutos // 5
    if ahora_utc < cierre_ib or ib is None:
        parcial = [b for b in rth if b[0] < ts_de_utc(cierre_ib)]
        prov = None
        if parcial:
            prov = {"alto": max(b[2] for b in parcial), "bajo": min(b[3] for b in parcial), "velas": len(parcial), "de": n_ib}
            prov["ancho"] = round(prov["alto"] - prov["bajo"], 4)
        res["ib_provisional"] = prov
        if ahora_utc < cierre_ib:
            res.update(estado="formando", motivo="IB en formación, %d de %d velas cerradas; se cierra a las %s (faltan %d minutos)"
                       % (len(parcial), n_ib, hhmm(a_ny(cierre_ib)), minutos_entre(ahora_utc, cierre_ib)))
        else:
            res.update(estado="formando", motivo="el IB tendría que estar cerrado desde las %s pero Yahoo solo ha enviado %d de %d velas: espera y repite"
                       % (hhmm(a_ny(cierre_ib)), len(parcial), n_ib))
        return res

    res["ib"] = {"alto": ib["alto"], "bajo": ib["bajo"], "ancho": ib["ancho"], "minutos": ib_minutos, "velas": ib["velas"],
                 "medio": al_tick((ib["alto"] + ib["bajo"]) / 2.0, tick)}
    disparo = None
    temprana = None
    for b in rth:
        if b[0] < ts_de_utc(cierre_ib):
            continue
        fin = b[0] + PASO
        if fin > ts_de_utc(corte):
            break
        lado = lado_de_vela(b, ib["alto"], ib["bajo"])
        if lado and fin < ts_de_utc(desde):
            temprana = (lado, b)
            continue
        if lado:
            disparo = (lado, b)
            break
    ultimo = rth[-1]
    res["ultimo"] = {"vela": hhmm(a_ny(utc_de_ts(ultimo[0]))), "cierre": ultimo[4],
                     "a_alto": round(ib["alto"] - ultimo[4], 4), "a_bajo": round(ultimo[4] - ib["bajo"], 4)}
    if temprana:
        res["avisos"].append("la vela de %s cerró %s del IB pero antes de las %s no hay entradas (sin_entradas_antes)" % (
            hhmm(a_ny(utc_de_ts(temprana[1][0]))), "por encima" if temprana[0] == "largo" else "por debajo", res["sin_entradas_antes"]))
    if disparo:
        lado, b = disparo
        precio = b[4]
        fin = utc_de_ts(b[0] + PASO)
        stop = res["ib"]["medio"]
        riesgo = abs(precio - stop)
        objetivo = al_tick(precio + riesgo if lado == "largo" else precio - riesgo, tick)
        res.update(estado="disparado", lado=lado, hora=hhmm(a_ny(fin)), barra=(b[0] - ots) // PASO + 1, precio=precio,
                   vela=hhmm(a_ny(utc_de_ts(b[0]))), minutos_desde=minutos_entre(fin, ahora_utc),
                   motivo="la vela de %s (barra %d) cerró en %s, %s del IB %s %s" % (
                       hhmm(a_ny(utc_de_ts(b[0]))), (b[0] - ots) // PASO + 1, pts(precio),
                       "por encima" if lado == "largo" else "por debajo", "alto" if lado == "largo" else "bajo",
                       pts(ib["alto"] if lado == "largo" else ib["bajo"])),
                   stop_defecto=stop, objetivo_defecto=objetivo,
                   despues=seguimiento(rth, b[0], lado, stop, objetivo) if riesgo else None)
        return res
    pend = res["retraso"]
    pendiente_util = pend and pend["pendiente"] and pend["cierra_ts"] <= ts_de_utc(corte)
    if ahora_utc >= corte and not pendiente_util:
        res.update(estado="caducado", motivo="ninguna vela cerró por encima de %s ni por debajo de %s antes de las %s NY, la última hora para una entrada nueva%s"
                   % (pts(ib["alto"]), pts(ib["bajo"]), hhmm(a_ny(corte)), " (sesión recortada: %s)" % recortado if recortado else ""))
        return res
    res.update(estado="esperando", motivo="último cierre %s (vela de %s), a %s %s del IB alto %s y a %s del IB bajo %s"
               % (pts(ultimo[4]), res["ultimo"]["vela"], pts(res["ultimo"]["a_alto"]), res["unidad"], pts(ib["alto"]),
                  pts(res["ultimo"]["a_bajo"]), pts(ib["bajo"])))
    return res


def publico(res):
    return {k: v for k, v in res.items() if not k.startswith("_")}


def doc_entrada(res, ahora_utc):
    """kemet/entrada.json: el contrato de archivo del pack."""
    ib = res.get("ib")
    return {"generado": iso(ahora_utc), "mercado": res["mercado"], "instrumento": res.get("instrumento", "futuro"), "micro": res["micro"],
            "fecha": res["fecha"], "sistema": SISTEMA, "estado": res["estado"], "motivo": res["motivo"], "lado": res.get("lado"),
            "hora": res.get("hora"), "barra": res.get("barra"), "precio": res.get("precio"),
            "ib": {"alto": ib["alto"], "bajo": ib["bajo"], "ancho": ib["ancho"], "minutos": ib["minutos"]} if ib else None,
            "avisos": res.get("avisos") or [], "comprobado": res["ahora"]}


# ---------------------------------------------------------------- palabras

ETIQUETA = {"cerrado": "CERRADO", "formando": "FORMANDO", "esperando": "ESPERANDO", "disparado": "DISPARADO", "caducado": "CADUCADO"}


def cabecera(res):
    ny = dt.datetime.strptime(res["ahora"], "%Y-%m-%d %H:%M")
    retraso = "puede ir con retraso" if res.get("instrumento") == "accion" else "unos 10 minutos de retraso"
    return "%s, %s, %s · ruptura del IB de %d minutos sobre velas de 5 minutos de Yahoo (gratis, %s)" % (
        res["mercado"], fecha_es(dt.date.fromisoformat(res["fecha"])), hora_doble(de_ny(ny)), res["ib_minutos"], retraso)


def linea_ib(res):
    ib = res["ib"]
    return "IB %s a %s: alto %s, bajo %s, %s %s (%d velas), medio %s." % (
        res["apertura"], res["cierre_ib"], pts(ib["alto"]), pts(ib["bajo"]), pts(ib["ancho"]), res.get("unidad", "puntos"), ib["velas"], pts(ib["medio"]))


def describir(res):
    out = [cabecera(res)]
    e = res["estado"]
    if res.get("ib"):
        out.append(linea_ib(res))
    elif res.get("ib_provisional"):
        p = res["ib_provisional"]
        out.append("IB provisional: alto %s, bajo %s, %s %s (%d de %d velas)." % (pts(p["alto"]), pts(p["bajo"]), pts(p["ancho"]), res.get("unidad", "puntos"), p["velas"], p["de"]))
    if e == "disparado":
        out.append("DISPARADO %s a las %s NY en %s: %s." % (res["lado"], res["hora"], pts(res["precio"]), res["motivo"]))
        d = res.get("despues")
        if res.get("minutos_desde", 0) > 5 and d:
            if d["objetivo_tocado"]:
                que = "un objetivo de 1R (%s) se habría tocado a las %s y el stop no" % (pts(res["objetivo_defecto"]), d["objetivo_tocado"])
            elif d["stop_tocado"]:
                que = "el stop en el medio del IB (%s) se habría tocado a las %s" % (pts(res["stop_defecto"]), d["stop_tocado"])
            else:
                que = "ni el medio del IB (%s) ni 1R (%s) se han tocado" % (pts(res["stop_defecto"]), pts(res["objetivo_defecto"]))
            out.append("Después del disparo (%d velas): máximo %s, mínimo %s, último cierre %s (vela de %s); con el stop y el objetivo por defecto de kemet-salida, %s." % (
                d["velas"], pts(d["maximo"]), pts(d["minimo"]), pts(d["ultimo"]), d["ultima_vela"], que))
            out.append("Han pasado %d minutos: una entrada tardía es otra operación, no esta regla." % res["minutos_desde"])
        else:
            out.append("Este es el momento de la entrada, si la tomas. No se ha enviado ninguna orden.")
        out.append("Siguiente: stop y objetivo antes de pulsar nada, con kemet-salida (salida.py plan).")
    else:
        out.append("%s  %s." % (ETIQUETA[e], res["motivo"]))
        r = res.get("retraso")
        if r and e in ("esperando", "formando"):
            if r["pendiente"]:
                out.append("La vela de %s ya cerró pero aún no está en Yahoo (%d s): cuenta cuando llegue, un minuto como mucho." % (r["vela"], r["segundos"]))
            else:
                out.append("Yahoo va con retraso: la última vela recibida no es la de %s (hace %d minutos)." % (r["vela"], r["segundos"] // 60))
        if e == "caducado":
            out.append("Hoy no hay entrada con esta regla. No se ha enviado ninguna orden.")
        if e == "esperando":
            out.append("Nada que hacer hasta que una vela cierre fuera del IB. No se ha enviado ninguna orden.")
        if res.get("proxima_apertura"):
            out.append("Próxima apertura de %s: %s NY." % ("la NYSE" if res.get("instrumento") == "accion" else "Globex", res["proxima_apertura"]))
    for av in res.get("avisos") or []:
        out.append("Aviso: %s." % av)
    if res.get("recortado"):
        out.append("Sesión recortada hoy (%s): cierre a las %s, sin entradas nuevas después de las %s." % (
            res["recortado"], res["cierre"], res["sin_entradas_despues"]))
    return out


def linea_vela(b, res):
    """Una línea de watch por vela cerrada."""
    inicio = hhmm(a_ny(utc_de_ts(b[0])))
    ib = res.get("ib")
    n_ib = res["ib_minutos"] // 5
    ots = ts_de_utc(de_ny(dt.datetime.combine(dt.date.fromisoformat(res["fecha"]), parse_hhmm(res["apertura"]))))
    barra = (b[0] - ots) // PASO + 1
    if barra <= n_ib:
        vistas = [x for x in res["_velas"] if x[0] <= b[0]]
        if barra == n_ib and ib:
            nota = "IB cerrado: %s a %s, %s %s" % (pts(ib["bajo"]), pts(ib["alto"]), pts(ib["ancho"]), res.get("unidad", "puntos"))
        else:
            nota = "IB provisional %s a %s (%d de %d)" % (pts(min(x[3] for x in vistas)), pts(max(x[2] for x in vistas)), barra, n_ib)
    elif res["estado"] == "disparado" and res["barra"] == barra:
        nota = "cierre %s del IB %s %s: DISPARADO %s a las %s en %s (barra %d)" % (
            "por encima" if res["lado"] == "largo" else "por debajo", "alto" if res["lado"] == "largo" else "bajo",
            pts(ib["alto"] if res["lado"] == "largo" else ib["bajo"]), res["lado"], res["hora"], pts(res["precio"]), barra)
    elif ib:
        if b[4] > ib["alto"] or b[4] < ib["bajo"]:
            nota = "cierre %s del IB, pero antes de las %s no hay entradas" % (
                "por encima" if b[4] > ib["alto"] else "por debajo", res["sin_entradas_antes"])
        else:
            nota = "a %s del IB alto %s y a %s del IB bajo %s" % (pts(ib["alto"] - b[4]), pts(ib["alto"]), pts(b[4] - ib["bajo"]), pts(ib["bajo"]))
    else:
        nota = ""
    return "%s  cierre %s  %s" % (inicio, pts(b[4]), nota)


# ---------------------------------------------------------------- watch

class RelojSimulado(object):
    """Un reloj que solo avanza cuando duerme: repite un día sin esperar."""

    def __init__(self, inicio):
        self.t = inicio

    def ahora(self):
        return self.t

    def dormir(self, segundos):
        self.t += dt.timedelta(seconds=max(1, int(round(segundos))))


def bucle_watch(codigo, proveedor, reloj, dormir, emitir, cfg, ib_minutos=None, cada=30, hasta=None, max_errores=5, al_disparar=None):
    """Vela a vela hasta el disparo (0), el caducado, el cierre o --hasta (1). proveedor(ahora) -> velas,
    reloj() -> UTC, dormir(segundos), emitir(línea). Duerme en tramos de `cada` segundos como mucho y vuelve a
    leer el reloj, así un portátil que se durmió se pone al día al despertar."""
    inst = resolver(codigo)
    codigo = inst["codigo"]
    impresa, errores, primera, dicho_pre = -1, 0, True, False
    siguiente = None
    while True:
        ahora = reloj()
        if siguiente is not None and ahora < siguiente:
            dormir(max(1, min(cada, (siguiente - ahora).total_seconds())))
            continue
        ny = a_ny(ahora)
        cerrado, motivo_g = mercado_cerrado(inst, ahora)
        if cerrado:
            emitir("%s: %s (%s). Nada que vigilar." % (fecha_es(ny.date()), "NYSE cerrada" if es_accion(inst) else "Globex cerrado", motivo_g))
            return 1, None
        dia = dia_de(inst, ny)
        o, c = sesion_regular(codigo, dia)
        if ahora < o + dt.timedelta(seconds=PASO):
            if not dicho_pre:
                emitir("%s NY  %s: vigilo desde el cierre de la primera vela, a las %s." % (
                    hhmm(ny), "sesión regular aún no abierta" if ahora < o else "abierta, ninguna vela cerrada",
                    hhmm(a_ny(o + dt.timedelta(seconds=PASO)))))
                dicho_pre = True
            siguiente = o + dt.timedelta(seconds=PASO + GRACIA)
            continue
        try:
            ch = proveedor(ahora)
            errores = 0
        except KemetError as e:
            errores += 1
            emitir("%s NY  no pude leer velas: %s" % (hhmm(ny), e))
            if errores >= max_errores:
                emitir("Paro tras %d lecturas fallidas seguidas." % errores)
                return 1, None
            siguiente = ahora + dt.timedelta(seconds=cada)
            continue
        res = evaluar(codigo, ch, ahora, cfg, ib_minutos)
        velas_ = res["_velas"]
        lineas = describir(res)
        if primera:
            emitir(lineas[0])
            if res.get("ib"):
                emitir(linea_ib(res))
            if velas_ and res["estado"] != "disparado":
                emitir(linea_vela(velas_[-1], res))
            impresa = velas_[-1][0] if velas_ else -1
            primera = False
        else:
            for b in velas_:
                if b[0] > impresa:
                    emitir(linea_vela(b, res))
                    impresa = b[0]
        if res["estado"] == "disparado":
            for l in lineas[1:]:
                if l.startswith("IB "):
                    continue
                emitir(l)
            if al_disparar:
                al_disparar(res, ahora)
            return 0, res
        if res["estado"] == "caducado" or ahora >= c:
            emitir("%s  %s." % (ETIQUETA[res["estado"]], res["motivo"]))
            return 1, res
        if hasta and ny >= hasta:
            emitir("Paro en --hasta %s sin disparo. %s." % (hhmm(hasta), res["motivo"]))
            return 1, res
        r = res.get("retraso")
        if r and r["pendiente"]:
            emitir("%s NY  la vela de %s aún no está en Yahoo: espero hasta %d s." % (hhmm(ny), r["vela"], ESPERA_YAHOO))
        n_actual = int((ahora - o).total_seconds()) // PASO
        atrasado = (not velas_) or (velas_[-1][0] - ts_de_utc(o)) // PASO < n_actual - 1
        if atrasado:
            espera = cada
        else:
            prox = o + dt.timedelta(seconds=(n_actual + 1) * PASO + GRACIA)
            espera = (prox - ahora).total_seconds()
        corte = de_ny(dt.datetime.combine(dia, parse_hhmm(res["sin_entradas_despues"])))
        for tope in ((de_ny(hasta) if hasta else None), corte, c):
            if tope and tope > ahora:
                espera = min(espera, (tope - ahora).total_seconds())
        siguiente = ahora + dt.timedelta(seconds=max(1, espera))


# ---------------------------------------------------------------- comandos

def leer_velas(codigo, ahora, offline):
    """Las velas de 5 minutos: 5d basta para hoy y los últimos días, 60d para repetir un día más antiguo. En una carpeta
    offline se prueba primero el archivo de 60d y luego el de 5d (los fixtures de CL y GC son de 5 días)."""
    if offline:
        try:
            return velas(codigo, "60d", "5m", offline)
        except KemetError:
            return velas(codigo, "5d", "5m", offline)
    return velas(codigo, "5d" if (utc_ahora() - ahora).days < 4 else "60d", "5m")


def cargar(codigo, a, ahora):
    """(velas, ahora). Un archivo offline sin --ahora se lee a la hora de su propio reloj."""
    ch = leer_velas(codigo, ahora or utc_ahora(), a.offline)
    if ahora is None:
        if a.offline and ch.get("ts_mercado"):
            ahora = utc_de_ts(ch["ts_mercado"])
        else:
            ahora = utc_ahora()
    return ch, ahora


def cmd_check(a):
    cfg = leer_config()
    codigo = mercado_de(a.mercado, cfg)
    ahora = parse_ahora(a.ahora) if a.ahora else None
    ch, ahora = cargar(codigo, a, ahora)
    res = evaluar(codigo, ch, ahora, cfg, a.ib_minutos)
    ruta_out = None
    if a.escribir:
        ruta_out = escribir_json("entrada.json", doc_entrada(res, ahora))
    if a.json:
        print(json.dumps(publico(res), ensure_ascii=False, indent=1))
    else:
        for l in describir(res):
            print(l)
        if cfg is None:
            print("Sin kemet/config.json: valores por defecto (entradas de %s a %s NY)." % (POR_DEFECTO["sin_entradas_antes"], POR_DEFECTO["sin_entradas_despues"]))
        if ruta_out:
            print("Escrito %s (estado %s)." % (ruta_out, res["estado"]))
    return 0 if res["estado"] == "disparado" else 1


def cmd_watch(a):
    cfg = leer_config()
    codigo = mercado_de(a.mercado, cfg)
    if a.cada <= 0:
        raise KemetError("--cada tiene que ser mayor que 0 segundos")
    inicio = parse_ahora(a.ahora) if a.ahora else None
    if a.offline or inicio is not None:
        if inicio is None:
            inicio = cargar(codigo, a, None)[1]
        reloj = RelojSimulado(inicio)
        fn_ahora, fn_dormir = reloj.ahora, reloj.dormir
    else:
        fn_ahora, fn_dormir = utc_ahora, time.sleep

    def proveedor(ahora):
        return leer_velas(codigo, ahora, a.offline)

    hasta = None
    if a.hasta:
        hasta = dt.datetime.combine(a_ny(fn_ahora()).date(), parse_hhmm(a.hasta, "--hasta"))

    def al_disparar(res, ahora):
        if a.escribir:
            print("Escrito %s." % escribir_json("entrada.json", doc_entrada(res, ahora)), flush=True)
        else:
            print("No se ha guardado nada (sin --escribir): repite con entrada.py check --escribir antes de kemet-salida.", flush=True)

    def emitir(l):
        print(l, flush=True)

    if cfg is None:
        emitir("Sin kemet/config.json: valores por defecto (entradas de %s a %s NY)." % (POR_DEFECTO["sin_entradas_antes"], POR_DEFECTO["sin_entradas_despues"]))
    codigo_salida, _ = bucle_watch(codigo, proveedor, fn_ahora, fn_dormir, emitir, cfg, ib_minutos=a.ib_minutos, cada=a.cada,
                                   hasta=hasta, al_disparar=al_disparar)
    return codigo_salida


def linea_watchlist(res):
    """Una línea por símbolo de la watchlist."""
    s = res["mercado"]
    e = res["estado"]
    u = res.get("unidad", "puntos")
    ib = res.get("ib")
    if e == "disparado":
        return "%-6s DISPARADO %s a las %s NY en %s (vela de %s, barra %d); IB de %d min %s a %s; stop por defecto %s, objetivo 1R %s." % (
            s, res["lado"], res["hora"], pts(res["precio"]), res["vela"], res["barra"], res["ib_minutos"], pts(ib["bajo"]), pts(ib["alto"]),
            pts(res["stop_defecto"]), pts(res["objetivo_defecto"]))
    if e == "esperando" and ib and res.get("ultimo"):
        return "%-6s ESPERANDO  último %s (vela de %s), a %s %s del IB alto %s y a %s del IB bajo %s (IB de %d min)." % (
            s, pts(res["ultimo"]["cierre"]), res["ultimo"]["vela"], pts(res["ultimo"]["a_alto"]), u, pts(ib["alto"]),
            pts(res["ultimo"]["a_bajo"]), pts(ib["bajo"]), res["ib_minutos"])
    return "%-6s %s  %s." % (s, ETIQUETA[e], res["motivo"])


def cmd_watchlist(a):
    cfg = leer_config()
    ruta_w = a.watchlist or comun.ruta("watchlist.json")
    doc = leer_json(ruta_w, obligatorio=False)
    aciertos = (doc or {}).get("aciertos") if isinstance(doc, dict) else None
    if not doc:
        print("No hay watchlist en %s: kemet-scanner la escribe (scanner.py diario, orb o futuros)." % ruta_w)
        return 1
    if not isinstance(aciertos, list) or not aciertos:
        print("La watchlist %s no tiene aciertos: nada que vigilar. Vuelve a pasar kemet-scanner." % ruta_w)
        return 1
    simbolos = []
    for ac in aciertos:
        s = str((ac or {}).get("simbolo") or "").strip().upper() if isinstance(ac, dict) else str(ac or "").strip().upper()
        if s and s not in simbolos:
            simbolos.append(s)
    ahora_fijo = parse_ahora(a.ahora) if a.ahora else None
    resultados, lineas, disparos, ahora_ref = [], [], 0, ahora_fijo
    for s in simbolos:
        try:
            codigo = resolver(s)["codigo"]
            ch, ahora_s = cargar(codigo, a, ahora_fijo)
            ahora_ref = ahora_ref or ahora_s
            res = evaluar(codigo, ch, ahora_s, cfg, a.ib_minutos)
            resultados.append(publico(res))
            lineas.append(linea_watchlist(res))
            disparos += res["estado"] == "disparado"
        except KemetError as e:
            resultados.append({"mercado": s, "estado": "error", "motivo": str(e)})
            lineas.append("%-6s error: %s." % (s, e))
    ahora_ref = ahora_ref or utc_ahora()
    if a.json:
        print(json.dumps({"generado": iso(ahora_ref), "watchlist": ruta_w, "modo": doc.get("modo"), "generada": doc.get("generado"),
                          "simbolos": resultados, "disparados": disparos}, ensure_ascii=False, indent=1))
        return 0 if disparos else 1
    print("Watchlist %s (modo %s, %d símbolo%s), %s · ruptura del balance inicial, 60 min en futuros y 15 en acciones salvo --ib-minutos" % (
        ruta_w, doc.get("modo") or "sin modo", len(simbolos), "" if len(simbolos) == 1 else "s", hora_doble(ahora_ref)))
    for l in lineas:
        print(l)
    if cfg is None:
        print("Sin kemet/config.json: valores por defecto (entradas de %s a %s NY)." % (POR_DEFECTO["sin_entradas_antes"], POR_DEFECTO["sin_entradas_despues"]))
    print("%s No se ha enviado ninguna orden. Para seguir uno: entrada.py check --mercado SIMBOLO --escribir y después kemet-salida." % (
        "%d disparo%s." % (disparos, "" if disparos == 1 else "s") if disparos else "Ningún disparo."))
    return 0 if disparos else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="kemet-entrada: la ruptura del balance inicial vela a vela.")
    sub = ap.add_subparsers(dest="cmd")

    def comunes(p):
        p.add_argument("--mercado", "--simbolo", dest="mercado", help="un futuro (ES, NQ, CL, GC...) o un ticker de EE. UU. (TSLA); por defecto el de kemet/config.json, si no NQ")
        p.add_argument("--ib-minutos", dest="ib_minutos", type=int, choices=IB_MINUTOS, default=None, help="minutos del balance inicial (60 en futuros, 15 en acciones)")
        p.add_argument("--ahora", help='hora de Nueva York, por ejemplo "2026-11-11 10:45"')
        p.add_argument("--offline", metavar="RUTA", help="JSON de Yahoo guardado (.json o .json.gz) o la carpeta tests/fixtures/yahoo")
        p.add_argument("--escribir", action="store_true", help="guarda kemet/entrada.json")

    p = sub.add_parser("check", help="el estado de la ruptura ahora mismo")
    comunes(p)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("watch", help="vela a vela hasta el disparo o el caducado")
    comunes(p)
    p.add_argument("--cada", type=float, default=30, help="segundos entre lecturas mientras Yahoo va por detrás")
    p.add_argument("--hasta", help="parar a esta hora de Nueva York (HH:MM)")
    p = sub.add_parser("watchlist", help="el estado de la ruptura en cada símbolo de kemet/watchlist.json")
    p.add_argument("--watchlist", metavar="RUTA", help="por defecto kemet/watchlist.json (la escribe kemet-scanner)")
    p.add_argument("--ib-minutos", dest="ib_minutos", type=int, choices=IB_MINUTOS, default=None, help="minutos del balance inicial (60 en futuros, 15 en acciones)")
    p.add_argument("--ahora", help='hora de Nueva York, por ejemplo "2026-11-11 10:45"')
    p.add_argument("--offline", metavar="RUTA", help="la carpeta con un JSON de Yahoo por símbolo (tests/fixtures/yahoo)")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"check": cmd_check, "watch": cmd_watch, "watchlist": cmd_watchlist}[a.cmd](a)
    except KemetError as e:
        print("entrada.py: %s" % e, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("entrada.py: parado.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
