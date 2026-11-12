#!/usr/bin/env python3
"""Cuántos contratos caben con tu stop en tu cuenta de fondeo, con la regla Kemet para quien empieza.

Solo biblioteca estándar, sin red. Lee y escribe en `kemet/` del directorio actual (variable KEMET_DIR).

    python3 tamano.py listar                                             # firmas y cuentas que conoce
    python3 tamano.py config --firma apex --cuenta eod-pa-50 --mercado NQ  # escribe kemet/config.json
    python3 tamano.py calc --stop 18                                     # micros que caben con ese stop
    python3 tamano.py calc --firma apex --cuenta eod-pa-50 --mercado NQ --stop 18
    python3 tamano.py calc --drawdown 2000 --diario 1000 --mercado ES --stop 6   # sin firma: tus límites
    python3 tamano.py orden --escribir                                   # kemet/plan.json -> kemet/orden.json

Reglas:
- Pérdida máxima del día = la menor entre el límite diario de la firma (si lo tiene) y un cuarto del drawdown.
  Con --semaforo ambar se reduce a la mitad; con --semaforo rojo también. Con `config --perdida-dia` la fija
  el usuario, nunca por encima del límite diario de la firma.
- Riesgo por operación = pérdida máxima del día entre tres (tres fallos y paras).
- Contratos = riesgo por operación entre (stop en puntos × valor del punto del micro), con el tope de micros
  de la cuenta y con lo que queda del día (lo ya arriesgado hoy según kemet/estado/dia.json).
- Una orden de 0 contratos es un rechazo con motivo, no una orden más pequeña.
Sin señales: esto solo dice cuánto cabe. Nada se envía a ninguna plataforma.
"""
import argparse
import datetime as dt
import json
import math
import os
import sys

import comun
from comun import KemetError, num, pts, usd

AQUI = os.path.dirname(os.path.abspath(__file__))
REGLAS = os.path.join(AQUI, "reglas-de-firmas.json")
FALLOS_Y_PARAS = 3
SIN_ENTRADAS_ANTES = "09:45"
SIN_ENTRADAS_DESPUES = "15:00"
MARGEN_HORA_LIMITE = 5          # minutos: plano_a nunca después de la hora límite menos esto
FASE = {"evaluation": "evaluacion", "funded": "financiada"}
LADO_ORDEN = {"largo": "compra", "corto": "venta", "compra": "compra", "venta": "venta", "long": "compra", "short": "venta"}

# Valores por defecto cuando no hay kemet/config.json (cada tool lo dice en una línea).
DEFECTO = {"mercado": "NQ", "firma": None, "cuenta": None, "cuenta_nombre": "sin cuenta configurada", "fase": None,
           "drawdown": None, "drawdown_tipo": None, "limite_diario_firma": None, "max_micro": None, "max_mini": None,
           "hora_limite": None, "hora_limite_tz": "America/New_York", "noticias": None, "consistencia": None,
           "perdida_max_dia": None, "fallos_y_paras": FALLOS_Y_PARAS, "semaforo": "verde",
           "sin_entradas_antes": SIN_ENTRADAS_ANTES, "sin_entradas_despues": SIN_ENTRADAS_DESPUES, "plano_a": None,
           "zona_usuario": "Europe/Madrid", "papel": True, "comprobado": None, "fuente": None}


# ---------------------------------------------------------------- firmas

def cargar_reglas(path=REGLAS):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise KemetError("falta %s: la carpeta kemet-tamano está incompleta" % path)
    except ValueError as e:
        raise KemetError("%s no es JSON válido: %s" % (path, e))


def buscar(datos, firma, cuenta):
    """(firma, cuenta) del archivo de reglas, o (None, None)."""
    for f in datos.get("firms", []):
        if f["id"] == (firma or "").lower():
            for a in f["accounts"]:
                if a["id"] == (cuenta or "").lower():
                    return f, a
    return None, None


def nombre_cuenta(f, a):
    return "%s · %s" % (f["name"], a["label"].replace(" · ", " "))


# ---------------------------------------------------------------- horas

