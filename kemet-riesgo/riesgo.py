#!/usr/bin/env python3
"""PASS o BLOCK para cada orden de kemet/orden.json antes de que la pongas en tu plataforma.

Solo biblioteca estándar, sin red. Lee y escribe en `kemet/` del directorio actual (variable KEMET_DIR).

    python3 riesgo.py check                          # kemet/orden.json contra tus reglas; escribe kemet/estado/riesgo.json
    python3 riesgo.py check --ahora "2026-11-11 10:40" --sin-escribir
    python3 riesgo.py registrar --abrir              # la orden que pasó ya está puesta: apúntala como abierta
    python3 riesgo.py registrar --resultado -120 --hora 11:05   # cierra la última abierta con su resultado
    python3 riesgo.py hoy                            # el día: operaciones, riesgo abierto, pérdida, lo que queda

Entradas y cierres. Una orden con `"cierre": true` solo saca de una posición: se le mira el formato y que Globex esté
abierto; todo lo demás se convierte en aviso. Salir siempre tiene que ser posible. En acciones, una venta de lo que
tienes en kemet/portfolio.json también es un cierre.

Acciones (cuenta propia, orden en el formato de place_stock_order de Alpaca: symbol, side, qty, type, time_in_force,
order_class bracket, take_profit_limit_price, stop_loss_stop_price, más plan e instrumento): además de lo de abajo se
mira el reloj de la NYSE (festivos y 09:30 a 16:00), la lista de bloqueados, el tamaño mínimo y máximo en dólares, la
posición (max_posicion_pct del presupuesto), el efectivo con su colchón (kemet/portfolio.json o el presupuesto), los
cortos sin permiso, las opciones sin permiso, y lo colocado hoy según kemet/estado/broker.json. Un precio fresco en
kemet/precios.json (menos de 15 minutos) por encima de la entrada del plan sube el riesgo medido; nunca al revés.

Qué bloquea una entrada:
  formato        símbolo que no es un micro o mini conocido, lado que no es compra o venta, contratos que no son un
                 entero mayor que 0, precio que no es un número
  stop           sin stop, o stop del lado equivocado de la entrada; objetivo detrás de la entrada
  pérdida        contratos × riesgo en puntos × valor del punto, por encima del riesgo por operación
  día            riesgo de las operaciones abiertas + pérdidas realizadas + esta, por encima de perdida_max_dia
  operaciones    ya hay fallos_y_paras operaciones hoy (la tercera entra, la cuarta no)
  contratos      más micros (o minis) que el tope de la cuenta
  ventana        dentro de la ventana de un dato de kemet/agenda.json (±10 min, ±20 si es fuerte) o en los primeros
                 15 minutos de la sesión regular (09:30–09:45 NY en índices)
  horario        antes de sin_entradas_antes, después de sin_entradas_despues, después de plano_a o de la hora
                 límite de la firma (convertida a NY), o Globex en pausa o cerrado
  duplicado      la misma orden (misma huella) ya apuntada hoy en kemet/estado/dia.json, o repetida en el archivo
Avisos que no bloquean: la regla de consistencia de la firma (no se puede medir aquí), `"papel": false`, hora límite
en Chicago, sin config.

Código de salida: 0 si todo PASS, 1 si algún BLOCK, 2 si hay un error.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import sys

import comun
from comun import KemetError, num, pts, usd

FALLOS_Y_PARAS = 3
DEFECTO = {"mercado": "NQ", "cuenta_nombre": "sin cuenta configurada", "perdida_max_dia": 500, "fallos_y_paras": FALLOS_Y_PARAS,
           "max_micro": None, "max_mini": None, "hora_limite": None, "hora_limite_tz": "America/New_York",
           "sin_entradas_antes": "09:45", "sin_entradas_despues": "15:00", "plano_a": None, "consistencia": None, "papel": True}
CAMPOS_HUELLA = ("simbolo", "lado", "contratos", "tipo", "precio", "stop", "objetivo", "cierre")
# Los parámetros de place_stock_order de Alpaca: la huella de una orden de acción son estos más `cierre`, exactamente como en
# kemet-broker/broker.py (si no coinciden, el ticket nunca sale LISTO).
CAMPOS_ALPACA = ("symbol", "side", "qty", "notional", "type", "time_in_force", "limit_price", "stop_price", "trail_price",
                 "trail_percent", "extended_hours", "client_order_id", "order_class", "take_profit_limit_price",
                 "stop_loss_stop_price", "stop_loss_limit_price", "advanced_instructions")
CAMPOS_HUELLA_ACCION = CAMPOS_ALPACA + ("cierre",)
# La cuenta propia sin config: los topes del pack de referencia.
DEFECTO_PROPIA = {"mercado": "TSLA", "cuenta_nombre": "sin cuenta configurada", "presupuesto": None, "efectivo_pct": 10, "max_posicion_pct": 75,
                  "max_orden_usd": 4000, "min_orden_usd": 5, "perdida_max_dia": 150, "riesgo_por_operacion": 50, "fallos_y_paras": FALLOS_Y_PARAS,
                  "permitir_cortos": False, "permitir_margen": False, "permitir_opciones": False, "bloqueados": [], "hora_limite": None,
                  "sin_entradas_antes": "09:45", "sin_entradas_despues": "15:00", "plano_a": "15:55", "consistencia": None, "papel": True}
LADO_ALPACA = {"buy": "compra", "sell": "venta", "compra": "compra", "venta": "venta"}
LADO_ALPACA_INV = {"compra": "buy", "venta": "sell"}
TIPO_ALPACA = {"market": "market", "mercado": "market", "limit": "limit", "limite": "limit"}
OCC = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")            # un contrato de opciones (símbolo OCC)
PRECIO_FRESCO_MIN = 15
MARGEN_PLANO_MIN = 5      # los 5 minutos antes de plano_a y de la hora límite de la firma no se abre nada
COLOCADAS = ("colocada", "llenada", "placed", "filled")  # estados de kemet/estado/broker.json que cuentan como puestas
APERTURA_MIN = 15
LADOS = ("compra", "venta")
DIA = os.path.join("estado", "dia.json")
RIESGO = os.path.join("estado", "riesgo.json")
BROKER = os.path.join("estado", "broker.json")


# ---------------------------------------------------------------- utilidades

def _f(x):
    """Un número finito, o None. NaN e infinito son None: con NaN todas las comparaciones dan falso y la puerta se abría."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _riesgo_al_tick(distancia, tick):
    """Los puntos de riesgo redondeados al tick hacia arriba (el lado prudente): nunca 0 si el stop está a menos de un tick."""
    return round(math.ceil(distancia / tick - 1e-9) * tick, 6)


def _posiciones_futuro(cartera):
    """Las posiciones de futuros de kemet/portfolio.json (las apunta broker.py registrar) como operaciones abiertas."""
    out = []
    for p in (cartera or {}).get("posiciones") or [] if isinstance(cartera, dict) else []:
        if isinstance(p, dict) and str(p.get("instrumento") or "") == "futuro":
            q = _f(p.get("cantidad")) or 0.0
            if q:
                out.append({"simbolo": p.get("simbolo"), "lado": "compra" if q > 0 else "venta", "contratos": int(abs(q))})
    return out


def _cierra_algo(sim, lado, n, abiertas):
    """¿Hay en kemet/estado/dia.json una operación abierta de ese contrato, del lado contrario y con al menos n contratos?"""
    for o in abiertas:
        if str(o.get("simbolo") or "").upper() == sim and str(o.get("lado") or "").lower() != lado and (_entero(o.get("contratos")) or 0) >= (n or 0):
            return True
    return False


