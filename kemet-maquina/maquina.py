#!/usr/bin/env python3
"""La máquina del tiempo de kemet-maquina. Solo biblioteca estándar.

Repite el resto de la sesión 10.000 veces desde tu entrada, con las velas reales del propio contrato, y vuelve a
pasar la regla del plan por cada sesión anterior del archivo. Antes de poner nada.

    python3 maquina.py run                               # kemet/plan.json, 10.000 repeticiones, semilla 19
    python3 maquina.py run --escribir                    # además guarda kemet/maquina.json
    python3 maquina.py run --hasta 15:55                 # cada repetición termina a tu hora de estar plano
    python3 maquina.py run --semilla 7 --repeticiones 20000 --json
    python3 maquina.py run --mercado NQ --fecha 2026-11-11 --lado largo --entrada 28426.25 \\
        --stop 28199 --objetivo 28539.75 --hora-entrada 10:45
    python3 maquina.py chart                             # abanico ASCII de las repeticiones
    python3 maquina.py chart --desde kemet/maquina.json

Cómo funcionan las repeticiones (el algoritmo del Time Machine de day-trader-skill, MIT, llevado a futuros):
  1. Velas de 5 minutos de Yahoo (60 días). Se guardan solo las SESIONES REGULARES COMPLETAS del contrato
     anteriores a la fecha del plan: NQ y ES 78 velas de 09:30 a 16:00 NY, CL 66 (09:00 a 14:30), GC 62
     (08:20 a 13:30), por día de negociación de CME. Sesiones recortadas, con huecos y la de hoy se quedan fuera.
  2. El pool: para cada posición de vela 1..N-1 del día, la vela de cada sesión pasada como ratios sobre el
     cierre de la vela anterior: (apertura, máximo, mínimo, cierre) / cierre previo.
  3. Una repetición arranca en el precio de entrada y recorre el resto de la sesión. Para cada vela i elige
     una posición j = i + randint(-ventana, ventana) dentro de 1..N-1, una vela pasada de pool[j] al azar
     (random.choice) y la escala al precio actual. El stop se comprueba antes que el objetivo en cada vela:
     una vela que toca los dos cuenta como stop (lo conservador). En un corto el stop está por encima y el
     objetivo por debajo.
  4. Resultados: "objetivo" o "stop" (el que se tocó primero) o "ninguno" cuando la operación sigue abierta a
     --hasta (por defecto plano_a del plan: 15:55 en índices, 14:25 en CL, 13:25 en GC).
     "verde" = objetivo primero, o por encima de la entrada a --hasta (por debajo en un corto).
     R = la R del objetivo si llegó, -1 en el stop, si no (precio a --hasta - entrada) / riesgo. Un hueco a
     través del stop cuenta -1R aquí; un relleno real puede ser peor.
  5. Precio a --hasta: mediana y percentiles 5 y 95 de todas las repeticiones (pct(a, q) = a ordenada en
     int(q * n)). El abanico usa una segunda tirada de 2.000 caminos con la misma semilla. El histograma tiene
     24 cajas entre los percentiles 1 y 99.
  6. La historia: la regla del plan tal cual en cada sesión del pool. Balance inicial (IB) de los mismos minutos
     (60 por defecto: 09:30 a 10:30 NY en índices); disparo = la primera vela de 5 minutos cerrada después del IB que
     CIERRA por encima del IB alto (largo) o por debajo del IB bajo (corto); una mecha no dispara, un cierre exacto
     en el nivel tampoco; entrada = ese cierre; sin entradas antes de sin_entradas_antes (09:45) ni después de
     sin_entradas_despues (15:00); stop según regla_stop (ib-medio por defecto, ib-opuesto, pts:X), objetivo según
     regla_objetivo (R:1 por defecto, R:2); stop antes que objetivo vela a vela; plano a --hasta. Sin filtro: cuentan
     todas las sesiones en las que disparó, una operación por día, los dos lados. Un objetivo o un stop a un precio
     fijo (precio:X) no se puede repetir en otros días: se usa la distancia del plan en puntos y se dice.

La línea del veredicto mira solo las repeticiones que tocan un lado (objetivo o stop) y compara la parte del
objetivo, objetivo / (objetivo + stop), con la que empata a la R del plan: 1 / (1 + R), el 50 % a 1R, el 33 % a 2R,
el 67 % a 0,5R. La diferencia, en puntos porcentuales:
  menos de 5 puntos    "Casi una moneda al aire" (1R) / "Casi en el punto de equilibrio" (otra R)
  de 5 a 15 puntos     "Se inclina hacia el objetivo" / "Se inclina hacia el stop"
  15 puntos o más      "Claramente hacia el objetivo" / "Claramente hacia el stop"
Debajo: una nota cuando más del 40 % de las repeticiones no toca ningún lado (el precio a --hasta decide esas), y
la R media cuando su signo va contra la inclinación.

Velas de 5 minutos: Yahoo guarda 60 días en 5 m y unos 7 en 1 m, pocas sesiones para un pool justo. Rechaza en
una línea con menos de 20 sesiones completas. Mismo plan, mismos datos y misma --semilla dan los mismos números
en cualquier máquina. Una simulación hecha con las velas recientes del contrato no es una predicción: un dato,
una noticia o un día de pánico hacen lo que los últimos 60 días no hicieron.

Convención de velas: `hora_entrada` es la hora a la que CIERRA la vela del disparo y `barra` su número desde la
apertura (la vela 1 cierra a las 09:35; la 15, a las 10:45). Las repeticiones empiezan en la vela siguiente.
Todo en puntos del contrato y en R; los dólares por micro (comun.CONTRATOS) son contexto, nunca un resultado.
"""
import argparse
import datetime as dt
import json
import math
import os
import random
import statistics
import sys

import comun
from comun import KemetError

