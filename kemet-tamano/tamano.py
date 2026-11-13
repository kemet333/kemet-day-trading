#!/usr/bin/env python3
"""Cuántos contratos caben con tu stop en tu cuenta de fondeo, con la regla Kemet para quien empieza.

Solo biblioteca estándar, sin red. Lee y escribe en `kemet/` del directorio actual (variable KEMET_DIR).

    python3 tamano.py listar                                             # firmas y cuentas que conoce
    python3 tamano.py config --firma apex --cuenta eod-pa-50 --mercado NQ  # escribe kemet/config.json
    python3 tamano.py calc --stop 18                                     # micros que caben con ese stop
    python3 tamano.py calc --firma apex --cuenta eod-pa-50 --mercado NQ --stop 18
    python3 tamano.py calc --drawdown 2000 --diario 1000 --mercado ES --stop 6   # sin firma: tus límites
    python3 tamano.py orden --escribir                                   # kemet/plan.json -> kemet/orden.json

Cuenta propia (acciones de EE. UU., o futuros sin firma):

    python3 tamano.py config --propia --presupuesto 5000 --max-perdida-operacion 50 --max-perdida-dia 150 --mercado TSLA
    python3 tamano.py calc --stop 3.57 --entrada 393.08                  # acciones enteras que caben (TSLA del config)
    python3 tamano.py calc --stop 3.57 --mercado TSLA --presupuesto 5000 --max-perdida-operacion 50   # sin config
    python3 tamano.py orden --escribir                                   # plan de una acción -> orden bracket (formato Alpaca)
    python3 tamano.py orden --limite 393.00 --escribir                   # una orden límite a ese precio

Reglas:
- Pérdida máxima del día = la menor entre el límite diario de la firma (si lo tiene) y un cuarto del drawdown.
  Con --semaforo ambar se reduce a la mitad; con --semaforo rojo también. Con `config --perdida-dia` la fija
  el usuario, nunca por encima del límite diario de la firma.
- Riesgo por operación = pérdida máxima del día entre tres (tres fallos y paras).
- Contratos = riesgo por operación entre (stop en puntos × valor del punto del micro), con el tope de micros
  de la cuenta y con lo que queda del día (lo ya arriesgado hoy según kemet/estado/dia.json).
- Acciones (cuenta propia) = el menor de: riesgo por operación / riesgo por acción, max_posicion_pct × presupuesto /
  entrada, max_orden_usd / entrada, efectivo disponible (kemet/portfolio.json si existe, si no el presupuesto menos
  el colchón) / entrada, y lo que queda del día. Un precio fresco en kemet/precios.json (menos de 15 minutos) por
  encima de la entrada de un largo sube el riesgo medido y baja las acciones; nunca al revés.
- Una orden de 0 contratos (o 0 acciones) es un rechazo con motivo, no una orden más pequeña.
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
LADO_ALPACA = {"compra": "buy", "venta": "sell"}
PRECIO_FRESCO_MIN = 15          # minutos: un precio de kemet/precios.json más viejo no cuenta
SEC_USER_AGENT = "Nombre correo@ejemplo.com"

# Valores por defecto cuando no hay kemet/config.json (cada tool lo dice en una línea).
DEFECTO = {"mercado": "NQ", "firma": None, "cuenta": None, "cuenta_nombre": "sin cuenta configurada", "fase": None,
           "drawdown": None, "drawdown_tipo": None, "limite_diario_firma": None, "max_micro": None, "max_mini": None,
           "hora_limite": None, "hora_limite_tz": "America/New_York", "noticias": None, "consistencia": None,
           "perdida_max_dia": None, "fallos_y_paras": FALLOS_Y_PARAS, "semaforo": "verde",
           "sin_entradas_antes": SIN_ENTRADAS_ANTES, "sin_entradas_despues": SIN_ENTRADAS_DESPUES, "plano_a": None,
           "zona_usuario": "Europe/Madrid", "papel": True, "comprobado": None, "fuente": None}
# La cuenta propia: los topes del pack de referencia, en dólares.
PROPIA = {"max_posicion_pct": 75, "max_orden_usd": 4000, "min_orden_usd": 5, "efectivo_pct": 10,
          "permitir_cortos": False, "permitir_margen": False, "permitir_opciones": False, "bloqueados": []}


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
        pmd, origen = round(perdida_dia * (1.0 if semaforo == "verde" else 0.5), 2), "usuario"
        if semaforo != "verde":
            notas.append("semáforo %s: tu pérdida del día de %s baja a la mitad, %s" % (semaforo, usd(perdida_dia), usd(pmd)))
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


# ---------------------------------------------------------------- la cuenta propia

def es_propia(cfg):
    return (cfg or {}).get("tipo_cuenta") == "propia" or (cfg or {}).get("cuenta") == "propia"


def _entero_si_cabe(x):
    x = round(float(x), 2)
    return int(x) if x == int(x) else x


def construir_config_propia(presupuesto, max_perdida_operacion, max_perdida_dia, mercado="NQ", max_posicion_pct=None, max_orden=None,
                            min_orden=None, efectivo_pct=None, semaforo="verde", zona="Europe/Madrid", plano_a=None, sec_user_agent=None,
                            permitir_cortos=False, max_micro=None):
    """El contrato de kemet/config.json para una cuenta propia (acciones de EE. UU., o futuros sin firma). (config, notas)."""
    notas = []
    inst = comun.resolver(mercado)
    if semaforo not in ("verde", "ambar", "rojo"):
        raise KemetError("el semáforo es verde, ambar o rojo")
    for nombre, v in (("--presupuesto", presupuesto), ("--max-perdida-operacion", max_perdida_operacion), ("--max-perdida-dia", max_perdida_dia)):
        if v is None or v <= 0:
            raise KemetError("%s tiene que ser mayor que 0" % nombre)
    if max_perdida_dia < max_perdida_operacion:
        raise KemetError("--max-perdida-dia (%s) no puede ser menor que --max-perdida-operacion (%s)" % (usd(max_perdida_dia), usd(max_perdida_operacion)))
    pct = PROPIA["max_posicion_pct"] if max_posicion_pct is None else max_posicion_pct
    efe = PROPIA["efectivo_pct"] if efectivo_pct is None else efectivo_pct
    if not 0 < pct <= 100:
        raise KemetError("--max-posicion-pct va de 1 a 100")
    if not 0 <= efe < 100:
        raise KemetError("--efectivo-pct va de 0 a 99")
    mo = PROPIA["max_orden_usd"] if max_orden is None else max_orden
    mi = PROPIA["min_orden_usd"] if min_orden is None else min_orden
    if mo <= 0 or mi < 0 or mi > mo:
        raise KemetError("--max-orden tiene que ser mayor que 0 y --min-orden entre 0 y --max-orden")
    if max_micro is not None and max_micro <= 0:
        raise KemetError("--max-micro tiene que ser mayor que 0")
    factor = 1.0 if semaforo == "verde" else 0.5
    pmd, por_op = _entero_si_cabe(max_perdida_dia * factor), _entero_si_cabe(max_perdida_operacion * factor)
    if factor < 1:
        notas.append("semáforo %s: pérdida máxima del día %s y riesgo por operación %s, la mitad de lo que has dado" % (semaforo, usd(pmd), usd(por_op, 2)))
    plano = comun.parse_hhmm(plano_a, "--plano-a") if plano_a else comun.parse_hhmm(inst["plano"])
    cfg = {
        "mercado": inst["codigo"], "tipo_cuenta": "propia", "firma": None, "cuenta": "propia",
        "cuenta_nombre": "Cuenta propia · %s" % usd(presupuesto), "presupuesto": _entero_si_cabe(presupuesto),
        "efectivo_pct": _entero_si_cabe(efe), "max_posicion_pct": _entero_si_cabe(pct), "max_orden_usd": _entero_si_cabe(mo), "min_orden_usd": _entero_si_cabe(mi),
        "perdida_max_dia": pmd, "riesgo_por_operacion": por_op, "fallos_y_paras": FALLOS_Y_PARAS, "semaforo": semaforo,
        "max_micro": max_micro, "hora_limite": None, "hora_limite_tz": None,
        "sin_entradas_antes": SIN_ENTRADAS_ANTES, "sin_entradas_despues": SIN_ENTRADAS_DESPUES, "plano_a": comun.hhmm(plano),
        "zona_usuario": zona, "papel": True, "permitir_cortos": bool(permitir_cortos), "permitir_margen": False, "permitir_opciones": False,
        "bloqueados": [], "sec_user_agent": sec_user_agent or os.environ.get("SEC_USER_AGENT") or SEC_USER_AGENT,
    }
    if cfg["sec_user_agent"] == SEC_USER_AGENT:
        notas.append("sec_user_agent es un ejemplo: pon tu nombre y tu correo (lo piden EDGAR y el House Clerk) o la variable SEC_USER_AGENT")
    if inst["tipo"] == "futuro" and max_micro is None:
        notas.append("futuros sin firma: el tope de micros lo pone solo el riesgo; con --max-micro fijas el de tu plataforma")
    return cfg, notas


def informe_config_propia(cfg, notas, ruta_escrita):
    inst = comun.resolver(cfg["mercado"])
    lineas = ["Config escrita en %s" % ruta_escrita,
              "Cuenta: %s · mercado %s (%s)" % (cfg["cuenta_nombre"], cfg["mercado"], "acción" if inst["tipo"] == "accion" else "futuro, sin firma"),
              "Pérdida máxima del día (%s): %s · riesgo por operación: %s · como mucho %d operaciones al día"
              % (cfg["semaforo"], usd(cfg["perdida_max_dia"]), usd(cfg["riesgo_por_operacion"], 2), cfg["fallos_y_paras"]),
              "Topes: posición %s %% del presupuesto (%s) · orden entre %s y %s · colchón de efectivo %s %% (%s)"
              % (num(cfg["max_posicion_pct"], 0), usd(cfg["presupuesto"] * cfg["max_posicion_pct"] / 100.0), usd(cfg["min_orden_usd"]), usd(cfg["max_orden_usd"]),
                 num(cfg["efectivo_pct"], 0), usd(cfg["presupuesto"] * cfg["efectivo_pct"] / 100.0)),
              "Sin hora límite de firma · plano a las %s NY · sin entradas antes de %s ni después de %s NY"
              % (cfg["plano_a"], cfg["sin_entradas_antes"], cfg["sin_entradas_despues"]),
              "Cortos: %s · margen: no · opciones: no · bloqueados: %s" % ("permitidos" if cfg["permitir_cortos"] else "no", ", ".join(cfg["bloqueados"]) or "ninguno")]
    for n in notas:
        lineas.append("Nota: " + n)
    lineas.append("Simulación (papel: true) hasta que tú lo cambies en el archivo.")
    return "\n".join(lineas)


def riesgo_por_operacion_de(cfg):
    """El riesgo por operación de la config: el explícito de la cuenta propia o la pérdida del día entre fallos_y_paras."""
    if cfg.get("riesgo_por_operacion"):
        return float(cfg["riesgo_por_operacion"])
    pmd = cfg.get("perdida_max_dia")
    if not pmd:
        raise KemetError("la config no tiene perdida_max_dia: ejecuta tamano.py config")
    return pmd / float(cfg.get("fallos_y_paras") or FALLOS_Y_PARAS)


def acciones_que_caben(usd_, por_accion):
    """Acciones enteras que caben en usd_ a por_accion, en céntimos exactos."""
    u, p = int(round(float(usd_) * 100)), int(round(float(por_accion) * 100))
    if p <= 0 or u <= 0:
        return 0
    return u // p


def efectivo_disponible(cfg, cartera=None):
    """(efectivo disponible para comprar, cómo se ha calculado). El presupuesto menos el colchón, o el efectivo de
    kemet/portfolio.json menos el colchón si es menor."""
    presupuesto = float(cfg.get("presupuesto") or 0)
    colchon = round(presupuesto * float(cfg.get("efectivo_pct") or 0) / 100.0, 2)
    disponible = presupuesto - colchon
    como = "%s menos %s de colchón" % (usd(presupuesto), usd(colchon))
    efectivo = _f((cartera or {}).get("efectivo")) if isinstance(cartera, dict) else None
    if efectivo is not None and efectivo - colchon < disponible - 0.005:
        disponible = efectivo - colchon
        como = "%s de efectivo en kemet/portfolio.json menos %s de colchón" % (usd(efectivo), usd(colchon))
    return max(round(disponible, 2), 0.0), como


def posicion_en_cartera(cartera, simbolo):
    """Acciones que ya tienes de ese símbolo según kemet/portfolio.json (0 si no hay)."""
    n = 0.0
    posiciones = cartera.get("posiciones") if isinstance(cartera, dict) else None
    for p in posiciones or []:
        if isinstance(p, dict) and str(p.get("simbolo") or p.get("symbol") or "").upper() == simbolo:
            n += _f(p.get("cantidad", p.get("qty"))) or 0.0
    return n


def limites_accion(cfg, simbolo, ref, riesgo_por_accion, queda=None, cartera=None):
    """Los límites en acciones enteras de la cuenta propia. Cada uno: nombre, usd, acciones, como."""
    por_op = riesgo_por_operacion_de(cfg)
    limites = [{"nombre": "riesgo por operación", "usd": round(por_op, 2), "acciones": acciones_que_caben(por_op, riesgo_por_accion),
                "como": "%s / %s por acción" % (usd(por_op, 2), usd(riesgo_por_accion, 2))}]
    presupuesto = float(cfg.get("presupuesto") or 0)
    if presupuesto and cfg.get("max_posicion_pct"):
        tope = round(presupuesto * float(cfg["max_posicion_pct"]) / 100.0, 2)
        ya = posicion_en_cartera(cartera, simbolo)
        libre = max(tope - ya * ref, 0.0)
        como = "%s %% de %s = %s / %s" % (num(float(cfg["max_posicion_pct"]), 0), usd(presupuesto), usd(tope), usd(ref, 2))
        if ya:
            como = "%s %% de %s = %s, menos %s acciones que ya tienes = %s / %s" % (num(float(cfg["max_posicion_pct"]), 0), usd(presupuesto), usd(tope), num(ya, 0), usd(libre), usd(ref, 2))
        limites.append({"nombre": "posición máxima", "usd": round(libre, 2), "acciones": acciones_que_caben(libre, ref), "como": como})
    if cfg.get("max_orden_usd"):
        limites.append({"nombre": "orden máxima", "usd": float(cfg["max_orden_usd"]), "acciones": acciones_que_caben(float(cfg["max_orden_usd"]), ref),
                        "como": "%s / %s" % (usd(float(cfg["max_orden_usd"])), usd(ref, 2))})
    if presupuesto:
        disponible, como = efectivo_disponible(cfg, cartera)
        limites.append({"nombre": "efectivo", "usd": disponible, "acciones": acciones_que_caben(disponible, ref), "como": "%s = %s / %s" % (como, usd(disponible), usd(ref, 2))})
    if queda is not None:
        limites.append({"nombre": "lo que queda del día", "usd": queda["queda"], "acciones": acciones_que_caben(max(queda["queda"], 0), riesgo_por_accion),
                        "como": "%s menos %s abierto y %s perdido = %s / %s" % (usd(queda["pmd"]), usd(queda["abierto"]), usd(queda["realizada"]), usd(queda["queda"]), usd(riesgo_por_accion, 2))})
    n = max(0, min(l["acciones"] for l in limites))
    manda = [l for l in limites if l["acciones"] == n][0]
    for l in limites:
        l["manda"] = l is manda
        l["contratos"] = l["acciones"]
    return limites, n, manda


def precio_fresco(doc, simbolo, ahora_utc, minutos=PRECIO_FRESCO_MIN):
    """(precio, leído hace N minutos) del símbolo en kemet/precios.json si tiene menos de `minutos`; si no, (None, None).
    Acepta el formato de alertas.py ({"precios": {SIM: {"precio", "leido"…}}}) y un número suelto por símbolo con `generado`."""
    if not isinstance(doc, dict):
        return None, None
    q = (doc.get("precios") or {}).get(simbolo)
    if q is None:
        return None, None
    precio = _f(q.get("precio")) if isinstance(q, dict) else _f(q)
    if not precio or precio <= 0:
        return None, None
    cuando = None
    for texto in ((q.get("leido"), q.get("generado")) if isinstance(q, dict) else ()) + (doc.get("generado"),):
        if texto:
            try:
                cuando = dt.datetime.strptime(str(texto), "%Y-%m-%dT%H:%M:%SZ")
                break
            except ValueError:
                continue
    if cuando is None:
        return None, None
    edad = (ahora_utc - cuando).total_seconds()
    if -60 <= edad <= minutos * 60:
        return precio, int(max(edad, 0) // 60)
    return None, None


# ---------------------------------------------------------------- calc (lo que hacía el tamano.py anterior)

def calcular(drawdown, diario, cap, mercado, stop, semaforo="verde", perdida_max_dia=None, cap_mini=None):
    """Pura: cuántos micros caben. Devuelve un dict con todas las cifras. `perdida_max_dia` es la que fijó el usuario: manda
    sobre la regla Kemet y también baja a la mitad en ámbar o rojo. ZN y ZB no tienen micro: cuentan con el tope de minis."""
    mercado = mercado.upper()
    if mercado not in comun.CONTRATOS:
        raise KemetError("mercado %s no soportado: %s" % (mercado, ", ".join(comun.CONTRATOS)))
    c = comun.CONTRATOS[mercado]
    if stop is None or not stop == stop or stop <= 0:
        raise KemetError("hace falta --stop en puntos (mayor que 0)")
    if stop < c["tick"] - 1e-12:
        raise KemetError("un stop de %s puntos es menos de un tick de %s (%s): no existe en la plataforma" % (pts(stop), mercado, pts(c["tick"])))
    hoy, cuarto = perdida_maxima_dia(drawdown, diario, semaforo)
    if perdida_max_dia is not None:
        hoy = round(perdida_max_dia * (1.0 if semaforo == "verde" else 0.5), 2)
    por_op = hoy / float(FALLOS_Y_PARAS)
    crudo = micros_que_caben(por_op, stop, c["punto_micro"])
    if comun.sin_micro(mercado):
        cap = cap_mini
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
    if not r["tope_cuenta"]:
        lineas.append("AVISO: esta cuenta no publica tope de contratos en el archivo de reglas: mira el de tu panel y pásalo con --max-micro")
    if extra:
        lineas.extend(extra)
    return "\n".join(lineas)


def calcular_propia(cfg, mercado, stop, entrada=None, semaforo=None, cartera=None):
    """Pura: cuántas acciones (o micros, en un futuro sin firma) caben en una cuenta propia. Devuelve un dict."""
    inst = comun.resolver(mercado)
    if stop is None or stop <= 0:
        raise KemetError("hace falta --stop (%s, mayor que 0)" % ("en dólares por acción" if inst["tipo"] == "accion" else "en puntos"))
    factor = 0.5 if semaforo in ("ambar", "rojo") and cfg.get("semaforo", "verde") == "verde" else 1.0
    pmd = float(cfg["perdida_max_dia"]) * factor
    por_op = riesgo_por_operacion_de(cfg) * factor
    c = dict(cfg, perdida_max_dia=pmd, riesgo_por_operacion=por_op)
    r = {"mercado": inst["codigo"], "tipo": inst["tipo"], "semaforo": semaforo or cfg.get("semaforo", "verde"), "perdida_max_dia": _entero_si_cabe(pmd),
         "riesgo_por_operacion": round(por_op, 2), "stop_pts": stop, "presupuesto": cfg.get("presupuesto")}
    if inst["tipo"] == "futuro":
        crudo = micros_que_caben(por_op, stop, inst["punto_micro"])
        cap = cfg.get("max_micro")
        r.update({"micro": inst["micro"], "punto_micro": inst["punto_micro"], "riesgo_usd_micro": round(stop * inst["punto_micro"], 2),
                  "sin_tope": crudo, "tope_cuenta": cap, "contratos": min(crudo, int(cap)) if cap else crudo})
        return r
    riesgo = comun.al_tick(stop, inst["tick"])
    r.update({"simbolo": inst["codigo"], "riesgo_por_accion": riesgo, "entrada": entrada})
    if entrada is None or entrada <= 0:
        n = acciones_que_caben(por_op, riesgo)
        r.update({"acciones": n, "contratos": n, "limites": [], "manda": "riesgo por operación",
                  "nota": "sin --entrada solo cuenta el riesgo: dime el precio de entrada para aplicar posición, orden máxima y efectivo"})
        return r
    limites, n, manda = limites_accion(c, inst["codigo"], comun.al_tick(entrada, inst["tick"]), riesgo, None, cartera)
    r.update({"acciones": n, "contratos": n, "limites": limites, "manda": manda["nombre"], "coste": round(n * entrada, 2), "perdida_max_usd": round(n * riesgo, 2)})
    return r


def informe_calc_propia(r, cuenta_nombre):
    lineas = ["Cuenta: %s" % cuenta_nombre,
              "Pérdida máxima de hoy (%s): %s · riesgo por operación: %s (%d operaciones como mucho)"
              % (r["semaforo"], usd(r["perdida_max_dia"]), usd(r["riesgo_por_operacion"], 2), FALLOS_Y_PARAS)]
    if r["tipo"] == "futuro":
        lineas.append("Stop %g pts × %g $/pt del %s = %s $ por micro" % (r["stop_pts"], r["punto_micro"], r["micro"], num(r["riesgo_usd_micro"], 2)))
        lineas.append("Contratos: %d %s" % (r["contratos"], r["micro"])
                      + (" (tope: %d)" % r["tope_cuenta"] if r["tope_cuenta"] and r["sin_tope"] > r["tope_cuenta"] else "")
                      + (" · no cabe ninguno: reduce el stop" if r["contratos"] == 0 else ""))
        return "\n".join(lineas)
    lineas.append("Stop %s por acción de %s%s" % (usd(r["riesgo_por_accion"], 2), r["simbolo"], (" · entrada %s" % usd(r["entrada"], 2)) if r.get("entrada") else ""))
    if r.get("limites"):
        lineas.append("Límites (acciones enteras; manda el menor):")
        for l in r["limites"]:
            lineas.append("  %-22s %-64s %4d %s%s" % (l["nombre"], l["como"], l["acciones"], r["simbolo"], "  <- manda" if l["manda"] else ""))
        lineas.append("Acciones: %d %s (%s). Pérdida al stop: %d × %s = %s." % (r["acciones"], r["simbolo"], usd(r["coste"], 2), r["acciones"], usd(r["riesgo_por_accion"], 2), usd(r["perdida_max_usd"], 2))
                      + (" No cabe ninguna: reduce el stop o déjala pasar." if r["acciones"] == 0 else ""))
    else:
        lineas.append("Acciones: %d %s por el riesgo por operación%s" % (r["acciones"], r["simbolo"], " · no cabe ninguna: reduce el stop" if r["acciones"] == 0 else ""))
        lineas.append("Nota: " + r["nota"])
    return "\n".join(lineas)


# ---------------------------------------------------------------- orden (desde kemet/plan.json)

def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


COLOCADAS = ("colocada", "llenada", "placed", "filled")  # estados de kemet/estado/broker.json que cuentan como puestas


def colocadas_hoy(broker_doc, fecha):
    """Lo que kemet-broker apuntó como colocado (o llenado) hoy en kemet/estado/broker.json: el último estado de cada huella;
    las aprobadas sin colocar, las denegadas y las fallidas no cuentan."""
    if not isinstance(broker_doc, dict) or str(broker_doc.get("fecha")) != fecha:
        return []
    ultimo = {}
    for k, o in enumerate(broker_doc.get("ordenes") or []):
        if isinstance(o, dict) and str(o.get("fecha") or fecha) == fecha:
            ultimo[o.get("huella") or ("#%d" % k)] = o
    return [o for o in ultimo.values() if str(o.get("estado") or "").lower() in COLOCADAS]


def hoy_en_dia(dia_doc, fecha, broker_doc=None):
    """Lo ya arriesgado hoy según kemet/estado/dia.json, más lo colocado en kemet/estado/broker.json que no esté ya apuntado
    en dia.json (misma huella): (riesgo_abierto, perdida_realizada, n_operaciones)."""
    ops = (dia_doc.get("operaciones") or []) if dia_doc and str(dia_doc.get("fecha")) == fecha else []
    abierto = sum(_f(o.get("riesgo_usd")) or 0.0 for o in ops if o.get("cerrada") in (None, False))
    neto = sum(_f(o.get("resultado_usd")) or 0.0 for o in ops if o.get("cerrada") not in (None, False))
    n = len(ops)
    huellas = {o.get("huella") for o in ops if o.get("huella")}
    for o in colocadas_hoy(broker_doc, fecha):
        if o.get("huella") in huellas or o.get("clase") == "cierre" or o.get("cierre") or str(o.get("lado") or "").lower() in ("venta", "sell"):
            continue
        n += 1
        abierto += _f(o.get("perdida_al_stop")) or _f(o.get("riesgo_usd")) or _f(o.get("perdida_max_usd")) or 0.0
    return round(abierto, 2), round(max(0.0, -neto), 2), n


def instrumento_del_plan(plan, cfg):
    """El instrumento del plan: su micro, su mercado o su símbolo; si no, el mercado de la config."""
    for clave in ("micro", "mercado", "simbolo", "symbol"):
        if plan.get(clave):
            try:
                return comun.resolver(plan[clave])
            except KemetError:
                continue
    return comun.resolver((cfg or {}).get("mercado") or "NQ")


def dimensionar(plan, cfg, hoy, dia_doc=None, tipo="stop", limite=None, precios=None, cartera=None, broker_doc=None, ahora_utc=None):
    """Pura: un plan + la config + el día -> el tamaño (dict). `contratos` puede ser 0: entonces `rechazo` dice por qué.
    Con un plan de una acción y una cuenta propia, el tamaño va en acciones enteras (ver dimensionar_accion)."""
    if not isinstance(plan, dict):
        raise KemetError("kemet/plan.json no es un objeto JSON")
    if not plan.get("fecha"):
        return {"rechazo": "el plan no dice de qué día es: haz un plan nuevo con kemet-salida", "contratos": 0, "limites": []}
    if str(plan["fecha"]) != hoy:
        return {"rechazo": "el plan es del %s y hoy es %s en Nueva York: haz un plan nuevo con kemet-salida" % (plan["fecha"], hoy),
                "contratos": 0, "limites": []}
    lado = LADO_ORDEN.get(str(plan.get("lado") or "").lower())
    if not lado:
        raise KemetError("el plan necesita un lado (largo o corto), no %r" % plan.get("lado"))
    inst = instrumento_del_plan(plan, cfg)
    entrada, stop, objetivo = _f(plan.get("entrada")), _f(plan.get("stop")), _f(plan.get("objetivo"))
    for nombre, v in (("entrada", entrada), ("stop", stop), ("objetivo", objetivo)):
        if v is None or v <= 0:
            raise KemetError("el plan necesita %s (un precio mayor que 0): ejecuta kemet-salida" % nombre)
    if inst["tipo"] == "accion":
        return dimensionar_accion(plan, cfg, hoy, inst, lado, entrada, stop, objetivo, dia_doc, limite, precios, cartera, broker_doc, ahora_utc)
    if es_propia(cfg) and not cfg.get("perdida_max_dia"):
        raise KemetError("la config de la cuenta propia no tiene perdida_max_dia: ejecuta tamano.py config --propia")
    mercado = inst["codigo"]
    c = comun.CONTRATOS[mercado]
    micro = c["micro"]
    if limite is not None:
        tipo = "limite"
        if limite is not True:
            entrada = float(limite)
    largo = lado == "compra"
    if (largo and stop >= entrada) or (not largo and stop <= entrada):
        return {"rechazo": "el stop %s no está %s de la entrada %s en un %s" % (pts(stop), "debajo" if largo else "encima", pts(entrada), plan.get("lado")),
                "contratos": 0, "limites": []}
    if (largo and objetivo <= entrada) or (not largo and objetivo >= entrada):
        return {"rechazo": "el objetivo %s no está %s de la entrada %s" % (pts(objetivo), "encima" if largo else "debajo", pts(entrada)),
                "contratos": 0, "limites": []}
    if abs(entrada - stop) < c["tick"] - 1e-9:
        return {"rechazo": "el stop está a menos de un tick (%s) de la entrada: no existe en la plataforma" % pts(c["tick"]), "contratos": 0, "limites": []}
    riesgo_pts = comun.al_tick(abs(entrada - stop), c["tick"])
    if riesgo_pts < abs(entrada - stop) - 1e-9:
        riesgo_pts = round(riesgo_pts + c["tick"], 8)          # al tick hacia arriba: el riesgo nunca se mide por debajo del real
    if _f(plan.get("riesgo_pts")) and abs(_f(plan["riesgo_pts"]) - riesgo_pts) > c["tick"]:
        raise KemetError("el plan dice riesgo_pts %s pero entrada menos stop son %s puntos" % (pts(_f(plan["riesgo_pts"])), pts(riesgo_pts)))
    por_micro = round(riesgo_pts * c["punto_micro"], 2)
    por_op = riesgo_por_operacion_de(cfg)
    pmd = cfg.get("perdida_max_dia")
    abierto, realizada, n_ops = hoy_en_dia(dia_doc, hoy, broker_doc)
    queda = round(pmd - abierto - realizada, 2)
    limites = [{"nombre": "riesgo por operación", "usd": round(por_op, 2), "contratos": micros_que_caben(por_op, riesgo_pts, c["punto_micro"]),
                "como": "%s / %s por micro" % (usd(por_op, 2), usd(por_micro, 2))}]
    tope = cfg.get("max_mini") if comun.sin_micro(mercado) else cfg.get("max_micro")
    if tope:
        limites.append({"nombre": "tope de la cuenta", "usd": None, "contratos": int(tope),
                        "como": "%d %s en %s" % (int(tope), "contratos" if comun.sin_micro(mercado) else "micros", cfg.get("cuenta_nombre") or "tu cuenta")})
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


def dimensionar_accion(plan, cfg, hoy, inst, lado, entrada, stop, objetivo, dia_doc=None, limite=None, precios=None, cartera=None, broker_doc=None, ahora_utc=None):
    """Pura: un plan de una acción + la cuenta propia + el día -> el tamaño en acciones enteras (dict)."""
    sim = inst["codigo"]
    if not es_propia(cfg):
        raise KemetError("el plan es de una acción (%s) y la config es de una cuenta de firma (futuros): para acciones ejecuta "
                         "tamano.py config --propia --presupuesto … --max-perdida-operacion … --max-perdida-dia …" % sim)
    if not cfg.get("presupuesto"):
        raise KemetError("la config de la cuenta propia no tiene presupuesto: ejecuta tamano.py config --propia")
    tick = inst["tick"]
    largo = lado == "compra"
    base = {"simbolo": sim, "mercado": sim, "instrumento": "accion", "lado": lado, "lado_plan": plan.get("lado"), "contratos": 0, "acciones": 0,
            "limites": [], "fecha": hoy, "hora_entrada": plan.get("hora_entrada"), "plan": plan}
    if sim in [str(b).upper() for b in cfg.get("bloqueados") or []]:
        return dict(base, rechazo="%s está en tu lista de bloqueados (config: bloqueados)" % sim)
    if not largo and not cfg.get("permitir_cortos"):
        return dict(base, rechazo="el plan es un corto de %s y tu cuenta no permite cortos (permitir_cortos: false). Déjalo pasar o cámbialo en kemet/config.json" % sim)
    entrada = comun.al_tick(entrada, tick)
    stop, objetivo = comun.al_tick(stop, tick), comun.al_tick(objetivo, tick)
    notas = []
    tipo, ref, origen = "market", entrada, "plan"
    if limite is not None:
        tipo = "limit"
        if limite is not True:
            ref, origen = comun.al_tick(float(limite), tick), "limite"
    else:
        fresco, hace = precio_fresco(precios, sim, ahora_utc or comun.utc_ahora())
        if fresco is not None:
            fresco = comun.al_tick(fresco, tick)
            if (largo and fresco > entrada) or (not largo and fresco < entrada):
                ref, origen = fresco, "precio"
                notas.append("último precio de %s en kemet/precios.json: %s (hace %d min), %s de la entrada del plan %s: el riesgo se mide desde %s"
                             % (sim, usd(fresco, 2), hace, "por encima" if largo else "por debajo", usd(entrada, 2), usd(fresco, 2)))
            else:
                notas.append("último precio de %s en kemet/precios.json: %s (hace %d min), no empeora la entrada del plan: se mide desde %s" % (sim, usd(fresco, 2), hace, usd(entrada, 2)))
    if (largo and stop >= ref) or (not largo and stop <= ref):
        return dict(base, rechazo="el stop %s no está %s de la entrada %s en un %s" % (usd(stop, 2), "debajo" if largo else "encima", usd(ref, 2), plan.get("lado")))
    if (largo and objetivo <= ref) or (not largo and objetivo >= ref):
        return dict(base, rechazo="el objetivo %s no está %s de la entrada %s%s" % (usd(objetivo, 2), "encima" if largo else "debajo", usd(ref, 2),
                                                                                  ": el recorrido ya se ha hecho" if origen == "precio" else ""))
    riesgo = comun.al_tick(abs(ref - stop), tick)
    if _f(plan.get("riesgo_pts")) and origen == "plan" and abs(_f(plan["riesgo_pts"]) - riesgo) > tick:
        raise KemetError("el plan dice riesgo_pts %s pero entrada menos stop son %s por acción" % (num(_f(plan["riesgo_pts"]), 2), num(riesgo, 2)))
    por_op = riesgo_por_operacion_de(cfg)
    pmd = float(cfg.get("perdida_max_dia") or 0)
    if not pmd:
        raise KemetError("la config de la cuenta propia no tiene perdida_max_dia: ejecuta tamano.py config --propia")
    abierto, realizada, n_ops = hoy_en_dia(dia_doc, hoy, broker_doc)
    queda = round(pmd - abierto - realizada, 2)
    limites, n, manda = limites_accion(cfg, sim, ref, riesgo, {"queda": queda, "pmd": pmd, "abierto": abierto, "realizada": realizada}, cartera)
    coste = round(n * ref, 2)
    rechazo = None
    if n == 0:
        if manda["nombre"] == "riesgo por operación":
            rechazo = ("una acción de %s arriesga %s al stop (entrada %s menos stop %s), más que tu riesgo por operación de %s. "
                       "Déjala pasar o planifica un stop más corto con kemet-salida" % (sim, usd(riesgo, 2), usd(ref, 2), usd(stop, 2), usd(por_op, 2)))
        elif manda["nombre"] == "lo que queda del día":
            rechazo = "hoy quedan %s de tu pérdida máxima del día (%s) y una acción arriesga %s: el día está hecho" % (usd(max(queda, 0)), usd(pmd), usd(riesgo, 2))
        else:
            rechazo = "una acción de %s cuesta %s, más que tu límite de %s (%s)" % (sim, usd(ref, 2), manda["nombre"], manda["como"])
    elif cfg.get("min_orden_usd") and coste < float(cfg["min_orden_usd"]) - 0.005:
        rechazo = "%d acciones de %s son %s, menos que tu orden mínima de %s" % (n, sim, usd(coste, 2), usd(float(cfg["min_orden_usd"])))
    plano = plan.get("plano_a") or cfg.get("plano_a") or inst["plano"]
    if cfg.get("plano_a") and plan.get("plano_a") and comun.parse_hhmm(cfg["plano_a"]) < comun.parse_hhmm(plan["plano_a"]):
        plano = cfg["plano_a"]
    return dict(base, tipo=tipo, entrada=ref, entrada_plan=entrada, origen_entrada=origen, stop=stop, objetivo=objetivo, riesgo_pts=riesgo, riesgo_por_accion=riesgo,
                rr=round(abs(objetivo - ref) / riesgo, 2), riesgo_por_operacion=round(por_op, 2), perdida_max_dia=_entero_si_cabe(pmd), riesgo_abierto=abierto,
                perdida_realizada=realizada, operaciones_hoy=n_ops, queda=queda, limites=limites, contratos=n, acciones=n, manda=manda["nombre"],
                coste=coste, perdida_max_usd=round(n * riesgo, 2), minis=None, plano_a=plano, rechazo=rechazo, notas=notas)


def _precio_alpaca(x):
    return "%.2f" % round(float(x) + 1e-9, 2)


def orden_bracket_accion(s):
    """La orden propuesta de una acción con los campos de place_stock_order de Alpaca (cantidades y precios como texto),
    más `why`, `plan` e `instrumento`. None si hay rechazo."""
    if s.get("rechazo") or s["acciones"] <= 0:
        return None
    o = {"symbol": s["simbolo"], "side": LADO_ALPACA[s["lado"]], "qty": str(int(s["acciones"])), "type": s["tipo"]}
    if s["tipo"] == "limit":
        o["limit_price"] = _precio_alpaca(s["entrada"])
    o["time_in_force"] = "day"
    o["order_class"] = "bracket"
    o["take_profit_limit_price"] = _precio_alpaca(s["objetivo"])
    o["stop_loss_stop_price"] = _precio_alpaca(s["stop"])
    o["why"] = "%s %s: %d acciones, manda %s (%d × %s = %s al stop)" % (
        s["lado_plan"], s["simbolo"], s["acciones"], s["manda"], s["acciones"], usd(s["riesgo_por_accion"], 2), usd(s["perdida_max_usd"], 2))
    plan = dict(s["plan"])
    plan.update({"fecha": s["fecha"], "lado": s["lado_plan"], "entrada": s["entrada"], "stop": s["stop"], "objetivo": s["objetivo"], "plano_a": s["plano_a"],
                 "riesgo_pts": s["riesgo_por_accion"], "riesgo_por_accion": s["riesgo_por_accion"], "perdida_max_usd": s["perdida_max_usd"], "coste": s["coste"]})
    if s["origen_entrada"] != "plan":
        plan["entrada_plan"] = s["entrada_plan"]
    o["plan"] = plan
    o["instrumento"] = "accion"
    return o


def informe_orden_accion(s, orden, cfg, ahora_utc):
    lineas = ["ORDEN · %s · %s · %s" % (s["simbolo"], s.get("fecha", ""), comun.hora_doble(ahora_utc))]
    if s.get("rechazo") and not s.get("limites"):
        lineas.append("Sin orden: " + s["rechazo"])
        return "\n".join(lineas)
    origen = {"plan": "la entrada del plan", "precio": "el último precio, por encima del plan", "limite": "tu precio límite"}[s["origen_entrada"]]
    lineas.append("%s %s a %s%s · stop %s · objetivo %s · riesgo %s por acción (%s) · R %s"
                  % (s["lado_plan"], s["simbolo"], usd(s["entrada"], 2), (" (%s)" % s["hora_entrada"]) if s.get("hora_entrada") else "",
                     usd(s["stop"], 2), usd(s["objetivo"], 2), usd(s["riesgo_por_accion"], 2), origen, num(s["rr"], 2)))
    for n in s.get("notas") or []:
        lineas.append("Nota: " + n)
    lineas.append("Cuenta: %s · pérdida máxima del día %s · riesgo por operación %s · hoy %d operaciones, %s abierto, %s perdido"
                  % (cfg.get("cuenta_nombre"), usd(s["perdida_max_dia"]), usd(s["riesgo_por_operacion"], 2), s["operaciones_hoy"], usd(s["riesgo_abierto"]), usd(s["perdida_realizada"])))
    lineas.append("")
    lineas.append("Límites (acciones enteras; manda el menor):")
    for l in s["limites"]:
        lineas.append("  %-22s %-64s %4d %s%s" % (l["nombre"], l["como"], l["acciones"], s["simbolo"], "  <- manda" if l["manda"] else ""))
    lineas.append("")
    if orden is None:
        lineas.append("Sin orden: " + s["rechazo"])
        return "\n".join(lineas)
    lineas.append("Tamaño: %d acciones de %s = %s. Pérdida al stop: %d × %s = %s." % (s["acciones"], s["simbolo"], usd(s["coste"], 2), s["acciones"], usd(s["riesgo_por_accion"], 2), usd(s["perdida_max_usd"], 2)))
    lineas.append("Un stop es una orden, no una promesa: en un mercado rápido se llena peor que %s." % usd(s["stop"], 2))
    lineas.append("")
    lineas.append("Orden bracket propuesta (campos de place_stock_order; nada se ha enviado a ningún bróker):")
    como = ("límite %s" % orden["limit_price"]) if orden["type"] == "limit" else "a mercado"
    lineas.append("  %s %s %s, %s, día, objetivo %s, stop %s" % (orden["side"], orden["qty"], orden["symbol"], como, orden["take_profit_limit_price"], orden["stop_loss_stop_price"]))
    lineas.append("Plano a las %s NY: lo que siga abierto se cierra (kemet-alertas avisa)." % s["plano_a"])
    lineas.append("")
    lineas.append("Siguiente: kemet-riesgo la comprueba; kemet-broker te lee el ticket y espera tu sí.")
    return "\n".join(lineas)


def orden_bracket(s):
    """La orden propuesta con el contrato de kemet/orden.json. None si hay rechazo."""
    if s.get("instrumento") == "accion":
        return orden_bracket_accion(s)
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
            "por_que": por_que, "plan": plan, "instrumento": "futuro"}


def informe_orden(s, orden, cfg, ahora_utc):
    if s.get("instrumento") == "accion":
        return informe_orden_accion(s, orden, cfg, ahora_utc)
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
    if a.propia:
        if a.firma or a.cuenta:
            raise KemetError("--propia no lleva --firma ni --cuenta: es tu cuenta, sin firma")
        cfg, notas = construir_config_propia(a.presupuesto, a.max_perdida_operacion, a.max_perdida_dia, a.mercado, a.max_posicion_pct, a.max_orden,
                                             a.min_orden, a.efectivo_pct, a.semaforo, a.zona, a.plano_a, a.sec_user_agent, a.permitir_cortos, a.max_micro)
        informe = informe_config_propia
    else:
        if not a.firma or not a.cuenta:
            raise KemetError("di --firma y --cuenta (tamano.py listar), o --propia con --presupuesto, --max-perdida-operacion y --max-perdida-dia")
        datos = cargar_reglas()
        f, acc = buscar(datos, a.firma, a.cuenta)
        if not acc:
            raise KemetError("firma o cuenta no encontrada (%s / %s): usa tamano.py listar" % (a.firma, a.cuenta))
        cfg, notas = construir_config(f, acc, a.mercado, a.semaforo, a.zona, a.plano_a, a.perdida_dia, a.max_micro)
        informe = informe_config
    if a.json:
        print(json.dumps(cfg, ensure_ascii=False, indent=1))
    if a.sin_escribir:
        if not a.json:
            print(informe(cfg, notas, "(no escrita: --sin-escribir)"))
        return 0
    p = comun.escribir_json("config.json", cfg)
    if not a.json:
        print(informe(cfg, notas, p))
    return 0


def cmd_calc_propia(a, cfg, nombre):
    """calc con una cuenta propia (del config o de --presupuesto y --max-perdida-operacion): acciones o micros."""
    mercado = a.mercado or cfg.get("mercado") or "NQ"
    cartera = comun.leer_json(comun.ruta("portfolio.json"), obligatorio=False)
    r = calcular_propia(cfg, mercado, a.stop, a.entrada, a.semaforo, cartera)
    if a.json:
        r["cuenta_nombre"] = nombre
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print(informe_calc_propia(r, nombre))
    return 0 if r["contratos"] > 0 else 1


def cmd_calc(a):
    extra = []
    if a.presupuesto or a.max_perdida_operacion:
        if not (a.presupuesto and a.max_perdida_operacion):
            raise KemetError("sin config, una cuenta propia necesita --presupuesto y --max-perdida-operacion (y --max-perdida-dia si no es el triple)")
        cfg, _ = construir_config_propia(a.presupuesto, a.max_perdida_operacion, a.max_perdida_dia or 3 * a.max_perdida_operacion, a.mercado or "NQ", max_micro=a.max_micro)
        return cmd_calc_propia(a, cfg, cfg["cuenta_nombre"])
    if not (a.firma or a.drawdown):
        cfg, existe = cargar_config()
        if existe and es_propia(cfg):
            return cmd_calc_propia(a, cfg, cfg["cuenta_nombre"])
        if existe and a.mercado and comun.es_accion(a.mercado):
            raise KemetError("%s es una acción y tu config es de una cuenta de firma (futuros): para acciones ejecuta tamano.py config --propia" % a.mercado.upper())
    if a.mercado and comun.es_accion(a.mercado):
        raise KemetError("%s es una acción: pasa --presupuesto y --max-perdida-operacion, o ejecuta tamano.py config --propia" % a.mercado.upper())
    if a.firma or a.drawdown:
        if a.firma:
            datos = cargar_reglas()
            f, acc = buscar(datos, a.firma, a.cuenta)
            if not acc:
                raise KemetError("firma o cuenta no encontrada; usa tamano.py listar")
            nombre = "%s · %s" % (f["name"], acc["label"])
            tope = min([x for x in (acc.get("max_micro"), a.max_micro) if x] or [None]) if (acc.get("max_micro") or a.max_micro) else None
            r = calcular(acc["max_loss"], acc.get("daily_loss_limit"), tope, a.mercado or "NQ", a.stop, a.semaforo or "verde", cap_mini=acc.get("max_mini"))
            fb = acc.get("flat_by") or {}
            extra.append("Hora límite: %s %s · noticias: %s" % (fb.get("time", "?"), fb.get("tz", ""), acc.get("news", "?"))
                         + (" · consistencia: %s" % acc["consistency"] if acc.get("consistency") else ""))
            extra.append("Reglas comprobadas el %s: confírmalas en tu panel, las firmas las cambian." % f.get("checked", "?"))
        else:
            nombre = "propia"
            r = calcular(a.drawdown, a.diario, a.max_micro, a.mercado or "NQ", a.stop, a.semaforo or "verde", cap_mini=a.max_micro)
    else:
        cfg, existe = cargar_config()
        if not existe:
            raise KemetError("sin kemet/config.json: pasa --firma y --cuenta, o --drawdown (y --diario), o ejecuta tamano.py config")
        nombre = cfg["cuenta_nombre"]
        pmd = None
        semaforo = a.semaforo or cfg.get("semaforo") or "verde"
        if cfg.get("perdida_max_dia_origen") == "usuario":
            # la tuya manda siempre; la de la config ya lleva su semáforo, así que se vuelve a la de verde antes de aplicar el de hoy
            pmd = cfg["perdida_max_dia"] * (2.0 if (cfg.get("semaforo") or "verde") != "verde" else 1.0)
        r = calcular(cfg["drawdown"], cfg.get("limite_diario_firma"), cfg.get("max_micro"), a.mercado or cfg["mercado"], a.stop, semaforo, pmd,
                     cap_mini=cfg.get("max_mini"))
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
    plan = comun.leer_json(comun.dada(a.plan) or "plan.json", "ejecuta kemet-salida primero")
    dia = comun.leer_json(comun.ruta(os.path.join("estado", "dia.json")), obligatorio=False)
    broker = comun.leer_json(comun.ruta(os.path.join("estado", "broker.json")), obligatorio=False)
    precios = comun.leer_json(comun.ruta("precios.json"), obligatorio=False)
    cartera = comun.leer_json(comun.ruta("portfolio.json"), obligatorio=False)
    limite = None
    if a.limite is not None:
        limite = True if a.limite == "plan" else _f(a.limite)
        if limite is None or (limite is not True and limite <= 0):
            raise KemetError("--limite va solo (el precio de entrada del plan) o con un precio mayor que 0, no %r" % a.limite)
    s = dimensionar(plan, cfg, hoy, dia, a.tipo, limite, precios, cartera, broker, ahora)
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
    p = sub.add_parser("config", help="escribe kemet/config.json desde una firma y una cuenta, o tu cuenta propia (--propia)")
    p.add_argument("--firma")
    p.add_argument("--cuenta")
    p.add_argument("--mercado", default="NQ", help="ES, NQ, CL, GC… o un ticker de EE. UU. con --propia (TSLA)")
    p.add_argument("--semaforo", choices=["verde", "ambar", "rojo"], default="verde")
    p.add_argument("--zona", default="Europe/Madrid", help="tu zona horaria, solo informativa")
    p.add_argument("--plano-a", dest="plano_a", help="HH:MM NY a la que quieres estar plano (por defecto la del contrato)")
    p.add_argument("--perdida-dia", dest="perdida_dia", type=float, help="tu propia pérdida máxima del día en dólares (nunca por encima del límite diario de la firma)")
    p.add_argument("--max-micro", dest="max_micro", type=int, help="tope de micros de tu panel, si la cuenta no lo publica o el tuyo es menor")
    p.add_argument("--propia", action="store_true", help="cuenta propia, sin firma: acciones de EE. UU. o futuros con tus propios límites")
    p.add_argument("--presupuesto", type=float, help="(--propia) dinero de la cuenta en dólares")
    p.add_argument("--max-perdida-operacion", dest="max_perdida_operacion", type=float, help="(--propia) pérdida máxima por operación en dólares")
    p.add_argument("--max-perdida-dia", dest="max_perdida_dia", type=float, help="(--propia) pérdida máxima del día en dólares")
    p.add_argument("--max-posicion-pct", dest="max_posicion_pct", type=float, help="(--propia) tope de una posición en %% del presupuesto (75)")
    p.add_argument("--max-orden", dest="max_orden", type=float, help="(--propia) orden máxima en dólares (4.000)")
    p.add_argument("--min-orden", dest="min_orden", type=float, help="(--propia) orden mínima en dólares (5)")
    p.add_argument("--efectivo-pct", dest="efectivo_pct", type=float, help="(--propia) colchón de efectivo que no se invierte, en %% (10)")
    p.add_argument("--permitir-cortos", dest="permitir_cortos", action="store_true", help="(--propia) permite vender en corto")
    p.add_argument("--sec-user-agent", dest="sec_user_agent", help="(--propia) \"Nombre correo@ejemplo.com\" para EDGAR (o la variable SEC_USER_AGENT)")
    p.add_argument("--sin-escribir", dest="sin_escribir", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("calc", help="cuántos micros (o acciones, en una cuenta propia) caben con tu stop")
    p.add_argument("--stop", type=float, required=True, help="stop en puntos del contrato, o en dólares por acción")
    p.add_argument("--mercado")
    p.add_argument("--entrada", type=float, help="(acciones) precio de entrada, para los topes de posición, orden máxima y efectivo")
    p.add_argument("--semaforo", choices=["verde", "ambar", "rojo"])
    p.add_argument("--firma")
    p.add_argument("--cuenta")
    p.add_argument("--drawdown", type=float)
    p.add_argument("--diario", type=float)
    p.add_argument("--max-micro", dest="max_micro", type=int)
    p.add_argument("--presupuesto", type=float, help="(cuenta propia sin config) dinero de la cuenta")
    p.add_argument("--max-perdida-operacion", dest="max_perdida_operacion", type=float, help="(cuenta propia sin config) pérdida máxima por operación")
    p.add_argument("--max-perdida-dia", dest="max_perdida_dia", type=float, help="(cuenta propia sin config) pérdida máxima del día (por defecto el triple)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("orden", help="una orden bracket en micros (o en acciones, con una cuenta propia) desde kemet/plan.json")
    p.add_argument("--plan", help="otro plan.json (por defecto kemet/plan.json)")
    p.add_argument("--tipo", choices=["stop", "limite", "mercado"], default="stop", help="(futuros) tipo de la orden de entrada")
    p.add_argument("--limite", nargs="?", const="plan", metavar="PRECIO", help="una orden límite: a ese precio, o al de la entrada del plan si va solo")
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