def es_orden_accion(orden):
    """Una orden de acción lleva "instrumento": "accion" o el formato de Alpaca (symbol, side); una de futuro, simbolo y contratos.
    La misma regla que kemet-broker/broker.py (es_accion)."""
    if not isinstance(orden, dict):
        return False
    inst = str(orden.get("instrumento") or "").lower()
    if inst in ("accion", "acción", "futuro"):
        return inst != "futuro"
    return "symbol" in orden and "simbolo" not in orden


def huella(orden):
    """sha1 de 12 hex de los campos de la orden que importan para ponerla: la misma orden da la misma huella. Para un futuro,
    CAMPOS_HUELLA; para una acción, los campos de place_stock_order más `cierre`. Idéntica a la de kemet-broker/broker.py."""
    campos = CAMPOS_HUELLA_ACCION if es_orden_accion(orden) else CAMPOS_HUELLA
    core = {k: orden[k] for k in campos if k in orden and orden[k] is not None}
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def contrato_de(simbolo):
    """(código de mercado, es_micro, valor del punto) para MNQ, NQ, MES…; None si no lo conoce."""
    s = str(simbolo or "").strip().upper()
    if s in comun.MICRO_A_CODIGO:
        c = comun.MICRO_A_CODIGO[s]
        return c, True, comun.CONTRATOS[c]["punto_micro"]
    if s in comun.CONTRATOS:
        return s, False, comun.CONTRATOS[s]["punto_mini"]
    return None


def hora_a_ny(hhmm, tz):
    t = comun.parse_hhmm(hhmm, "la hora límite")
    if tz == "America/Chicago":
        return (dt.datetime.combine(dt.date(2000, 1, 1), t) + dt.timedelta(hours=1)).time()
    return t


def mas_min(t, minutos):
    return (dt.datetime.combine(dt.date(2000, 1, 1), t) + dt.timedelta(minutes=minutos)).time()


def ventanas_del_dia(agenda, fecha, mercado):
    """[(desde, hasta, motivo)] en hora NY de los datos de la agenda de ese día que afectan al mercado."""
    out = []
    if not agenda or str(agenda.get("fecha")) != fecha:
        return out
    for d in agenda.get("datos") or []:
        mercados = d.get("mercados")
        if mercados and mercado not in [m.upper() for m in mercados]:
            continue
        try:
            t = comun.parse_hhmm(d.get("hora", ""), "la hora del dato")
        except KemetError:
            continue
        m = 20 if d.get("fuerte") else 10
        out.append((mas_min(t, -m), mas_min(t, m), "%s a las %s (%s)" % (d.get("nombre", "dato"), comun.hhmm(t), "fuerte, ±20 min" if d.get("fuerte") else "±10 min")))
    return out


def cargar_config():
    doc = comun.leer_json("config.json", obligatorio=False)
    cfg = dict(DEFECTO)
    if doc:
        cfg.update(doc)
    return cfg, bool(doc)


def leer_dia(fecha):
    """kemet/estado/dia.json si es de hoy; si no, un día vacío."""
    doc = comun.leer_json(comun.ruta(DIA), obligatorio=False)
    if not doc or str(doc.get("fecha")) != fecha:
        return {"fecha": fecha, "operaciones": [], "perdida_realizada": 0.0, "riesgo_abierto": 0.0}
    doc.setdefault("operaciones", [])
    return doc


def recalcular(dia):
    ops = dia.get("operaciones") or []
    dia["riesgo_abierto"] = round(sum(_f(o.get("riesgo_usd")) or 0.0 for o in ops if not o.get("cerrada")), 2)
    neto = sum(_f(o.get("resultado_usd")) or 0.0 for o in ops if o.get("cerrada"))
    dia["perdida_realizada"] = round(max(0.0, -neto), 2)
    dia["resultado_neto"] = round(neto, 2)
    return dia


# ---------------------------------------------------------------- la comprobación

def colocadas_hoy(broker, fecha):
    """Lo que kemet-broker apuntó como colocado (o llenado) hoy en kemet/estado/broker.json: el último estado de cada huella;
    las aprobadas sin colocar, las denegadas y las fallidas no cuentan."""
    if not isinstance(broker, dict) or str(broker.get("fecha")) != fecha:
        return []
    ultimo = {}
    for k, o in enumerate(broker.get("ordenes") or []):
        if isinstance(o, dict) and str(o.get("fecha") or fecha) == fecha:
            ultimo[o.get("huella") or ("#%d" % k)] = o
    return [o for o in ultimo.values() if str(o.get("estado") or "").lower() in COLOCADAS]


def cuenta_propia(cartera, c, precios):
    """El estado de la cuenta propia: efectivo, acciones por símbolo y su valor. Sin kemet/portfolio.json, el presupuesto en efectivo."""
    presupuesto = _f(c.get("presupuesto"))
    if not isinstance(cartera, dict):
        return {"efectivo": presupuesto, "acciones": {}, "valores": {}, "origen": "presupuesto"}
    efectivo = _f(cartera.get("efectivo"))
    acciones, valores = {}, {}
    for p in cartera.get("posiciones") or []:
        if not isinstance(p, dict):
            continue
        s = str(p.get("simbolo") or p.get("symbol") or "").upper()
        n = _f(p.get("cantidad", p.get("qty"))) or 0.0
        if not s or not n:
            continue
        acciones[s] = acciones.get(s, 0.0) + n
        precio = (precios or {}).get(s) or _f(p.get("precio_medio")) or 0.0
        valores[s] = valores.get(s, 0.0) + n * precio
    return {"efectivo": efectivo if efectivo is not None else presupuesto, "acciones": acciones, "valores": valores, "origen": "kemet/portfolio.json"}


def precios_de(doc, ahora_utc):
    """{SIMBOLO: (precio, fresco)} de kemet/precios.json; fresco = leído hace menos de PRECIO_FRESCO_MIN minutos."""
    out = {}
    if not isinstance(doc, dict):
        return out
    for s, q in (doc.get("precios") or {}).items():
        precio = _f(q.get("precio")) if isinstance(q, dict) else _f(q)
        if not precio or precio <= 0:
            continue
        cuando = None
        for texto in ((q.get("leido"), q.get("generado")) if isinstance(q, dict) else ()) + (doc.get("generado"),):
            if texto:
                try:
                    cuando = dt.datetime.strptime(str(texto), "%Y-%m-%dT%H:%M:%SZ")
                    break
                except ValueError:
                    continue
        fresco = cuando is not None and -60 <= (ahora_utc - cuando).total_seconds() <= PRECIO_FRESCO_MIN * 60
        out[str(s).upper()] = (precio, fresco)
    return out


def _entero(x):
    """"9" -> 9, 9.0 -> 9; None si no es un entero mayor que 0."""
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x if x > 0 else None
    v = _f(x)
    if v is None or v <= 0 or abs(v - round(v)) > 1e-9:
        return None
    return int(round(v))


