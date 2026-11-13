#!/usr/bin/env python3
"""El plan de sesión escrito antes de abrir: franjas, ventanas sin operar, semáforo, niveles, tamaño y hora límite.

    python3 plan.py plan                                  # el mercado de kemet/config.json (NQ si no hay)
    python3 plan.py plan --stop 40 --escribir             # con el tamaño en contratos y guarda kemet/plan-sesion.json
    python3 plan.py plan --mercado ES --semaforo ambar    # fuerza el semáforo
    python3 plan.py plan --stop 40 --drawdown 2500 --diario 1000     # sin config: tus límites a mano
    python3 plan.py plan --mercado TSLA --stop 3.57                   # una acción con la cuenta propia (tamano.py config --propia)
    python3 plan.py agenda --fecha 2026-11-11 --dato "08:30 IPC fuerte" --dato "10:30 Inventarios EIA CL"

plan    Escribe el plan de `kemet-desk/references/plan-de-sesion.md`: las franjas de la sesión de Nueva York (y su
        hora en Madrid), las ventanas en las que no se opera (10 minutos a cada lado de cada dato de kemet/agenda.json,
        20 si es fuerte; la apertura 09:30–09:45 para quien empieza; los 5 minutos antes de estar plano), el semáforo
        del día con sus razones, los niveles de la sesión anterior y de la noche, el tamaño con la regla Kemet y la
        hora límite de la firma. Sin kemet/agenda.json avisa de que no conoce los datos del día. Sin kemet/config.json
        funciona con los valores por defecto y lo dice; el bloque de tamaño solo sale con límites (config o --drawdown).
agenda  Escribe kemet/agenda.json desde flags: cada --dato es "HH:MM nombre [fuerte] [ES NQ CL GC]". Con --auto la baja
        del calendario semanal gratuito de Forex Factory (una sola petición, sin clave): datos USD del día, High como
        fuerte, Medium como no fuerte, Low fuera, nombres habituales traducidos; si la red falla, una línea y código 1.

Regla Kemet del tamaño: pérdida máxima del día = la menor entre el límite diario de la firma (si lo hay) y un cuarto
del drawdown; en ámbar o rojo, la mitad. Riesgo por operación = pérdida máxima del día entre 3 (tres fallos y paras).
Contratos = parte entera de riesgo por operación / (stop en puntos × valor del punto del micro), con el tope de micros
de la cuenta. Un semáforo ámbar sale solo cuando hay un dato fuerte en la agenda para ese mercado.
Cuenta propia (tamano.py config --propia): la pérdida máxima del día y el riesgo por operación son los tuyos (la mitad
en ámbar o rojo). En una acción el stop va en dólares por acción y el tamaño en acciones enteras: riesgo por operación /
stop, y con el cierre de ayer como precio de referencia los topes de posición, orden máxima y efectivo. Sin hora límite
de firma; las ventanas son las de la agenda y la apertura 09:30 a 09:45; sin niveles de la noche.

Código de salida 0 si hay plan, 1 si no se pudo escribir (sin datos ni sesión), 2 si hay un error.
"""
import argparse
import datetime as dt
import json
import math
import os
import sys
import urllib.error

import comun
from comun import KemetError

DIAS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
VENTANA, VENTANA_FUERTE = 10, 20
APERTURA = ("09:30", "09:45")
ANTES_DE_PLANO = 5
FRANJAS_INDICES = (
    ("Preapertura", "08:00", "09:30", "marca niveles, revisa la agenda, decide el tamaño; el dato de las 08:30 no se opera"),
    ("Apertura", "09:30", "09:45", "quien empieza, espera; quien no, tamaño reducido y stop amplio"),
    ("Mejor franja", "09:45", "11:30", "se forma el balance inicial; aquí van las operaciones del plan"),
    ("Hora de comer", "11:30", "13:30", "rango y falsas rupturas: tamaño mínimo o nada; revisión de media sesión"),
    ("Tarde", "13:30", "15:30", "vuelve el volumen; a las 14:00 hay datos (FOMC, Tesoro)"),
    ("Cierre", "15:30", "16:00", "reposicionamiento; plano antes de la hora límite, sin aperturas nuevas"),
)
CALENDARIO_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
# Nombres de Forex Factory que se traducen (se busca en este orden; el resto se deja tal cual). Tercer campo: mercados.
TRADUCCIONES = (
    ("Core CPI", "IPC subyacente", None), ("CPI", "IPC", None),
    ("Non-Farm Employment Change", "nóminas no agrícolas", None), ("Unemployment Claims", "peticiones de desempleo", None),
    ("Unemployment Rate", "tasa de paro", None), ("Average Hourly Earnings", "salarios por hora", None),
    ("FOMC Press Conference", "rueda de prensa del FOMC", None), ("FOMC Meeting Minutes", "actas del FOMC", None),
    ("FOMC Statement", "FOMC", None), ("Federal Funds Rate", "FOMC", None), ("FOMC Economic Projections", "proyecciones del FOMC", None),
    ("Core PPI", "PPI subyacente", None), ("PPI", "PPI", None),
    ("Core PCE Price Index", "PCE subyacente", None), ("PCE", "PCE", None),
    ("Advance GDP", "PIB adelantado", None), ("Prelim GDP", "PIB preliminar", None), ("Final GDP", "PIB final", None), ("GDP", "PIB", None),
    ("Core Retail Sales", "ventas minoristas subyacentes", None), ("Retail Sales", "ventas minoristas", None),
    ("ISM Manufacturing PMI", "ISM manufacturero", None), ("ISM Services PMI", "ISM servicios", None),
    ("Crude Oil Inventories", "inventarios EIA", ["CL"]), ("Natural Gas Storage", "almacenamiento de gas natural", ["NG"]),
    ("CB Consumer Confidence", "confianza del consumidor (Conference Board)", None),
    ("Prelim UoM Consumer Sentiment", "confianza del consumidor (Michigan, preliminar)", None),
    ("Revised UoM Consumer Sentiment", "confianza del consumidor (Michigan, revisada)", None),
    ("10-y Bond Auction", "subasta del Tesoro a 10 años", None), ("30-y Bond Auction", "subasta del Tesoro a 30 años", None),
    ("Bank Holiday", "festivo bancario", []),
)
DEFECTO = {"mercado": "NQ", "semaforo": "verde", "fallos_y_paras": 3, "sin_entradas_antes": "09:45", "sin_entradas_despues": "14:00",
           "zona_usuario": "Europe/Madrid", "hora_limite_tz": "America/New_York"}