def hora_a_ny(hhmm, tz):
    """Una hora en la zona de la firma a hora de Nueva York. Chicago va una hora por detrás de NY, todo el año."""
    t = comun.parse_hhmm(hhmm, "la hora límite")
    if tz == "America/Chicago":
        return (dt.datetime.combine(dt.date(2000, 1, 1), t) + dt.timedelta(hours=1)).time()
    if tz in (None, "", "America/New_York"):
        return t
    raise KemetError("no sé convertir la zona %s a Nueva York" % tz)


def restar_min(t, minutos):
    return (dt.datetime.combine(dt.date(2000, 1, 1), t) - dt.timedelta(minutes=minutos)).time()


# ---------------------------------------------------------------- la regla Kemet

def perdida_maxima_dia(drawdown, limite_diario, semaforo="verde"):
    """La menor entre el límite diario de la firma (si lo hay) y un cuarto del drawdown; en ámbar o rojo, la mitad.
    Devuelve (perdida_max_dia, cuarto)."""
    cuarto = round(drawdown * 0.25)
    base = min(limite_diario, cuarto) if limite_diario else cuarto
    factor = 1.0 if semaforo == "verde" else 0.5
    return round(base * factor), cuarto


def micros_que_caben(riesgo_op, stop_pts, punto_micro):
    if stop_pts <= 0 or punto_micro <= 0:
        return 0
    return int(math.floor(riesgo_op / (stop_pts * punto_micro) + 1e-9))


# ---------------------------------------------------------------- config

def cargar_config(obligatorio=False):
    """kemet/config.json con los valores por defecto debajo. (config, existe)."""
    doc = comun.leer_json("config.json", "ejecuta tamano.py config", obligatorio=obligatorio)
    cfg = dict(DEFECTO)
    if doc:
        cfg.update(doc)
    return cfg, bool(doc)


def construir_config(f, a, mercado, semaforo="verde", zona="Europe/Madrid", plano_a=None, perdida_dia=None, max_micro=None):
    """El contrato de kemet/config.json a partir de una cuenta del archivo de reglas. Devuelve (config, notas)."""
    notas = []
    mercado = mercado.upper()
    if mercado not in comun.CONTRATOS:
        raise KemetError("mercado %s no soportado: %s" % (mercado, ", ".join(comun.CONTRATOS)))
    if semaforo not in ("verde", "ambar", "rojo"):
        raise KemetError("el semáforo es verde, ambar o rojo")
    drawdown, diario = a["max_loss"], a.get("daily_loss_limit")
    regla, cuarto = perdida_maxima_dia(drawdown, diario, semaforo)
    if perdida_dia is not None:
        if perdida_dia <= 0:
            raise KemetError("--perdida-dia tiene que ser mayor que 0")
        if diario and perdida_dia > diario:
            raise KemetError("--perdida-dia %s supera el límite diario de la firma (%s): la firma manda"
                             % (usd(perdida_dia), usd(diario)))
        pmd, origen = round(perdida_dia, 2), "usuario"
        if pmd == int(pmd):
            pmd = int(pmd)
        if pmd > regla:
            notas.append("pérdida máxima del día fijada por ti en %s, por encima de la regla Kemet (%s)" % (usd(pmd), usd(regla)))
        else:
            notas.append("pérdida máxima del día fijada por ti en %s (regla Kemet: %s)" % (usd(pmd), usd(regla)))
    else:
        pmd, origen = regla, "regla-kemet"
    fb = a.get("flat_by") or {}
    hora_limite, tz = fb.get("time"), fb.get("tz") or "America/New_York"
    plano = comun.parse_hhmm(plano_a, "--plano-a") if plano_a else comun.parse_hhmm(comun.CONTRATOS[mercado]["plano"])
    if hora_limite:
        tope = restar_min(hora_a_ny(hora_limite, tz), MARGEN_HORA_LIMITE)
        if plano > tope:
            notas.append("plano a las %s NY, no a las %s: la hora límite de la firma es %s %s (%s NY) y se está plano %d minutos antes"
                         % (comun.hhmm(tope), comun.hhmm(plano), hora_limite, tz, comun.hhmm(hora_a_ny(hora_limite, tz)), MARGEN_HORA_LIMITE))
            plano = tope
    mm = a.get("max_micro")
    if max_micro is not None:
        if max_micro <= 0:
            raise KemetError("--max-micro tiene que ser mayor que 0")
        if mm and max_micro > mm:
            raise KemetError("--max-micro %d supera el tope de la cuenta (%d micros): la firma manda" % (max_micro, mm))
        mm = max_micro
    if mm is None:
        notas.append("esta cuenta no publica un tope de contratos: ponlo con --max-micro según tu panel (sin él, el tope lo pone solo el riesgo)")
    cfg = {
        "mercado": mercado, "firma": f["id"], "cuenta": a["id"], "cuenta_nombre": nombre_cuenta(f, a),
        "fase": FASE.get(a.get("phase"), a.get("phase")),
        "drawdown": drawdown, "drawdown_tipo": a.get("max_loss_type"), "limite_diario_firma": diario,
        "max_micro": mm, "max_mini": a.get("max_mini"),
        "hora_limite": hora_limite, "hora_limite_tz": tz,
        "noticias": a.get("news"), "consistencia": a.get("consistency"),
        "perdida_max_dia": pmd, "perdida_max_dia_origen": origen, "fallos_y_paras": FALLOS_Y_PARAS, "semaforo": semaforo,
        "sin_entradas_antes": SIN_ENTRADAS_ANTES, "sin_entradas_despues": SIN_ENTRADAS_DESPUES, "plano_a": comun.hhmm(plano),
        "zona_usuario": zona, "papel": True, "comprobado": f.get("checked"), "fuente": f.get("source"),
    }
    if a.get("note"):
        notas.append("nota de la firma: %s" % a["note"])
    return cfg, notas