def _ventanas_y_horario(ctx, t, rth_inicio, plano_cfg, con_hora_limite):
    """Las comprobaciones de ventanas y horario de una entrada (comunes a futuros y acciones). Devuelve la lista de motivos."""
    c = ctx["c"]
    luego = []
    apertura = comun.parse_hhmm(rth_inicio)
    if apertura <= t < mas_min(apertura, APERTURA_MIN):
        luego.append("ventana: apertura %s–%s NY, los quince minutos más bruscos del día (son las %s)"
                     % (comun.hhmm(apertura), comun.hhmm(mas_min(apertura, APERTURA_MIN)), comun.hhmm(t)))
    for desde, hasta, motivo in ctx["ventanas"]:
        if desde <= t <= hasta:
            luego.append("ventana: %s, de %s a %s NY no se abre ni se mantiene (son las %s)" % (motivo, comun.hhmm(desde), comun.hhmm(hasta), comun.hhmm(t)))
    antes = comun.parse_hhmm(c["sin_entradas_antes"]) if c.get("sin_entradas_antes") else None
    despues = comun.parse_hhmm(c["sin_entradas_despues"]) if c.get("sin_entradas_despues") else None
    if antes and t < antes:
        luego.append("horario: sin entradas antes de las %s NY (son las %s)" % (comun.hhmm(antes), comun.hhmm(t)))
    if despues and t > despues:
        luego.append("horario: sin entradas después de las %s NY (son las %s)" % (comun.hhmm(despues), comun.hhmm(t)))
    plano = comun.parse_hhmm(plano_cfg)
    if t >= plano:
        luego.append("horario: a las %s NY se está plano, no se abre nada (son las %s)" % (plano_cfg, comun.hhmm(t)))
    elif t >= mas_min(plano, -MARGEN_PLANO_MIN):
        luego.append("horario: los %d minutos antes de estar plano (%s NY) no se abre nada (son las %s)" % (MARGEN_PLANO_MIN, plano_cfg, comun.hhmm(t)))
    if con_hora_limite and ctx["hora_limite_ny"] and t >= mas_min(ctx["hora_limite_ny"], -MARGEN_PLANO_MIN):
        luego.append("horario: la hora límite de tu firma es %s %s (%s NY): ni en ella ni en los %d minutos de antes se abre nada (son las %s)"
                     % (c["hora_limite"], c.get("hora_limite_tz"), comun.hhmm(ctx["hora_limite_ny"]), MARGEN_PLANO_MIN, comun.hhmm(t)))
    return luego


def _plano_de(o, c, por_defecto):
    """La hora de estar plano que antes llega: la del plan, la de la config o la del contrato (CL 14:25, GC 13:25…)."""
    plan = o.get("plan", {}).get("plano_a") if isinstance(o.get("plan"), dict) else None
    horas = [h for h in (plan, c.get("plano_a"), por_defecto) if h]
    return min(horas, key=comun.parse_hhmm)


def _comprobar_futuro(o, ctx):
    """Una orden de futuros (simbolo MNQ, lado compra/venta, contratos…): la comprobación de siempre."""
    c, cfg, t = ctx["c"], ctx["cfg"], ctx["t"]
    motivos, avisos, info, luego = [], [], [], []
    sim = str(o.get("simbolo") or "").strip().upper()
    lado = str(o.get("lado") or "").strip().lower()
    n = o.get("contratos")
    cierre = bool(o.get("cierre"))
    if cierre and not _cierra_algo(sim, lado, n if isinstance(n, int) else None, ctx["abiertas"]):
        # cerrar una posición que el pack no conoce no se bloquea, pero no puede ser más grande que lo que la cuenta deja abrir
        ct0 = contrato_de(sim)
        tope = (c.get("max_mini") if (ct0 and (not ct0[1] or comun.sin_micro(ct0[0]))) else c.get("max_micro")) if ct0 else None
        if tope and isinstance(n, int) and n > int(tope):
            motivos.append("cierre: %d %s, más que el tope de %d de tu cuenta; no puedes tener abiertos más de esos" % (n, sim, int(tope)))
        avisos.append("cierre de %s %s que no está en kemet/estado/dia.json ni en kemet/portfolio.json: comprueba en tu plataforma que esa posición existe; "
                      "si no, esta orden abre una nueva" % (n, sim))
    precio, stop, objetivo = _f(o.get("precio")), _f(o.get("stop")), _f(o.get("objetivo"))
    ct = contrato_de(sim)
    if not ct:
        motivos.append("formato: %r no es un micro ni un mini que conozca (%s); una acción va en el formato de acciones (symbol, side, qty) o con \"instrumento\": \"accion\""
                       % (o.get("simbolo"), ", ".join(sorted(comun.MICRO_A_CODIGO))))
    if lado not in LADOS:
        motivos.append("formato: el lado tiene que ser compra o venta, no %r" % o.get("lado"))
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        motivos.append("formato: contratos tiene que ser un entero mayor que 0, no %r" % (n,))
        n = 0
    if precio is None or precio <= 0:
        motivos.append("formato: precio tiene que ser un número mayor que 0, no %r" % o.get("precio"))
    globex, motivo_globex = ctx["globex"]
    if globex != "abierto":
        (avisos if o.get("cierre") else motivos).append("globex: %s (%s), %s NY" % (globex, motivo_globex, comun.hhmm(t)))
    mercado, es_micro, punto = ct if ct else (None, True, 0.0)
    if ct and mercado != ctx["mercado_cfg"] and cfg:
        avisos.append("la orden es de %s y la config de %s: compruebo con las reglas de la cuenta y las ventanas de %s" % (mercado, ctx["mercado_cfg"], mercado))
    ctx["ventanas"] = ventanas_del_dia(ctx["agenda"], ctx["fecha"], mercado) if ct else []
    perdida = None
    riesgo_pts = None
    if ct and lado in LADOS and precio and cierre:
        info.append("cierre: solo se mira el formato y que Globex esté abierto")
    if ct and lado in LADOS and precio and not cierre:
        largo = lado == "compra"
        if stop is None:
            luego.append("stop: sin stop. Toda entrada lleva su stop puesto en la plataforma antes de confirmarla")
        elif (largo and stop >= precio) or (not largo and stop <= precio):
            luego.append("stop: el stop %s tiene que estar %s de la entrada %s en una %s" % (pts(stop), "debajo" if largo else "encima", pts(precio), lado))
        else:
            tick = comun.tick_de(mercado, es_micro)
            riesgo_pts = _riesgo_al_tick(abs(precio - stop), tick)
            perdida = round(n * riesgo_pts * punto, 2)
            if abs(precio - stop) < tick - 1e-9:
                luego.append("stop: a menos de un tick (%s) de la entrada; un stop así no existe en la plataforma" % pts(tick))
            if objetivo is not None and ((largo and objetivo <= precio) or (not largo and objetivo >= precio)):
                luego.append("objetivo: el objetivo %s tiene que estar %s de la entrada %s" % (pts(objetivo), "encima" if largo else "debajo", pts(precio)))
            if ctx["por_op"] and perdida > ctx["por_op"] + 0.005:
                luego.append("pérdida: %d × %s pts × %s $/pt = %s al stop, más que tu riesgo por operación de %s"
                             % (n, pts(riesgo_pts), num(punto, 0), usd(perdida, 2), usd(ctx["por_op"], 2)))
            if ctx["pmd"]:
                usado = ctx["abierto"] + ctx["realizada"] + ctx["lote_riesgo"]
                if usado + perdida > ctx["pmd"] + 0.005:
                    luego.append("día: %s abierto y perdido hoy más %s de esta = %s, más que tu pérdida máxima del día de %s"
                                 % (usd(usado, 2), usd(perdida, 2), usd(usado + perdida, 2), usd(ctx["pmd"])))
            info.append("entrada %s, stop %s, objetivo %s: riesgo %s pts = %s por %s" % (
                pts(precio), pts(stop), pts(objetivo) if objetivo is not None else "ninguno", pts(riesgo_pts), usd(riesgo_pts * punto, 2), sim))
            info.append("pérdida al stop %s%s" % (usd(perdida, 2), (" (riesgo por operación %s)" % usd(ctx["por_op"], 2)) if ctx["por_op"] else ""))
        fyp = ctx["fyp"]
        if fyp and ctx["entradas_hoy"] + ctx["lote_entradas"] >= fyp:
            luego.append("operaciones: hoy ya hay %d%s y tu regla son %d al día (tres fallos y paras)"
                         % (ctx["entradas_hoy"], (" más %d de este archivo" % ctx["lote_entradas"]) if ctx["lote_entradas"] else "", fyp))
        tope = c.get("max_micro") if es_micro else c.get("max_mini")
        if tope and n > int(tope):
            luego.append("contratos: %d %s, más que el tope de %d %s de tu cuenta" % (n, sim, int(tope), "micros" if es_micro else "minis"))
        elif not tope and cfg:
            avisos.append("tu cuenta no publica tope de %s: mira el de tu panel" % ("micros" if es_micro else "minis"))
        luego.extend(_ventanas_y_horario(ctx, t, comun.CONTRATOS[mercado]["rth"][0], _plano_de(o, c, comun.CONTRATOS[mercado]["plano"]), True))
        if ctx["pmd"] or fyp:
            info.append("hoy antes de esta: %d de %d operaciones, %s abierto, %s perdido, %s de %s del día"
                        % (ctx["entradas_hoy"] + ctx["lote_entradas"], fyp, usd(ctx["abierto"]), usd(ctx["realizada"]), usd(ctx["abierto"] + ctx["realizada"] + ctx["lote_riesgo"]), usd(ctx["pmd"])))
    return {"sim": sim, "lado": lado, "n": o.get("contratos"), "precio": precio, "stop": stop, "objetivo": objetivo, "riesgo_pts": riesgo_pts,
            "perdida": perdida, "cierre": cierre, "instrumento": "futuro", "motivos": motivos, "avisos": avisos, "info": info, "luego": luego, "tipo": o.get("tipo")}