# ---------------------------------------------------------------- horas

def t_de(hhmm_):
    return comun.parse_hhmm(hhmm_)


def mas(hhmm_, minutos):
    base = dt.datetime.combine(dt.date(2000, 1, 1), t_de(hhmm_)) + dt.timedelta(minutes=minutos)
    return comun.hhmm(base.time())


def ny_a_usuario(hhmm_, fecha, zona):
    """HH:MM de Nueva York en la zona del usuario, o None si la zona no es Madrid (solo sabemos calcular esa)."""
    if zona != "Europe/Madrid":
        return None
    return comun.hhmm(comun.a_madrid(comun.de_ny(dt.datetime.combine(fecha, t_de(hhmm_)))))


def a_ny_desde(hhmm_, tz, fecha):
    """La hora límite de la firma, que viene en su zona, en hora de Nueva York. None si no sabemos convertirla."""
    t = t_de(hhmm_)
    if tz in ("America/New_York", None, ""):
        return comun.hhmm(t)
    if tz == "America/Chicago":            # Chicago cambia de hora el mismo instante que Nueva York: siempre una hora menos
        return mas(hhmm_, 60)
    if tz in ("UTC", "Etc/UTC"):
        return comun.hhmm(comun.a_ny(dt.datetime.combine(fecha, t)))
    if tz == "Europe/Madrid":
        utc = dt.datetime.combine(fecha, t)
        utc -= dt.timedelta(hours=comun.madrid_offset(utc))
        return comun.hhmm(comun.a_ny(utc))
    return None


def fecha_es(d):
    return "%s %s" % (DIAS[d.weekday()], d.isoformat())


# ---------------------------------------------------------------- archivos

def config():
    cfg = comun.leer_json("config.json", obligatorio=False)
    if cfg is None:
        return None
    out = dict(DEFECTO)
    out.update({k: v for k, v in cfg.items() if v is not None})
    return out


def agenda(fecha):
    """La agenda del día o (None, aviso)."""
    doc = comun.leer_json("agenda.json", obligatorio=False)
    if not doc:
        return None, "no hay kemet/agenda.json: no conozco los datos de hoy (escríbela con `plan.py agenda`)"
    if doc.get("fecha") != fecha.isoformat():
        return None, "kemet/agenda.json es del %s, no del %s: no conozco los datos de hoy" % (doc.get("fecha"), fecha.isoformat())
    datos = []
    for d in doc.get("datos") or []:
        try:
            comun.parse_hhmm(d["hora"], "la hora del dato %r" % d.get("nombre"))
        except (KeyError, TypeError):
            raise KemetError("un dato de la agenda no tiene hora: %r" % (d,))
        datos.append({"hora": d["hora"], "nombre": d.get("nombre") or "dato", "fuerte": bool(d.get("fuerte")),
                      "mercados": [m.upper() for m in (d.get("mercados") or [])]})
    return sorted(datos, key=lambda d: d["hora"]), None


def parse_dato(texto):
    """"08:30 IPC fuerte" | "10:30 Inventarios EIA CL" -> {"hora", "nombre", "fuerte", "mercados"}."""
    partes = texto.split()
    if len(partes) < 2:
        raise KemetError("un --dato es \"HH:MM nombre [fuerte] [ES NQ CL GC]\", no %r" % texto)
    hora = comun.hhmm(comun.parse_hhmm(partes[0], "la hora de %r" % texto))
    resto, fuerte, mercados = [], False, []
    for p in partes[1:]:
        if p.lower() == "fuerte":
            fuerte = True
        elif p.upper() in comun.CONTRATOS and p.upper() == p:
            mercados.append(p.upper())
        else:
            resto.append(p)
    if not resto:
        raise KemetError("el dato %r no tiene nombre" % texto)
    d = {"hora": hora, "nombre": " ".join(resto), "fuerte": fuerte}
    if mercados:
        d["mercados"] = mercados
    return d


def traducir(titulo):
    """(nombre en español, mercados o None). Mercados [] = no abre ventana en futuros (festivo, gas natural)."""
    t = titulo.strip()
    for ingles, espanol, mercados in TRADUCCIONES:
        if ingles.lower() in t.lower():
            return espanol, mercados
    return t, None


def datos_del_calendario(texto, fecha, mercado=None):
    """Los datos USD de un día del calendario semanal de Forex Factory, ya en la forma de kemet/agenda.json."""
    try:
        eventos = json.loads(texto)
    except ValueError:
        raise KemetError("el calendario no es JSON válido")
    if not isinstance(eventos, list):
        raise KemetError("el calendario no tiene la forma esperada (una lista de eventos)")
    # Forex Factory solo publica la semana en curso: otro día no es «un día sin datos», es un día que no conocemos
    dias = set()
    for e in eventos:
        try:
            c = dt.datetime.fromisoformat(e["date"])
            dias.add(comun.a_ny((c - c.utcoffset()).replace(tzinfo=None)).date() if c.utcoffset() is not None else c.date())
        except (KeyError, TypeError, ValueError):
            continue
    if dias:
        desde, hasta = min(dias), max(max(dias), min(dias) + dt.timedelta(days=6))     # de domingo a sábado
        if not desde <= fecha <= hasta:
            raise KemetError("el calendario gratuito solo trae la semana del %s al %s y pides el %s: escribe los datos de ese día con --dato "
                             "(\"08:30 IPC fuerte\") o repite esa semana" % (desde.isoformat(), hasta.isoformat(), fecha.isoformat()))
    por_hora = {}
    fuera = []
    for e in eventos:
        if (e.get("country") or "").upper() != "USD":
            continue
        impacto = (e.get("impact") or "").lower()
        if impacto not in ("high", "medium", "holiday"):
            continue
        try:
            cuando = dt.datetime.fromisoformat(e["date"])      # ISO con el desfase de Nueva York del propio dato
        except (KeyError, TypeError, ValueError):
            continue
        if cuando.utcoffset() is not None:
            cuando = comun.a_ny((cuando - cuando.utcoffset()).replace(tzinfo=None))
        if cuando.date() != fecha:
            continue
        nombre, mercados = traducir(e.get("title") or "dato")
        if mercados == [] or impacto == "holiday":
            fuera.append(nombre)
            continue
        if mercado and mercados and mercado not in mercados:
            continue
        clave = (comun.hhmm(cuando.time()), tuple(mercados or []))
        d = por_hora.setdefault(clave, {"hora": clave[0], "nombre": [], "fuerte": False})
        if nombre not in d["nombre"]:
            d["nombre"].append(nombre)
        d["fuerte"] = d["fuerte"] or impacto == "high"
    datos = []
    for (hora, mercados), d in sorted(por_hora.items()):
        dato = {"hora": hora, "nombre": " y ".join(d["nombre"]), "fuerte": d["fuerte"]}
        if mercados:
            dato["mercados"] = list(mercados)
        datos.append(dato)
    return datos, fuera


