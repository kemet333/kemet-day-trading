#!/usr/bin/env python3
"""Alertas de precio y de hora con el reloj de Globex (futuros) y el de la NYSE (acciones de EE. UU.), para kemet-alertas.
Solo biblioteca estándar.

    python3 alertas.py reloj                            # Globex abierto, en pausa o cerrado; la sesión regular de tu contrato
    python3 alertas.py add --desde-plan                 # stop, objetivo y "plano a" de kemet/plan.json, para su fecha
    python3 alertas.py add --simbolo NQ --stop 28312.5 --lado largo
    python3 alertas.py add --simbolo NQ --objetivo 28547
    python3 alertas.py add --simbolo NQ --encima 28500
    python3 alertas.py add --simbolo NQ --pct 1 --direccion baja
    python3 alertas.py add --a 15:55 --etiqueta "plano a"
    python3 alertas.py add --hora-limite                # 5 minutos antes de la hora límite de tu firma (kemet/config.json)
    python3 alertas.py add --apertura                   # la apertura de la sesión regular del contrato
    python3 alertas.py check                            # suena lo que tocó, una vez; código 1 si nada
    python3 alertas.py check --ahora "2026-11-11 15:55" --offline tests/fixtures/yahoo
    python3 alertas.py quote NQ --escribir              # el último cierre de Yahoo -> kemet/precios.json
    python3 alertas.py list
    python3 alertas.py reset nq-plan-stop
    python3 alertas.py reloj --mercado TSLA                 # el reloj de la NYSE: abierta de 09:30 a 16:00 NY, festivos, días recortados
    python3 alertas.py add --simbolo TSLA --apertura        # el campanazo de las 09:30 NY, una vez por día
    python3 alertas.py quote TSLA --escribir                # el último cierre de una acción -> kemet/precios.json

Tipos de regla (archivo kemet/alertas.json, ejemplo en alertas.example.json):
  encima        el precio está en o por encima de "precio"
  debajo        el precio está en o por debajo de "precio"
  stop          tu stop: por debajo de "precio" en un largo, por encima en un corto ("lado")
  objetivo      tu objetivo: por encima en un largo, por debajo en un corto
  pct           el precio se ha movido "pct" por ciento o más desde el cierre de la sesión regular anterior;
                "direccion": "sube" o "baja" si solo quieres un sentido (suena una vez al día)
  hora          el reloj de Nueva York pasó "a" (HH:MM); con "fecha", solo ese día (una vez por día)
  hora_limite   5 minutos antes de la hora límite de la firma de kemet/config.json (hora_limite y su zona,
                America/Chicago en Topstep, convertida a Nueva York); una vez por día
  apertura      abrió la sesión regular del contrato (09:30 NY en índices, 09:00 CL, 08:20 GC); una vez por día

Una regla con "fecha" solo se vigila ese día de Nueva York (las del plan llevan la fecha del plan). Cada regla
suena UNA vez y queda callada hasta que la rearmes con reset. Las de hora suenan una vez por día.

Precio: el último cierre de Yahoo (vela de 1 minuto si la hay, si no de 5), con la hora de la vela y el retraso.
Futuros con unos 10 minutos de retraso: sirve para alertas, nunca para cronometrar una orden. --offline RUTA lee un
JSON guardado o la carpeta de fixtures en vez de la red.

Reloj: CME Globex (comun.estado_globex): abre el domingo a las 18:00 NY, cierra el viernes a las 17:00, pausa
diaria de 17:00 a 18:00, festivos de cierre completo y sesiones recortadas de 2026 y 2027. Fuera de esos años
el reloj avisa de que no conoce los festivos. Con una acción (--mercado TSLA o una regla con simbolo TSLA) el reloj
es el de la NYSE (comun.estado_nyse): abierta de 09:30 a 16:00 NY entre semana, 13:00 en los días recortados,
cerrada los festivos; la apertura suena a las 09:30 y los precios van al céntimo.
"""
import argparse
import datetime as dt
import glob
import json
import os
import sys

import comun
from comun import KemetError

DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
TIPOS = ("encima", "debajo", "stop", "objetivo", "pct", "hora", "hora_limite", "apertura")
SIN_PRECIO = ("hora", "hora_limite", "apertura")
ANTES_LIMITE = 5    # minutos antes de la hora límite de la firma


# ---------------------------------------------------------------- horas y reloj

def fecha_es(d):
    return d.strftime("%d/%m/%Y")


def codigo_de(simbolo):
    """El código del instrumento: un futuro (NQ, o el micro MNQ) o un ticker de acciones de EE. UU. (TSLA, BRK.B)."""
    return comun.resolver(simbolo)["codigo"]


def es_accion(codigo):
    return comun.resolver(codigo)["tipo"] == "accion"


def nombre_reloj(codigo):
    return "la NYSE" if es_accion(codigo) else "Globex"


def dia_de(codigo, utc):
    """El día de negociación de CME en un futuro; la fecha de Nueva York en una acción."""
    ny = comun.a_ny(utc)
    return ny.date() if es_accion(codigo) else comun.dia_negociacion(ny)