def _comprobar_accion(o, ctx):
    """Una orden de una acción en el formato de place_stock_order de Alpaca (o con instrumento: accion), contra la cuenta propia."""
    c, cfg, t = ctx["c"], ctx["cfg"], ctx["t"]
    motivos, avisos, info, luego = [], [], [], []
    sim = str(o.get("symbol") or o.get("simbolo") or "").strip().upper().replace(" ", "")
    lado = LADO_ALPACA.get(str(o.get("side") or o.get("lado") or "").strip().lower())
    tipo = TIPO_ALPACA.get(str(o.get("type") or o.get("tipo") or "market").strip().lower())
    tif = str(o.get("time_in_force") or "day").strip().lower()
    n = _entero(o.get("qty", o.get("contratos", o.get("cantidad"))))
    plan = o.get("plan") if isinstance(o.get("plan"), dict) else {}
    clase = str(o.get("order_class") or "").strip().lower()
    patas = o.get("take_profit_limit_price") is not None or o.get("stop_loss_stop_price") is not None
    bracket = clase == "bracket" or (not clase and patas)
    cierre_declarado = bool(o.get("cierre"))
    es_opcion = bool(OCC.match(sim))
    # formato
    if not sim:
        motivos.append("formato: sin símbolo")
    elif not es_opcion and not comun._TICKER.match(sim):
        motivos.append("formato: %r no parece un ticker de EE. UU. (TSLA, BRK.B); este pack opera acciones, ETF y futuros" % sim)
    if lado is None:
        motivos.append("formato: side tiene que ser buy o sell, no %r" % (o.get("side") if "side" in o else o.get("lado")))
    if n is None:
        motivos.append("formato: qty tiene que ser un entero mayor que 0 (acciones enteras), no %r" % (o.get("qty", o.get("contratos")),))
    if tipo is None:
        motivos.append("formato: type tiene que ser market o limit, no %r" % o.get("type"))
    if tipo == "limit" and not _f(o.get("limit_price")):
        motivos.append("formato: una orden limit necesita limit_price")
    if tif not in ("day", "gtc"):
        motivos.append("formato: time_in_force tiene que ser day o gtc, no %r" % tif)
    for k, por_que in (("notional", "el tamaño se mide en acciones enteras (qty); una orden por importe no se puede comprobar"),
                       ("extended_hours", "fuera de la sesión regular no se opera con este pack"),
                       ("advanced_instructions", "kemet-riesgo no sabe medirlas"),
                       ("trail_price", "kemet-riesgo no mide un stop móvil"), ("trail_percent", "kemet-riesgo no mide un stop móvil"),
                       ("stop_price", "las entradas van a mercado o limit; el stop va en stop_loss_stop_price")):
        if o.get(k) not in (None, False, "", "false"):
            motivos.append("formato: %s no se admite: %s" % (k, por_que))
    if bracket and not cierre_declarado and (o.get("take_profit_limit_price") is None or o.get("stop_loss_stop_price") is None):
        motivos.append("formato: una orden bracket lleva take_profit_limit_price y stop_loss_stop_price")
    for k in ("qty", "limit_price", "take_profit_limit_price", "stop_loss_stop_price"):
        if o.get(k) is not None:
            v = _f(o.get(k))
            if v is None or v <= 0:
                motivos.append("formato: %s tiene que ser un número mayor que 0, no %r" % (k, o.get(k)))
            elif not isinstance(o.get(k), str):
                avisos.append("%s va como número (%s); place_stock_order lo quiere como texto (\"%s\")" % (k, o.get(k), o.get(k)))
    # el reloj de la NYSE y la cuenta
    nyse, motivo_nyse = ctx["nyse"]
    if nyse != "abierto":
        motivos.append("mercado: NYSE %s (%s), %s NY" % (nyse, motivo_nyse, comun.hhmm(t)))
    if es_opcion:
        if not c.get("permitir_opciones"):
            motivos.append("opciones: %s es un contrato de opciones y tu cuenta no las permite (permitir_opciones: false)" % sim)
        else:
            avisos.append("orden de opciones: se puede perder todo lo pagado")
    if cfg and not ctx["propia"]:
        luego.append("cuenta: tu config es de una cuenta de firma (futuros); para acciones configura una cuenta propia con tamano.py config --propia")
    ctx["ventanas"] = ventanas_del_dia(ctx["agenda"], ctx["fecha"], sim)
    # el precio de referencia: lo que cuesta entrar
    cuenta = ctx["cuenta"]
    precios = ctx["precios"]
    largo = lado == "compra"
    entrada_plan = _f(plan.get("entrada") if plan.get("entrada") is not None else plan.get("entry"))
    fresco = precios.get(sim, (None, False))
    ref, origen = None, None
    if tipo == "limit":
        ref, origen = _f(o.get("limit_price")), "precio límite"
    if ref is None:
        candidatos = [(p, w) for p, w in ((entrada_plan, "entrada del plan"), (fresco[0] if fresco[1] else None, "último precio")) if p]
        if candidatos:
            ref, origen = (max if largo or lado is None else min)(candidatos, key=lambda x: x[0])
            if origen == "último precio" and entrada_plan and abs(ref - entrada_plan) > 0.005:
                info.append("último precio de %s %s, %s de la entrada del plan %s: el riesgo se mide desde %s"
                            % (sim, usd(ref, 2), "por encima" if largo else "por debajo", usd(entrada_plan, 2), usd(ref, 2)))
        elif fresco[0]:
            ref, origen = fresco[0], "precio viejo"
            avisos.append("el precio de %s en kemet/precios.json tiene más de %d minutos: se usa, pero pide uno nuevo (alertas.py quote %s --escribir)" % (sim, PRECIO_FRESCO_MIN, sim))
    valor = round(n * ref, 2) if n and ref else None
    # entrada o cierre
    tiene = cuenta["acciones"].get(sim, 0.0)
    # Un cierre solo es cierre si reduce una posición de kemet/portfolio.json: marcar "cierre": true ya no se salta las reglas.
    cierre = (lado == "venta" and n is not None and 0 < n <= tiene + 1e-9) or (lado == "compra" and tiene < 0 and n is not None and n <= -tiene + 1e-9)
    if cierre:
        info.append("cierre: solo se mira el formato, la NYSE abierta y que no sea un corto (%s %s acciones de %s en kemet/portfolio.json)"
                    % ("vendes" if lado == "venta" else "recompras", n, sim))
    elif cierre_declarado and lado == "venta" and n:
        cierre = True
        avisos.append("cierre de %d %s y en kemet/portfolio.json hay %s: antes de enviarla, get_open_position %s tiene que decir que tienes %d o más; "
                      "si no, esta venta abre un corto" % (n, sim, num(tiene, 0), sim, n))
    elif cierre_declarado:
        avisos.append("marcada como cierre, pero en kemet/portfolio.json no hay un corto de %s que recomprar: la compruebo como entrada" % sim)
    if not cierre and n and ref is None:
        luego.append("precio: sin precio de %s para medir %d acciones: pon la entrada en plan o guarda kemet/precios.json (alertas.py quote %s --escribir)" % (sim, n, sim))
    # lista de bloqueados y tamaño
    if sim in ctx["bloqueados"]:
        luego.append("bloqueado: %s está en tu lista de bloqueados (config: bloqueados)" % sim)
    if valor is not None:
        if c.get("min_orden_usd") and valor < float(c["min_orden_usd"]) - 0.005:
            luego.append("tamaño: %s, menos que tu orden mínima de %s" % (usd(valor, 2), usd(float(c["min_orden_usd"]))))
        if c.get("max_orden_usd") and valor > float(c["max_orden_usd"]) + 0.005:
            luego.append("tamaño: %s, más que tu orden máxima de %s" % (usd(valor, 2), usd(float(c["max_orden_usd"]))))
    # efectivo y posición, simulados en orden
    presupuesto = _f(c.get("presupuesto"))
    efectivo = cuenta["efectivo"]
    if valor is not None and lado == "compra" and not cierre:
        if efectivo is None:
            avisos.append("sin presupuesto en la config ni kemet/portfolio.json: no mido el efectivo ni la posición")
        else:
            colchon = round((presupuesto or efectivo) * float(c.get("efectivo_pct") or 0) / 100.0, 2)
            despues = efectivo - valor
            if despues < -0.005 and not c.get("permitir_margen"):
                luego.append("efectivo: hacen falta %s y hay %s de efectivo; eso sería margen (dinero prestado) y no lo permites" % (usd(valor, 2), usd(efectivo, 2)))
            elif despues < colchon - 0.005:
                luego.append("efectivo: dejaría %s de efectivo, por debajo de tu colchón del %s %% (%s)" % (usd(max(despues, 0), 2), num(float(c.get("efectivo_pct") or 0), 0), usd(colchon)))
            base = presupuesto or (efectivo + sum(cuenta["valores"].values()))
            tope = base * float(c.get("max_posicion_pct") or 100) / 100.0
            pos = cuenta["valores"].get(sim, 0.0) + valor
            if base > 0 and pos > tope + 0.005:
                luego.append("posición: %s sería %s, el %s %% de %s, más que tu tope del %s %% (%s)"
                             % (sim, usd(pos, 2), num(100.0 * pos / base, 1), usd(base), num(float(c.get("max_posicion_pct") or 100), 0), usd(tope)))
    # cortos
    if lado == "venta" and sim and n and not cierre and not c.get("permitir_cortos"):
        luego.append("corto: vendes %d %s y tienes %s; vender en corto no está permitido (permitir_cortos: false). Si las compraste, apunta el fill primero (broker.py registrar)" % (n, sim, num(tiene, 0)))
    # stop, pérdida, día, operaciones, ventanas y horario
    perdida = riesgo = stop = objetivo = None
    if not cierre and lado:
        stop_pata, stop_plan = _f(o.get("stop_loss_stop_price")), _f(plan.get("stop"))
        stop = stop_pata or stop_plan
        objetivo = _f(o.get("take_profit_limit_price")) or _f(plan.get("objetivo") if plan.get("objetivo") is not None else plan.get("target"))
        if stop_pata and stop_plan and abs(stop_pata - stop_plan) > 0.005:
            avisos.append("el stop del bracket %s no es el del plan %s: el bróker usa el del bracket" % (usd(stop_pata, 2), usd(stop_plan, 2)))
        if stop and not stop_pata:
            luego.append("stop: el stop %s está en el plan, no en la orden. Una entrada va como bracket con stop_loss_stop_price, de kemet-tamano" % usd(stop, 2))
        if clase and clase != "bracket":
            luego.append("formato: order_class %r; una entrada va como bracket, con su stop y su objetivo en el bróker" % clase)
        if not stop:
            luego.append("stop: sin stop. Toda entrada lleva su stop: el stop_loss_stop_price del bracket, de kemet-salida y kemet-tamano")
        elif ref:
            if (largo and stop >= ref - 0.005) or (not largo and stop <= ref + 0.005):
                luego.append("stop: el stop %s tiene que estar %s de la entrada %s en una %s" % (usd(stop, 2), "debajo" if largo else "encima", usd(ref, 2), lado))
            else:
                riesgo = round(abs(ref - stop), 2)
                perdida = round((n or 0) * riesgo, 2)
                if objetivo is not None and ((largo and objetivo <= ref + 0.005) or (not largo and objetivo >= ref - 0.005)):
                    luego.append("objetivo: el objetivo %s tiene que estar %s de la entrada %s" % (usd(objetivo, 2), "encima" if largo else "debajo", usd(ref, 2)))
                if ctx["por_op"] and perdida > ctx["por_op"] + 0.005:
                    luego.append("pérdida: %d × %s por acción = %s al stop, más que tu riesgo por operación de %s" % (n or 0, usd(riesgo, 2), usd(perdida, 2), usd(ctx["por_op"], 2)))
                if ctx["pmd"]:
                    usado = ctx["abierto"] + ctx["realizada"] + ctx["lote_riesgo"]
                    if usado + perdida > ctx["pmd"] + 0.005:
                        luego.append("día: %s abierto y perdido hoy más %s de esta = %s, más que tu pérdida máxima del día de %s"
                                     % (usd(usado, 2), usd(perdida, 2), usd(usado + perdida, 2), usd(ctx["pmd"])))
                info.append("entrada %s (%s), stop %s, objetivo %s: riesgo %s por acción" % (usd(ref, 2), origen, usd(stop, 2), usd(objetivo, 2) if objetivo else "ninguno", usd(riesgo, 2)))
                info.append("pérdida al stop %s%s · %d acciones = %s" % (usd(perdida, 2), (" (riesgo por operación %s)" % usd(ctx["por_op"], 2)) if ctx["por_op"] else "", n or 0, usd(valor or 0, 2)))
        fyp = ctx["fyp"]
        if fyp and ctx["entradas_hoy"] + ctx["lote_entradas"] >= fyp:
            luego.append("operaciones: hoy ya hay %d%s y tu regla son %d al día (tres fallos y paras)"
                         % (ctx["entradas_hoy"], (" más %d de este archivo" % ctx["lote_entradas"]) if ctx["lote_entradas"] else "", fyp))
        luego.extend(_ventanas_y_horario(ctx, t, "09:30", _plano_de(o, c, "15:55"), False))
        if ctx["pmd"] or fyp:
            info.append("hoy antes de esta: %d de %d operaciones, %s abierto, %s perdido, %s de %s del día"
                        % (ctx["entradas_hoy"] + ctx["lote_entradas"], fyp, usd(ctx["abierto"]), usd(ctx["realizada"]), usd(ctx["abierto"] + ctx["realizada"] + ctx["lote_riesgo"]), usd(ctx["pmd"])))
    return {"sim": sim, "lado": lado or str(o.get("side") or ""), "n": n if n is not None else o.get("qty"), "precio": ref, "stop": stop, "objetivo": objetivo, "riesgo_pts": riesgo,
            "perdida": perdida, "cierre": cierre, "instrumento": "accion", "motivos": motivos, "avisos": avisos, "info": info, "luego": luego,
            "tipo": tipo or o.get("type"), "valor": valor, "lado_alpaca": LADO_ALPACA_INV.get(lado), "ref_origen": origen,
            "efecto": (sim, lado, n or 0, valor or 0.0) if lado and n else None}