def descargar_calendario():
    """El calendario de la semana; se guarda una hora en kemet/estado/calendario.json (Forex Factory limita las peticiones)."""
    cache = comun.ruta(os.path.join("estado", "calendario.json"))
    viejo = comun.leer_json(cache, obligatorio=False)
    if isinstance(viejo, dict) and viejo.get("texto"):
        cuando = comun.de_iso(viejo.get("leido"))
        if cuando and 0 <= (comun.utc_ahora() - cuando).total_seconds() < 3600:
            return viejo["texto"]
    texto = _bajar_calendario()
    if texto.lstrip().startswith("<"):
        raise KemetError("Forex Factory devolvió una página en vez del calendario (límite de peticiones): espera unos minutos o escribe la agenda con --dato")
    comun.escribir_json(cache, {"leido": comun.iso(comun.utc_ahora()), "texto": texto})
    return texto


def _bajar_calendario():
    try:
        return comun._open_url(CALENDARIO_URL)
    except urllib.error.HTTPError as e:
        raise KemetError("el calendario respondió HTTP %d: escribe la agenda con --dato" % e.code)
    except (urllib.error.URLError, OSError) as e:
        raise KemetError("no se pudo bajar el calendario (%s): escribe la agenda con --dato" % getattr(e, "reason", e))


# ---------------------------------------------------------------- las piezas del plan

def ventanas(datos, mercado, plano_a):
    out = []
    for d in datos or []:
        if d["mercados"] and mercado not in d["mercados"]:
            continue
        m = VENTANA_FUERTE if d["fuerte"] else VENTANA
        out.append({"desde": mas(d["hora"], -m), "hasta": mas(d["hora"], m),
                    "motivo": "%s a las %s%s" % (d["nombre"], d["hora"], ", dato fuerte" if d["fuerte"] else "")})
    try:
        abre = comun.resolver(mercado)["rth"][0] if mercado else APERTURA[0]   # CL y NG abren a las 09:00, GC a las 08:20
    except (KemetError, KeyError):
        abre = APERTURA[0]
    out.append({"desde": abre, "hasta": mas(abre, 15), "motivo": "apertura: quien empieza espera"})
    out.append({"desde": mas(plano_a, -ANTES_DE_PLANO), "hasta": plano_a, "motivo": "últimos minutos antes de estar plano"})
    return sorted(out, key=lambda v: v["desde"])


def semaforo(cfg, datos, mercado, forzado=None):
    fuertes = [d for d in (datos or []) if d["fuerte"] and (not d["mercados"] or mercado in d["mercados"])]
    if forzado:
        razones = ["lo has fijado tú"]
        if fuertes:
            razones.append("hay %s fuerte%s en la sesión: %s" % ("un dato" if len(fuertes) == 1 else "%d datos" % len(fuertes), "" if len(fuertes) == 1 else "s",
                                                                 ", ".join("%s a las %s" % (d["nombre"], d["hora"]) for d in fuertes)))
        return forzado, razones
    base = (cfg or DEFECTO).get("semaforo", "verde")
    razones = []
    if cfg and base != "verde":
        razones.append("tu config lo tiene en %s" % base)
    if fuertes:
        razones.append("hay %s fuerte%s en la sesión: %s" % ("un dato" if len(fuertes) == 1 else "%d datos" % len(fuertes), "" if len(fuertes) == 1 else "s",
                                                             ", ".join("%s a las %s" % (d["nombre"], d["hora"]) for d in fuertes)))
        if base == "verde":
            base = "ambar"
    if not razones:
        if datos is not None:
            razones.append("sin datos fuertes en la agenda")
        else:
            # sin agenda no se sabe si a las 08:30 sale el IPC: ámbar hasta que la haya (plan.py agenda --auto, o --dato)
            razones.append("sin agenda del día doy por hecho que no hay datos fuertes; no lo sé: escríbela con plan.py agenda --auto o --dato")
    return base, razones


def tamano(mercado, semaforo_, stop, drawdown, diario, max_micro, fallos=3, propia_dia=None, max_mini=None):
    """La regla Kemet, la misma de tamano.py: cuarto del drawdown o límite diario (el menor), mitad en ámbar/rojo, entre 3.
    `propia_dia` es la pérdida del día que fijó el usuario con tamano.py config --perdida-dia (en verde): manda sobre la regla."""
    c = comun.CONTRATOS[mercado]
    cuarto = round(drawdown * 0.25)
    base = min(diario, cuarto) if diario else cuarto
    if propia_dia:
        base = propia_dia
    factor = 1.0 if semaforo_ == "verde" else 0.5
    perdida = round(base * factor, 2) if propia_dia else round(base * factor)
    if comun.sin_micro(mercado):
        max_micro = max_mini
    riesgo = perdida / float(fallos)
    out = {"micro": c["micro"], "perdida_max_dia": perdida, "riesgo_por_operacion": round(riesgo, 2), "cuarto_drawdown": cuarto,
           "limite_diario_firma": diario, "fallos_y_paras": fallos, "max_micro": max_micro}
    if stop:
        por_micro = stop * c["punto_micro"]
        n = int(math.floor(riesgo / por_micro))
        out.update({"stop_pts": stop, "riesgo_usd_micro": round(por_micro, 2), "contratos_sin_tope": n,
                    "contratos": min(n, max_micro) if max_micro else n})
    return out


