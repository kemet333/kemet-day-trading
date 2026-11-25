#!/usr/bin/env python3
"""kemet-niveles · perfil.py: el perfil de volumen de cada sesión de un futuro (Asia, Londres y Nueva York) con su POC, VAH y VAL.

    python3 perfil.py --mercado NQ                     # la sesión de CME de hoy y la de Nueva York de ayer
    python3 perfil.py --mercado ES --ahora "2026-11-11 09:20" --json
    python3 perfil.py --mercado NQ --fila 5 --escribir # filas de 5 puntos; guarda kemet/perfil.json

Sesiones en hora de Nueva York, dentro del día de CME (empieza a las 18:00 de la víspera): Asia de 18:00 a 03:00, Londres de 03:00
a la apertura regular del contrato y Nueva York en su sesión regular (9:30 a 16:00 en índices). El volumen de cada vela de 5 min se
reparte a partes iguales entre las filas de precio que toca: es una aproximación del perfil real, que se hace con cada operación.
POC: la fila con más volumen. Zona de valor (VAH y VAL): desde el POC se va sumando la fila vecina con más volumen hasta el 70 %.

Código de salida: 0 con perfiles, 2 si hay un error.
"""
import argparse
import datetime as dt
import json
import math
import os
import sys

import comun
from comun import KemetError, pts

AREA_VALOR = 0.70
FILAS_OBJETIVO = 60                  # sin --fila, el tamaño de fila que da unas 60 filas en el rango de la sesión
ASIA = (dt.time(18, 0), dt.time(3, 0))
LONDRES_DESDE = dt.time(3, 0)
COLORES = {"asia": "naranja", "londres": "azul", "nueva_york": "rojo"}
NOMBRES = {"asia": "Asia", "londres": "Londres", "nueva_york": "Nueva York"}
FUENTE = "velas de 5 min de Yahoo (gratis, ~10 min de retraso); volumen repartido dentro de cada vela"


def tramos(codigo, dia):
    """{sesión: (desde_utc, hasta_utc)} del día de CME `dia` (date)."""
    o, c = comun.sesion_regular(codigo, dia)
    vispera = dia - dt.timedelta(days=1)
    a0 = comun.de_ny(dt.datetime.combine(vispera, ASIA[0]))
    a1 = comun.de_ny(dt.datetime.combine(dia, ASIA[1]))
    return {"asia": (a0, a1), "londres": (a1, o), "nueva_york": (o, c)}


def tamano_fila(codigo, alto, bajo, fila=None):
    """Tamaño de fila en puntos: el pedido (al tick) o el que da unas FILAS_OBJETIVO filas, en múltiplos del tick del mini."""
    tick = comun.tick_de(codigo, micro=False)
    if fila:
        if fila < tick - 1e-12:
            raise KemetError("--fila %s es menos que un tick de %s (%s)" % (pts(fila), codigo, pts(tick)))
        return comun.al_tick(fila, tick)
    bruto = max(tick, (alto - bajo) / float(FILAS_OBJETIVO)) / tick      # en ticks
    escala = 10 ** math.floor(math.log10(bruto))
    for m in (1, 2, 2.5, 5, 10):                                           # filas redondas: 1, 2, 5, 10, 20, 25… ticks
        if m * escala >= bruto - 1e-9 and float(m * escala).is_integer():
            return comun.al_tick(m * escala * tick, tick)
    return comun.al_tick(math.ceil(bruto) * tick, tick)


def perfil(velas_, codigo, fila=None):
    """Perfil de volumen de una lista de velas (ts, o, h, l, c, v). Devuelve None sin velas o sin volumen."""
    velas_ = [b for b in velas_ if b[5] > 0]
    if not velas_:
        return None
    alto, bajo = max(b[2] for b in velas_), min(b[3] for b in velas_)
    paso = tamano_fila(codigo, alto, bajo, fila)
    base = math.floor(bajo / paso + 1e-9) * paso
    n = int(math.floor((alto - base) / paso + 1e-9)) + 1
    filas = [0.0] * n
    for b in velas_:
        i0 = int(math.floor((b[3] - base) / paso + 1e-9))
        i1 = int(math.floor((b[2] - base) / paso + 1e-9))
        i0, i1 = max(0, i0), min(n - 1, i1)
        parte = b[5] / float(i1 - i0 + 1)
        for i in range(i0, i1 + 1):
            filas[i] += parte
    total = sum(filas)
    poc = max(range(n), key=lambda i: (filas[i], -abs(i - n / 2.0)))
    lo = hi = poc
    dentro = filas[poc]
    while dentro < AREA_VALOR * total - 1e-9 and (lo > 0 or hi < n - 1):
        arriba = filas[hi + 1] if hi < n - 1 else -1
        abajo = filas[lo - 1] if lo > 0 else -1
        if arriba >= abajo:
            hi += 1
            dentro += arriba
        else:
            lo -= 1
            dentro += abajo
    centro = lambda i: base + (i + 0.5) * paso
    tick = comun.tick_de(codigo, micro=False)
    vah = min(alto, comun.al_tick(base + (hi + 1) * paso, tick))
    val = max(bajo, comun.al_tick(base + lo * paso, tick))
    return {"poc": min(alto, max(bajo, comun.al_tick(centro(poc), tick))), "vah": vah, "val": val,
            "alto": alto, "bajo": bajo, "volumen": int(round(total)), "velas": len(velas_), "fila": paso,
            "filas": [[comun.al_tick(centro(i), tick), int(round(v))] for i, v in enumerate(filas)]}