def fecha_de(ny, cfg, ordenes=()):
    """El día de las reglas: el de CME (empieza a las 18:00 NY de la víspera) en una cuenta de futuros; el natural en acciones."""
    acciones = any(es_orden_accion(o) for o in ordenes) or (cfg or {}).get("tipo_cuenta") == "propia" or (cfg or {}).get("cuenta") == "propia"
    return (ny.date() if acciones else comun.dia_negociacion(ny)).isoformat()


def check(ordenes, cfg, agenda=None, dia=None, ahora_utc=None, broker=None, cartera=None, precios=None, sesion=None):
    """Pura. Devuelve {"fecha", "ahora_ny", "papel", "resultados": [...], "pass", "block", "avisos", "hoy"}.
    `broker` es kemet/estado/broker.json (lo colocado hoy), `cartera` kemet/portfolio.json y `precios` kemet/precios.json."""
    hay_acciones = any(es_orden_accion(o) for o in ordenes)
    propia = bool(cfg) and (cfg.get("tipo_cuenta") == "propia" or cfg.get("cuenta") == "propia")
    c = dict(DEFECTO_PROPIA if (hay_acciones and not cfg) else DEFECTO)
    c.update(cfg or {})
    ahora_utc = ahora_utc or comun.utc_ahora()
    ny = comun.a_ny(ahora_utc)
    fecha, t = fecha_de(ny, cfg, ordenes), ny.time().replace(second=0, microsecond=0)
    dia = dia if dia and str(dia.get("fecha")) == fecha else {"fecha": fecha, "operaciones": []}
    ops_hoy = dia.get("operaciones") or []
    abierto = sum(_f(o.get("riesgo_usd")) or 0.0 for o in ops_hoy if not o.get("cerrada"))
    neto = sum(_f(o.get("resultado_usd")) or 0.0 for o in ops_hoy if o.get("cerrada"))
    realizada = max(0.0, -neto)
    huellas_hoy = {o.get("huella") for o in ops_hoy if o.get("huella")}
    entradas_hoy = len(ops_hoy)
    colocadas = colocadas_hoy(broker, fecha)
    claves_colocadas = set()
    avisos_top = []
    for o in colocadas:
        s = str(o.get("simbolo") or o.get("symbol") or "").upper()
        l = str(o.get("lado") or o.get("side") or "").lower()
        claves_colocadas.add((s, LADO_ALPACA.get(l, l)))
        if o.get("huella") in huellas_hoy:
            continue
        if o.get("huella"):
            huellas_hoy.add(o["huella"])
        if o.get("clase") == "cierre" or o.get("cierre") or LADO_ALPACA.get(l, l) == "venta":
            continue
        entradas_hoy += 1
        r = _f(o.get("perdida_al_stop")) or _f(o.get("riesgo_usd")) or _f(o.get("perdida_max_usd"))
        if r is None:
            avisos_top.append("una orden colocada hoy (%s %s, kemet/estado/broker.json) no trae su pérdida al stop: cuenta como operación, no en el día; apúntala con registrar --abrir" % (l or "?", s or "?"))
        else:
            abierto += r
    pmd = _f(c.get("perdida_max_dia")) or 0.0
    sem = str((sesion or {}).get("semaforo") or "verde") if isinstance(sesion, dict) and str(sesion.get("fecha")) == fecha else "verde"
    if sem in ("ambar", "rojo") and str(c.get("semaforo") or "verde") == "verde" and pmd:
        avisos_top.append("semáforo %s en el plan de hoy (kemet/plan-sesion.json): la pérdida máxima del día baja a la mitad, de %s a %s"
                          % ({"ambar": "ámbar"}.get(sem, sem), usd(pmd), usd(pmd / 2.0)))
        pmd = round(pmd / 2.0, 2)
        mitad = True
    else:
        mitad = False
    fyp = int(c.get("fallos_y_paras") or FALLOS_Y_PARAS)
    por_op = _f(c.get("riesgo_por_operacion")) if propia and c.get("riesgo_por_operacion") else (pmd / fyp if pmd else None)
    if mitad and propia and c.get("riesgo_por_operacion") and por_op:
        por_op = round(por_op / 2.0, 2)
    if not cfg:
        if hay_acciones:
            avisos_top.append("sin kemet/config.json: compruebo con los valores por defecto de una cuenta propia (pérdida máxima del día %s, %s por operación, tres fallos y paras); ejecuta tamano.py config --propia" % (usd(pmd), usd(por_op or 0)))
        else:
            avisos_top.append("sin kemet/config.json: compruebo con los valores por defecto (pérdida máxima del día %s, tres fallos y paras); ejecuta tamano.py config" % usd(pmd))
    if not c.get("papel", True):
        avisos_top.append("cuenta REAL (papel: false): estas órdenes van con dinero de verdad")
    if c.get("consistencia"):
        avisos_top.append("consistencia de la firma: %s. No se puede medir aquí: mírala en tu panel antes de pedir un cobro" % c["consistencia"])
    hora_limite_ny = None
    if c.get("hora_limite"):
        hora_limite_ny = hora_a_ny(c["hora_limite"], c.get("hora_limite_tz"))
        if c.get("hora_limite_tz") == "America/Chicago":
            avisos_top.append("hora límite de la firma %s Chicago = %s NY" % (c["hora_limite"], comun.hhmm(hora_limite_ny)))
    if agenda and str(agenda.get("fecha")) != fecha:
        avisos_top.append("kemet/agenda.json es del %s, no de hoy: no conozco los datos de hoy" % agenda.get("fecha"))
    elif not agenda:
        avisos_top.append("sin kemet/agenda.json: no conozco los datos de hoy, solo la ventana de la apertura")
    ctx = {"c": c, "cfg": cfg, "fecha": fecha, "t": t, "agenda": agenda, "ventanas": [], "globex": comun.estado_globex(ahora_utc), "nyse": comun.estado_nyse(ahora_utc),
           "hora_limite_ny": hora_limite_ny, "mercado_cfg": (c.get("mercado") or "NQ").upper(), "pmd": pmd, "fyp": fyp, "por_op": por_op,
           "abierto": abierto, "realizada": realizada, "entradas_hoy": entradas_hoy, "lote_entradas": 0, "lote_riesgo": 0.0, "propia": propia,
           "bloqueados": {str(b).upper() for b in c.get("bloqueados") or []}, "precios": {}, "cuenta": None,
           "abiertas": [o for o in ops_hoy if isinstance(o, dict) and not o.get("cerrada")] + _posiciones_futuro(cartera)}
    if hay_acciones:
        ctx["precios"] = precios_de(precios, ahora_utc)
        ctx["cuenta"] = cuenta_propia(cartera, c, {s: p for s, (p, fresco) in ctx["precios"].items() if fresco})
        if cartera is None and not c.get("presupuesto"):
            avisos_top.append("sin kemet/portfolio.json ni presupuesto: no mido el efectivo ni el tope de posición")

    resultados, vistas = [], set()
    for i, o in enumerate(ordenes, 1):
        r = _comprobar_accion(o, ctx) if es_orden_accion(o) else _comprobar_futuro(o, ctx)
        motivos, avisos, info, luego, cierre = r["motivos"], r["avisos"], r["info"], r["luego"], r["cierre"]
        h = huella(o)
        if h in vistas:
            luego.append("duplicado: la misma orden aparece dos veces en el archivo")
        if h in huellas_hoy:
            luego.append("duplicado: esta misma orden (huella %s) ya está apuntada hoy en kemet/estado/dia.json" % h)
        elif (r["sim"], r["lado"]) in claves_colocadas and not cierre:
            luego.append("duplicado: hoy ya se colocó una %s de %s (kemet/estado/broker.json)" % (r["lado"], r["sim"]))
        vistas.add(h)
        if cierre:
            avisos.extend("cierre, no bloquea: " + x for x in luego)
        else:
            motivos.extend(luego)
        veredicto = "BLOCK" if motivos else "PASS"
        if veredicto == "PASS" and not cierre and r["perdida"] is not None:
            ctx["lote_entradas"] += 1
            ctx["lote_riesgo"] += r["perdida"]
        if veredicto == "PASS" and r.get("efecto") and ctx["cuenta"]:
            sim, lado, n, valor = r["efecto"]
            cu = ctx["cuenta"]
            signo = 1 if lado == "compra" else -1
            cu["acciones"][sim] = cu["acciones"].get(sim, 0.0) + signo * n
            if cu["efectivo"] is not None:
                cu["efectivo"] -= signo * valor
            cu["valores"][sim] = max(cu["valores"].get(sim, 0.0) + signo * valor, 0.0)
        res = {"indice": i, "simbolo": r["sim"], "lado": r["lado"], "contratos": r["n"], "tipo": r["tipo"],
               "precio": r["precio"], "stop": r["stop"], "objetivo": r["objetivo"], "riesgo_pts": r["riesgo_pts"], "perdida_max_usd": r["perdida"],
               "clase": "cierre" if cierre else "entrada", "instrumento": r["instrumento"], "huella": h, "veredicto": veredicto,
               "motivos": motivos, "avisos": avisos, "info": info, "orden": o}
        if r["instrumento"] == "accion":
            res["valor_usd"] = r.get("valor")
        resultados.append(res)
    return {"fecha": fecha, "ahora_ny": ny.strftime("%Y-%m-%d %H:%M"), "ahora": comun.hora_doble(ahora_utc), "papel": bool(c.get("papel", True)),
            "cuenta": c.get("cuenta_nombre"), "resultados": resultados,
            "pass": sum(1 for r in resultados if r["veredicto"] == "PASS"), "block": sum(1 for r in resultados if r["veredicto"] == "BLOCK"),
            "avisos": avisos_top, "hoy": {"operaciones": entradas_hoy, "riesgo_abierto": round(abierto, 2), "perdida_realizada": round(realizada, 2),
                                          "perdida_max_dia": pmd, "queda": round(pmd - abierto - realizada, 2) if pmd else None,
                                          "colocadas_broker": len(colocadas)}}