def tamano_propia(inst, semaforo_, stop, cfg, precio_ref=None):
    """La cuenta propia: la pérdida del día y el riesgo por operación de la config (la mitad en ámbar o rojo). En una acción,
    acciones enteras = riesgo / stop en dólares por acción; con un precio de referencia (el cierre de ayer) se aplican además
    los topes de posición, orden máxima y efectivo. En un futuro sin firma, micros como siempre con el tope opcional."""
    factor = 1.0 if semaforo_ == "verde" else 0.5
    perdida = float(cfg["perdida_max_dia"]) * factor
    riesgo = float(cfg["riesgo_por_operacion"]) * factor if cfg.get("riesgo_por_operacion") else perdida / float(cfg.get("fallos_y_paras") or 3)
    perdida = int(perdida) if perdida == int(perdida) else round(perdida, 2)
    out = {"micro": inst["micro"], "instrumento": inst["tipo"], "perdida_max_dia": perdida, "riesgo_por_operacion": round(riesgo, 2), "cuarto_drawdown": None,
           "limite_diario_firma": None, "fallos_y_paras": int(cfg.get("fallos_y_paras") or 3), "max_micro": cfg.get("max_micro"), "presupuesto": cfg.get("presupuesto")}
    if not stop:
        return out
    if inst["tipo"] == "futuro":
        por_micro = stop * inst["punto_micro"]
        n = int(math.floor(riesgo / por_micro))
        cap = cfg.get("max_micro")
        out.update({"stop_pts": stop, "riesgo_usd_micro": round(por_micro, 2), "contratos_sin_tope": n, "contratos": min(n, int(cap)) if cap else n})
        return out
    stop = comun.al_tick(stop, inst["tick"])
    limites = [{"nombre": "riesgo por operación", "acciones": int(math.floor(riesgo / stop + 1e-9)), "como": "%s / %s por acción" % (comun.usd(riesgo, 2), comun.usd(stop, 2))}]
    presupuesto = float(cfg.get("presupuesto") or 0)
    if precio_ref and presupuesto:
        if cfg.get("max_posicion_pct"):
            tope = presupuesto * float(cfg["max_posicion_pct"]) / 100.0
            limites.append({"nombre": "posición máxima", "acciones": int(math.floor(tope / precio_ref + 1e-9)), "como": "%s %% de %s = %s / %s" % (comun.num(float(cfg["max_posicion_pct"]), 0), comun.usd(presupuesto), comun.usd(tope), comun.usd(precio_ref, 2))})
        if cfg.get("max_orden_usd"):
            limites.append({"nombre": "orden máxima", "acciones": int(math.floor(float(cfg["max_orden_usd"]) / precio_ref + 1e-9)), "como": "%s / %s" % (comun.usd(float(cfg["max_orden_usd"])), comun.usd(precio_ref, 2))})
        colchon = presupuesto * float(cfg.get("efectivo_pct") or 0) / 100.0
        limites.append({"nombre": "efectivo", "acciones": int(math.floor((presupuesto - colchon) / precio_ref + 1e-9)), "como": "%s menos %s de colchón = %s / %s" % (comun.usd(presupuesto), comun.usd(colchon), comun.usd(presupuesto - colchon), comun.usd(precio_ref, 2))})
    n = max(0, min(l["acciones"] for l in limites))
    manda = [l for l in limites if l["acciones"] == n][0]
    for l in limites:
        l["manda"] = l is manda
    out.update({"stop_pts": stop, "riesgo_por_accion": stop, "limites": limites, "acciones_sin_tope": limites[0]["acciones"], "acciones": n, "contratos": n,
                "manda": manda["nombre"], "precio_referencia": precio_ref})
    return out


def niveles(mercado, fecha, ahora_utc, offline=None):
    """Los niveles del día: kemet/niveles.json si es de hoy y de este mercado; si no, de Yahoo (o del --offline). (doc, nota)."""
    guardado = comun.leer_json("niveles.json", obligatorio=False)
    if guardado and guardado.get("mercado") == mercado and guardado.get("fecha") == fecha.isoformat() and not offline:
        return {k: guardado[k] for k in ("pdh", "pdl", "pdc", "onh", "onl", "orh", "orl", "ibh", "ibl") if k in guardado}, "de kemet/niveles.json (%s)" % guardado.get("generado", "")
    ch = None
    ultimo_error = None
    for rango in (("60d", "5d") if offline else ("5d",)):
        try:
            ch = comun.velas(mercado, rango, "5m", offline)
            break
        except KemetError as e:
            ultimo_error = e
    if ch is None:
        raise ultimo_error
    cerradas = comun.velas_cerradas(ch, ahora_utc)
    dias = comun.por_dia(cerradas, mercado)
    accion = comun.es_accion(mercado)
    previos = [d for d in dias if d < fecha and comun.regular(mercado, dias[d], d)]
    if not previos:
        return {}, "sin sesión anterior en los datos"
    ayer = previos[-1]
    rth = comun.regular(mercado, dias[ayer], ayer)
    out = {"pdh": max(b[2] for b in rth), "pdl": min(b[3] for b in rth), "pdc": rth[-1][4]}
    apertura, _ = comun.sesion_regular(mercado, fecha)
    t_ap = comun.ts_de_utc(apertura)
    hoy = dias.get(fecha, [])
    noche = [b for b in hoy if b[0] < t_ap] if not accion else []      # una acción no tiene sesión nocturna
    if noche:
        out["onh"], out["onl"] = comun.rango(noche)
    rth_hoy = comun.regular(mercado, hoy, fecha)
    if rth_hoy and comun.ts_de_utc(ahora_utc) >= t_ap + 900:
        out["orh"], out["orl"] = comun.rango([b for b in rth_hoy if b[0] < t_ap + 900])
    ib = comun.balance_inicial(mercado, hoy, fecha) if not accion else None     # en una acción el balance es la apertura de 15 min
    if ib:
        out["ibh"], out["ibl"] = ib["alto"], ib["bajo"]
    tick = comun.resolver(mercado)["tick"]
    out = {k: comun.al_tick(v, tick) for k, v in out.items()}      # Yahoo trae ruido de coma flotante en GC
    return out, "sesión anterior %s, velas de 5 min de Yahoo" % ayer.isoformat()