MIN_SESIONES = 20
CAMINOS = 160
CAMINOS_BANDAS = 2000
BANDAS_Q = (0.05, 0.25, 0.5, 0.75, 0.95)
CAJAS = 24
MONEDA = 0.05          # umbrales del veredicto, ver el docstring
CLARO = 0.15
MUCHOS_NINGUNO = 0.40
IB_MINUTOS = 60
SIN_ENTRADAS_ANTES = "09:45"
SIN_ENTRADAS_DESPUES = "15:00"
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


# ---------------------------------------------------------------- horas y velas

def fecha_es(d):
    return d.strftime("%d/%m/%Y")


def minutos(t):
    return t.hour * 60 + t.minute


def hhmm_min(m):
    return "%02d:%02d" % divmod(m, 60)


def sesion_min(codigo, dia):
    """(apertura, cierre) en minutos NY de la sesión regular de ese día y cuántas velas de 5 min tiene."""
    o, c = comun.sesion_regular(codigo, dia)
    a, z = minutos(comun.a_ny(o)), minutos(comun.a_ny(c))
    return a, z, (z - a) // 5


def velas_normales(codigo):
    o, c = comun.CONTRATOS[codigo]["rth"]
    return (minutos(comun.parse_hhmm(c)) - minutos(comun.parse_hhmm(o))) // 5


def indice_cierre(codigo, dia, hora, que):
    """Hora de cierre de una vela (HH:MM NY) -> índice 0..N-1 de esa vela en la sesión regular."""
    t = comun.parse_hhmm(hora, que)
    a, z, n = sesion_min(codigo, dia)
    m = minutos(t)
    if (m - a) % 5:
        raise KemetError("%s %s no cae en la rejilla de 5 minutos (usa el cierre de la vela, p. ej. 10:45)" % (que, hora))
    k = (m - a) // 5 - 1
    if not 0 <= k <= n - 1:
        raise KemetError("%s %s está fuera de la sesión regular de %s (%s a %s)" % (que, hora, codigo, hhmm_min(a), hhmm_min(z)))
    return k


def hora_cierre(codigo, dia, k):
    a, _, _ = sesion_min(codigo, dia)
    return hhmm_min(a + 5 * (k + 1))


