#!/usr/bin/env python3
"""PASS o BLOCK para cada orden de kemet/orden.json antes de que la pongas en tu plataforma.

Solo biblioteca estándar, sin red. Lee y escribe en `kemet/` del directorio actual (variable KEMET_DIR).

    python3 riesgo.py check                          # kemet/orden.json contra tus reglas; escribe kemet/estado/riesgo.json
    python3 riesgo.py check --ahora "2026-11-11 10:40" --sin-escribir
    python3 riesgo.py registrar --abrir              # la orden que pasó ya está puesta: apúntala como abierta
    python3 riesgo.py registrar --resultado -120 --hora 11:05   # cierra la última abierta con su resultado
    python3 riesgo.py hoy                            # el día: operaciones, riesgo abierto, pérdida, lo que queda

Entradas y cierres. Una orden con `"cierre": true` solo saca de una posición: se le mira el formato y que Globex esté
abierto; todo lo demás se convierte en aviso. Salir siempre tiene que ser posible.

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
import os
import sys

import comun
from comun import KemetError, num, pts, usd

FALLOS_Y_PARAS = 3
DEFECTO = {"mercado": "NQ", "cuenta_nombre": "sin cuenta configurada", "perdida_max_dia": 500, "fallos_y_paras": FALLOS_Y_PARAS,
           "max_micro": None, "max_mini": None, "hora_limite": None, "hora_limite_tz": "America/New_York",
           "sin_entradas_antes": "09:45", "sin_entradas_despues": "15:00", "plano_a": None, "consistencia": None, "papel": True}
CAMPOS_HUELLA = ("simbolo", "lado", "contratos", "tipo", "precio", "stop", "objetivo", "cierre")
APERTURA_MIN = 15
LADOS = ("compra", "venta")
DIA = os.path.join("estado", "dia.json")
RIESGO = os.path.join("estado", "riesgo.json")


# ---------------------------------------------------------------- utilidades

def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def huella(orden):
    """sha1 de los campos de la orden (los que importan para ponerla): la misma orden da la misma huella."""
    core = {k: orden[k] for k in CAMPOS_HUELLA if k in orden and orden[k] is not None}
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

def check(ordenes, cfg, agenda=None, dia=None, ahora_utc=None):
    """Pura. Devuelve {"fecha", "ahora_ny", "papel", "resultados": [...], "pass", "block", "avisos", "hoy"}."""
    c = dict(DEFECTO)
    c.update(cfg or {})
    ahora_utc = ahora_utc or comun.utc_ahora()
    ny = comun.a_ny(ahora_utc)
    fecha, t = ny.date().isoformat(), ny.time().replace(second=0, microsecond=0)
    dia = dia if dia and str(dia.get("fecha")) == fecha else {"fecha": fecha, "operaciones": []}
    ops_hoy = dia.get("operaciones") or []
    abierto = sum(_f(o.get("riesgo_usd")) or 0.0 for o in ops_hoy if not o.get("cerrada"))
    neto = sum(_f(o.get("resultado_usd")) or 0.0 for o in ops_hoy if o.get("cerrada"))
    realizada = max(0.0, -neto)
    huellas_hoy = {o.get("huella") for o in ops_hoy if o.get("huella")}
    pmd = _f(c.get("perdida_max_dia")) or 0.0
    fyp = int(c.get("fallos_y_paras") or FALLOS_Y_PARAS)
    por_op = pmd / fyp if pmd else None
    avisos_top = []
    if not cfg:
        avisos_top.append("sin kemet/config.json: compruebo con los valores por defecto (pérdida máxima del día %s, tres fallos y paras); ejecuta tamano.py config" % usd(pmd))
    if not c.get("papel", True):
        avisos_top.append("cuenta REAL (papel: false): estas órdenes van con dinero de verdad")
    if c.get("consistencia"):
        avisos_top.append("consistencia de la firma: %s. No se puede medir aquí: mírala en tu panel antes de pedir un cobro" % c["consistencia"])
    globex, motivo_globex = comun.estado_globex(ahora_utc)
    hora_limite_ny = None
    if c.get("hora_limite"):
        hora_limite_ny = hora_a_ny(c["hora_limite"], c.get("hora_limite_tz"))
        if c.get("hora_limite_tz") == "America/Chicago":
            avisos_top.append("hora límite de la firma %s Chicago = %s NY" % (c["hora_limite"], comun.hhmm(hora_limite_ny)))
    mercado_cfg = (c.get("mercado") or "NQ").upper()
    if agenda and str(agenda.get("fecha")) != fecha:
        avisos_top.append("kemet/agenda.json es del %s, no de hoy: no conozco los datos de hoy" % agenda.get("fecha"))
    elif not agenda:
        avisos_top.append("sin kemet/agenda.json: no conozco los datos de hoy, solo la ventana de la apertura")

    resultados, vistas = [], set()
    lote_entradas, lote_riesgo = 0, 0.0
    for i, o in enumerate(ordenes, 1):
        motivos, avisos, info, luego = [], [], [], []
        cierre = bool(o.get("cierre"))
        sim = str(o.get("simbolo") or "").strip().upper()
        lado = str(o.get("lado") or "").strip().lower()
        n = o.get("contratos")
        precio, stop, objetivo = _f(o.get("precio")), _f(o.get("stop")), _f(o.get("objetivo"))
        ct = contrato_de(sim)
        if not ct:
            motivos.append("formato: %r no es un micro ni un mini que conozca (%s)" % (o.get("simbolo"), ", ".join(sorted(comun.MICRO_A_CODIGO))))
        if lado not in LADOS:
            motivos.append("formato: el lado tiene que ser compra o venta, no %r" % o.get("lado"))
        if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
            motivos.append("formato: contratos tiene que ser un entero mayor que 0, no %r" % (n,))
            n = 0
        if precio is None or precio <= 0:
            motivos.append("formato: precio tiene que ser un número mayor que 0, no %r" % o.get("precio"))
        if globex != "abierto":
            motivos.append("globex: %s (%s), %s NY" % (globex, motivo_globex, comun.hhmm(t)))
        mercado, es_micro, punto = ct if ct else (None, True, 0.0)
        if ct and mercado != mercado_cfg and cfg:
            avisos.append("la orden es de %s y la config de %s: compruebo con las reglas de la cuenta y las ventanas de %s" % (mercado, mercado_cfg, mercado))
        ventanas = ventanas_del_dia(agenda, fecha, mercado) if ct else []
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
                riesgo_pts = comun.al_tick(abs(precio - stop), comun.CONTRATOS[mercado]["tick"])
                perdida = round(n * riesgo_pts * punto, 2)
                if objetivo is not None and ((largo and objetivo <= precio) or (not largo and objetivo >= precio)):
                    luego.append("objetivo: el objetivo %s tiene que estar %s de la entrada %s" % (pts(objetivo), "encima" if largo else "debajo", pts(precio)))
                if por_op and perdida > por_op + 0.005:
                    luego.append("pérdida: %d × %s pts × %s $/pt = %s al stop, más que tu riesgo por operación de %s"
                                 % (n, pts(riesgo_pts), num(punto, 0), usd(perdida, 2), usd(por_op, 2)))
                if pmd:
                    usado = abierto + realizada + lote_riesgo
                    if usado + perdida > pmd + 0.005:
                        luego.append("día: %s abierto y perdido hoy más %s de esta = %s, más que tu pérdida máxima del día de %s"
                                     % (usd(usado, 2), usd(perdida, 2), usd(usado + perdida, 2), usd(pmd)))
                info.append("entrada %s, stop %s, objetivo %s: riesgo %s pts = %s por %s" % (
                    pts(precio), pts(stop), pts(objetivo) if objetivo is not None else "ninguno", pts(riesgo_pts), usd(riesgo_pts * punto, 2), sim))
                info.append("pérdida al stop %s%s" % (usd(perdida, 2), (" (riesgo por operación %s)" % usd(por_op, 2)) if por_op else ""))
            if fyp and len(ops_hoy) + lote_entradas >= fyp:
                luego.append("operaciones: hoy ya hay %d%s y tu regla son %d al día (tres fallos y paras)"
                             % (len(ops_hoy), (" más %d de este archivo" % lote_entradas) if lote_entradas else "", fyp))
            tope = c.get("max_micro") if es_micro else c.get("max_mini")
            if tope and n > int(tope):
                luego.append("contratos: %d %s, más que el tope de %d %s de tu cuenta" % (n, sim, int(tope), "micros" if es_micro else "minis"))
            elif not tope and cfg:
                avisos.append("tu cuenta no publica tope de %s: mira el de tu panel" % ("micros" if es_micro else "minis"))
            # ventanas
            apertura = comun.parse_hhmm(comun.CONTRATOS[mercado]["rth"][0])
            if apertura <= t < mas_min(apertura, APERTURA_MIN):
                luego.append("ventana: apertura %s–%s NY, los quince minutos más bruscos del día (son las %s)"
                             % (comun.hhmm(apertura), comun.hhmm(mas_min(apertura, APERTURA_MIN)), comun.hhmm(t)))
            for desde, hasta, motivo in ventanas:
                if desde <= t <= hasta:
                    luego.append("ventana: %s, de %s a %s NY no se abre ni se mantiene (son las %s)" % (motivo, comun.hhmm(desde), comun.hhmm(hasta), comun.hhmm(t)))
            # horario
            antes = comun.parse_hhmm(c["sin_entradas_antes"]) if c.get("sin_entradas_antes") else None
            despues = comun.parse_hhmm(c["sin_entradas_despues"]) if c.get("sin_entradas_despues") else None
            if antes and t < antes:
                luego.append("horario: sin entradas antes de las %s NY (son las %s)" % (comun.hhmm(antes), comun.hhmm(t)))
            if despues and t > despues:
                luego.append("horario: sin entradas después de las %s NY (son las %s)" % (comun.hhmm(despues), comun.hhmm(t)))
            plano = o.get("plan", {}).get("plano_a") if isinstance(o.get("plan"), dict) else None
            plano = plano or c.get("plano_a") or comun.CONTRATOS[mercado]["plano"]
            if c.get("plano_a") and comun.parse_hhmm(c["plano_a"]) < comun.parse_hhmm(plano):
                plano = c["plano_a"]
            if t >= comun.parse_hhmm(plano):
                luego.append("horario: a las %s NY se está plano, no se abre nada (son las %s)" % (plano, comun.hhmm(t)))
            if hora_limite_ny and t >= hora_limite_ny:
                luego.append("horario: la hora límite de tu firma es %s %s (%s NY) y son las %s" % (c["hora_limite"], c.get("hora_limite_tz"), comun.hhmm(hora_limite_ny), comun.hhmm(t)))
            if pmd or fyp:
                info.append("hoy antes de esta: %d de %d operaciones, %s abierto, %s perdido, %s de %s del día"
                            % (len(ops_hoy) + lote_entradas, fyp, usd(abierto), usd(realizada), usd(abierto + realizada + lote_riesgo), usd(pmd)))
        h = huella(o)
        if h in vistas:
            luego.append("duplicado: la misma orden aparece dos veces en el archivo")
        if h in huellas_hoy:
            luego.append("duplicado: esta misma orden (huella %s) ya está apuntada hoy en kemet/estado/dia.json" % h)
        vistas.add(h)
        if cierre:
            avisos.extend("cierre, no bloquea: " + x for x in luego)
        else:
            motivos.extend(luego)
        veredicto = "BLOCK" if motivos else "PASS"
        if veredicto == "PASS" and not cierre and perdida is not None:
            lote_entradas += 1
            lote_riesgo += perdida
        resultados.append({"indice": i, "simbolo": sim, "lado": lado, "contratos": o.get("contratos"), "tipo": o.get("tipo"),
                           "precio": precio, "stop": stop, "objetivo": objetivo, "riesgo_pts": riesgo_pts, "perdida_max_usd": perdida,
                           "clase": "cierre" if cierre else "entrada", "huella": h, "veredicto": veredicto,
                           "motivos": motivos, "avisos": avisos, "info": info, "orden": o})
    return {"fecha": fecha, "ahora_ny": ny.strftime("%Y-%m-%d %H:%M"), "ahora": comun.hora_doble(ahora_utc), "papel": bool(c.get("papel", True)),
            "cuenta": c.get("cuenta_nombre"), "resultados": resultados,
            "pass": sum(1 for r in resultados if r["veredicto"] == "PASS"), "block": sum(1 for r in resultados if r["veredicto"] == "BLOCK"),
            "avisos": avisos_top, "hoy": {"operaciones": len(ops_hoy), "riesgo_abierto": round(abierto, 2), "perdida_realizada": round(realizada, 2),
                                          "perdida_max_dia": pmd, "queda": round(pmd - abierto - realizada, 2) if pmd else None}}


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
    fecha = comun.a_ny(ahora).date().isoformat()
    doc = comun.leer_json(a.orden or "orden.json", "ejecuta tamano.py orden --escribir")
    ordenes = doc.get("ordenes") if isinstance(doc, dict) else doc
    if not isinstance(ordenes, list) or not ordenes:
        raise KemetError("no hay órdenes en %s" % (a.orden or comun.ruta("orden.json")))
    cfg, existe = cargar_config()
    agenda = comun.leer_json("agenda.json", obligatorio=False)
    dia = leer_dia(fecha)
    res = check(ordenes, cfg if existe else None, agenda, dia, ahora)
    if not a.sin_escribir:
        rec = dict(res)
        rec["resultados"] = [{k: v for k, v in r.items()} for r in res["resultados"]]
        rec["comprobado"] = comun.iso(ahora)
        comun.escribir_json(comun.ruta(RIESGO), rec)
    print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else informe(res))
    return 1 if res["block"] else 0


def cmd_registrar(a):
    ahora = comun.parse_ahora(a.ahora)
    ny = comun.a_ny(ahora)
    fecha = ny.date().isoformat()
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
            nuevas.append({"hora": hora, "simbolo": r["simbolo"], "lado": r["lado"], "contratos": r["contratos"], "entrada": r["precio"],
                           "stop": r["stop"], "objetivo": r["objetivo"], "riesgo_usd": r["perdida_max_usd"], "resultado_usd": None,
                           "cerrada": None, "huella": r["huella"]})
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
    fecha = comun.a_ny(ahora).date().isoformat()
    dia = leer_dia(fecha)
    cfg, existe = cargar_config()
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