def informe(res):
    lineas = ["RIESGO · %s · %s · %s" % (res.get("cuenta") or "sin cuenta", res["fecha"], res["ahora"])]
    for a in res["avisos"]:
        lineas.append("AVISO: " + a)
    lineas.append("")
    for r in res["resultados"]:
        lineas.append("%-5s #%d %s %s %s, %s" % (r["veredicto"], r["indice"], r["lado"], r["contratos"], r["simbolo"], r["clase"]))
        for x in r["info"]:
            lineas.append("          " + x)
        for x in r["motivos"]:
            lineas.append("        - " + x)
        for x in r["avisos"]:
            lineas.append("        ~ " + x)
    lineas.append("")
    lineas.append("%d PASS, %d BLOCK a las %s NY (%s)." % (res["pass"], res["block"], res["ahora_ny"][-5:], "simulación" if res["papel"] else "cuenta REAL"))
    if res["block"]:
        lineas.append("Una orden con BLOCK no se pone. Cambia la orden o espera; las reglas no se tocan a media sesión.")
    else:
        lineas.append("Todo PASS. Un PASS es una comprobación de reglas, no una recomendación: la pones tú, con su stop, y la apuntas con `registrar --abrir`.")
    return "\n".join(lineas)


# ---------------------------------------------------------------- subcomandos