def informe_config(cfg, notas, ruta_escrita):
    riesgo_op = cfg["perdida_max_dia"] / cfg["fallos_y_paras"]
    lineas = ["Config escrita en %s" % ruta_escrita,
              "Cuenta: %s (%s) · mercado %s" % (cfg["cuenta_nombre"], cfg["fase"], cfg["mercado"]),
              "Drawdown %s (%s) · límite diario de la firma %s" % (usd(cfg["drawdown"]), cfg["drawdown_tipo"],
                                                                  usd(cfg["limite_diario_firma"]) if cfg["limite_diario_firma"] else "ninguno"),
              "Pérdida máxima del día (%s): %s · riesgo por operación: %s (tres fallos y paras)"
              % (cfg["semaforo"], usd(cfg["perdida_max_dia"]), usd(riesgo_op, 2)),
              "Tope de contratos: %s micros · %s minis" % (cfg["max_micro"] if cfg["max_micro"] else "según tu panel",
                                                           cfg["max_mini"] if cfg["max_mini"] else "según tu panel"),
              "Hora límite de la firma: %s %s · plano a las %s NY · sin entradas antes de %s ni después de %s NY"
              % (cfg["hora_limite"], cfg["hora_limite_tz"], cfg["plano_a"], cfg["sin_entradas_antes"], cfg["sin_entradas_despues"]),
              "Noticias: %s" % (cfg["noticias"] or "sin regla publicada")]
    if cfg.get("consistencia"):
        lineas.append("Consistencia: %s" % cfg["consistencia"])
    for n in notas:
        lineas.append("Nota: " + n)
    lineas.append("Simulación (papel: true) hasta que tú lo cambies en el archivo.")
    lineas.append("Reglas comprobadas el %s: confírmalas en tu panel, las firmas las cambian." % cfg["comprobado"])
    return "\n".join(lineas)


# ---------------------------------------------------------------- calc (lo que hacía el tamano.py anterior)

def calcular(drawdown, diario, cap, mercado, stop, semaforo="verde", perdida_max_dia=None):
    """Pura: cuántos micros caben. Devuelve un dict con todas las cifras."""
    mercado = mercado.upper()
    if mercado not in comun.CONTRATOS:
        raise KemetError("mercado %s no soportado: %s" % (mercado, ", ".join(comun.CONTRATOS)))
    if stop is None or stop <= 0:
        raise KemetError("hace falta --stop en puntos (mayor que 0)")
    hoy, cuarto = perdida_maxima_dia(drawdown, diario, semaforo)
    if perdida_max_dia is not None:
        hoy = perdida_max_dia
    por_op = hoy / float(FALLOS_Y_PARAS)
    c = comun.CONTRATOS[mercado]
    crudo = micros_que_caben(por_op, stop, c["punto_micro"])
    n = min(crudo, cap) if cap else crudo
    return {"mercado": mercado, "micro": c["micro"], "punto_micro": c["punto_micro"], "drawdown": drawdown,
            "limite_diario_firma": diario, "cuarto": cuarto, "semaforo": semaforo, "perdida_max_dia": hoy,
            "riesgo_por_operacion": round(por_op, 2), "stop_pts": stop, "riesgo_usd_micro": round(stop * c["punto_micro"], 2),
            "sin_tope": crudo, "tope_cuenta": cap, "contratos": n}