def de_zona(local, zona):
    """Hora de pared (naive) en una zona -> UTC. Solo Nueva York, Chicago y Madrid (sin zoneinfo)."""
    z = (zona or "America/New_York").strip()
    if z in ("America/New_York", "US/Eastern", "EST", "ET"):
        return comun.de_ny(local)
    if z in ("America/Chicago", "US/Central", "CST", "CT"):
        return comun.de_ny(local + dt.timedelta(hours=1))      # Chicago va una hora detrás de Nueva York todo el año
    if z in ("Europe/Madrid", "CET", "Europe/Paris", "Europe/Berlin"):
        guess = local - dt.timedelta(hours=1)
        return local - dt.timedelta(hours=comun.madrid_offset(guess))
    if z in ("UTC", "Etc/UTC", "GMT"):
        return local
    raise KemetError("no sé convertir la zona %r (uso America/New_York, America/Chicago, Europe/Madrid o UTC)" % zona)


def hora_limite_ny(cfg):
    """(hora NY de la hora límite de la firma, texto de la zona) desde kemet/config.json, o None."""
    hl = cfg.get("hora_limite")
    if not hl:
        return None
    t = comun.parse_hhmm(str(hl), "hora_limite")
    zona = cfg.get("hora_limite_tz") or "America/New_York"
    hoy = dt.date(2026, 1, 5)   # cualquier día: Chicago y Nueva York cambian de hora a la vez
    utc = de_zona(dt.datetime.combine(hoy, t), zona)
    return comun.a_ny(utc).time(), zona


def proxima_apertura(utc, codigo=None):
    """Cuándo vuelve a abrir: Globex a las 18:00 NY del primer día en que a esa hora está abierto; la NYSE a las 09:30 del
    primer día de sesión (en una acción)."""
    ny = comun.a_ny(utc)
    accion = bool(codigo) and es_accion(codigo)
    hora = dt.time(9, 30) if accion else dt.time(18, 0)
    for i in range(0, 12):
        d = (ny + dt.timedelta(days=i)).date()
        cand = comun.de_ny(dt.datetime.combine(d, hora))
        if cand <= utc:
            continue
        if (comun.estado_nyse(cand) if accion else comun.estado_globex(cand))[0] == "abierto":
            return cand
    return None


def estado(utc, codigo):
    """El reloj completo: Globex (o la NYSE en una acción), la sesión regular del instrumento y lo que viene.
    `estado` es abierto | pausa | cerrado; `globex` lleva lo mismo en un futuro y `nyse` en una acción."""
    ny = comun.a_ny(utc)
    d = ny.date()
    accion = es_accion(codigo)
    g, motivo = comun.estado_mercado(codigo, utc)
    dia = dia_de(codigo, utc)
    o, c = comun.sesion_regular(codigo, dia)
    rth = o <= utc < c and g == "abierto"
    st = {"ahora_ny": ny.strftime("%Y-%m-%d %H:%M"), "ahora_madrid": comun.a_madrid(utc).strftime("%Y-%m-%d %H:%M"),
          "fecha": d.isoformat(), "dia_semana": DIAS[d.weekday()], "dia_negociacion": dia.isoformat(),
          "reloj": "nyse" if accion else "globex", "estado": g, "motivo": motivo, "calendario_conocido": d.year in comun.CALENDARIO,
          "mercado": codigo, "instrumento": "accion" if accion else "futuro", "regular": rth,
          "regular_abre": comun.hhmm(comun.a_ny(o)), "regular_cierra": comun.hhmm(comun.a_ny(c)),
          "recortada": (comun.NYSE_RECORTADO if accion else comun.CME_RECORTADO).get(dia.isoformat())}
    st["nyse" if accion else "globex"] = g
    if g == "abierto":
        st["regular_estado"] = "en sesión regular" if rth else ("antes de la sesión regular" if utc < o else "después de la sesión regular")
    if g != "abierto":
        p = proxima_apertura(utc, codigo)
        if p:
            st["proxima_apertura"] = "%s %s" % (fecha_es(comun.a_ny(p).date()), comun.hhmm(comun.a_ny(p)))
    elif accion:
        st["cierra_hoy"] = st["regular_cierra"]
    elif ny.time() < dt.time(17, 0) and d.weekday() < 5:
        st["cierra_hoy"] = "17:00" if d.weekday() < 4 else "17:00 (cierre semanal)"
    return st


# ---------------------------------------------------------------- precio

def _archivo_offline(offline, codigo, intervalo):
    """La ruta del archivo guardado para ese intervalo, o None. Una carpeta: <yahoo>-*-<intervalo>.json(.gz)."""
    if os.path.isfile(offline):
        return offline
    y = comun.resolver(codigo)["yahoo"]
    for patron in ("%s-*-%s.json.gz" % (y, intervalo), "%s-*-%s.json" % (y, intervalo)):
        hits = sorted(glob.glob(os.path.join(offline, patron)))
        if hits:
            return hits[-1]
    return None


def velas_al_tick(ch, codigo):
    """Una acción: los precios de Yahoo (float32) redondeados al céntimo. Un futuro queda tal cual. None pasa."""
    if not ch:
        return ch
    inst = comun.resolver(codigo)
    if inst["tipo"] != "accion":
        return ch
    t = inst["tick"]
    return dict(ch, velas=[(b[0], comun.al_tick(b[1], t), comun.al_tick(b[2], t), comun.al_tick(b[3], t), comun.al_tick(b[4], t), b[5]) for b in ch["velas"]])