def siguiente(ahora_ny, cfg, vents, plano_a, cierre_rth, mercado="NQ"):
    """La única cosa que hace el usuario a continuación, según la hora."""
    if comun.es_accion(mercado):
        clave = ahora_ny.date().isoformat()
        estado = "cerrado" if ahora_ny.weekday() >= 5 or clave in comun.NYSE_CERRADO else "abierto"
        motivo = comun.NYSE_CERRADO.get(clave, "fin de semana")
    else:
        estado, motivo = comun.estado_globex(comun.de_ny(ahora_ny))
    if estado == "cerrado":
        return "Mercado cerrado (%s): revisa el diario, marca máximo, mínimo y cierre de la última sesión y mira qué datos salen el próximo día." % motivo
    h = comun.hhmm(ahora_ny.time())
    for v in vents:
        if v["desde"] <= h < v["hasta"]:
            return "Estás en una ventana sin operar (%s) hasta las %s NY: ni abrir, ni mantener, ni dejar órdenes pendientes." % (v["motivo"], v["hasta"])
    antes, despues = cfg["sin_entradas_antes"], cfg["sin_entradas_despues"]
    if h < "08:00":
        return "Marca los niveles en el gráfico y vuelve a las 08:00 NY con la agenda del día."
    if h < antes:
        return "Pon el stop y el tamaño por escrito, marca los niveles en la plataforma y no entres antes de las %s NY." % antes
    if h < despues:
        return "Operaciones del plan hasta las %s NY, cada una con el stop puesto en la plataforma antes de entrar." % despues
    if h < plano_a:
        return "Sin entradas nuevas: gestiona lo abierto y estate plano a las %s NY." % plano_a
    if h < cierre_rth:
        return "Plano. Nada más hoy."
    return "Sesión cerrada: apunta la sesión en el diario; el plan de mañana se escribe antes de las 08:00 NY con la agenda nueva."


# ---------------------------------------------------------------- el plan

def construir(a):
    ahora = comun.parse_ahora(a.ahora)
    ahora_ny = comun.a_ny(ahora)
    cfg = config()
    avisos = []
    if cfg is None:
        avisos.append("sin kemet/config.json: valores por defecto (NQ, verde, entradas 09:45–14:00, plano a las 15:55, Madrid); el tamaño solo con --drawdown")
        cfg = dict(DEFECTO)
    fecha = ahora_ny.date() if comun.es_accion(a.mercado or cfg.get("mercado") or "NQ") else comun.dia_negociacion(ahora_ny)
    inst = comun.resolver(a.mercado or cfg.get("mercado") or "NQ")
    mercado, accion, propia = inst["codigo"], inst["tipo"] == "accion", cfg.get("tipo_cuenta") == "propia" or cfg.get("cuenta") == "propia"
    c = inst
    if accion and not propia:
        avisos.append("%s es una acción y %s: el tamaño en acciones sale con una cuenta propia (tamano.py config --propia)"
                      % (mercado, "la config es de una cuenta de firma (futuros)" if cfg.get("firma") else "no hay cuenta propia configurada"))
    plano_a = cfg.get("plano_a") or c["plano"]
    comun.parse_hhmm(plano_a, "plano_a")
    # festivos y sesiones recortadas: el plan no puede decir «hasta las 15:00» el día que CME para a las 13:00
    clave = fecha.isoformat()
    cerrados, recortados = (comun.NYSE_CERRADO, comun.NYSE_RECORTADO) if accion else (comun.CME_CERRADO, comun.CME_RECORTADO)
    if clave in cerrados:
        avisos.append("%s está cerrado el %s (%s): no hay sesión que planificar" % ("La NYSE" if accion else "CME", clave, cerrados[clave]))
    elif clave in recortados:
        corte = comun.CME_CORTE_RECORTADO.strftime("%H:%M")
        plano_rec = "12:55"
        cfg = dict(cfg, sin_entradas_despues=min(cfg.get("sin_entradas_despues") or "12:30", "12:30"))
        plano_a = min(plano_a, plano_rec)
        avisos.append("sesión recortada (%s): %s para a las %s NY. Plano a las %s y sin entradas nuevas después de las 12:30 NY%s"
                      % (recortados[clave], "la NYSE" if accion else "CME", corte, plano_a,
                         "" if accion or mercado in comun.INDICES else "; en %s confirma su horario de hoy en cmegroup.com" % mercado))
    zona = cfg.get("zona_usuario") or "Europe/Madrid"
    datos, aviso_agenda = agenda(fecha)
    if aviso_agenda:
        avisos.append(aviso_agenda)
    vents = ventanas(datos, mercado, plano_a)
    sem, razones = semaforo(cfg, datos, mercado, a.semaforo)
    # tamaño
    drawdown = a.drawdown or cfg.get("drawdown")
    diario = a.diario if a.diario is not None else cfg.get("limite_diario_firma")
    tam, aviso_tam = None, None
    if propia and cfg.get("perdida_max_dia"):
        tam = tamano_propia(inst, sem, a.stop, cfg, None)
        if not a.stop:
            aviso_tam = "dime tu stop (--stop, %s) y te digo cuánt%s caben" % (("en dólares por acción", "as acciones") if accion else ("en puntos", "os " + c["micro"]))
    elif accion:
        aviso_tam = "sin cuenta propia no hay tamaño en acciones: tamano.py config --propia --presupuesto … --max-perdida-operacion … --max-perdida-dia …"
    elif drawdown:
        propia_dia = None
        if cfg.get("perdida_max_dia_origen") == "usuario" and cfg.get("perdida_max_dia"):
            propia_dia = float(cfg["perdida_max_dia"]) * (2.0 if (cfg.get("semaforo") or "verde") != "verde" else 1.0)
        tam = tamano(mercado, sem, a.stop, float(drawdown), float(diario) if diario else None, cfg.get("max_micro"), int(cfg.get("fallos_y_paras") or 3),
                     propia_dia, cfg.get("max_mini"))
        if not a.stop:
            aviso_tam = "dime tu stop en puntos (--stop) y te digo cuántos %s caben" % c["micro"]
    elif a.stop:
        raise KemetError("con --stop y sin kemet/config.json hacen falta tus límites: --drawdown (y --diario si tu firma lo tiene)")
    else:
        aviso_tam = "sin límites de cuenta no hay bloque de tamaño: escribe kemet/config.json con tamano.py o pasa --stop con --drawdown"
    # niveles
    niv, nota_niv = {}, None
    if not a.sin_niveles:
        try:
            niv, nota_niv = niveles(mercado, fecha, ahora, a.offline)
        except KemetError as e:
            nota_niv = "no disponibles: %s" % e
            avisos.append("sin niveles de %s (%s): márcalos a mano o ejecuta niveles.py" % (mercado, e))
    if tam and accion and "stop_pts" in tam:
        tam = tamano_propia(inst, sem, a.stop, cfg, niv.get("pdc"))
    # hora límite
    hora_limite = cfg.get("hora_limite")
    hora_limite_ny = a_ny_desde(hora_limite, cfg.get("hora_limite_tz"), fecha) if hora_limite else None
    if propia:
        hora_limite = None
    if hora_limite and hora_limite_ny is None:
        avisos.append("no sé convertir la zona %s de la hora límite: la dejo como viene" % cfg.get("hora_limite_tz"))
    if hora_limite_ny and plano_a >= hora_limite_ny:
        avisos.append("plano_a (%s) no está antes de la hora límite de la firma (%s NY): adelántalo" % (plano_a, hora_limite_ny))
    _, cierre = comun.sesion_regular(mercado, fecha)
    doc = {"generado": comun.iso(ahora), "mercado": mercado, "instrumento": inst["tipo"], "fecha": fecha.isoformat(), "semaforo": sem, "razones": razones,
           "ventanas": vents, "niveles": niv, "tamano": tam, "hora_limite": hora_limite, "hora_limite_tz": cfg.get("hora_limite_tz"),
           "hora_limite_ny": hora_limite_ny, "plano_a": plano_a, "sin_entradas_antes": cfg["sin_entradas_antes"], "sin_entradas_despues": cfg["sin_entradas_despues"],
           "zona_usuario": zona, "agenda": datos, "avisos": avisos, "nota_niveles": nota_niv, "nota_tamano": aviso_tam,
           "siguiente": siguiente(ahora_ny, cfg, vents, plano_a, comun.hhmm(comun.a_ny(cierre).time()), mercado),
           "tipo_cuenta": "propia" if propia else ("firma" if cfg.get("firma") else None)}
    if cfg.get("cuenta_nombre"):
        doc["cuenta"] = cfg["cuenta_nombre"]
    return doc, ahora