def informe_calc(r, cuenta_nombre, extra=None):
    lineas = ["Cuenta: %s" % cuenta_nombre,
              "Drawdown %s $ · límite diario de la firma %s · regla Kemet: 25%% del drawdown = %s $"
              % (num(r["drawdown"], 0), (num(r["limite_diario_firma"], 0) + " $") if r["limite_diario_firma"] else "ninguno", num(r["cuarto"], 0)),
              "Pérdida máxima de hoy (%s): %s $ · riesgo por operación: %s $ (tres fallos y paras)"
              % (r["semaforo"], num(r["perdida_max_dia"], 0), num(r["riesgo_por_operacion"], 0)),
              "Stop %g pts × %g $/pt del %s = %s $ por micro" % (r["stop_pts"], r["punto_micro"], r["micro"], num(r["riesgo_usd_micro"], 2)),
              "Contratos: %d %s" % (r["contratos"], r["micro"])
              + (" (tope de la cuenta: %d)" % r["tope_cuenta"] if r["tope_cuenta"] and r["sin_tope"] > r["tope_cuenta"] else "")
              + (" · no cabe ninguno: reduce el stop o espera un día verde" if r["contratos"] == 0 else "")]
    if extra:
        lineas.extend(extra)
    return "\n".join(lineas)


# ---------------------------------------------------------------- orden (desde kemet/plan.json)

def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def hoy_en_dia(dia_doc, fecha):
    """Lo ya arriesgado hoy según kemet/estado/dia.json: (riesgo_abierto, perdida_realizada, n_operaciones)."""
    if not dia_doc or str(dia_doc.get("fecha")) != fecha:
        return 0.0, 0.0, 0
    ops = dia_doc.get("operaciones") or []
    abierto = sum(_f(o.get("riesgo_usd")) or 0.0 for o in ops if o.get("cerrada") in (None, False))
    neto = sum(_f(o.get("resultado_usd")) or 0.0 for o in ops if o.get("cerrada") not in (None, False))
    return round(abierto, 2), round(max(0.0, -neto), 2), len(ops)