def cargar_velas(codigo, offline=None):
    """(velas de 1 m o None, velas de 5 m o None). Con --offline no se toca la red."""
    ch1, ch5 = _cargar_velas(codigo, offline)
    return velas_al_tick(ch1, codigo), velas_al_tick(ch5, codigo)


def _cargar_velas(codigo, offline=None):
    ch1 = ch5 = None
    if offline:
        if not os.path.exists(offline):
            raise KemetError("no existe %s" % offline)
        p1, p5 = _archivo_offline(offline, codigo, "1m"), _archivo_offline(offline, codigo, "5m")
        if os.path.isfile(offline):
            ch = comun.velas(codigo, offline=offline)
            if ch["intervalo"] == "1m":
                ch1 = ch
            else:
                ch5 = ch
        else:
            if p1:
                ch1 = comun.velas(codigo, offline=p1)
            if p5:
                ch5 = comun.velas(codigo, offline=p5)
        if not (ch1 or ch5):
            raise KemetError("no hay un archivo de %s en %s" % (codigo, offline))
        return ch1, ch5
    try:
        ch1 = comun.velas(codigo, "1d", "1m")
    except KemetError:
        ch1 = None
    comun._sleep(comun.PAUSE)
    ch5 = comun.velas(codigo, "5d", "5m")
    return ch1, ch5


def cierre_regular_anterior(codigo, ch5, ahora):
    """(cierre, fecha) de la última sesión regular ya terminada a esa hora, o (None, None)."""
    if not ch5:
        return None, None
    dias = comun.por_dia(comun.velas_cerradas(ch5, ahora), codigo)
    for d in sorted(dias, reverse=True):
        o, c = comun.sesion_regular(codigo, d)
        if c > ahora:
            continue
        rth = comun.regular(codigo, dias[d], d)
        if rth:
            return rth[-1][4], d.isoformat()
    return None, None