def sesiones_completas(codigo, dias, antes):
    """Sesiones regulares completas (todas las velas, sin huecos) anteriores a `antes`, de la más vieja a la más nueva,
    y las cortas que se quedaron fuera (recortadas, huecos)."""
    n_normal = velas_normales(codigo)
    completas, cortas = [], []
    for d in sorted(dias):
        if d >= antes:
            break
        o, c = comun.sesion_regular(codigo, d)
        n = int((c - o).total_seconds() // 300)
        rth = comun.regular(codigo, dias[d], d)
        por_ts = {b[0]: b for b in rth}
        esperadas = [comun.ts_de_utc(o) + 300 * i for i in range(n)]
        if n == n_normal and all(t in por_ts for t in esperadas):
            completas.append((d, [por_ts[t] for t in esperadas]))
        else:
            cortas.append({"fecha": d.isoformat(), "velas": len(rth)})
    return completas, cortas


# ---------------------------------------------------------------- la simulación

def construir_pool(sesiones, n):
    """pool[i] = la vela i de cada sesión pasada como (o, h, l, c) / cierre de la vela i-1, en orden de fecha."""
    pool = [[] for _ in range(n)]
    for _, D in sesiones:
        for i in range(1, n):
            pc = D[i - 1][4]
            pool[i].append((D[i][1] / pc, D[i][2] / pc, D[i][3] / pc, D[i][4] / pc))
    return pool


def pct(a, q):
    return a[min(len(a) - 1, int(q * len(a)))]


def simular(pool, entrada, stop, objetivo, k, last, repeticiones=10000, semilla=19, ventana=2, largo=True):
    """Repeticiones Monte Carlo de las velas k+1..last. Mismas tiradas y mismo orden que el Time Machine original."""
    n = len(pool)
    riesgo = (entrada - stop) if largo else (stop - entrada)
    r_objetivo = round(((objetivo - entrada) if largo else (entrada - objetivo)) / riesgo, 4)

    def pos(rng, i):
        return i if ventana == 0 else min(n - 1, max(1, i + rng.randint(-ventana, ventana)))

    rng = random.Random(semilla)
    elegir = rng.choice
    resultados, cierres, caminos = [], [], []
    for r in range(repeticiones):
        p = entrada
        res = None
        guardar = r < CAMINOS
        camino = [entrada]
        for i in range(k + 1, last + 1):
            o, h, l, c = elegir(pool[pos(rng, i)])
            hi, lo, cl = p * h, p * l, p * c
            if res is None:
                if largo:
                    if lo <= stop:
                        res = "stop"          # los dos en la misma vela: cuenta la pérdida (conservador)
                    elif hi >= objetivo:
                        res = "objetivo"
                else:
                    if hi >= stop:
                        res = "stop"
                    elif lo <= objetivo:
                        res = "objetivo"
            p = cl
            if guardar:
                camino.append(round(p, 2))
        resultados.append(res or "ninguno")
        cierres.append(p)
        if guardar:
            caminos.append(camino)
    cnt = {x: resultados.count(x) for x in ("objetivo", "stop", "ninguno")}
    verde = sum(1 for res, p in zip(resultados, cierres)
                if res == "objetivo" or (res == "ninguno" and (p > entrada if largo else p < entrada)))
    Rs = [r_objetivo if res == "objetivo" else -1.0 if res == "stop" else ((p - entrada) if largo else (entrada - p)) / riesgo
          for res, p in zip(resultados, cierres)]
    srt = sorted(cierres)
    # bandas por vela para el abanico: una segunda tirada de 2.000 caminos, misma semilla
    rng = random.Random(semilla)
    elegir = rng.choice
    todos = []
    for r in range(CAMINOS_BANDAS):
        p = entrada
        camino = [entrada]
        for i in range(k + 1, last + 1):
            o, h, l, c = elegir(pool[pos(rng, i)])
            p = p * c
            camino.append(p)
        todos.append(camino)
    bandas = []
    for j in range(last - k + 1):
        col = sorted(pp[j] for pp in todos)
        bandas.append([round(pct(col, q), 2) for q in BANDAS_Q])
    lo_, hi_ = pct(srt, 0.01), pct(srt, 0.99)
    W = (hi_ - lo_) / CAJAS
    cajas = [0] * CAJAS
    for c in srt:
        b = int((c - lo_) / W) if W > 0 else 0
        if 0 <= b < CAJAS:
            cajas[b] += 1
    return {
        "repeticiones": repeticiones, "semilla": semilla, "ventana": ventana, "velas_restantes": last - k,
        "objetivo_primero": round(cnt["objetivo"] / repeticiones, 4), "stop_primero": round(cnt["stop"] / repeticiones, 4),
        "ninguno": round(cnt["ninguno"] / repeticiones, 4), "verde": round(verde / repeticiones, 4),
        "mediana_cierre": round(pct(srt, 0.5), 2), "p5": round(pct(srt, 0.05), 2), "p95": round(pct(srt, 0.95), 2),
        "r_media": round(statistics.mean(Rs), 3), "r_objetivo": r_objetivo,
        "caminos_bandas": CAMINOS_BANDAS, "bandas": bandas, "caminos": caminos,
        "histograma": {"desde": round(lo_, 2), "hasta": round(hi_, 2), "cajas": cajas},
    }


# ---------------------------------------------------------------- la historia: la regla del plan en cada sesión pasada

def regla_historia(plan, ib_dia, tick):
    """Qué regla repite la historia: la del plan. `regla_stop` y `regla_objetivo` vienen de salida.py; si faltan (plan por
    flags) se deducen comparando el stop y el objetivo con el IB del día. Lo que no se puede repetir en otros días (un
    precio fijo, un ATR que el plan no trae) se convierte en la distancia del plan en puntos y se apunta en `avisos`."""
    largo = plan["lado"] == "largo"
    riesgo = plan["riesgo_pts"]
    recompensa = round(abs(plan["objetivo"] - plan["entrada"]), 4)
    ib = plan.get("ib") or ib_dia
    rs, ro = plan.get("regla_stop"), plan.get("regla_objetivo")
    avisos = []
    if not rs:
        if ib and abs(plan["stop"] - comun.al_tick((ib["alto"] + ib["bajo"]) / 2.0, tick)) <= tick + 1e-9:
            rs = "ib-medio"
        elif ib and abs(plan["stop"] - (ib["bajo"] if largo else ib["alto"])) <= tick + 1e-9:
            rs = "ib-opuesto"
        else:
            rs = "pts:%s" % comun.pts(riesgo)
    if not ro:
        ro = "R:%s" % erres(plan["rr"])
    rs, ro = str(rs), str(ro)
    if rs in ("ib-medio", "ib-opuesto"):
        stop = {"regla": rs}
    elif rs.startswith("pts:"):
        try:
            stop = {"regla": "pts", "pts": float(rs[4:].replace(",", "."))}
        except ValueError:
            stop = {"regla": "pts", "pts": riesgo}
    else:
        stop = {"regla": "pts", "pts": riesgo}
        avisos.append("el stop del plan es %s y eso no se puede repetir en otros días: la historia usa su distancia, %s pts" % (rs, comun.pts(riesgo)))
    if ro[:2] in ("R:", "r:"):
        try:
            objetivo = {"regla": "R", "valor": float(ro[2:].replace(",", "."))}
        except ValueError:
            objetivo = {"regla": "R", "valor": plan["rr"]}
    else:
        objetivo = {"regla": "pts", "pts": recompensa}
        avisos.append("el objetivo del plan es %s y eso no se puede repetir en otros días: la historia usa su distancia, %s pts" % (ro, comun.pts(recompensa)))
    return {"stop": stop, "objetivo": objetivo, "regla_stop": rs, "regla_objetivo": ro, "avisos": avisos}


def describir_regla(regla, plan):
    s, o = regla["stop"], regla["objetivo"]
    st = {"ib-medio": "stop en el punto medio del IB", "ib-opuesto": "stop en el lado opuesto del IB"}.get(s["regla"], "stop a %s pts" % comun.pts(s.get("pts", 0)))
    ob = "objetivo %sR" % erres(o["valor"]) if o["regla"] == "R" else "objetivo a %s pts" % comun.pts(o["pts"])
    return ("la misma regla (IB de %d minutos, primera vela cerrada fuera del IB entre las %s y las %s, entrada en su cierre, %s, %s, plano a %s)"
            % (plan["ib_minutos"], plan["sin_entradas_antes"], plan["sin_entradas_despues"], st, ob, "la hora de --hasta"))


def historia_regla(codigo, sesiones, regla, plan, last):
    """La regla del plan en cada sesión completa anterior: IB de `ib_minutos`, primera vela cerrada después del IB que cierra
    fuera (largo por encima del IB alto, corto por debajo del IB bajo), dentro de la ventana de entradas; stop antes que
    objetivo vela a vela desde la vela siguiente; si no, el cierre de la vela `last`."""
    tick = comun.CONTRATOS[codigo]["tick"]
    ib_n = plan["ib_minutos"] // 5
    antes = minutos(comun.parse_hhmm(plan["sin_entradas_antes"]))
    despues = minutos(comun.parse_hhmm(plan["sin_entradas_despues"]))
    cuenta = {"sesiones": len(sesiones), "sin_disparo": 0, "largos": 0, "cortos": 0, "ib_minutos": plan["ib_minutos"]}
    ops = []
    for d, D in sesiones:
        if last >= len(D) or ib_n > last:
            continue
        a, _, _ = sesion_min(codigo, d)
        ib = D[:ib_n]
        alto, bajo = max(b[2] for b in ib), min(b[3] for b in ib)
        ancho = round(alto - bajo, 4)
        k = lado = None
        for i in range(ib_n, last):
            cierre_vela = a + 5 * (i + 1)
            if cierre_vela < antes:
                continue
            if cierre_vela > despues:
                break
            c = D[i][4]
            if c > alto:
                lado = "largo"
            elif c < bajo:
                lado = "corto"
            if lado:
                k = i
                break
        if k is None:
            cuenta["sin_disparo"] += 1
            continue
        largo = lado == "largo"
        entrada = D[k][4]
        if regla["stop"]["regla"] == "ib-medio":
            stop = (alto + bajo) / 2.0
        elif regla["stop"]["regla"] == "ib-opuesto":
            stop = bajo if largo else alto
        else:
            stop = entrada - regla["stop"]["pts"] if largo else entrada + regla["stop"]["pts"]
        stop = comun.al_tick(stop, tick)
        riesgo = (entrada - stop) if largo else (stop - entrada)
        if riesgo <= 0:
            cuenta["sin_disparo"] += 1
            continue
        o = regla["objetivo"]
        dist = o["valor"] * riesgo if o["regla"] == "R" else o["pts"]
        objetivo = comun.al_tick(entrada + dist if largo else entrada - dist, tick)
        res = None
        for b in D[k + 1:last + 1]:
            if (b[3] <= stop) if largo else (b[2] >= stop):
                res = "stop"
                break
            if (b[2] >= objetivo) if largo else (b[3] <= objetivo):
                res = "objetivo"
                break
        cierre = D[last][4]
        R = (((objetivo - entrada) if largo else (entrada - objetivo)) / riesgo if res == "objetivo" else -1.0 if res == "stop"
             else ((cierre - entrada) if largo else (entrada - cierre)) / riesgo)
        cuenta["largos" if largo else "cortos"] += 1
        ops.append({"fecha": d.isoformat(), "lado": lado, "hora": hora_cierre(codigo, d, k), "barra": k + 1,
                    "ib": {"alto": alto, "bajo": bajo, "ancho": ancho}, "entrada": entrada, "stop": stop, "objetivo": objetivo,
                    "riesgo_pts": round(riesgo, 4), "resultado": res or "ninguno", "R": round(R, 2)})
    cuenta.update({
        "disparos": len(ops),
        "objetivo": sum(1 for x in ops if x["resultado"] == "objetivo"),
        "stop": sum(1 for x in ops if x["resultado"] == "stop"),
        "ninguno": sum(1 for x in ops if x["resultado"] == "ninguno"),
        "verdes": sum(1 for x in ops if x["R"] > 0),
        "r_media": round(statistics.mean(x["R"] for x in ops), 3) if ops else None,
        "regla": {k: v for k, v in regla.items() if k != "avisos"}, "operaciones": ops,
    })
    return cuenta


# ---------------------------------------------------------------- el plan

def _num(v, que):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise KemetError("el plan necesita un número en %s, no %r" % (que, v))
    if not x > 0 or math.isinf(x):
        raise KemetError("%s del plan tiene que ser un precio positivo, no %r" % (que, v))
    return x


def mercado_por_defecto(a):
    if getattr(a, "mercado", None):
        return a.mercado.upper()
    cfg = comun.leer_json("config.json", obligatorio=False) or {}
    return str(cfg.get("mercado") or "NQ").upper()


def cargar_plan(a, ahora):
    """El plan de kemet/plan.json (o --plan RUTA) o de los flags, comprobado y normalizado."""
    if a.entrada is not None or a.stop is not None or a.objetivo is not None:
        faltan = [f for f in ("entrada", "stop", "objetivo") if getattr(a, f) is None]
        if faltan:
            raise KemetError("con el plan por flags hacen falta también %s" % ", ".join("--" + f for f in faltan))
        crudo = {"mercado": mercado_por_defecto(a), "lado": a.lado, "fecha": a.fecha or comun.a_ny(ahora).date().isoformat(),
                 "entrada": a.entrada, "stop": a.stop, "objetivo": a.objetivo, "hora_entrada": a.hora_entrada,
                 "plano_a": a.hasta, "regla_stop": a.regla_stop, "regla_objetivo": a.regla_objetivo}
        origen = "flags"
    else:
        p = a.plan or comun.ruta("plan.json")
        crudo = comun.leer_json(p, "pásalo por kemet-salida primero, o da --mercado --fecha --lado --entrada --stop --objetivo --hora-entrada")
        if not isinstance(crudo, dict):
            raise KemetError("%s no es un plan" % p)
        if a.hora_entrada:
            crudo = dict(crudo, hora_entrada=a.hora_entrada, barra=None)
        origen = p
    cfg = comun.leer_json("config.json", obligatorio=False) or {}
    return normalizar_plan(crudo, origen, cfg, a.ib_minutos)


def normalizar_plan(crudo, origen="flags", cfg=None, ib_minutos=None):
    codigo = str(crudo.get("mercado") or comun.MICRO_A_CODIGO.get(str(crudo.get("micro") or "").upper()) or "").upper()
    if codigo not in comun.CONTRATOS:
        raise KemetError("el plan necesita un mercado de %s, no %r" % ("/".join(sorted(comun.CONTRATOS)), crudo.get("mercado")))
    lado = str(crudo.get("lado") or "largo").lower()
    if lado not in ("largo", "corto"):
        raise KemetError("lado tiene que ser largo o corto, no %r" % crudo.get("lado"))
    try:
        fecha = dt.date.fromisoformat(str(crudo.get("fecha") or ""))
    except ValueError:
        raise KemetError("el plan necesita una fecha como 2026-11-11, no %r" % crudo.get("fecha"))
    entrada, stop, objetivo = (_num(crudo.get(k), k) for k in ("entrada", "stop", "objetivo"))
    largo = lado == "largo"
    if largo and not stop < entrada < objetivo:
        raise KemetError("un largo necesita stop < entrada < objetivo (stop %s, entrada %s, objetivo %s)"
                         % (comun.pts(stop), comun.pts(entrada), comun.pts(objetivo)))
    if not largo and not objetivo < entrada < stop:
        raise KemetError("un corto necesita objetivo < entrada < stop (objetivo %s, entrada %s, stop %s)"
                         % (comun.pts(objetivo), comun.pts(entrada), comun.pts(stop)))
    notas = []
    k = None
    if crudo.get("hora_entrada"):
        k = indice_cierre(codigo, fecha, str(crudo["hora_entrada"]), "hora_entrada")
    if crudo.get("barra") is not None:
        try:
            kb = int(crudo["barra"]) - 1
        except (TypeError, ValueError):
            raise KemetError("barra tiene que ser el número de la vela, no %r" % crudo["barra"])
        if k is not None and kb != k:
            raise KemetError("el plan se contradice: barra %d pero hora_entrada %s es la vela %d" % (kb + 1, crudo["hora_entrada"], k + 1))
        k = kb
    a, z, n = sesion_min(codigo, fecha)
    cfg = cfg or {}
    ib_crudo = crudo.get("ib") if isinstance(crudo.get("ib"), dict) else {}
    ib_min = int(ib_minutos or ib_crudo.get("minutos") or IB_MINUTOS)
    if ib_min < 5 or ib_min % 5 or ib_min >= (z - a):
        raise KemetError("los minutos del IB tienen que ser un múltiplo de 5 dentro de la sesión, no %s" % ib_min)
    if k is None:
        k = ib_min // 5                     # la primera vela que puede cerrar fuera del IB
        notas.append("el plan no trae hora_entrada: se simula desde la primera vela después del IB, la que cierra a las %s"
                     % hhmm_min(a + 5 * (k + 1)))
    if not 0 <= k <= n - 2:
        raise KemetError("la entrada tiene que cerrar entre %s y %s para dejar velas que repetir (vela %d)"
                         % (hhmm_min(a + 5), hhmm_min(z - 5), k + 1))
    riesgo = round((entrada - stop) if largo else (stop - entrada), 4)
    c = comun.CONTRATOS[codigo]
    ib = dict(ib_crudo) if all(x in ib_crudo for x in ("alto", "bajo")) else None
    if ib and "ancho" not in ib:
        ib["ancho"] = round(ib["alto"] - ib["bajo"], 4)
    antes = str(crudo.get("sin_entradas_antes") or cfg.get("sin_entradas_antes") or SIN_ENTRADAS_ANTES)
    despues = str(crudo.get("sin_entradas_despues") or cfg.get("sin_entradas_despues") or SIN_ENTRADAS_DESPUES)
    comun.parse_hhmm(antes, "sin_entradas_antes")
    comun.parse_hhmm(despues, "sin_entradas_despues")
    return {
        "mercado": codigo, "micro": c["micro"], "fecha": fecha.isoformat(), "lado": lado,
        "entrada": entrada, "hora_entrada": hhmm_min(a + 5 * (k + 1)), "barra": k + 1,
        "stop": stop, "objetivo": objetivo, "riesgo_pts": riesgo,
        "recompensa_pts": round(abs(objetivo - entrada), 4),
        "rr": round(abs(objetivo - entrada) / riesgo, 2),
        "riesgo_usd_micro": round(riesgo * c["punto_micro"], 2), "riesgo_usd_mini": round(riesgo * c["punto_mini"], 2),
        "plano_a": crudo.get("plano_a") or cfg.get("plano_a") or c["plano"],
        "regla_stop": crudo.get("regla_stop"), "regla_objetivo": crudo.get("regla_objetivo"),
        "ib": ib, "ib_minutos": ib_min, "sin_entradas_antes": antes, "sin_entradas_despues": despues,
        "origen": origen, "notas": notas,
    }


# ---------------------------------------------------------------- veredicto

def inclinacion(mc):
    """(diferencia, parte, equilibrio): la parte del objetivo entre las repeticiones que tocan un lado, menos la que
    empata a la R del objetivo. None si ninguna tocó un lado."""
    po, ps = mc["objetivo_primero"], mc["stop_primero"]
    if po + ps <= 0:
        return None
    r = mc.get("r_objetivo") or 1.0
    parte, equilibrio = po / (po + ps), 1.0 / (1.0 + r)
    return parte - equilibrio, parte, equilibrio


def pc(x, d=1):
    return comun.num(100.0 * x, d) + " %"


def veredicto(mc):
    hasta = mc.get("hasta", "el cierre")
    po, ps = mc["objetivo_primero"], mc["stop_primero"]
    lv = inclinacion(mc)
    if lv is None:
        return "Ninguna repetición tocó el objetivo ni el stop antes de las %s: el precio a esa hora decide todas." % hasta
    d, parte, equilibrio = lv
    r = mc.get("r_objetivo") or 1.0
    una_r = abs(r - 1.0) < 0.005
    if abs(d) < MONEDA:
        cabeza = "Casi una moneda al aire" if una_r else "Casi en el punto de equilibrio"
    elif abs(d) < CLARO:
        cabeza = "Se inclina hacia el objetivo" if d > 0 else "Se inclina hacia el stop"
    else:
        cabeza = "Claramente hacia el objetivo" if d > 0 else "Claramente hacia el stop"
    odds = "objetivo primero %s frente a stop primero %s" % (pc(po), pc(ps))
    if una_r:
        return "%s: %s." % (cabeza, odds)
    return ("%s: a %sR el objetivo tiene que llegar primero en el %s de las repeticiones que tocan un lado; llegó en el %s (%s)."
            % (cabeza, erres(round(r, 2)), pc(equilibrio, 0), pc(parte, 0), odds))


def notas_veredicto(mc):
    notas = []
    hasta = mc.get("hasta", "el cierre")
    pn = mc.get("ninguno", 0)
    lv = inclinacion(mc)
    if pn > MUCHOS_NINGUNO and lv is not None:
        notas.append("El %s de las repeticiones no toca ni el objetivo ni el stop antes de las %s; el precio a esa hora decide esas."
                     % (pc(pn), hasta))
    media = mc.get("r_media")
    if lv and abs(lv[0]) >= MONEDA and media is not None and media != 0 and (media > 0) != (lv[0] > 0):
        notas.append("La R media es %s de todos modos: las repeticiones que no tocan ningún lado tiran hacia el otro."
                     % signo(media, 3))
    return notas


def signo(x, d=3):
    return ("+" if x > 0 else "") + comun.num(x, d)


def erres(x):
    """0.5 -> 0,5; 1.0 -> 1; 1.25 -> 1,25 (la R del objetivo)."""
    s = comun.num(x, 2).rstrip("0").rstrip(",")
    return s or "0"


def dinero(x):
    return comun.usd(x, 0) if abs(x - round(x)) < 1e-9 else comun.usd(x, 2)


# ---------------------------------------------------------------- la corrida

def maquina(ch, plan, ahora, repeticiones=10000, semilla=19, ventana=2, hasta=None, fuente="yahoo"):
    if not 1 <= repeticiones <= 1000000:
        raise KemetError("--repeticiones tiene que estar entre 1 y 1.000.000")
    if not 0 <= ventana <= 10:
        raise KemetError("--ventana tiene que estar entre 0 y 10 velas")
    if ch.get("intervalo") and ch["intervalo"] != "5m":
        raise KemetError("los datos son velas de %s; la máquina necesita velas de 5 minutos" % ch["intervalo"])
    codigo = plan["mercado"]
    c = comun.CONTRATOS[codigo]
    tick = c["tick"]
    fecha = dt.date.fromisoformat(plan["fecha"])
    velas_ = comun.velas_cerradas(ch, ahora)
    if not velas_:
        raise KemetError("no hay velas de 5 minutos cerradas de %s en los datos" % codigo)
    a, z, n_dia = sesion_min(codigo, fecha)
    n = velas_normales(codigo)
    k = plan["barra"] - 1
    hasta = hasta or plan.get("plano_a") or c["plano"]
    last = indice_cierre(codigo, fecha, hasta, "--hasta")
    if last <= k:
        raise KemetError("--hasta %s no deja nada que repetir después de la entrada de las %s" % (hasta, plan["hora_entrada"]))
    dias = comun.por_dia(velas_)
    sesiones, cortas = sesiones_completas(codigo, dias, fecha)
    if len(sesiones) < MIN_SESIONES:
        raise KemetError("solo %d sesión(es) completa(s) de %s antes del %s en los datos; la máquina necesita al menos %d"
                         % (len(sesiones), codigo, fecha_es(fecha), MIN_SESIONES))
    avisos = list(plan.get("notas") or [])
    dia_plan = dias.get(fecha, [])
    rth_plan = comun.regular(codigo, dia_plan, fecha) if dia_plan else []
    o_utc, _ = comun.sesion_regular(codigo, fecha)
    ts_k = comun.ts_de_utc(o_utc) + 300 * k
    vela_k = next((b for b in rth_plan if b[0] == ts_k), None)
    if vela_k is None:
        avisos.append("la vela de entrada (cierra a las %s del %s) no está en los datos: se simula desde el precio del plan sin comprobarla"
                      % (plan["hora_entrada"], fecha_es(fecha)))
    elif not vela_k[3] - tick <= plan["entrada"] <= vela_k[2] + tick:
        avisos.append("la entrada del plan %s queda fuera del rango de esa vela, %s a %s"
                      % (comun.pts(plan["entrada"]), comun.pts(vela_k[3]), comun.pts(vela_k[2])))
    if fecha.isoformat() in comun.CME_RECORTADO:
        avisos.append("el %s es sesión recortada (%s): la sesión regular cierra a las %s NY"
                      % (fecha_es(fecha), comun.CME_RECORTADO[fecha.isoformat()], hhmm_min(z)))
    pool = construir_pool(sesiones, n)
    mc = simular(pool, plan["entrada"], plan["stop"], plan["objetivo"], k, last, repeticiones, semilla, ventana, plan["lado"] == "largo")
    mc.update(hasta=hhmm_min(a + 5 * (last + 1)), sesiones_pool=len(sesiones), pool_desde=sesiones[0][0].isoformat(),
              pool_hasta=sesiones[-1][0].isoformat(), horas_bandas=[hhmm_min(a + 5 * (j + 1)) for j in range(k, last + 1)])
    ib_dia = comun.balance_inicial(codigo, dia_plan, fecha, plan["ib_minutos"]) if dia_plan else None
    regla = regla_historia(plan, ib_dia, tick)
    avisos += regla["avisos"]
    historia = historia_regla(codigo, sesiones, regla, plan, last)
    historia["descripcion"] = describir_regla(regla, plan)
    plan_out = dict(plan, regla_stop=regla["regla_stop"], regla_objetivo=regla["regla_objetivo"])
    plan_out.pop("notas", None)
    ultima = velas_[-1]
    return {
        "generado": comun.iso(ahora), "herramienta": "kemet-maquina", "fuente": fuente,
        "mercado": codigo, "fecha": plan["fecha"],
        "datos": {"intervalo": "5m", "ultima_vela": "%s %s NY" % (comun.a_ny(comun.utc_de_ts(ultima[0])).date().isoformat(),
                                                                     comun.hhmm(comun.a_ny(comun.utc_de_ts(ultima[0])))),
                  "sesiones_pool": len(sesiones), "pool_desde": sesiones[0][0].isoformat(), "pool_hasta": sesiones[-1][0].isoformat(),
                  "cortas_fuera": cortas},
        "plan": plan_out, "mc": mc, "historia": historia,
        "veredicto": veredicto(mc), "notas": notas_veredicto(mc), "avisos": avisos,
        "nota": ("Simulación hecha con las últimas %d sesiones completas de %s. No es una predicción: un dato, una noticia o un "
                 "día de pánico hacen lo que esas sesiones no hicieron. Misma semilla, mismos números." % (len(sesiones), codigo)),
    }


# ---------------------------------------------------------------- salida

def informe(doc, ahora=None):
    p, m, h = doc["plan"], doc["mc"], doc["historia"]
    codigo = p["mercado"]
    c = comun.CONTRATOS[codigo]
    largo = p["lado"] == "largo"
    fecha = dt.date.fromisoformat(p["fecha"])
    hasta = m["hasta"]
    cab = "Máquina del tiempo de %s, %s %s" % (codigo, DIAS[fecha.weekday()], fecha_es(fecha))
    if ahora is not None:
        cab += " (%s)" % comun.hora_doble(ahora)
    lineas = [
        cab,
        "%s %s: entrada %s a las %s (vela %d), stop %s (%s pts), objetivo %s (%s pts, %sR)."
        % (codigo, p["lado"], comun.pts(p["entrada"]), p["hora_entrada"], p["barra"], comun.pts(p["stop"]), comun.pts(p["riesgo_pts"]),
           comun.pts(p["objetivo"]), comun.pts(p["recompensa_pts"]), erres(m["r_objetivo"])),
        "1R = %s pts = %s por %s (%s por %s). Es contexto del tamaño, no un resultado esperado."
        % (comun.pts(p["riesgo_pts"]), dinero(p["riesgo_usd_micro"]), c["micro"], dinero(p["riesgo_usd_mini"]), c["mini"]),
        "%s repeticiones del resto de la sesión, de %s a %s (%d velas de 5 minutos), semilla %d."
        % (comun.num(m["repeticiones"], 0), p["hora_entrada"], hasta, m["velas_restantes"], m["semilla"]),
        "Cada vela sale entera de las velas de 5 minutos de %s a la misma hora del día (más o menos %d velas) en sus últimas %d "
        "sesiones regulares completas (%s a %s)."
        % (codigo, m["ventana"], m["sesiones_pool"], fecha_es(dt.date.fromisoformat(m["pool_desde"])), fecha_es(dt.date.fromisoformat(m["pool_hasta"]))),
        "",
        "  objetivo primero   %s" % pc(m["objetivo_primero"]),
        "  stop primero       %s" % pc(m["stop_primero"]),
        "  ninguno            %-8s sigue abierta a las %s" % (pc(m["ninguno"]), hasta),
        "  verde              %-8s objetivo primero, o por %s de la entrada a las %s" % (pc(m["verde"]), "encima" if largo else "debajo", hasta),
        "",
        "  Precio a las %s: mediana %s, el 90 %% de las repeticiones entre %s y %s."
        % (hasta, comun.pts(m["mediana_cierre"]), comun.pts(m["p5"]), comun.pts(m["p95"])),
        "  R media: %s (1R = %s pts; +%sR en el objetivo, -1R en el stop)." % (signo(m["r_media"]), comun.pts(p["riesgo_pts"]), erres(m["r_objetivo"])),
        "",
    ]
    if h.get("disparos"):
        lineas.append("Historia: %s en esas %d sesiones reales disparó %d veces (%d largos, %d cortos; %d sesiones sin cierre fuera del IB): "
                      "%d objetivo, %d stop, %d ninguno a las %s. R media %s."
                      % (h["descripcion"], h["sesiones"], h["disparos"], h["largos"], h["cortos"], h["sin_disparo"],
                         h["objetivo"], h["stop"], h["ninguno"], hasta, signo(h["r_media"])))
    else:
        lineas.append("Historia: %s no disparó en ninguna de esas %d sesiones." % (h["descripcion"], h["sesiones"]))
    lineas += ["", doc["veredicto"]] + list(doc.get("notas") or []) + [""]
    for w in doc.get("avisos") or []:
        lineas.append("Aviso: %s." % w)
    cortas = doc["datos"].get("cortas_fuera") or []
    if cortas:
        lineas.append("Fuera del pool %d sesión(es) corta(s) (recortadas o con huecos): %s."
                      % (len(cortas), ", ".join(fecha_es(dt.date.fromisoformat(x["fecha"])) for x in cortas)))
    lineas.append(doc["nota"] + " Repite esta corrida con --semilla %d." % m["semilla"])
    return lineas


def dibujar(doc, alto=17):
    """Abanico ASCII de las bandas: una columna por vela de 5 minutos."""
    p, m = doc["plan"], doc["mc"]
    bandas, horas = m["bandas"], m["horas_bandas"]
    lo = min([b[0] for b in bandas] + [p["stop"], p["objetivo"]])
    hi = max([b[4] for b in bandas] + [p["stop"], p["objetivo"]])
    margen = (hi - lo) * 0.04 or 0.01
    lo, hi = lo - margen, hi + margen
    paso = (hi - lo) / (alto - 1)

    def fila(precio):
        return max(0, min(alto - 1, int(round((hi - precio) / paso))))
    rejilla = [[" "] * len(bandas) for _ in range(alto)]
    for j, b in enumerate(bandas):
        r5, r25, r50, r75, r95 = [fila(x) for x in b]
        for r in range(r95, r5 + 1):
            rejilla[r][j] = "."
        for r in range(r75, r25 + 1):
            rejilla[r][j] = ":"
        rejilla[r50][j] = "*"
    marcas = {fila(p["objetivo"]): "objetivo", fila(p["stop"]): "stop"}
    if fila(p["entrada"]) not in marcas:
        marcas[fila(p["entrada"])] = "entrada"
    for r in (fila(p["objetivo"]), fila(p["stop"])):
        rejilla[r] = ["-" if ch == " " else ch for ch in rejilla[r]]
    out = ["%s %s, %s caminos desde la entrada de las %s (semilla %d)"
           % (p["mercado"], fecha_es(dt.date.fromisoformat(p["fecha"])), comun.num(m.get("caminos_bandas", CAMINOS_BANDAS), 0), p["hora_entrada"], m["semilla"])]
    for r in range(alto):
        etiqueta = marcas.get(r)
        precio = {"objetivo": p["objetivo"], "stop": p["stop"], "entrada": p["entrada"]}.get(etiqueta, hi - r * paso)
        izq = ("%10s |" % comun.pts(precio)) if (etiqueta or r in (0, alto - 1)) else "           |"
        out.append(izq + "".join(rejilla[r]) + ("  " + etiqueta if etiqueta else ""))
    eje = [" "] * len(bandas)
    for j in sorted({0, len(bandas) // 2, len(bandas) - 1}):
        lab = horas[j]
        s = max(0, min(j, len(bandas) - len(lab)))
        eje[s:s + len(lab)] = list(lab)
    out.append("           +" + "-" * len(bandas))
    out.append("            " + "".join(eje))
    out.append("* mediana   : la mitad central de los caminos   . el 90 % de los caminos   - stop y objetivo")
    return out


# ---------------------------------------------------------------- comandos

def calcular(a):
    ahora = comun.parse_ahora(a.ahora)
    plan = cargar_plan(a, ahora)
    ch = comun.velas(plan["mercado"], "60d", "5m", a.offline)
    return maquina(ch, plan, ahora, a.repeticiones, a.semilla, a.ventana, a.hasta, "offline" if a.offline else "yahoo"), ahora


def cmd_run(a):
    doc, ahora = calcular(a)
    ruta = None
    if a.escribir:
        ruta = comun.escribir_json("maquina.json", doc)
    if a.json:
        fino = dict(doc, mc={k: v for k, v in doc["mc"].items() if k != "caminos"})
        print(json.dumps(fino, indent=2, ensure_ascii=False))
    else:
        print("\n".join(informe(doc, ahora)))
        if ruta:
            print("Escrito %s." % ruta)
        print("Siguiente: kemet-tamano dice cuántos micros caben con este stop en tu cuenta; kemet-riesgo lo comprueba.")
    return 0


def cmd_chart(a):
    if a.desde is not None:
        p = a.desde or comun.ruta("maquina.json")
        doc = comun.leer_json(p, "ejecuta antes maquina.py run --escribir")
        try:
            doc["mc"]["bandas"]
        except (KeyError, TypeError):
            raise KemetError("%s no es un resultado de la máquina del tiempo" % p)
    else:
        doc, _ = calcular(a)
    print("\n".join(dibujar(doc)))
    print("\n".join([doc.get("veredicto", "")] + list(doc.get("notas") or [])))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="La máquina del tiempo: repite una operación planificada (kemet-maquina).")
    sub = ap.add_subparsers(dest="cmd")

    def comunes(p):
        p.add_argument("--plan", metavar="RUTA", help="el plan de kemet-salida (por defecto kemet/plan.json)")
        p.add_argument("--mercado", help="o el plan por flags: ES, NQ, CL o GC")
        p.add_argument("--fecha", help="el día del plan, AAAA-MM-DD (por defecto hoy en Nueva York)")
        p.add_argument("--lado", default="largo", choices=["largo", "corto"])
        p.add_argument("--entrada", type=float)
        p.add_argument("--stop", type=float)
        p.add_argument("--objetivo", type=float)
        p.add_argument("--hora-entrada", dest="hora_entrada", help="la hora a la que cierra la vela del disparo, p. ej. 10:45")
        p.add_argument("--regla-stop", dest="regla_stop", help="ib-medio, ib-opuesto o pts:X (si no, se deduce del IB del día)")
        p.add_argument("--regla-objetivo", dest="regla_objetivo", help="R:1, R:2... (si no, la R del plan)")
        p.add_argument("--ib-minutos", dest="ib_minutos", type=int, help="minutos del balance inicial (por defecto los del plan, si no 60)")
        p.add_argument("--repeticiones", type=int, default=10000)
        p.add_argument("--semilla", type=int, default=19)
        p.add_argument("--ventana", type=int, default=2, help="velas de la misma hora del día, más o menos estas")
        p.add_argument("--hasta", help="cada repetición termina a esta hora (por defecto plano_a del plan)")
        p.add_argument("--offline", metavar="RUTA", help="un JSON de Yahoo guardado (.json o .json.gz) o la carpeta de fixtures, sin red")
        p.add_argument("--ahora", help='fija el reloj: "2026-11-11 16:30" en hora de Nueva York')

    p = sub.add_parser("run", help="repite el plan: 10.000 sesiones simuladas más la historia")
    comunes(p)
    p.add_argument("--json", action="store_true")
    p.add_argument("--escribir", action="store_true", help="guarda kemet/maquina.json")
    p = sub.add_parser("chart", help="abanico ASCII de las repeticiones")
    comunes(p)
    p.add_argument("--desde", nargs="?", const="", metavar="RUTA", help="dibuja un resultado guardado (por defecto kemet/maquina.json)")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"run": cmd_run, "chart": cmd_chart}[a.cmd](a)
    except KemetError as e:
        print("maquina.py: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