def dimensionar(plan, cfg, hoy, dia_doc=None, tipo="stop"):
    """Pura: un plan + la config + el día -> el tamaño (dict). `contratos` puede ser 0: entonces `rechazo` dice por qué."""
    if not isinstance(plan, dict):
        raise KemetError("kemet/plan.json no es un objeto JSON")
    if plan.get("fecha") and str(plan["fecha"]) != hoy:
        return {"rechazo": "el plan es del %s y hoy es %s en Nueva York: haz un plan nuevo con kemet-salida" % (plan["fecha"], hoy),
                "contratos": 0, "limites": []}
    lado = LADO_ORDEN.get(str(plan.get("lado") or "").lower())
    if not lado:
        raise KemetError("el plan necesita un lado (largo o corto), no %r" % plan.get("lado"))
    micro = str(plan.get("micro") or "").upper()
    mercado = comun.MICRO_A_CODIGO.get(micro) or (micro if micro in comun.CONTRATOS else None) or cfg.get("mercado") or "NQ"
    c = comun.CONTRATOS[mercado]
    micro = c["micro"]
    entrada, stop, objetivo = _f(plan.get("entrada")), _f(plan.get("stop")), _f(plan.get("objetivo"))
    for nombre, v in (("entrada", entrada), ("stop", stop), ("objetivo", objetivo)):
        if v is None or v <= 0:
            raise KemetError("el plan necesita %s (un precio mayor que 0): ejecuta kemet-salida" % nombre)
    largo = lado == "compra"
    if (largo and stop >= entrada) or (not largo and stop <= entrada):
        return {"rechazo": "el stop %s no está %s de la entrada %s en un %s" % (pts(stop), "debajo" if largo else "encima", pts(entrada), plan.get("lado")),
                "contratos": 0, "limites": []}
    if (largo and objetivo <= entrada) or (not largo and objetivo >= entrada):
        return {"rechazo": "el objetivo %s no está %s de la entrada %s" % (pts(objetivo), "encima" if largo else "debajo", pts(entrada)),
                "contratos": 0, "limites": []}
    riesgo_pts = comun.al_tick(abs(entrada - stop), c["tick"])
    if _f(plan.get("riesgo_pts")) and abs(_f(plan["riesgo_pts"]) - riesgo_pts) > c["tick"]:
        raise KemetError("el plan dice riesgo_pts %s pero entrada menos stop son %s puntos" % (pts(_f(plan["riesgo_pts"])), pts(riesgo_pts)))
    por_micro = round(riesgo_pts * c["punto_micro"], 2)
    pmd = cfg.get("perdida_max_dia")
    if not pmd:
        raise KemetError("la config no tiene perdida_max_dia: ejecuta tamano.py config")
    por_op = pmd / float(cfg.get("fallos_y_paras") or FALLOS_Y_PARAS)
    abierto, realizada, n_ops = hoy_en_dia(dia_doc, hoy)
    queda = round(pmd - abierto - realizada, 2)
    limites = [{"nombre": "riesgo por operación", "usd": round(por_op, 2), "contratos": micros_que_caben(por_op, riesgo_pts, c["punto_micro"]),
                "como": "%s / %s por micro" % (usd(por_op, 2), usd(por_micro, 2))}]
    if cfg.get("max_micro"):
        limites.append({"nombre": "tope de la cuenta", "usd": None, "contratos": int(cfg["max_micro"]), "como": "%d micros en %s" % (cfg["max_micro"], cfg.get("cuenta_nombre") or "tu cuenta")})
    limites.append({"nombre": "lo que queda del día", "usd": queda, "contratos": micros_que_caben(max(queda, 0), riesgo_pts, c["punto_micro"]),
                    "como": "%s menos %s abierto y %s perdido = %s / %s" % (usd(pmd), usd(abierto), usd(realizada), usd(queda), usd(por_micro, 2))})
    contratos = max(0, min(l["contratos"] for l in limites))
    manda = [l for l in limites if l["contratos"] == contratos][0]
    for l in limites:
        l["manda"] = l is manda
    rechazo = None
    if contratos == 0:
        if manda["nombre"] == "riesgo por operación":
            rechazo = ("un %s arriesga %s al stop (%s puntos × %s $/pt), más que tu riesgo por operación de %s. "
                       "Déjala pasar o planifica un stop más corto con kemet-salida" % (micro, usd(por_micro, 2), pts(riesgo_pts), num(c["punto_micro"], 0), usd(por_op, 2)))
        elif manda["nombre"] == "lo que queda del día":
            rechazo = ("hoy quedan %s de tu pérdida máxima del día (%s) y un %s arriesga %s: el día está hecho"
                       % (usd(max(queda, 0)), usd(pmd), micro, usd(por_micro, 2)))
        else:
            rechazo = "el tope de contratos de la cuenta es 0"
    perdida_max = round(contratos * por_micro, 2)
    minis = None
    if contratos >= 10 and cfg.get("max_mini"):
        minis = {"n": min(contratos // 10, int(cfg["max_mini"])), "micros_sueltos": contratos - 10 * min(contratos // 10, int(cfg["max_mini"])), "mini": c["mini"]}
    plano = plan.get("plano_a") or cfg.get("plano_a") or c["plano"]
    if cfg.get("plano_a") and plan.get("plano_a") and comun.parse_hhmm(cfg["plano_a"]) < comun.parse_hhmm(plan["plano_a"]):
        plano = cfg["plano_a"]
    return {"simbolo": micro, "mercado": mercado, "lado": lado, "lado_plan": plan.get("lado"), "tipo": tipo, "entrada": entrada, "stop": stop,
            "objetivo": objetivo, "riesgo_pts": riesgo_pts, "riesgo_usd_micro": por_micro, "rr": round(abs(objetivo - entrada) / riesgo_pts, 2),
            "riesgo_por_operacion": round(por_op, 2), "perdida_max_dia": pmd, "riesgo_abierto": abierto, "perdida_realizada": realizada,
            "operaciones_hoy": n_ops, "queda": queda, "limites": limites, "contratos": contratos, "manda": manda["nombre"],
            "perdida_max_usd": perdida_max, "minis": minis, "plano_a": plano, "rechazo": rechazo, "fecha": hoy,
            "hora_entrada": plan.get("hora_entrada"), "plan": plan}


def orden_bracket(s):
    """La orden propuesta con el contrato de kemet/orden.json. None si hay rechazo."""
    if s.get("rechazo") or s["contratos"] <= 0:
        return None
    por_que = "%s %s: %d %s, manda %s (%d × %s = %s al stop)" % (
        s["lado_plan"], s["mercado"], s["contratos"], s["simbolo"], s["manda"], s["contratos"], usd(s["riesgo_usd_micro"], 2), usd(s["perdida_max_usd"], 2))
    if s["minis"] and s["minis"]["n"]:
        por_que += "; equivale a %d %s%s" % (s["minis"]["n"], s["minis"]["mini"], (" y %d %s" % (s["minis"]["micros_sueltos"], s["simbolo"])) if s["minis"]["micros_sueltos"] else "")
    plan = dict(s["plan"])
    plan.update({"fecha": s["fecha"], "plano_a": s["plano_a"], "riesgo_pts": s["riesgo_pts"], "riesgo_usd_micro": s["riesgo_usd_micro"]})
    return {"simbolo": s["simbolo"], "lado": s["lado"], "contratos": s["contratos"], "tipo": s["tipo"], "precio": s["entrada"],
            "stop": s["stop"], "objetivo": s["objetivo"], "riesgo_pts": s["riesgo_pts"], "perdida_max_usd": s["perdida_max_usd"],
            "por_que": por_que, "plan": plan}


def informe_orden(s, orden, cfg, ahora_utc):
    lineas = ["ORDEN · %s · %s · %s" % (s.get("mercado") or cfg.get("mercado"), s.get("fecha", ""), comun.hora_doble(ahora_utc))]
    if s.get("rechazo") and not s.get("limites"):
        lineas.append("Sin orden: " + s["rechazo"])
        return "\n".join(lineas)
    lineas.append("%s %s a %s%s · stop %s · objetivo %s · riesgo %s pts = %s por %s · R %s"
                  % (s["lado_plan"], s["mercado"], pts(s["entrada"]), (" (%s)" % s["hora_entrada"]) if s.get("hora_entrada") else "",
                     pts(s["stop"]), pts(s["objetivo"]), pts(s["riesgo_pts"]), usd(s["riesgo_usd_micro"], 2), s["simbolo"], num(s["rr"], 2)))
    lineas.append("Cuenta: %s · pérdida máxima del día %s · riesgo por operación %s · hoy %d operaciones, %s abierto, %s perdido"
                  % (cfg.get("cuenta_nombre"), usd(s["perdida_max_dia"]), usd(s["riesgo_por_operacion"], 2), s["operaciones_hoy"], usd(s["riesgo_abierto"]), usd(s["perdida_realizada"])))
    lineas.append("")
    lineas.append("Límites (micros enteros; manda el menor):")
    for l in s["limites"]:
        lineas.append("  %-22s %-64s %4d %s%s" % (l["nombre"], l["como"], l["contratos"], s["simbolo"], "  <- manda" if l["manda"] else ""))
    lineas.append("")
    if orden is None:
        lineas.append("Sin orden: " + s["rechazo"])
        return "\n".join(lineas)
    lineas.append("Tamaño: %d %s. Pérdida al stop: %d × %s = %s." % (s["contratos"], s["simbolo"], s["contratos"], usd(s["riesgo_usd_micro"], 2), usd(s["perdida_max_usd"], 2)))
    if s["minis"] and s["minis"]["n"]:
        lineas.append("Tu cuenta permite minis: %d %s equivalen a %d %s%s (mismo riesgo, menos comisiones)."
                      % (s["contratos"], s["simbolo"], s["minis"]["n"], s["minis"]["mini"],
                         (" y %d %s" % (s["minis"]["micros_sueltos"], s["simbolo"])) if s["minis"]["micros_sueltos"] else ""))
    lineas.append("Un stop es una orden, no una promesa: en un mercado rápido se llena peor que %s." % pts(s["stop"]))
    lineas.append("")
    lineas.append("Orden bracket propuesta (nada se ha enviado a ninguna plataforma):")
    lineas.append("  %s %d %s, %s a %s, stop %s, objetivo %s" % (orden["lado"], orden["contratos"], orden["simbolo"], orden["tipo"], pts(orden["precio"]), pts(orden["stop"]), pts(orden["objetivo"])))
    lineas.append("Plano a las %s NY: lo que siga abierto se cierra (kemet-alertas avisa)." % s["plano_a"])
    lineas.append("")
    lineas.append("Siguiente: kemet-riesgo la comprueba; la pones tú en tu plataforma, con su stop.")
    return "\n".join(lineas)


# ---------------------------------------------------------------- subcomandos

def cmd_listar(a):
    datos = cargar_reglas()
    for f in datos.get("firms", []):
        print("%s: %s (comprobado %s)" % (f["id"], f["name"], f.get("checked", "?")))
        for acc in f["accounts"]:
            fb = acc.get("flat_by") or {}
            print("   %-22s %-36s %-11s drawdown %6s $ · diario %6s · %s micros · plano %s %s"
                  % (acc["id"], acc["label"], FASE.get(acc.get("phase"), acc.get("phase")), num(acc["max_loss"], 0),
                     (num(acc["daily_loss_limit"], 0) + " $") if acc.get("daily_loss_limit") else "ninguno",
                     acc.get("max_micro") if acc.get("max_micro") else "panel", fb.get("time", "?"), "Chicago" if fb.get("tz") == "America/Chicago" else "NY"))
    print("Uso: tamano.py config --firma <id> --cuenta <id> --mercado NQ")
    return 0


def cmd_config(a):
    datos = cargar_reglas()
    f, acc = buscar(datos, a.firma, a.cuenta)
    if not acc:
        raise KemetError("firma o cuenta no encontrada (%s / %s): usa tamano.py listar" % (a.firma, a.cuenta))
    cfg, notas = construir_config(f, acc, a.mercado, a.semaforo, a.zona, a.plano_a, a.perdida_dia, a.max_micro)
    if a.json:
        print(json.dumps(cfg, ensure_ascii=False, indent=1))
    if a.sin_escribir:
        if not a.json:
            print(informe_config(cfg, notas, "(no escrita: --sin-escribir)"))
        return 0
    p = comun.escribir_json("config.json", cfg)
    if not a.json:
        print(informe_config(cfg, notas, p))
    return 0


def cmd_calc(a):
    extra = []
    if a.firma or a.drawdown:
        if a.firma:
            datos = cargar_reglas()
            f, acc = buscar(datos, a.firma, a.cuenta)
            if not acc:
                raise KemetError("firma o cuenta no encontrada; usa tamano.py listar")
            nombre = "%s · %s" % (f["name"], acc["label"])
            r = calcular(acc["max_loss"], acc.get("daily_loss_limit"), acc.get("max_micro"), a.mercado or "NQ", a.stop, a.semaforo or "verde")
            fb = acc.get("flat_by") or {}
            extra.append("Hora límite: %s %s · noticias: %s" % (fb.get("time", "?"), fb.get("tz", ""), acc.get("news", "?"))
                         + (" · consistencia: %s" % acc["consistency"] if acc.get("consistency") else ""))
            extra.append("Reglas comprobadas el %s: confírmalas en tu panel, las firmas las cambian." % f.get("checked", "?"))
        else:
            nombre = "propia"
            r = calcular(a.drawdown, a.diario, a.max_micro, a.mercado or "NQ", a.stop, a.semaforo or "verde")
    else:
        cfg, existe = cargar_config()
        if not existe:
            raise KemetError("sin kemet/config.json: pasa --firma y --cuenta, o --drawdown (y --diario), o ejecuta tamano.py config")
        nombre = cfg["cuenta_nombre"]
        pmd = None
        if cfg.get("perdida_max_dia_origen") == "usuario" and not a.semaforo:
            pmd = cfg["perdida_max_dia"]
        r = calcular(cfg["drawdown"], cfg.get("limite_diario_firma"), cfg.get("max_micro"), a.mercado or cfg["mercado"], a.stop, a.semaforo or cfg.get("semaforo") or "verde", pmd)
        extra.append("Hora límite: %s %s · plano a las %s NY · noticias: %s" % (cfg.get("hora_limite"), cfg.get("hora_limite_tz"), cfg.get("plano_a"), cfg.get("noticias") or "?")
                     + (" · consistencia: %s" % cfg["consistencia"] if cfg.get("consistencia") else ""))
        extra.append("Reglas comprobadas el %s: confírmalas en tu panel, las firmas las cambian." % cfg.get("comprobado", "?"))
    if a.json:
        r["cuenta_nombre"] = nombre
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print(informe_calc(r, nombre, extra))
    return 0 if r["contratos"] > 0 else 1


def cmd_orden(a):
    ahora = comun.parse_ahora(a.ahora)
    hoy = comun.a_ny(ahora).date().isoformat()
    cfg, existe = cargar_config()
    if not existe:
        raise KemetError("sin kemet/config.json no sé tu pérdida máxima del día: ejecuta tamano.py config")
    plan = comun.leer_json(a.plan or "plan.json", "ejecuta kemet-salida primero")
    dia = comun.leer_json(comun.ruta(os.path.join("estado", "dia.json")), obligatorio=False)
    s = dimensionar(plan, cfg, hoy, dia, a.tipo)
    orden = orden_bracket(s) if s.get("limites") else None
    doc = None
    if orden:
        doc = {"generado": comun.iso(ahora), "ordenes": [orden], "cuenta": cfg.get("cuenta_nombre"), "papel": bool(cfg.get("papel", True))}
        if a.escribir:
            comun.escribir_json("orden.json", doc)
    if a.json:
        print(json.dumps({"tamano": {k: v for k, v in s.items() if k != "plan"}, "orden": doc}, ensure_ascii=False, indent=1, default=str))
    else:
        print(informe_orden(s, orden, cfg, ahora))
        if orden and a.escribir:
            print("Escrita 1 orden propuesta en %s" % comun.ruta("orden.json"))
        elif orden:
            print("No escrita: repite con --escribir para guardarla en kemet/orden.json")
    return 0 if orden else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Tamaño por operación en cuentas de fondeo (kemet-tamano).")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("listar", help="firmas y cuentas del archivo de reglas")
    p = sub.add_parser("config", help="escribe kemet/config.json desde una firma y una cuenta")
    p.add_argument("--firma", required=True)
    p.add_argument("--cuenta", required=True)
    p.add_argument("--mercado", default="NQ")
    p.add_argument("--semaforo", choices=["verde", "ambar", "rojo"], default="verde")
    p.add_argument("--zona", default="Europe/Madrid", help="tu zona horaria, solo informativa")
    p.add_argument("--plano-a", dest="plano_a", help="HH:MM NY a la que quieres estar plano (por defecto la del contrato)")
    p.add_argument("--perdida-dia", dest="perdida_dia", type=float, help="tu propia pérdida máxima del día en dólares (nunca por encima del límite diario de la firma)")
    p.add_argument("--max-micro", dest="max_micro", type=int, help="tope de micros de tu panel, si la cuenta no lo publica o el tuyo es menor")
    p.add_argument("--sin-escribir", dest="sin_escribir", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("calc", help="cuántos micros caben con tu stop")
    p.add_argument("--stop", type=float, required=True, help="stop en puntos del contrato")
    p.add_argument("--mercado")
    p.add_argument("--semaforo", choices=["verde", "ambar", "rojo"])
    p.add_argument("--firma")
    p.add_argument("--cuenta")
    p.add_argument("--drawdown", type=float)
    p.add_argument("--diario", type=float)
    p.add_argument("--max-micro", dest="max_micro", type=int)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("orden", help="una orden bracket en micros desde kemet/plan.json")
    p.add_argument("--plan", help="otro plan.json (por defecto kemet/plan.json)")
    p.add_argument("--tipo", choices=["stop", "limite", "mercado"], default="stop")
    p.add_argument("--ahora", help="hora de Nueva York, AAAA-MM-DD HH:MM")
    p.add_argument("--escribir", action="store_true")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    try:
        return {"listar": cmd_listar, "config": cmd_config, "calc": cmd_calc, "orden": cmd_orden}[a.cmd](a)
    except KemetError as e:
        print("tamano.py: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