def calcular(codigo, ch, ahora_utc, fila=None):
    """Los perfiles del día de CME en curso (lo que llevan sus sesiones a esta hora) y el de Nueva York de la sesión anterior."""
    inst = comun.resolver(codigo)
    if inst["tipo"] == "accion":
        raise KemetError("%s es una acción: solo tiene la sesión de Nueva York. Los perfiles por sesión son de futuros (NQ, ES, CL, GC…)" % codigo)
    velas_ = comun.velas_cerradas(ch, ahora_utc)
    hoy = comun.dia_negociacion(comun.a_ny(ahora_utc))
    out = {"mercado": codigo, "fecha": hoy.isoformat(), "fuente": FUENTE, "sesiones": [], "avisos": []}
    for dia, solo in ((hoy, None), (comun.dia_negociacion(comun.a_ny(ahora_utc)) - dt.timedelta(days=1), "nueva_york")):
        d = dia
        if solo:  # la sesión anterior con velas de Nueva York (salta fines de semana y festivos)
            for _ in range(7):
                o, c = tramos(codigo, d)["nueva_york"]
                if any(comun.ts_de_utc(o) <= b[0] < comun.ts_de_utc(c) for b in velas_):
                    break
                d -= dt.timedelta(days=1)
        for nombre, (t0, t1) in tramos(codigo, d).items():
            if solo and nombre != solo:
                continue
            a, z = comun.ts_de_utc(t0), comun.ts_de_utc(t1)
            sel = [b for b in velas_ if a <= b[0] < z]
            p = perfil(sel, codigo, fila)
            if not p:
                if not solo and t0 <= ahora_utc:
                    out["avisos"].append("%s %s: sin velas con volumen" % (NOMBRES[nombre], d.isoformat()))
                continue
            p.update({"sesion": nombre, "nombre": NOMBRES[nombre] + (" de ayer" if solo else ""), "color": COLORES[nombre], "dia": d.isoformat(),
                      "desde_ny": comun.hhmm(comun.a_ny(t0).time()), "hasta_ny": comun.hhmm(comun.a_ny(t1).time()),
                      "en_curso": t0 <= ahora_utc < t1})
            out["sesiones"].append(p)
    if not out["sesiones"]:
        raise KemetError("sin velas con volumen para %s en esas sesiones" % codigo)
    return out


def informe(doc, ahora_utc):
    L = ["PERFILES DE VOLUMEN · %s · día de CME %s · %s" % (doc["mercado"], doc["fecha"], comun.hora_doble(ahora_utc))]
    for p in doc["sesiones"]:
        L.append("  %-18s %s–%s NY%s · POC %s · VAH %s · VAL %s · rango %s–%s · %s velas · filas de %s pts · %s"
                 % (p["nombre"], p["desde_ny"], p["hasta_ny"], " (en curso)" if p["en_curso"] else "", pts(p["poc"]), pts(p["vah"]), pts(p["val"]),
                    pts(p["bajo"]), pts(p["alto"]), p["velas"], pts(p["fila"]), p["color"]))
    for a in doc["avisos"]:
        L.append("AVISO: " + a)
    L.append("Fuente: %s. Es una aproximación con velas de 5 min, no el perfil de cada operación; márcalo en tu plataforma." % doc["fuente"])
    return "\n".join(L)


def main(argv=None):
    p = argparse.ArgumentParser(description="Perfiles de volumen por sesión (Asia, Londres, Nueva York) de un futuro (kemet-niveles).")
    p.add_argument("--mercado", default=None, help="un futuro: NQ, ES, CL, GC… (por defecto el de kemet/config.json, y si no hay, NQ)")
    p.add_argument("--fila", type=float, help="tamaño de fila en puntos (por defecto el que da unas 60 filas)")
    p.add_argument("--ahora", help='hora de Nueva York, "AAAA-MM-DD HH:MM"')
    p.add_argument("--offline", help="archivo JSON de Yahoo (.json o .json.gz) o la carpeta tests/fixtures/yahoo")
    p.add_argument("--escribir", action="store_true", help="guarda kemet/perfil.json")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    try:
        ahora = comun.parse_ahora(a.ahora)
        cfg = comun.leer_json("config.json", obligatorio=False) or {}
        codigo = comun.resolver((a.mercado or cfg.get("mercado") or "NQ").upper())["codigo"]
        ch = comun.velas(codigo, "60d", "5m", a.offline) if not a.offline else _offline(codigo, a.offline)
        doc = calcular(codigo, ch, ahora, a.fila)
        if a.escribir:
            comun.escribir_json("perfil.json", dict(doc, generado=comun.iso(ahora)))
        print(json.dumps(doc, ensure_ascii=False, indent=1) if a.json else informe(doc, ahora))
        return 0
    except KemetError as e:
        print("perfil.py: %s" % e, file=sys.stderr)
        return 2


def _offline(codigo, ruta):
    ultimo = None
    for r in ("60d", "5d"):
        try:
            return comun.velas(codigo, r, "5m", ruta)
        except KemetError as e:
            ultimo = e
    raise ultimo


if __name__ == "__main__":
    sys.exit(main())