def texto_tamano_accion(tam, doc):
    """El bloque de tamaño de una acción con la cuenta propia."""
    out = []
    detalle = "tu pérdida máxima del día" + (", la mitad por %s" % {"ambar": "ámbar"}.get(doc["semaforo"], doc["semaforo"]) if doc["semaforo"] != "verde" else "")
    if "acciones" not in tam:
        out.append("Mi tamaño: pérdida máxima del día %s (%s) · riesgo por operación %s" % (comun.usd(tam["perdida_max_dia"]), detalle, comun.usd(tam["riesgo_por_operacion"], 2)))
        out.append("  %s" % doc["nota_tamano"])
        return out
    linea = "Mi tamaño: %d acciones de %s por operación con stop de %s por acción" % (tam["acciones"], doc["mercado"], comun.usd(tam["stop_pts"], 2))
    if tam["manda"] != "riesgo por operación":
        linea += " (manda %s)" % tam["manda"]
    if tam["acciones"] == 0:
        linea += " · no cabe ninguna: reduce el stop o espera un día verde"
    out.append(linea)
    out.append("  pérdida máxima del día %s (%s) · riesgo por operación %s · al stop pierdes %s por acción" % (
        comun.usd(tam["perdida_max_dia"]), detalle, comun.usd(tam["riesgo_por_operacion"], 2), comun.usd(tam["stop_pts"], 2)))
    for l in tam["limites"]:
        out.append("  %-22s %-48s %4d acciones%s" % (l["nombre"], l["como"], l["acciones"], "  <- manda" if l["manda"] else ""))
    if tam.get("precio_referencia"):
        out.append("  posición, orden máxima y efectivo con el cierre de ayer (%s) como precio; con la entrada real los recalcula kemet-tamano" % comun.usd(tam["precio_referencia"], 2))
    else:
        out.append("  sin precio de referencia no aplico posición, orden máxima ni efectivo: los recalcula kemet-tamano con la entrada")
    return out


def _doble(hhmm_, fecha, zona):
    u = ny_a_usuario(hhmm_, fecha, zona)
    return "%s NY" % hhmm_ if u is None else "%s NY (%s Madrid)" % (hhmm_, u)