def cmd_check(a):
    ahora = comun.parse_ahora(a.ahora)
    doc = comun.leer_json(comun.dada(a.orden) or "orden.json", "ejecuta tamano.py orden --escribir")
    ordenes = doc.get("ordenes") if isinstance(doc, dict) else doc
    if not isinstance(ordenes, list) or not ordenes:
        raise KemetError("no hay órdenes en %s" % (a.orden or comun.ruta("orden.json")))
    cfg, existe = cargar_config()
    fecha = fecha_de(comun.a_ny(ahora), cfg if existe else None, ordenes)
    agenda = comun.leer_json("agenda.json", obligatorio=False)
    dia = leer_dia(fecha)
    broker = comun.leer_json(comun.ruta(BROKER), obligatorio=False)
    cartera = comun.leer_json(comun.ruta("portfolio.json"), obligatorio=False)
    precios = comun.leer_json(comun.ruta("precios.json"), obligatorio=False)
    sesion = comun.leer_json("plan-sesion.json", obligatorio=False)
    res = check(ordenes, cfg if existe else None, agenda, dia, ahora, broker, cartera, precios, sesion)
    if not a.sin_escribir:
        rec = dict(res)
        rec["resultados"] = [{k: v for k, v in r.items()} for r in res["resultados"]]
        rec["comprobado"] = comun.iso(ahora)
        rec["simulado"] = bool(a.ahora)                 # un check con --ahora no vale para el bróker
        rec["dia_huella"] = comun.huella_dia(comun.leer_json(comun.ruta(DIA), obligatorio=False))
        comun.escribir_json(comun.ruta(RIESGO), rec)
    print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else informe(res))
    return 1 if res["block"] else 0