def precio_ultimo(codigo, ahora, offline=None):
    """El último cierre: {"simbolo", "precio", "hora_vela", "cierra", "intervalo", "retraso_min", "cierre_anterior", "fecha_cierre_anterior"}."""
    ch1, ch5 = cargar_velas(codigo, offline)
    vela = ch = None
    for cand in (ch1, ch5):
        if not cand:
            continue
        vs = comun.velas_cerradas(cand, ahora)
        if vs and (vela is None or vs[-1][0] + cand["paso"] > vela[0] + ch["paso"]):
            vela, ch = vs[-1], cand
    if vela is None:
        raise KemetError("no hay ninguna vela cerrada de %s a esa hora en los datos" % codigo)
    ini = comun.utc_de_ts(vela[0])
    fin = ini + dt.timedelta(seconds=ch["paso"])
    cierre_ant, fecha_ant = cierre_regular_anterior(codigo, ch5, ahora)
    return {"simbolo": codigo, "precio": vela[4], "hora_vela": comun.a_ny(ini).strftime("%Y-%m-%d %H:%M"),
            "cierra": comun.hhmm(comun.a_ny(fin)), "intervalo": ch["intervalo"],
            "retraso_min": max(0, int((ahora - fin).total_seconds() // 60)),
            "cierre_anterior": cierre_ant, "fecha_cierre_anterior": fecha_ant}


def precios(codigos, ahora, offline=None):
    out, errores = {}, []
    for i, c in enumerate(codigos):
        try:
            if i and not offline:
                comun._sleep(comun.PAUSE)
            out[c] = precio_ultimo(c, ahora, offline)
        except KemetError as e:
            errores.append(str(e))
    return out, errores


def escribir_precios(ruta, qs, ahora):
    viejo = comun.leer_json(ruta, obligatorio=False) if os.path.exists(ruta) else None
    viejo = viejo if isinstance(viejo, dict) else {}
    ps = dict(viejo.get("precios") or {})
    for c, q in qs.items():
        ps[c] = {"precio": q["precio"], "hora_vela": q["hora_vela"], "intervalo": q["intervalo"], "retraso_min": q["retraso_min"],
                 "cierre_anterior": q["cierre_anterior"], "leido": comun.iso(ahora)}
    doc = {"generado": comun.iso(ahora), "fuente": "yahoo",
           "nota": "Último cierre de Yahoo, con retraso: para alertas y comprobar un tamaño. El precio que te llena es el de tu plataforma.",
           "precios": ps}
    comun.escribir_json(ruta, doc)
    return doc


def texto_precio(q):
    return "%s (vela de %s de las %s, cerrada a las %s, retraso %d min)" % (
        comun.pts(q["precio"]), "1 m" if q["intervalo"] == "1m" else "5 m", q["hora_vela"][-5:], q["cierra"], q["retraso_min"])


# ---------------------------------------------------------------- reglas

def _es_fecha(s):
    try:
        dt.date.fromisoformat(str(s))
        return True
    except ValueError:
        return False


def validar(r):
    t = r.get("tipo")
    if t not in TIPOS:
        raise KemetError("regla %s: tipo %r desconocido (%s)" % (r.get("id"), t, ", ".join(TIPOS)))
    if t not in ("hora", "hora_limite") and not r.get("simbolo"):
        raise KemetError("regla %s necesita simbolo" % r.get("id"))
    if r.get("simbolo"):
        codigo_de(r["simbolo"])
    if t in ("encima", "debajo", "stop", "objetivo") and not isinstance(r.get("precio"), (int, float)):
        raise KemetError("regla %s necesita un precio numérico" % r.get("id"))
    if t in ("stop", "objetivo") and r.get("lado", "largo") not in ("largo", "corto"):
        raise KemetError("regla %s: lado tiene que ser largo o corto" % r.get("id"))
    if t == "pct" and not isinstance(r.get("pct"), (int, float)):
        raise KemetError("regla %s necesita pct numérico" % r.get("id"))
    if t == "pct" and r.get("direccion") not in (None, "sube", "baja"):
        raise KemetError("regla %s: direccion tiene que ser sube o baja" % r.get("id"))
    if t == "hora":
        comun.parse_hhmm(str(r.get("a") or ""), "regla %s: \"a\"" % r.get("id"))
    if r.get("fecha") and not _es_fecha(r["fecha"]):
        raise KemetError("regla %s: fecha tiene que ser AAAA-MM-DD" % r.get("id"))


def vigente(r, hoy):
    return not r.get("fecha") or str(r["fecha"]) == hoy


def _sono_hoy(stamp, hoy):
    if not stamp:
        return False
    try:
        utc = dt.datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return stamp[:10] == hoy
    return comun.a_ny(utc).date().isoformat() == hoy


def dia_con_reloj(utc, codigo=None):
    """Las reglas de hora suenan cualquier día que no sea sábado ni festivo de cierre completo (de la NYSE si el símbolo es una acción)."""
    ny = comun.a_ny(utc)
    if codigo and es_accion(codigo):
        return ny.weekday() < 5 and ny.date().isoformat() not in comun.NYSE_CERRADO
    return ny.weekday() != 5 and ny.date().isoformat() not in comun.CME_CERRADO


def evaluar(reglas, qs, st, cfg, estado_, ahora):
    """Función pura. Devuelve (sonaron, estado nuevo). Cada toque: {id, simbolo, mensaje}."""
    estado_ = json.loads(json.dumps(estado_ or {}))
    sonaron = estado_.setdefault("sonaron", {})
    hoy = st["fecha"]
    ny = comun.a_ny(ahora)
    stamp = comun.iso(ahora)
    toques = []
    for r in reglas:
        validar(r)
        rid = r.get("id") or "%s-%s" % (str(r.get("simbolo") or "reloj").lower(), r["tipo"])
        if not vigente(r, hoy):
            continue
        t = r["tipo"]
        if t == "apertura":
            codigo = codigo_de(r["simbolo"])
            accion = es_accion(codigo)
            o, c = comun.sesion_regular(codigo, dia_de(codigo, ahora))
            abierto_hoy = dia_con_reloj(ahora, codigo) if accion else (st["estado"] != "cerrado" and dia_con_reloj(ahora))
            if ahora >= o and abierto_hoy and not _sono_hoy(sonaron.get(rid), hoy):
                if accion:
                    msg = "Campanazo de apertura de la NYSE para %s: %s NY (%s Madrid)." % (codigo, comun.hhmm(comun.a_ny(o)), comun.hhmm(comun.a_madrid(o)))
                else:
                    msg = "Apertura de la sesión regular de %s: %s NY (%s Madrid)." % (codigo, comun.hhmm(comun.a_ny(o)), comun.hhmm(comun.a_madrid(o)))
                recortada = (comun.NYSE_RECORTADO if accion else comun.CME_RECORTADO).get(dia_de(codigo, ahora).isoformat())
                if recortada:
                    msg += " Sesión recortada (%s): cierra a las %s NY." % (recortada, comun.hhmm(comun.a_ny(c)))
                toques.append({"id": rid, "simbolo": codigo, "mensaje": msg})
                sonaron[rid] = stamp
            continue
        if t in ("hora", "hora_limite"):
            if t == "hora":
                a = comun.parse_hhmm(str(r["a"]))
                etiqueta = r.get("etiqueta") or "aviso de hora"
                detalle = "fijado a las %s" % comun.hhmm(a)
            else:
                hl = hora_limite_ny(cfg)
                if not hl:
                    continue
                a_firma, zona = hl
                a = (dt.datetime.combine(dt.date(2000, 1, 1), a_firma) - dt.timedelta(minutes=ANTES_LIMITE)).time()
                etiqueta = "hora límite de %s" % (cfg.get("cuenta_nombre") or cfg.get("firma") or "la firma")
                detalle = "tienes que estar plano a las %s NY, %s %s" % (comun.hhmm(a_firma), cfg.get("hora_limite"), zona)
            if ny.time() >= a and dia_con_reloj(ahora) and not _sono_hoy(sonaron.get(rid), hoy):
                msg = "%s%s: son las %s NY (%s). " % (etiqueta[:1].upper(), etiqueta[1:], comun.hhmm(ny), detalle)
                if t == "hora_limite" and ny.time() < a_firma:
                    faltan = (dt.datetime.combine(dt.date(2000, 1, 1), a_firma) - dt.datetime.combine(dt.date(2000, 1, 1), ny.time())).seconds // 60
                    msg = "%s%s: faltan %d minutos, %s. " % (etiqueta[:1].upper(), etiqueta[1:], faltan, detalle)
                sim = str(r.get("simbolo") or "").upper()
                msg += "Si %s sigue abierta, ciérrala en tu plataforma." % (sim or "la operación")
                toques.append({"id": rid, "simbolo": sim, "mensaje": msg})
                sonaron[rid] = stamp
            continue
        codigo = codigo_de(r["simbolo"])
        q = qs.get(codigo)
        if not q:
            continue
        p = q["precio"]
        if t in ("encima", "debajo", "stop", "objetivo"):
            largo = r.get("lado", "largo") == "largo"
            arriba = t == "encima" or (t == "objetivo" and largo) or (t == "stop" and not largo)
            toca = p >= r["precio"] if arriba else p <= r["precio"]
            if toca and rid not in sonaron:
                que = {"stop": "tu stop", "objetivo": "tu objetivo"}.get(t, "tu nivel")
                toques.append({"id": rid, "simbolo": codigo, "mensaje": "%s último %s: en o por %s de %s %s%s."
                               % (codigo, texto_precio(q), "encima" if arriba else "debajo", que, comun.pts(r["precio"]),
                                  (" (" + r["nota"] + ")") if r.get("nota") else "")})
                sonaron[rid] = stamp
        elif t == "pct":
            ref = r.get("ref") or q.get("cierre_anterior")
            if not ref:
                continue
            mov = 100.0 * (p / float(ref) - 1)
            quiere = r.get("direccion")
            toca = abs(mov) >= r["pct"] and (not quiere or (quiere == "sube") == (mov > 0))
            if toca and not _sono_hoy(sonaron.get(rid), hoy):
                toques.append({"id": rid, "simbolo": codigo, "mensaje": "%s se ha movido un %s %% hasta %s desde el cierre regular anterior %s%s."
                               % (codigo, ("+" if mov > 0 else "") + comun.num(mov, 2), comun.pts(p), comun.pts(float(ref)),
                                  (" del " + fecha_es(dt.date.fromisoformat(q["fecha_cierre_anterior"]))) if not r.get("ref") and q.get("fecha_cierre_anterior") else "")})
                sonaron[rid] = stamp
    estado_["ultima_comprobacion"] = stamp
    return toques, estado_


def reglas_del_plan(plan, cfg):
    """kemet/plan.json -> stop, objetivo y "plano a", para el día del plan."""
    if not isinstance(plan, dict) or not (plan.get("mercado") or plan.get("micro")):
        raise KemetError("el plan no trae mercado (pásalo por kemet-salida primero)")
    codigo = codigo_de(plan.get("mercado") or plan.get("micro"))
    lado = str(plan.get("lado") or "largo").lower()
    if lado not in ("largo", "corto"):
        raise KemetError("el plan tiene lado %r; tiene que ser largo o corto" % plan.get("lado"))
    out = []
    for clave in ("stop", "objetivo"):
        v = plan.get(clave)
        if not isinstance(v, (int, float)) or v <= 0:
            raise KemetError("el plan no trae %s (kemet-salida lo escribe)" % clave)
        nota = clave + " del plan" + ((", " + str(plan["regla_" + clave])) if plan.get("regla_" + clave) else "")
        out.append({"id": "%s-plan-%s" % (codigo.lower(), clave), "simbolo": codigo, "tipo": clave, "precio": float(v), "lado": lado, "nota": nota})
    plano = plan.get("plano_a") or cfg.get("plano_a") or comun.resolver(codigo)["plano"]
    comun.parse_hhmm(str(plano), "plano_a del plan")
    out.append({"id": "%s-plano-a" % codigo.lower(), "simbolo": codigo, "tipo": "hora", "a": str(plano), "etiqueta": "plano a"})
    if plan.get("fecha"):
        if not _es_fecha(plan["fecha"]):
            raise KemetError("la fecha del plan %r no es AAAA-MM-DD" % plan["fecha"])
        for r in out:
            r["fecha"] = str(plan["fecha"])
    return out


# ---------------------------------------------------------------- comandos

def _leer(ruta, defecto):
    if not os.path.exists(ruta):
        return defecto
    return comun.leer_json(ruta)


def _config():
    return comun.leer_json("config.json", obligatorio=False) or {}


def _mercado(a, cfg):
    return (a.mercado or cfg.get("mercado") or "NQ").upper()


def cmd_reloj(a):
    cfg = _config()
    codigo = codigo_de(_mercado(a, cfg))
    ahora = comun.parse_ahora(a.ahora)
    st = estado(ahora, codigo)
    if a.json:
        print(json.dumps(st, indent=2, ensure_ascii=False))
        return 0 if st["estado"] == "abierto" else 1
    d = dt.date.fromisoformat(st["fecha"])
    if st["reloj"] == "nyse":
        print("Reloj de la NYSE: %s, %s %s. NYSE %s (%s)." % (comun.hora_doble(ahora), st["dia_semana"], fecha_es(d),
                                                             {"abierto": "ABIERTA", "cerrado": "CERRADA"}[st["estado"]], st["motivo"]))
    else:
        print("Reloj de Globex: %s, %s %s. Globex %s (%s)." % (comun.hora_doble(ahora), st["dia_semana"], fecha_es(d),
                                                                {"abierto": "ABIERTO", "pausa": "en PAUSA", "cerrado": "CERRADO"}[st["estado"]], st["motivo"]))
    linea = "Sesión regular de %s: %s a %s NY" % (codigo, st["regular_abre"], st["regular_cierra"])
    if st.get("regular_estado"):
        linea += ", %s" % st["regular_estado"]
    if st.get("recortada"):
        linea += " (recortada: %s)" % st["recortada"]
    print(linea + ".")
    hl = hora_limite_ny(cfg) if st["reloj"] == "globex" else None
    extra = []
    if cfg.get("plano_a"):
        extra.append("plano a las %s NY (tu hora)" % cfg["plano_a"])
    if hl:
        extra.append("hora límite de %s a las %s NY (%s %s)" % (cfg.get("cuenta_nombre") or "la firma", comun.hhmm(hl[0]), cfg.get("hora_limite"), hl[1]))
    if extra:
        print("Hoy: " + "; ".join(extra) + ".")
    if st["estado"] == "abierto":
        if st.get("cierra_hoy") and st["reloj"] == "globex":
            print("Globex cierra hoy a las %s NY; pausa diaria de 17:00 a 18:00." % st["cierra_hoy"])
        elif st.get("cierra_hoy"):
            print("La NYSE cierra hoy a las %s NY. Una acción no tiene hora límite de firma." % st["cierra_hoy"])
    elif st.get("proxima_apertura"):
        print("Próxima apertura de %s: %s NY." % (nombre_reloj(codigo), st["proxima_apertura"]))
    if not st["calendario_conocido"]:
        print("Los festivos cargados son de %s: comprueba este día en el calendario de %s." % (" y ".join(map(str, comun.CALENDARIO)), "la NYSE" if st["reloj"] == "nyse" else "CME"))
    return 0 if st["estado"] == "abierto" else 1


def cmd_quote(a):
    codigos = []
    for s in a.simbolos:
        c = codigo_de(s)
        if c not in codigos:
            codigos.append(c)
    if not codigos:
        cfg = _config()
        codigos = [codigo_de(_mercado(a, cfg))]
    ahora = comun.parse_ahora(a.ahora)
    qs, errores = precios(codigos, ahora, a.offline)
    ruta = a.precios or comun.ruta("precios.json")
    if a.escribir and qs:
        escribir_precios(ruta, qs, ahora)
    if a.json:
        print(json.dumps({"generado": comun.iso(ahora), "precios": qs, "errores": errores}, indent=2, ensure_ascii=False))
        return 0 if qs else 1
    print("Precios a las %s." % comun.hora_doble(ahora))
    for c in codigos:
        q = qs.get(c)
        if q:
            cambio = ""
            if q.get("cierre_anterior"):
                cambio = ", %s %% sobre el cierre regular del %s (%s)" % (
                    ("+" if q["precio"] >= q["cierre_anterior"] else "") + comun.num(100.0 * (q["precio"] / q["cierre_anterior"] - 1), 2),
                    fecha_es(dt.date.fromisoformat(q["fecha_cierre_anterior"])), comun.pts(q["cierre_anterior"]))
            print("%-3s último %s%s." % (c, texto_precio(q), cambio))
    for e in errores:
        print("error: " + e)
    if a.escribir and qs:
        print("Escrito %s con %d precio(s)." % (ruta, len(qs)))
    if all(es_accion(c) for c in codigos):
        print("El cierre de Yahoo puede ir con retraso: vale para alertas, no para cronometrar una orden. El precio que te llena es el de tu plataforma.")
    else:
        print("Yahoo va con unos 10 minutos de retraso en futuros: vale para alertas, no para cronometrar una orden. El precio que te llena es el de tu plataforma.")
    return 0 if qs else 1


def cmd_check(a):
    cfg = _config()
    ruta_reglas = a.reglas or comun.ruta("alertas.json")
    ruta_estado = a.estado or comun.ruta(os.path.join("estado", "alertas.json"))
    doc = _leer(ruta_reglas, None)
    if not doc or not doc.get("reglas"):
        raise KemetError("no hay reglas en %s: añade alguna con alertas.py add --desde-plan" % ruta_reglas)
    reglas = doc["reglas"]
    ahora = comun.parse_ahora(a.ahora)
    codigo = codigo_de(_mercado(a, cfg))
    st = estado(ahora, codigo)
    vigentes = [r for r in reglas if vigente(r, st["fecha"])]
    codigos = []
    for r in vigentes:
        if r.get("tipo") not in SIN_PRECIO and r.get("simbolo"):
            c = codigo_de(r["simbolo"])
            if c not in codigos:
                codigos.append(c)
    qs, errores = precios(codigos, ahora, a.offline) if codigos else ({}, [])
    estado_ = _leer(ruta_estado, {})
    toques, estado_ = evaluar(reglas, qs, st, cfg, estado_, ahora)
    if not a.sin_escribir:
        comun.escribir_json(ruta_estado, estado_)
        if qs:
            escribir_precios(a.precios or comun.ruta("precios.json"), qs, ahora)
    if a.json:
        print(json.dumps({"reloj": st, "sonaron": toques, "errores": errores,
                          "precios": {c: q["precio"] for c, q in qs.items()}}, indent=2, ensure_ascii=False))
        return 0 if toques else 1
    if st["reloj"] == "nyse":
        print("NYSE %s (%s, %s)." % ({"abierto": "abierta", "cerrado": "cerrada"}[st["estado"]], comun.hora_doble(ahora), st["motivo"]))
    else:
        print("Globex %s (%s, %s)." % ({"abierto": "abierto", "pausa": "en pausa", "cerrado": "cerrado"}[st["estado"]], comun.hora_doble(ahora), st["motivo"]))
    for t in toques:
        print("ALERTA " + t["mensaje"])
    if not toques:
        print("Nada ha sonado. %d regla(s) vigilada(s) hoy%s." % (
            len(vigentes), (", " + ", ".join("%s %s" % (c, texto_precio(qs[c])) for c in codigos if c in qs)) if qs else ""))
    for e in errores:
        print("error: " + e)
    if toques:
        print("Una alerta es información, no una orden. El stop que te saca es el que tienes puesto en tu plataforma; "
              "si ha saltado, apunta el resultado con kemet-riesgo registrar.")
    return 0 if toques else 1


def cmd_add(a):
    cfg = _config()
    ruta_reglas = a.reglas or comun.ruta("alertas.json")
    ruta_estado = a.estado or comun.ruta(os.path.join("estado", "alertas.json"))
    doc = _leer(ruta_reglas, {"reglas": []})
    doc.setdefault("reglas", [])
    if a.desde_plan:
        plan = comun.leer_json(a.plan or comun.ruta("plan.json"), "kemet-salida lo escribe")
        nuevas = reglas_del_plan(plan, cfg)
        ids = {r["id"] for r in nuevas}
        doc["reglas"] = [r for r in doc["reglas"] if r.get("id") not in ids] + nuevas
        estado_ = _leer(ruta_estado, {})
        if estado_.get("sonaron"):
            for i in ids:
                estado_["sonaron"].pop(i, None)
            comun.escribir_json(ruta_estado, estado_)
        comun.escribir_json(ruta_reglas, doc)
        for r in nuevas:
            print("Añadida %s: %s" % (r["id"], json.dumps(r, ensure_ascii=False)))
        print("Pasa alertas.py check cada pocos minutos mientras la operación esté abierta (una tarea programada o /loop). "
              "El precio de Yahoo va con retraso; el stop que te saca es el de tu plataforma.")
        return 0
    if a.apertura:
        codigo = codigo_de(a.simbolo or _mercado(a, cfg))
        regla = {"id": a.id or "apertura-%s" % codigo.lower(), "tipo": "apertura", "simbolo": codigo}
    elif a.hora_limite:
        if a.simbolo and es_accion(codigo_de(a.simbolo)):
            raise KemetError("una acción no tiene hora límite de firma: usa --a HH:MM para un aviso de hora, o --apertura")
        if not hora_limite_ny(cfg):
            raise KemetError("kemet/config.json no tiene hora_limite: escríbelo con tamano.py config")
        regla = {"id": a.id or "hora-limite", "tipo": "hora_limite"}
        if a.simbolo:
            regla["simbolo"] = codigo_de(a.simbolo)
    elif a.a:
        comun.parse_hhmm(a.a, "--a")
        regla = {"id": a.id or ("hora-%s" % a.a.replace(":", "")), "tipo": "hora", "a": a.a, "etiqueta": a.etiqueta or "aviso de hora"}
        if a.simbolo:
            regla["simbolo"] = codigo_de(a.simbolo)
    else:
        if not a.simbolo:
            raise KemetError("hace falta --simbolo (o --desde-plan, --a, --hora-limite, --apertura)")
        codigo = codigo_de(a.simbolo)
        if a.encima is not None:
            regla = {"tipo": "encima", "precio": a.encima}
        elif a.debajo is not None:
            regla = {"tipo": "debajo", "precio": a.debajo}
        elif a.stop is not None:
            regla = {"tipo": "stop", "precio": a.stop, "lado": a.lado}
        elif a.objetivo is not None:
            regla = {"tipo": "objetivo", "precio": a.objetivo, "lado": a.lado}
        elif a.pct is not None:
            regla = {"tipo": "pct", "pct": a.pct}
            if a.direccion:
                regla["direccion"] = a.direccion
        else:
            raise KemetError("da uno de --encima, --debajo, --stop, --objetivo o --pct")
        val = regla.get("precio", regla.get("pct"))
        regla = dict({"id": a.id or ("%s-%s-%s" % (codigo.lower(), regla["tipo"], ("%g" % val).replace(".", ",")))}, simbolo=codigo, **regla)
        if a.nota:
            regla["nota"] = a.nota
    if a.fecha:
        regla["fecha"] = a.fecha
    validar(regla)
    if any(r.get("id") == regla["id"] for r in doc["reglas"]):
        raise KemetError("ya hay una regla con id %s (reset %s la rearma, o da otro --id)" % (regla["id"], regla["id"]))
    doc["reglas"].append(regla)
    comun.escribir_json(ruta_reglas, doc)
    print("Añadida %s: %s" % (regla["id"], json.dumps(regla, ensure_ascii=False)))
    if regla["tipo"] == "apertura" and es_accion(regla["simbolo"]):
        print("Suena una vez por día a partir de las 09:30 NY (13:00 de cierre en los días recortados de la NYSE), nunca en festivo ni en fin de semana.")
    return 0


def cmd_list(a):
    doc = _leer(a.reglas or comun.ruta("alertas.json"), {"reglas": []})
    estado_ = _leer(a.estado or comun.ruta(os.path.join("estado", "alertas.json")), {})
    if not doc.get("reglas"):
        print("Todavía no hay reglas.")
        return 1
    for r in doc["reglas"]:
        rid = r.get("id")
        sono = (estado_.get("sonaron") or {}).get(rid)
        print("%-24s %s%s" % (rid, json.dumps({k: v for k, v in r.items() if k != "id"}, ensure_ascii=False), ("  (sonó %s)" % sono) if sono else ""))
    return 0


def cmd_reset(a):
    ruta_estado = a.estado or comun.ruta(os.path.join("estado", "alertas.json"))
    estado_ = _leer(ruta_estado, {})
    if a.id not in (estado_.get("sonaron") or {}):
        print("%s no ha sonado (nada que rearmar)." % a.id)
        return 1
    del estado_["sonaron"][a.id]
    comun.escribir_json(ruta_estado, estado_)
    print("Rearmada %s." % a.id)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Alertas de precio y de hora con el reloj de Globex (kemet-alertas).")
    sub = ap.add_subparsers(dest="cmd")

    def red(p):
        p.add_argument("--offline", metavar="RUTA", help="un JSON de Yahoo guardado o la carpeta de fixtures, sin red")
        p.add_argument("--ahora", help='fija el reloj: "2026-11-11 15:55" en hora de Nueva York')
        p.add_argument("--json", action="store_true")
        p.add_argument("--mercado", "--simbolo", dest="mercado", help="un futuro (ES, NQ, CL, GC...) o un ticker de EE. UU. (TSLA); por defecto el de kemet/config.json, si no NQ")

    def archivos(p):
        p.add_argument("--reglas", metavar="RUTA", help="por defecto kemet/alertas.json")
        p.add_argument("--estado", metavar="RUTA", help="por defecto kemet/estado/alertas.json")

    p = sub.add_parser("reloj", help="Globex abierto, en pausa o cerrado")
    red(p)
    p = sub.add_parser("quote", help="el último cierre de Yahoo")
    red(p)
    p.add_argument("simbolos", nargs="*", help="NQ ES CL GC (o MNQ, MES...) o tickers de EE. UU. (TSLA)")
    p.add_argument("--escribir", action="store_true", help="guarda kemet/precios.json")
    p.add_argument("--precios", metavar="RUTA", help="por defecto kemet/precios.json")
    p = sub.add_parser("check", help="comprueba cada regla y hace sonar lo que tocó")
    red(p)
    archivos(p)
    p.add_argument("--precios", metavar="RUTA", help="por defecto kemet/precios.json")
    p.add_argument("--sin-escribir", dest="sin_escribir", action="store_true")
    p = sub.add_parser("add", help="añade una regla")
    archivos(p)
    p.add_argument("--mercado")
    p.add_argument("--simbolo", help="NQ, ES, CL, GC, el micro, o un ticker de EE. UU. (TSLA)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--encima", type=float)
    g.add_argument("--debajo", type=float)
    g.add_argument("--stop", type=float)
    g.add_argument("--objetivo", type=float)
    g.add_argument("--pct", type=float)
    g.add_argument("--apertura", action="store_true")
    g.add_argument("--hora-limite", dest="hora_limite", action="store_true", help="5 minutos antes de la hora límite de tu firma")
    g.add_argument("--a", metavar="HH:MM", help="un aviso de hora, en hora de Nueva York")
    g.add_argument("--desde-plan", dest="desde_plan", action="store_true", help="stop, objetivo y plano a del plan")
    p.add_argument("--plan", metavar="RUTA", help="por defecto kemet/plan.json")
    p.add_argument("--lado", default="largo", choices=["largo", "corto"], help="de qué lado está la operación (stop y objetivo)")
    p.add_argument("--etiqueta", help='qué dice el aviso de hora, p. ej. "plano a"')
    p.add_argument("--fecha", help="vigila esta regla solo ese día de Nueva York (AAAA-MM-DD)")
    p.add_argument("--direccion", choices=["sube", "baja"])
    p.add_argument("--nota")
    p.add_argument("--id")
    p = sub.add_parser("list", help="las reglas")
    archivos(p)
    p = sub.add_parser("reset", help="rearma una regla que sonó")
    p.add_argument("id")
    p.add_argument("--estado", metavar="RUTA")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"reloj": cmd_reloj, "quote": cmd_quote, "check": cmd_check, "add": cmd_add, "list": cmd_list, "reset": cmd_reset}[a.cmd](a)
    except KemetError as e:
        print("alertas.py: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