def texto(doc, ahora):
    fecha = dt.date.fromisoformat(doc["fecha"])
    zona = doc["zona_usuario"]
    madrid = zona == "Europe/Madrid"
    c = comun.resolver(doc["mercado"])
    accion = c["tipo"] == "accion"
    out = ["PLAN · %s · %s · %s" % (doc["mercado"], fecha_es(fecha), comun.hora_doble(ahora))]
    if doc.get("cuenta"):
        out.append("Cuenta: %s" % doc["cuenta"])
    for av in doc["avisos"]:
        out.append("Aviso: %s" % av)
    if not madrid:
        out.append("Horas en Nueva York: tu zona es %s y solo sé convertir a Madrid." % zona)
    sem = {"verde": "verde", "ambar": "ámbar", "rojo": "rojo"}.get(doc["semaforo"], doc["semaforo"])
    out.append("Semáforo: %s porque %s" % (sem, "; ".join(doc["razones"])))
    if doc["semaforo"] == "rojo":
        out.append("  Rojo: quien empieza, mira; quien no, la mitad del tamaño y nunca dentro de la ventana de un dato.")
    out.append("Hoy no se opera en:")
    for v in doc["ventanas"]:
        rango = "%s–%s NY" % (v["desde"], v["hasta"])
        if madrid:
            rango += " (%s–%s Madrid)" % (ny_a_usuario(v["desde"], fecha, zona), ny_a_usuario(v["hasta"], fecha, zona))
        out.append("  %-42s %s" % (rango, v["motivo"]))
    out.append("  Dentro de la ventana no se abre, no se mantiene y no se dejan órdenes pendientes.")
    out.append("Entradas nuevas solo entre %s y %s." % (_doble(doc["sin_entradas_antes"], fecha, zona), _doble(doc["sin_entradas_despues"], fecha, zona)))
    niv = doc["niveles"]
    if niv:
        out.append("Niveles que marco (%s):" % doc["nota_niveles"])
        out.append("  Ayer       máximo %s   mínimo %s   cierre %s" % (comun.pts(niv["pdh"]), comun.pts(niv["pdl"]), comun.pts(niv["pdc"])))
        if "onh" in niv:
            out.append("  Noche      máximo %s   mínimo %s" % (comun.pts(niv["onh"]), comun.pts(niv["onl"])))
        if "orh" in niv:
            out.append("  Apertura   máximo %s   mínimo %s   (15 min)" % (comun.pts(niv["orh"]), comun.pts(niv["orl"])))
        if "ibh" in niv:
            out.append("  Balance    máximo %s   mínimo %s   (%s)" % (comun.pts(niv["ibh"]), comun.pts(niv["ibl"]), "15 min" if accion else "1 h"))
        if accion:
            out.append("  Sin sesión nocturna: una acción abre a las 09:30 y los primeros 15 minutos son su balance inicial.")
        if doc["mercado"] in ("ES", "NQ"):
            out.append("  Gamma: el pivote y los muros de calls y puts los marcas tú desde tu fuente de opciones; este pack no los tiene.")
    else:
        out.append("Niveles que marco: %s. Ejecuta niveles.py (kemet-niveles) y márcalos a mano." % (doc["nota_niveles"] or "no calculados"))
    tam = doc["tamano"]
    if tam and tam.get("instrumento") == "accion":
        out.extend(texto_tamano_accion(tam, doc))
    elif tam and doc.get("tipo_cuenta") == "propia":
        detalle = "tu pérdida máxima del día" + (", la mitad por %s" % sem if doc["semaforo"] != "verde" else "")
        if "contratos" in tam:
            linea = "Mi tamaño: %d %s por operación con stop de %s pts" % (tam["contratos"], tam["micro"], comun.pts(tam["stop_pts"]))
            if tam["max_micro"] and tam["contratos_sin_tope"] > tam["max_micro"]:
                linea += " (tu tope: %d micros)" % tam["max_micro"]
            if tam["contratos"] == 0:
                linea += " · no cabe ninguno: reduce el stop o espera un día verde"
            out.append(linea)
            out.append("  pérdida máxima del día %s (%s) · riesgo por operación %s · al stop pierdes %s por %s" % (
                comun.usd(tam["perdida_max_dia"]), detalle, comun.usd(tam["riesgo_por_operacion"], 2), comun.usd(tam["riesgo_usd_micro"], 2), tam["micro"]))
        else:
            out.append("Mi tamaño: pérdida máxima del día %s (%s) · riesgo por operación %s" % (comun.usd(tam["perdida_max_dia"]), detalle, comun.usd(tam["riesgo_por_operacion"], 2)))
            out.append("  %s" % doc["nota_tamano"])
    elif tam:
        detalle = "un cuarto del drawdown = %s" % comun.usd(tam["cuarto_drawdown"])
        if tam["limite_diario_firma"]:
            detalle += ", límite diario de la firma %s, manda el menor" % comun.usd(tam["limite_diario_firma"])
        if doc["semaforo"] != "verde":
            detalle += ", la mitad por %s" % sem
        if "contratos" in tam:
            linea = "Mi tamaño: %d %s por operación con stop de %s pts" % (tam["contratos"], tam["micro"], comun.pts(tam["stop_pts"]))
            if tam["max_micro"] and tam["contratos_sin_tope"] > tam["max_micro"]:
                linea += " (tope de la cuenta: %d micros)" % tam["max_micro"]
            if tam["contratos"] == 0:
                linea += " · no cabe ninguno: reduce el stop o espera un día verde"
            out.append(linea)
            out.append("  pérdida máxima del día %s (%s)" % (comun.usd(tam["perdida_max_dia"]), detalle))
            out.append("  riesgo por operación %s (entre %d fallos y paras) · al stop pierdes %s por %s" % (
                comun.usd(tam["riesgo_por_operacion"]), tam["fallos_y_paras"], comun.usd(tam["riesgo_usd_micro"], 2), tam["micro"]))
        else:
            out.append("Mi tamaño: pérdida máxima del día %s (%s) · riesgo por operación %s" % (comun.usd(tam["perdida_max_dia"]), detalle, comun.usd(tam["riesgo_por_operacion"])))
            out.append("  %s" % doc["nota_tamano"])
    else:
        out.append("Mi tamaño: %s" % doc["nota_tamano"])
    if doc.get("tipo_cuenta") == "propia":
        out.append("Hora límite: ninguna, es tu cuenta · plano a las %s" % _doble(doc["plano_a"], fecha, zona))
    elif doc["hora_limite"]:
        if doc["hora_limite_ny"]:
            lim = _doble(doc["hora_limite_ny"], fecha, zona)
            if doc["hora_limite_tz"] not in ("America/New_York", None, ""):
                lim += ", %s en %s" % (doc["hora_limite"], doc["hora_limite_tz"])
        else:
            lim = "%s %s" % (doc["hora_limite"], doc["hora_limite_tz"] or "")
        out.append("Hora límite de mi firma: %s · plano a las %s" % (lim, _doble(doc["plano_a"], fecha, zona)))
    else:
        out.append("Hora límite de mi firma: sin config no la conozco · plano a las %s" % _doble(doc["plano_a"], fecha, zona))
    out.append("Franjas del día (%s):" % ("NY / Madrid" if madrid else "NY"))
    if doc["mercado"] in ("ES", "NQ") or accion:
        for nombre, d, h, que in FRANJAS_INDICES:
            rango = "%s–%s" % (d, h)
            if madrid:
                rango += " / %s–%s" % (ny_a_usuario(d, fecha, zona), ny_a_usuario(h, fecha, zona))
            out.append("  %-14s %-28s %s" % (nombre, rango, que))
    else:
        o, cierre = c["rth"]
        out.append("  %-14s %-28s %s" % ("Pit", "%s–%s%s" % (o, cierre, (" / %s–%s" % (ny_a_usuario(o, fecha, zona), ny_a_usuario(cierre, fecha, zona))) if madrid else ""),
                                          "la sesión con volumen de %s; fuera de ella el precio existe, el volumen no" % c["nombre"]))
        if doc["mercado"] == "CL":
            out.append("  %-14s %-28s %s" % ("EIA", "miércoles 10:30%s" % ((" / " + ny_a_usuario("10:30", fecha, zona)) if madrid else ""), "inventarios de crudo: ventana de 10 minutos a cada lado"))
    out.append("Antes de cada operación: sé dónde va mi stop y lo pongo en la plataforma; opero como mucho los contratos que caben; "
               "he escrito por qué entro y qué me haría salir; si llego a mi pérdida máxima del día, cierro la plataforma.")
    out.append("Lo único que hago a continuación: %s" % (doc["siguiente"][:1].lower() + doc["siguiente"][1:]))
    return out