def cmd_registrar(a):
    ahora = comun.parse_ahora(a.ahora)
    ny = comun.a_ny(ahora)
    cfg_r, existe_r = cargar_config()
    ver_previo = comun.leer_json(comun.ruta(RIESGO), obligatorio=False) or {}
    ordenes_previas = [r.get("orden") for r in ver_previo.get("resultados") or [] if isinstance(r, dict)]
    fecha = fecha_de(ny, cfg_r if existe_r else None, [o for o in ordenes_previas if o])
    hora = a.hora or comun.hhmm(ny)
    comun.parse_hhmm(hora, "--hora")
    dia = leer_dia(fecha)
    if a.abrir:
        ver = comun.leer_json(comun.ruta(RIESGO), "ejecuta riesgo.py check primero", obligatorio=True)
        if str(ver.get("fecha")) != fecha:
            raise KemetError("el último check es del %s, no de hoy: repite riesgo.py check" % ver.get("fecha"))
        ya = {o.get("huella") for o in dia["operaciones"]}
        nuevas = []
        for r in ver.get("resultados", []):
            if r.get("veredicto") != "PASS" or r.get("clase") == "cierre":
                continue
            if r["huella"] in ya:
                print("ya apuntada: %s %s %s (huella %s)" % (r["lado"], r["contratos"], r["simbolo"], r["huella"]))
                continue
            op = {"hora": hora, "simbolo": r["simbolo"], "lado": r["lado"], "contratos": r["contratos"], "entrada": r["precio"],
                  "stop": r["stop"], "objetivo": r["objetivo"], "riesgo_usd": r["perdida_max_usd"], "resultado_usd": None,
                  "cerrada": None, "huella": r["huella"]}
            if r.get("instrumento") == "accion":
                op["instrumento"] = "accion"
            nuevas.append(op)
        if not nuevas:
            raise KemetError("no hay ninguna entrada con PASS en el último check que no esté ya apuntada")
        dia["operaciones"].extend(nuevas)
        recalcular(dia)
        p = comun.escribir_json(comun.ruta(DIA), dia)
        for o in nuevas:
            print("Abierta a las %s NY: %s %d %s a %s, stop %s, riesgo %s (huella %s)" % (o["hora"], o["lado"], o["contratos"], o["simbolo"], pts(o["entrada"]), pts(o["stop"]), usd(o["riesgo_usd"], 2), o["huella"]))
        print("Apuntado en %s · riesgo abierto %s · pérdida realizada %s" % (p, usd(dia["riesgo_abierto"], 2), usd(dia["perdida_realizada"], 2)))
        return 0
    if a.resultado is None:
        raise KemetError("di qué apunto: --abrir, o --resultado USD (negativo si es pérdida)")
    if not [o for o in dia["operaciones"] if not o.get("cerrada")] and fecha != ny.date().isoformat():
        previo = comun.leer_json(comun.ruta(DIA), obligatorio=False)
        if isinstance(previo, dict) and str(previo.get("fecha")) == ny.date().isoformat():
            dia, fecha = previo, ny.date().isoformat()      # después de las 18:00 NY: se cierra la operación de la sesión de hoy
            dia.setdefault("operaciones", [])
    abiertas = [o for o in dia["operaciones"] if not o.get("cerrada")]
    if not abiertas:
        raise KemetError("no hay ninguna operación abierta hoy en %s" % comun.ruta(DIA))
    op = abiertas[-1]
    op["resultado_usd"] = round(float(a.resultado), 2)
    op["cerrada"] = hora
    recalcular(dia)
    p = comun.escribir_json(comun.ruta(DIA), dia)
    print("Cerrada a las %s NY: %s %d %s de las %s, resultado %s" % (hora, op["lado"], op["contratos"], op["simbolo"], op["hora"], usd(op["resultado_usd"], 2)))
    print(resumen_dia(dia, cargar_config()[0]))
    return 0


def resumen_dia(dia, cfg):
    ops = dia.get("operaciones") or []
    pmd = _f(cfg.get("perdida_max_dia")) or 0.0
    fyp = int(cfg.get("fallos_y_paras") or FALLOS_Y_PARAS)
    recalcular(dia)
    queda = round(pmd - dia["riesgo_abierto"] - dia["perdida_realizada"], 2)
    fallos = sum(1 for o in ops if o.get("cerrada") and (_f(o.get("resultado_usd")) or 0) < 0)
    lineas = ["HOY · %s · %s" % (cfg.get("cuenta_nombre") or "sin cuenta", dia["fecha"])]
    for i, o in enumerate(ops, 1):
        estado = ("cerrada %s, %s" % (o["cerrada"], usd(o["resultado_usd"], 2))) if o.get("cerrada") else "abierta"
        lineas.append("  %d. %s %s %d %s a %s, stop %s, riesgo %s · %s" % (i, o.get("hora"), o.get("lado"), o.get("contratos") or 0, o.get("simbolo"), pts(_f(o.get("entrada")) or 0), pts(_f(o.get("stop")) or 0), usd(_f(o.get("riesgo_usd")) or 0, 2), estado))
    if not ops:
        lineas.append("  sin operaciones apuntadas")
    lineas.append("Operaciones: %d de %d · pérdidas: %d · riesgo abierto %s · pérdida realizada %s (neto %s)"
                  % (len(ops), fyp, fallos, usd(dia["riesgo_abierto"], 2), usd(dia["perdida_realizada"], 2), usd(dia["resultado_neto"], 2)))
    parar = []
    if pmd and queda <= 0:
        parar.append("la pérdida máxima del día (%s) está agotada" % usd(pmd))
    if len(ops) >= fyp:
        parar.append("ya van %d operaciones" % len(ops))
    if fallos >= fyp:
        parar.append("tres fallos")
    if parar:
        lineas.append("Toca parar: %s. Cierra la plataforma; mañana hay otra sesión." % " y ".join(parar))
    else:
        lineas.append("Queda del día: %s de %s · %d operaci%s más como mucho" % (usd(max(queda, 0), 2), usd(pmd), fyp - len(ops), "ón" if fyp - len(ops) == 1 else "ones"))
    dia["_parar"] = bool(parar)
    return "\n".join(lineas)


def cmd_hoy(a):
    ahora = comun.parse_ahora(a.ahora)
    cfg, existe = cargar_config()
    fecha = fecha_de(comun.a_ny(ahora), cfg if existe else None)
    dia = leer_dia(fecha)
    if a.json:
        recalcular(dia)
        print(json.dumps(dia, ensure_ascii=False, indent=1))
        return 0
    if not existe:
        print("AVISO: sin kemet/config.json, pérdida máxima del día por defecto %s" % usd(DEFECTO["perdida_max_dia"]))
    print(resumen_dia(dia, cfg))
    return 1 if dia.get("_parar") else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="PASS o BLOCK por orden antes de ponerla (kemet-riesgo).")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("check", help="comprueba kemet/orden.json")
    p.add_argument("--orden", help="otro archivo de órdenes (por defecto kemet/orden.json)")
    p.add_argument("--ahora", help="hora de Nueva York, AAAA-MM-DD HH:MM")
    p.add_argument("--sin-escribir", dest="sin_escribir", action="store_true", help="no guardar los veredictos")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("registrar", help="apunta en kemet/estado/dia.json lo que pusiste o cerraste")
    p.add_argument("--abrir", action="store_true", help="la orden que pasó el último check ya está puesta")
    p.add_argument("--resultado", type=float, help="resultado en dólares de la última operación abierta (negativo = pérdida)")
    p.add_argument("--hora", help="HH:MM NY (por defecto ahora)")
    p.add_argument("--ahora", help="hora de Nueva York, AAAA-MM-DD HH:MM")
    p = sub.add_parser("hoy", help="el día: operaciones, riesgo, lo que queda")
    p.add_argument("--ahora", help="hora de Nueva York, AAAA-MM-DD HH:MM")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    try:
        return {"check": cmd_check, "registrar": cmd_registrar, "hoy": cmd_hoy}[a.cmd](a)
    except KemetError as e:
        print("riesgo.py: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