# ---------------------------------------------------------------- main

def cmd_plan(a):
    doc, ahora = construir(a)
    if a.json:
        print(comun.json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        print("\n".join(texto(doc, ahora)))
    if a.escribir:
        guardado = {k: doc[k] for k in ("generado", "mercado", "fecha", "semaforo", "razones", "ventanas", "niveles", "tamano", "hora_limite", "plano_a", "siguiente")}
        guardado["hora_limite_ny"] = doc["hora_limite_ny"]
        ruta = comun.escribir_json("plan-sesion.json", guardado)
        if not a.json:
            print("Guardado %s" % ruta)
    return 0


def cmd_agenda(a):
    fecha = a.fecha or comun.dia_negociacion(comun.a_ny(comun.parse_ahora(a.ahora))).isoformat()
    try:
        dt.date.fromisoformat(fecha)
    except ValueError:
        raise KemetError("--fecha tiene que ser AAAA-MM-DD, no %r" % fecha)
    datos = sorted((parse_dato(t) for t in (a.dato or [])), key=lambda d: d["hora"])
    fuera = []
    if a.auto:
        try:
            texto = comun.leer_texto(a.offline) if a.offline else descargar_calendario()
            auto, fuera = datos_del_calendario(texto, dt.date.fromisoformat(fecha), (a.mercado or "").upper() or None)
        except KemetError as e:
            print("Error: %s" % e, file=sys.stderr)
            return 1
        datos = sorted(datos + auto, key=lambda d: d["hora"])
    doc = {"fecha": fecha, "datos": datos}
    if a.auto:
        doc["fuente"] = "Forex Factory (datos USD de impacto alto y medio)" if not a.offline else "archivo %s" % a.offline
    if a.json:
        print(comun.json.dumps(doc, ensure_ascii=False, indent=1))
        if not a.escribir:
            return 0                              # --json consulta; --escribir además la guarda
    else:
        print("Agenda del %s:" % fecha + ("" if datos else " sin datos (un día sin publicaciones también se escribe, para que el plan lo sepa)"))
        for d in datos:
            print("  %s  %s%s%s" % (d["hora"], d["nombre"], " · fuerte (ventana de 20 min)" if d["fuerte"] else " (ventana de 10 min)",
                                   " · solo " + ", ".join(d["mercados"]) if d.get("mercados") else ""))
        for nombre in fuera:
            print("  (%s: en el calendario, sin ventana)" % nombre)
        if a.auto:
            print("  Fuente: %s. Impacto alto = fuerte, medio = no fuerte, bajo fuera. Comprueba la hora de los datos que te importan." % (
                "calendario semanal de Forex Factory" if not a.offline else a.offline))
    ruta = comun.escribir_json("agenda.json", doc)
    print("Guardado %s" % ruta, file=sys.stderr if a.json else sys.stdout)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    sp = sub.add_parser("plan", help="el plan de sesión escrito")
    sp.add_argument("--mercado", help="ES, NQ, CL, GC… o un ticker de EE. UU. (por defecto el de kemet/config.json, y si no hay, NQ)")
    sp.add_argument("--stop", type=float, help="tu stop en puntos del contrato (o en dólares por acción), para el tamaño")
    sp.add_argument("--drawdown", type=float, help="drawdown de la cuenta en dólares, si no hay config")
    sp.add_argument("--diario", type=float, help="límite diario de la firma en dólares, si lo tiene")
    sp.add_argument("--semaforo", choices=["verde", "ambar", "rojo"], help="fuerza el semáforo del día")
    sp.add_argument("--sin-niveles", action="store_true", help="no consulta Yahoo ni kemet/niveles.json")
    sp.add_argument("--escribir", action="store_true", help="guarda kemet/plan-sesion.json")
    sp.add_argument("--ahora", help='hora de Nueva York, "AAAA-MM-DD HH:MM"')
    sp.add_argument("--offline", help="archivo JSON de Yahoo o la carpeta tests/fixtures/yahoo, para los niveles")
    sp.add_argument("--json", action="store_true")
    sa = sub.add_parser("agenda", help="escribe kemet/agenda.json desde flags")
    sa.add_argument("--fecha", help="AAAA-MM-DD (por defecto el día de negociación de ahora)")
    sa.add_argument("--dato", action="append", help='"HH:MM nombre [fuerte] [ES NQ CL GC]"; repetible')
    sa.add_argument("--auto", action="store_true", help="baja los datos USD del día del calendario semanal de Forex Factory (una petición)")
    sa.add_argument("--mercado", help="con --auto: deja fuera los datos que solo afectan a otro contrato (la EIA si no es CL)")
    sa.add_argument("--offline", help="con --auto: un ff_calendar_thisweek.json guardado en vez de la red")
    sa.add_argument("--ahora", help='hora de Nueva York, "AAAA-MM-DD HH:MM"')
    sa.add_argument("--json", action="store_true", help="imprime la agenda en JSON sin guardarla (con --escribir, también la guarda)")
    sa.add_argument("--escribir", action="store_true", help="con --json: guarda además kemet/agenda.json")
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-"):
        argv.insert(0, "plan")                 # `plan.py --stop 40` vale como `plan.py plan --stop 40`
    a = p.parse_args(argv)
    if a.cmd == "agenda":
        return cmd_agenda(a)
    return cmd_plan(a)


def run():
    try:
        sys.exit(main())
    except KemetError as e:
        print("Error: %s" % e, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    run()
