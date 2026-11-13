#!/usr/bin/env python3
"""Revisión del diario de operaciones: cumplimiento del plan antes que resultado.

Solo biblioteca estándar, sin red. Lee `kemet/config.json` y `kemet/agenda.json` si existen (variable KEMET_DIR).

    python3 diario.py revisar operaciones.csv                      # todo el archivo
    python3 diario.py revisar operaciones.csv --desde 2026-11-02 --hasta 2026-11-11
    python3 diario.py revisar operaciones.csv --stop-habitual 40   # riesgo de las operaciones sin stop, para las métricas
    python3 diario.py revisar operaciones.csv --json
    python3 diario.py plantilla                                    # la cabecera del CSV

El CSV: columnas en español o inglés, separador `,` o `;`, decimales con punto o con coma.
  fecha/date · hora/time (hora de Nueva York; `hora_madrid` se convierte) · simbolo/symbol (MNQ, NQ, MES, ES, MCL, MGC…
  o un ticker de EE. UU.: TSLA, AAPL) · lado/side (largo/corto, long/short, buy/sell) · contratos/qty/acciones ·
  entrada/entry · salida/exit · stop (puede faltar) · pnl (si falta, se calcula con entrada, salida, lado, cantidad y el
  valor del punto: 1 $ por acción en una acción) · nota (opcional). En acciones la cantidad va en acciones, sin micros.

Qué cuenta (hechos, no calificaciones): operaciones sin stop, entradas en la apertura (09:30–09:45 NY) y en las
ventanas de datos de kemet/agenda.json si es de un día del archivo, riesgo al stop por encima del riesgo por operación
de la config, pérdidas mayores que el stop, entradas después de plano_a, de la hora límite de la firma y de
sin_entradas_despues, días que superaron perdida_max_dia y entradas después de la tercera pérdida del día. Después las
métricas (con 20 operaciones o más) y la revisión de kemet-desk: tres cosas bien con evidencia, dos rupturas del plan
con su coste, una sola corrección para mañana.

Código de salida: 0 si no hay rupturas del plan, 1 si las hay, 2 si hay un error.
"""
import argparse
import csv
import datetime as dt
import io
import re
import json
import os
import sys
import unicodedata

import comun
from comun import KemetError, num, pts, usd

FALLOS_Y_PARAS = 3
APERTURA_MIN = 15
TOLERANCIA_STOP = 1.15          # una pérdida mayor que el stop × esto cuenta como stop movido o deslizamiento grande
MINIMO_METRICAS = 20
FRANJAS = [("preapertura", "08:00", "09:30"), ("apertura", "09:30", "09:45"), ("mejor franja", "09:45", "11:30"),
           ("hora de comer", "11:30", "13:30"), ("tarde", "13:30", "15:30"), ("cierre", "15:30", "16:00")]
DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
COLUMNAS = {
    "fecha": ("fecha", "date", "dia", "day", "fecha_ny"),
    "hora": ("hora", "time", "hora_ny", "hora_entrada", "entry_time", "time_ny", "hora_madrid", "time_madrid"),
    "simbolo": ("simbolo", "symbol", "mercado", "instrumento", "instrument", "ticker", "contrato", "contract"),
    "lado": ("lado", "side", "direccion", "direction"),
    "contratos": ("contratos", "qty", "cantidad", "quantity", "size", "contracts", "acciones", "shares"),
    "entrada": ("entrada", "entry", "precio_entrada", "entry_price", "avg_entry"),
    "salida": ("salida", "exit", "precio_salida", "exit_price", "avg_exit"),
    "stop": ("stop", "stop_loss", "sl", "stoploss"),
    "pnl": ("pnl", "resultado", "p&l", "profit", "beneficio", "resultado_usd", "net_pnl", "pl"),
    "nota": ("nota", "note", "notas", "notes", "comentario", "comment", "por_que", "why"),
}
LADOS = {"largo": "largo", "long": "largo", "buy": "largo", "compra": "largo", "l": "largo", "b": "largo", "alcista": "largo",
         "corto": "corto", "short": "corto", "sell": "corto", "venta": "corto", "s": "corto", "bajista": "corto"}
ETIQUETAS = {
    "sin_stop": "sin stop puesto", "apertura": "entrada en la apertura (09:30–09:45 NY)", "ventana": "entrada en una ventana de datos",
    "tamano": "riesgo al stop mayor que el riesgo por operación", "stop_ampliado": "pérdida mayor que el stop (movido o deslizamiento)",
    "plano": "entrada después de la hora de estar plano", "hora_limite": "entrada después de la hora límite de la firma",
    "horario": "entrada después de la última hora de entrada del plan", "tras_limite": "entrada con la pérdida máxima del día ya superada",
    "tras_tercer_fallo": "entrada después de la tercera pérdida del día",
}
PLANTILLA = "fecha,hora,simbolo,lado,contratos,entrada,salida,stop,pnl,nota"


# ---------------------------------------------------------------- lectura del CSV

def _norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii")
    return s.strip().lower().replace(" ", "_")


MILES_EEUU = re.compile(r"^\(?-?\d{1,3}(,\d{3})+(\.\d+)?\)?$")     # 26,812 · 1,234.50: coma de miles
MILES_ES = re.compile(r"^\(?-?\d{1,3}(\.\d{3})+(,\d+)?\)?$")       # 26.812 · 1.234,50: punto de miles


def _limpio(x):
    s = str(x if x is not None else "").strip().replace("$", "").replace("€", "").replace(" ", "").replace("\u00a0", "")
    return "" if s.lower() in ("", "-", "\u2014", "na", "n/a", "none", "null") else s


def estilo_de(valores):
    """«punto» (EE. UU.: 1,234.50) o «coma» (España: 1.234,50) según las cifras del archivo; None si ninguna lo decide."""
    eeuu = es = 0
    for x in valores:
        s = _limpio(x)
        if "," in s and "." in s:
            if s.rfind(".") > s.rfind(","):
                eeuu += 1
            else:
                es += 1
        elif "," in s and not MILES_EEUU.match(s):
            es += 1                                      # 1,5 · 28426,25: coma decimal
        elif "." in s and not MILES_ES.match(s):
            eeuu += 1                                    # 393.10: punto decimal
    if eeuu and not es:
        return "punto"
    if es and not eeuu:
        return "coma"
    return None


def _f(x, estilo=None):
    """'28.426,25' -> 28426.25 · '28426.25' -> 28426.25 · '26,812' -> 26812 en un archivo de EE. UU. · '(120)' -> -120 · '' -> None."""
    s = _limpio(x)
    if not s:
        return None
    negativo = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", "") if (estilo == "punto" and MILES_EEUU.match(s)) else s.replace(",", ".")
    elif "." in s and estilo == "coma" and MILES_ES.match(s):
        s = s.replace(".", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if negativo else v


FECHA_BARRA = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})")


def orden_de_fechas(valores):
    """«dmy» o «mdy» para las fechas con barra del archivo (11/02/2026); None si ninguna lo decide (todas con día ≤ 12)."""
    dmy = mdy = False
    for x in valores:
        m = FECHA_BARRA.match(str(x or "").strip())
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            dmy = dmy or a > 12
            mdy = mdy or b > 12
    if dmy and mdy:
        raise KemetError("las fechas del CSV mezclan día/mes y mes/día: pasa --fechas dmy o --fechas mdy")
    return "dmy" if dmy else ("mdy" if mdy else None)


def _fecha(x, orden="dmy"):
    s = str(x or "").strip()
    m = FECHA_BARRA.match(s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        d, mes = (a, b) if orden != "mdy" else (b, a)
        try:
            return dt.date(y, mes, d)
        except ValueError:
            return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(s[:10], fmt).date()
        except ValueError:
            pass
    return None


def _hora(x):
    s = str(x or "").strip().upper().replace(".", "") if re.search(r"[AP]\.?M", str(x or ""), re.I) else str(x or "").strip()
    if " " in s and re.match(r"^\d{4}-\d{2}-\d{2} ", s):      # fecha y hora en la misma columna
        s = s.split(" ", 1)[1]
    for fmt in ("%H:%M", "%H:%M:%S", "%H.%M", "%I:%M %p", "%I:%M:%S %p", "%I:%M%p"):
        try:
            return dt.datetime.strptime(s, fmt).time().replace(second=0)
        except ValueError:
            pass
    return None


def madrid_a_ny(fecha, hora):
    """Hora de Madrid (naive) a hora de Nueva York del mismo instante."""
    local = dt.datetime.combine(fecha, hora)
    utc = local - dt.timedelta(hours=comun.madrid_offset(local - dt.timedelta(hours=1)))
    return comun.a_ny(utc)


def contrato_de(simbolo):
    """(código, es_micro, valor del punto) para MNQ, NQ, MNQZ6, NQZ26… o un ticker de EE. UU. (TSLA: 1 $ por acción); None si no lo conoce."""
    s = str(simbolo or "").strip().upper().replace(" ", "")
    candidatos = [s]
    # la letra del mes solo se quita si detrás va el año (MNQZ6, NQZ26): CLF, SIG o HGV son acciones, no CL, SI o HG
    m = re.match(r"^([A-Z0-9]*?[A-Z])(\d{1,4})$", s)
    if m:
        base = m.group(1)
        for c in (base, base[:-1] if base[-1] in "FGHJKMNQUVXZ" else None):
            if c and (c in comun.CONTRATOS or c in comun.MICRO_A_CODIGO):
                candidatos.append(c)
    for c in candidatos:
        if c in comun.MICRO_A_CODIGO:
            k = comun.MICRO_A_CODIGO[c]
            return k, True, comun.CONTRATOS[k]["punto_micro"]
        if c in comun.CONTRATOS:
            return c, False, comun.CONTRATOS[c]["punto_mini"]
    try:
        inst = comun.resolver(s)
    except KemetError:
        return None
    if inst["tipo"] == "accion":
        return inst["codigo"], False, 1.0
    return None


def es_accion(mercado):
    return comun.resolver(mercado)["tipo"] == "accion"


def mapear_columnas(cabecera):
    """{campo: índice} a partir de la cabecera, con los alias en español e inglés."""
    normal = [_norm(h) for h in cabecera]
    out = {}
    for campo, alias in COLUMNAS.items():
        for i, h in enumerate(normal):
            if h in alias and campo not in out:
                out[campo] = i
    out["_hora_madrid"] = "hora" in out and normal[out["hora"]] in ("hora_madrid", "time_madrid")
    return out


def leer_csv(ruta, decimal=None, fechas=None):
    """Lee el CSV y devuelve (operaciones, avisos). Cada operación es un dict con las cifras ya en números."""
    try:
        with open(ruta, encoding="utf-8-sig") as fh:
            texto = fh.read()
    except FileNotFoundError:
        raise KemetError("no encuentro %s" % ruta)
    lineas = [l for l in texto.splitlines() if l.strip()]
    if not lineas:
        raise KemetError("%s está vacío" % ruta)
    sep = ";" if lineas[0].count(";") > lineas[0].count(",") else ","
    filas = list(csv.reader(io.StringIO("\n".join(lineas)), delimiter=sep))
    col = mapear_columnas(filas[0])
    faltan = [c for c in ("fecha", "hora", "simbolo", "lado", "entrada") if c not in col]
    if faltan:
        raise KemetError("al CSV le faltan columnas: %s (cabecera leída: %s). `diario.py plantilla` imprime la cabecera esperada"
                         % (", ".join(faltan), ", ".join(filas[0])))
    ops, avisos = [], []

    def columna(campo):
        i = col.get(campo)
        return [f[i] for f in filas[1:] if i is not None and i < len(f)]
    estilo = decimal or estilo_de(sum((columna(c) for c in ("entrada", "salida", "stop", "pnl", "contratos")), []))
    orden = fechas or orden_de_fechas(columna("fecha"))
    if orden is None and any(FECHA_BARRA.match(str(x).strip()) for x in columna("fecha")):
        orden = "mdy" if estilo == "punto" else "dmy"
        avisos.append("las fechas con barra no dicen si son día/mes o mes/día: las leo como %s (%s); si no es así, pasa --fechas %s"
                      % ("mes/día" if orden == "mdy" else "día/mes", "las cifras son de EE. UU." if estilo == "punto" else "formato español",
                         "dmy" if orden == "mdy" else "mdy"))
    if estilo is None:
        # «26,812» en NQ: con coma decimal (26,812) no cae en el tick de 0,25; con coma de miles (26.812) sí. Un precio así decide el archivo.
        for fila in filas[1:]:
            i = col.get("simbolo")
            ct = contrato_de(fila[i]) if i is not None and i < len(fila) else None
            if not ct:
                continue
            try:
                tick = comun.resolver(ct[0])["tick"] if ct[2] != 1.0 else 0.01
            except KemetError:
                continue
            for c in ("entrada", "salida", "stop"):
                j = col.get(c)
                s = _limpio(fila[j]) if j is not None and j < len(fila) else ""
                if MILES_EEUU.match(s) and "." not in s:
                    dec, miles = float(s.replace(",", ".")), float(s.replace(",", ""))
                    en_tick = lambda x: abs(x / tick - round(x / tick)) < 1e-6
                    if en_tick(miles) and not en_tick(dec):
                        estilo = "punto"
        if estilo == "punto":
            avisos.append("leo las comas como separador de miles (formato de EE. UU.): algún precio no cae en el tick del contrato con coma decimal; si no es así, pasa --decimal coma")
    if estilo is None and any(MILES_EEUU.match(_limpio(x)) for c in ("entrada", "salida", "stop", "pnl") for x in columna(c)):
        avisos.append("hay cifras como «1,234» que pueden ser miles (EE. UU.) o decimales (España): las leo con coma decimal; si tu exportación es de EE. UU., pasa --decimal punto")
    for n, fila in enumerate(filas[1:], 2):
        def v(campo):
            i = col.get(campo)
            return fila[i].strip() if i is not None and i < len(fila) else ""
        fecha, hora = _fecha(v("fecha"), orden), _hora(v("hora"))
        ct = contrato_de(v("simbolo"))
        lado = LADOS.get(_norm(v("lado")))
        entrada, salida, stop, pnl = _f(v("entrada"), estilo), _f(v("salida"), estilo), _f(v("stop"), estilo), _f(v("pnl"), estilo)
        contratos = _f(v("contratos"), estilo)
        if fecha is None or hora is None or not ct or not lado or entrada is None:
            avisos.append("línea %d descartada: fecha, hora, símbolo, lado o entrada ilegibles (%s)" % (n, sep.join(fila)[:60]))
            continue
        if col.get("_hora_madrid"):
            ny = madrid_a_ny(fecha, hora)
            fecha, hora = ny.date(), ny.time()
        codigo, es_micro, punto = ct
        if contratos is None:
            contratos = 1
            if "contratos" in col:
                avisos.append("línea %d: cantidad ilegible (%r), cuento 1" % (n, v("contratos")))
        elif contratos == 0:
            avisos.append("línea %d descartada: cantidad 0" % n)
            continue
        elif contratos < 0 or contratos != int(contratos):
            avisos.append("línea %d: cantidad %s, cuento %d" % (n, v("contratos"), max(1, int(abs(contratos)))))
        contratos = max(1, int(abs(contratos)))
        if pnl is None:
            if salida is None:
                avisos.append("línea %d: sin pnl ni salida, resultado desconocido" % n)
            else:
                pnl = round((salida - entrada if lado == "largo" else entrada - salida) * contratos * punto, 2)
        riesgo_pts = None
        if stop is not None:
            if (lado == "largo" and stop >= entrada) or (lado == "corto" and stop <= entrada):
                avisos.append("línea %d: el stop %s está del lado equivocado de la entrada %s; se trata como sin stop" % (n, pts(stop), pts(entrada)))
                stop = None
            else:
                riesgo_pts = comun.al_tick(abs(entrada - stop), comun.resolver(codigo)["tick"])
        ops.append({"linea": n, "fecha": fecha, "hora": hora, "simbolo": v("simbolo").upper(), "mercado": codigo, "micro": es_micro, "punto": punto,
                    "lado": lado, "contratos": contratos, "entrada": entrada, "salida": salida, "stop": stop, "riesgo_pts": riesgo_pts,
                    "riesgo_usd": round(riesgo_pts * punto * contratos, 2) if riesgo_pts else None, "pnl": pnl, "nota": v("nota"),
                    "infracciones": []})
    if not ops:
        raise KemetError("ninguna operación legible en %s" % ruta)
    ops.sort(key=lambda o: (o["fecha"], o["hora"], o["linea"]))
    return ops, avisos


# ---------------------------------------------------------------- la revisión

def franja_de(t):
    for nombre, a, b in FRANJAS:
        if comun.parse_hhmm(a) <= t < comun.parse_hhmm(b):
            return nombre
    return "fuera de la sesión regular"


def _mas(t, minutos):
    return (dt.datetime.combine(dt.date(2000, 1, 1), t) + dt.timedelta(minutes=minutos)).time()


def hora_limite_ny(cfg):
    if not cfg or not cfg.get("hora_limite"):
        return None
    t = comun.parse_hhmm(cfg["hora_limite"], "la hora límite")
    return _mas(t, 60) if cfg.get("hora_limite_tz") == "America/Chicago" else t


def ventanas_agenda(agenda, mercado):
    """{fecha: [(desde, hasta, motivo)]} de kemet/agenda.json (una agenda, un día)."""
    if not agenda or not agenda.get("fecha"):
        return {}
    f = _fecha(agenda["fecha"])
    out = []
    for d in agenda.get("datos") or []:
        if d.get("mercados") and mercado not in [m.upper() for m in d["mercados"]]:
            continue
        t = _hora(d.get("hora"))
        if not t:
            continue
        m = 20 if d.get("fuerte") else 10
        out.append((_mas(t, -m), _mas(t, m), "%s a las %s" % (d.get("nombre", "dato"), comun.hhmm(t))))
    return {f: out} if f and out else {}


def revisar(ops, cfg=None, agenda=None, stop_habitual=None):
    """Pura: operaciones + config + agenda -> el documento de la revisión (dict)."""
    c = cfg or {}
    pmd = c.get("perdida_max_dia")
    fyp = int(c.get("fallos_y_paras") or FALLOS_Y_PARAS)
    riesgo_op = float(c["riesgo_por_operacion"]) if c.get("riesgo_por_operacion") else ((pmd / float(fyp)) if pmd else None)
    mercado = (c.get("mercado") or ops[0]["mercado"]).upper()
    plano = comun.parse_hhmm(c["plano_a"]) if c.get("plano_a") else comun.parse_hhmm(comun.resolver(ops[0]["mercado"])["plano"])
    limite = hora_limite_ny(c)
    despues = comun.parse_hhmm(c["sin_entradas_despues"]) if c.get("sin_entradas_despues") else None
    ventanas = {f: v for f, v in ventanas_agenda(agenda, mercado).items() if ops[0]["fecha"] <= f <= ops[-1]["fecha"]}
    # por operación
    for o in ops:
        o["franja"] = franja_de(o["hora"])
        apertura = comun.parse_hhmm(comun.resolver(o["mercado"])["rth"][0])
        inf = o["infracciones"]
        if o["stop"] is None:
            inf.append("sin_stop")
            if stop_habitual:
                o["riesgo_pts"] = float(stop_habitual)
                o["riesgo_usd"] = round(stop_habitual * o["punto"] * o["contratos"], 2)
                o["riesgo_supuesto"] = True
        if apertura <= o["hora"] < _mas(apertura, APERTURA_MIN):
            inf.append("apertura")
        for desde, hasta, motivo in ventanas.get(o["fecha"], []):
            if desde <= o["hora"] <= hasta:
                inf.append("ventana")
                o["ventana"] = motivo
                break
        if riesgo_op and o["riesgo_usd"] and not o.get("riesgo_supuesto") and o["riesgo_usd"] > riesgo_op + 0.005:
            inf.append("tamano")
        if o["stop"] is not None and o["pnl"] is not None and o["pnl"] < 0 and -o["pnl"] > o["riesgo_usd"] * TOLERANCIA_STOP:
            inf.append("stop_ampliado")
        if o["hora"] >= plano:
            inf.append("plano")
        if limite and o["hora"] >= limite:
            inf.append("hora_limite")
        if despues and o["hora"] > despues and "plano" not in inf:
            inf.append("horario")
    # por día
    dias = {}
    for o in ops:
        # un futuro cuenta en su sesión de CME (empieza a las 18:00 NY): tres pérdidas de 23:40 a 01:10 son del mismo día
        dia = o["fecha"] if o["punto"] == 1.0 else comun.dia_negociacion(dt.datetime.combine(o["fecha"], o["hora"]))
        dias.setdefault(dia, []).append(o)
    resumen_dias = []
    for f in sorted(dias):
        lista = dias[f]
        acumulado, fallos, superado_en, tercer_fallo_en = 0.0, 0, None, None
        for o in lista:
            if superado_en is not None:
                o["infracciones"].append("tras_limite")
            if tercer_fallo_en is not None:
                o["infracciones"].append("tras_tercer_fallo")
            if o["pnl"] is not None:
                acumulado += o["pnl"]
                if o["pnl"] < 0:
                    fallos += 1
                    if fallos == fyp and tercer_fallo_en is None:
                        tercer_fallo_en = o["hora"]
            if pmd and acumulado < -pmd - 0.005 and superado_en is None:
                superado_en = o["hora"]
        resumen_dias.append({"fecha": f.isoformat(), "dia_semana": DIAS_SEMANA[f.weekday()], "operaciones": len(lista), "pnl": round(acumulado, 2),
                             "perdidas": fallos, "supero_limite_a_las": comun.hhmm(superado_en) if superado_en else None,
                             "tercera_perdida_a_las": comun.hhmm(tercer_fallo_en) if tercer_fallo_en else None,
                             "tras_limite": sum(1 for o in lista if "tras_limite" in o["infracciones"]),
                             "tras_tercer_fallo": sum(1 for o in lista if "tras_tercer_fallo" in o["infracciones"])})
    # cumplimiento
    cumplimiento = {}
    for clave in ETIQUETAS:
        afectadas = [o for o in ops if clave in o["infracciones"]]
        if clave == "tamano":
            coste = sum(min(-o["pnl"], o["riesgo_usd"] - riesgo_op) for o in afectadas if o["pnl"] is not None and o["pnl"] < 0)
        elif clave == "stop_ampliado":
            coste = sum(-o["pnl"] - o["riesgo_usd"] for o in afectadas if o["pnl"] is not None)
        else:
            coste = sum(-o["pnl"] for o in afectadas if o["pnl"] is not None and o["pnl"] < 0)
        medible = True
        if clave in ("tamano", "tras_limite") and not riesgo_op:
            medible = False
        if clave == "ventana" and not ventanas:
            medible = False
        if clave == "hora_limite" and not limite:
            medible = False
        if clave == "horario" and not despues:
            medible = False
        cumplimiento[clave] = {"etiqueta": ETIQUETAS[clave], "n": len(afectadas), "coste": round(max(coste, 0.0), 2), "medible": medible,
                               "operaciones": [_ref(o) for o in afectadas[:4]]}
    # franjas y días de la semana
    por_franja = []
    for nombre, a, b in FRANJAS + [("fuera de la sesión regular", "", "")]:
        lista = [o for o in ops if o["franja"] == nombre]
        if lista or nombre != "fuera de la sesión regular":
            por_franja.append({"franja": nombre, "horas": ("%s–%s" % (a, b)) if a else "", "operaciones": len(lista),
                               "pnl": round(sum(o["pnl"] or 0 for o in lista), 2), "perdidas": sum(1 for o in lista if (o["pnl"] or 0) < 0)})
    por_dia_semana = []
    for i, nombre in enumerate(DIAS_SEMANA[:5]):
        lista = [o for o in ops if o["fecha"].weekday() == i]
        if lista:
            por_dia_semana.append({"dia": nombre, "operaciones": len(lista), "pnl": round(sum(o["pnl"] or 0 for o in lista), 2)})
    metricas = calcular_metricas(ops, c)
    bien = tres_cosas_bien(ops, cumplimiento, resumen_dias, por_franja, ventanas, riesgo_op)
    rupturas = [dict(v, clave=k) for k, v in cumplimiento.items() if v["n"] and v["medible"]]
    rupturas.sort(key=lambda r: (-r["coste"], -r["n"]))
    correccion = una_correccion(rupturas, ops, c, riesgo_op, ventanas, plano, despues, stop_habitual)
    return {"operaciones": len(ops), "desde": ops[0]["fecha"].isoformat(), "hasta": ops[-1]["fecha"].isoformat(), "mercado": mercado,
            "config": {"cuenta_nombre": c.get("cuenta_nombre"), "perdida_max_dia": pmd, "riesgo_por_operacion": round(riesgo_op, 2) if riesgo_op else None,
                       "fallos_y_paras": fyp, "plano_a": comun.hhmm(plano), "hora_limite_ny": comun.hhmm(limite) if limite else None,
                       "sin_entradas_despues": comun.hhmm(despues) if despues else None, "drawdown": c.get("drawdown")},
            "agenda_dias": [f.isoformat() for f in ventanas], "cumplimiento": cumplimiento, "dias": resumen_dias, "por_franja": por_franja,
            "por_dia_semana": por_dia_semana, "metricas": metricas, "bien": bien, "rupturas": rupturas[:2], "correccion": correccion,
            "detalle": [_op_json(o) for o in ops]}


def _pl(n, uno, varios=None):
    return "%d %s" % (n, uno if n == 1 else (varios or uno + "s"))


def _ref(o, con_pnl=True):
    return "%s %s %s %d %s%s" % (o["fecha"].strftime("%d/%m"), comun.hhmm(o["hora"]), o["lado"], o["contratos"], o["simbolo"],
                                 (" " + usd(o["pnl"], 0)) if con_pnl and o["pnl"] is not None else "")


def _op_json(o):
    d = dict(o)
    d["fecha"], d["hora"] = o["fecha"].isoformat(), comun.hhmm(o["hora"])
    return d


def calcular_metricas(ops, c):
    con_pnl = [o for o in ops if o["pnl"] is not None]
    n = len(con_pnl)
    if n < MINIMO_METRICAS:
        return {"operaciones": n, "suficientes": False, "nota": "con menos de %d operaciones las métricas son ruido; se omiten" % MINIMO_METRICAS}
    ganan = [o["pnl"] for o in con_pnl if o["pnl"] > 0]
    pierden = [o["pnl"] for o in con_pnl if o["pnl"] < 0]
    total = sum(o["pnl"] for o in con_pnl)
    rs = [o["pnl"] / o["riesgo_usd"] for o in con_pnl if o.get("riesgo_usd")]
    racha = peor = 0
    for o in con_pnl:
        racha = racha + 1 if o["pnl"] < 0 else 0
        peor = max(peor, racha)
    pico = acumulado = dd = 0.0
    for o in con_pnl:
        acumulado += o["pnl"]
        pico = max(pico, acumulado)
        dd = max(dd, pico - acumulado)
    pf = (sum(ganan) / -sum(pierden)) if pierden else None
    return {"operaciones": n, "suficientes": True, "resultado_total": round(total, 2), "expectativa_usd": round(total / n, 2),
            "expectativa_r": round(sum(rs) / len(rs), 2) if rs else None, "con_r": len(rs), "acierto": round(100.0 * len(ganan) / n, 1),
            "ganancia_media": round(sum(ganan) / len(ganan), 2) if ganan else None, "perdida_media": round(sum(pierden) / len(pierden), 2) if pierden else None,
            "ratio_ganancia_perdida": round((sum(ganan) / len(ganan)) / (-sum(pierden) / len(pierden)), 2) if ganan and pierden else None,
            "ganancias_entre_perdidas": round(pf, 2) if pf else None, "racha_perdidas": peor, "drawdown_usd": round(dd, 2), "drawdown_cuenta": c.get("drawdown")}


def tres_cosas_bien(ops, cump, dias, franjas, ventanas, riesgo_op):
    out = []
    con_stop = [o for o in ops if o["stop"] is not None]
    if ops and len(con_stop) >= 0.75 * len(ops):
        cortadas = [o for o in con_stop if o["pnl"] is not None and o["pnl"] < 0 and -o["pnl"] <= o["riesgo_usd"] * TOLERANCIA_STOP]
        if cortadas:
            peor = min(cortadas, key=lambda o: o["pnl"])
            out.append("%d de %d operaciones con stop puesto; la de %s salió en el stop con %s, el riesgo que tenía previsto"
                       % (len(con_stop), len(ops), _ref(peor, False), usd(peor["pnl"], 0)))
    if ventanas and cump["ventana"]["n"] == 0:
        f = sorted(ventanas)[0]
        v = ventanas[f][0]
        primeras = [o for o in ops if o["fecha"] == f]
        out.append("ninguna entrada en las ventanas de datos: el %s había %s (sin operar de %s a %s)%s"
                   % (f.strftime("%d/%m"), v[2], comun.hhmm(v[0]), comun.hhmm(v[1]), (" y la primera entrada fue a las %s" % comun.hhmm(primeras[0]["hora"])) if primeras else ""))
    if cump["apertura"]["n"] == 0:
        primera = min(ops, key=lambda o: o["hora"])
        out.append("ninguna entrada en la apertura 09:30–09:45: la más temprana fue a las %s (%s)" % (comun.hhmm(primera["hora"]), primera["fecha"].strftime("%d/%m")))
    if cump["plano"]["n"] == 0 and cump["hora_limite"]["n"] == 0:
        ultima = max(ops, key=lambda o: o["hora"])
        out.append("ninguna entrada después de la hora de estar plano: la más tardía fue a las %s (%s)" % (comun.hhmm(ultima["hora"]), ultima["fecha"].strftime("%d/%m")))
    paro = [d for d in dias if d["tercera_perdida_a_las"] and d["tras_tercer_fallo"] == 0]
    if paro:
        d = paro[0]
        out.append("el %s paraste tras la tercera pérdida (a las %s): ninguna operación después" % (d["fecha"][8:] + "/" + d["fecha"][5:7], d["tercera_perdida_a_las"]))
    dentro = [d for d in dias if d["supero_limite_a_las"] is None]
    if riesgo_op and dias and len(dentro) == len(dias):
        peor = min(dias, key=lambda d: d["pnl"])
        out.append("ningún día pasó de la pérdida máxima del día: el peor fue el %s con %s" % (peor["fecha"][8:] + "/" + peor["fecha"][5:7], usd(peor["pnl"], 0)))
    riesgos = sorted(o["riesgo_usd"] for o in con_stop if o["riesgo_usd"])
    if len(riesgos) >= 5:
        med = comun.mediana(riesgos)
        cerca = [r for r in riesgos if abs(r - med) <= 0.25 * med]
        if len(cerca) >= 0.8 * len(riesgos):
            if min(cerca) == max(cerca):
                out.append("riesgo constante: %d de %d operaciones con stop arriesgaron %s" % (len(cerca), len(riesgos), usd(med, 0)))
            else:
                out.append("riesgo casi constante: %d de %d operaciones con stop arriesgaron entre %s y %s (mediana %s)"
                           % (len(cerca), len(riesgos), usd(min(cerca), 0), usd(max(cerca), 0), usd(med, 0)))
    mejor = [f for f in franjas if f["franja"] == "mejor franja"]
    if mejor and ops and mejor[0]["operaciones"] >= 0.5 * len(ops):
        out.append("%d de %d entradas en la mejor franja (09:45–11:30), con %s en total" % (mejor[0]["operaciones"], len(ops), usd(mejor[0]["pnl"], 0)))
    if cump["stop_ampliado"]["n"] == 0 and con_stop:
        out.append("ninguna pérdida mayor que su stop en %d operaciones con stop" % len(con_stop))
    return out[:3]


def una_correccion(rupturas, ops, c, riesgo_op, ventanas, plano, despues, stop_habitual):
    if not rupturas:
        riesgos = [o["riesgo_usd"] for o in ops if o["riesgo_usd"]]
        return "Mañana, lo mismo: riesgo constante%s y el stop puesto antes de entrar." % ((" de %s" % usd(comun.mediana(riesgos), 0)) if riesgos else "")
    r = rupturas[0]
    k = r["clave"]
    if k == "sin_stop":
        return "Mañana el stop va en la plataforma antes de confirmar la entrada; sin stop no hay orden. Comprobable: 0 operaciones sin stop en el CSV de mañana."
    if k == "apertura":
        return "Mañana la primera entrada no antes de las 09:45 NY. Comprobable: la hora de la primera fila."
    if k == "ventana":
        f = sorted(ventanas)[0]
        v = ventanas[f][0]
        return "Mañana ninguna entrada ni posición dentro de la ventana del dato (%s a %s para %s). Comprobable: la hora de cada fila contra la agenda." % (comun.hhmm(v[0]), comun.hhmm(v[1]), v[2])
    if k == "tamano":
        stops = [o["riesgo_pts"] for o in ops if o["stop"] is not None]
        stop = float(stop_habitual) if stop_habitual else (comun.mediana(stops) if stops else None)
        o = ops[0]
        if stop and riesgo_op and es_accion(o["mercado"]):
            n = int(riesgo_op // stop)
            return "Mañana como mucho %d acciones de %s con stop de %s por acción (%s de riesgo por operación). Comprobable: acciones × stop ≤ %s en cada fila." % (
                n, o["mercado"], usd(stop, 2), usd(riesgo_op, 2), usd(riesgo_op, 2))
        if stop and riesgo_op:
            n = int(riesgo_op // (stop * o["punto"]))
            return "Mañana como mucho %d %s con stop de %s pts (%s de riesgo por operación). Comprobable: contratos × stop × %s $ ≤ %s en cada fila." % (
                n, comun.CONTRATOS[o["mercado"]]["micro"], pts(stop), usd(riesgo_op, 2), num(o["punto"], 0), usd(riesgo_op, 2))
        return "Mañana cada operación arriesga como mucho %s al stop. Comprobable: contratos × stop × valor del punto en cada fila." % usd(riesgo_op, 2)
    if k == "stop_ampliado":
        return "Mañana el stop no se mueve en contra: si salta, se acepta. Comprobable: ninguna pérdida mayor que contratos × stop × valor del punto."
    if k == "plano":
        return "Mañana plano a las %s NY y ninguna entrada después. Comprobable: la hora de la última fila." % comun.hhmm(plano)
    if k == "hora_limite":
        return "Mañana nada abierto a la hora límite de tu firma (%s NY). Comprobable: la hora de la última fila." % c.get("hora_limite")
    if k == "horario":
        return "Mañana ninguna entrada después de las %s NY. Comprobable: la hora de la última fila." % comun.hhmm(despues)
    if k in ("tras_limite", "tras_tercer_fallo"):
        return "Mañana a la tercera pérdida%s se cierra la plataforma. Comprobable: ninguna fila después de la tercera pérdida del día." % (
            (" o al llegar a %s de pérdida" % usd(c["perdida_max_dia"], 0)) if c.get("perdida_max_dia") else "")
    return "Mañana: " + r["etiqueta"]


# ---------------------------------------------------------------- informe

def informe(doc, ruta, ahora_utc, avisos):
    L = ["DIARIO · %s · %d operaciones · del %s al %s · %s" % (os.path.basename(ruta), doc["operaciones"], doc["desde"], doc["hasta"], comun.hora_doble(ahora_utc))]
    cf = doc["config"]
    if cf["perdida_max_dia"]:
        L.append("Config: %s · pérdida máxima del día %s · riesgo por operación %s · plano a las %s NY%s"
                 % (cf["cuenta_nombre"], usd(cf["perdida_max_dia"]), usd(cf["riesgo_por_operacion"], 2), cf["plano_a"],
                    (" · hora límite %s NY" % cf["hora_limite_ny"]) if cf["hora_limite_ny"] else ""))
    else:
        L.append("Sin kemet/config.json: no mido el tamaño ni la pérdida máxima del día; plano a las %s NY por defecto. Ejecuta tamano.py config" % cf["plano_a"])
    L.append("Agenda: %s" % (("ventanas de datos del " + ", ".join(doc["agenda_dias"])) if doc["agenda_dias"] else "sin kemet/agenda.json de esos días, solo la ventana de la apertura"))
    for a in avisos:
        L.append("AVISO: " + a)
    L.append("")
    L.append("Cumplimiento del plan (antes que el resultado):")
    for k, v in doc["cumplimiento"].items():
        if not v["medible"]:
            L.append("  %-58s no medible" % v["etiqueta"])
            continue
        if v["n"] == 0:
            L.append("  %-58s 0" % v["etiqueta"])
        else:
            L.append("  %-58s %d · coste %s · %s" % (v["etiqueta"], v["n"], usd(v["coste"], 0), "; ".join(v["operaciones"]) + (" …" if v["n"] > 4 else "")))
    L.append("")
    L.append("Por franja (hora NY):")
    for f in doc["por_franja"]:
        L.append("  %-26s %-12s %3d op · %s · %s" % (f["franja"], f["horas"], f["operaciones"], usd(f["pnl"], 0), _pl(f["perdidas"], "pérdida")))
    L.append("")
    L.append("Por día:")
    for d in doc["dias"]:
        extra = ""
        if d["supero_limite_a_las"]:
            extra += " · superó la pérdida máxima del día a las %s" % d["supero_limite_a_las"] + ((", %s después" % _pl(d["tras_limite"], "operación", "operaciones")) if d["tras_limite"] else "")
        if d["tercera_perdida_a_las"]:
            extra += " · tercera pérdida a las %s" % d["tercera_perdida_a_las"] + (", %d después" % d["tras_tercer_fallo"] if d["tras_tercer_fallo"] else ", paraste")
        L.append("  %s %-10s %2d op · %s%s" % (d["fecha"], d["dia_semana"], d["operaciones"], usd(d["pnl"], 0), extra))
    m = doc["metricas"]
    L.append("")
    if not m["suficientes"]:
        L.append("Métricas: %s." % m["nota"])
    else:
        L.append("Métricas (%d operaciones):" % m["operaciones"])
        L.append("  resultado total %s · expectativa %s por operación%s" % (usd(m["resultado_total"], 0), usd(m["expectativa_usd"], 2),
                                                                           (" · %s R (%d con riesgo conocido)" % (num(m["expectativa_r"], 2), m["con_r"])) if m["expectativa_r"] is not None else ""))
        L.append("  acierto %s %% · ganancia media %s · pérdida media %s · ratio %s" % (num(m["acierto"], 1), usd(m["ganancia_media"] or 0, 0), usd(m["perdida_media"] or 0, 0), num(m["ratio_ganancia_perdida"], 2) if m["ratio_ganancia_perdida"] else "n/d"))
        L.append("  ganancias entre pérdidas %s%s · racha máxima de pérdidas %d · drawdown máximo %s%s"
                 % (num(m["ganancias_entre_perdidas"], 2) if m["ganancias_entre_perdidas"] else "n/d", " (por debajo de 1,1 no hay nada que optimizar: cambia el método, no el tamaño)" if m["ganancias_entre_perdidas"] and m["ganancias_entre_perdidas"] < 1.1 else "",
                    m["racha_perdidas"], usd(m["drawdown_usd"], 0), (" de los %s de la cuenta" % usd(m["drawdown_cuenta"], 0)) if m["drawdown_cuenta"] else ""))
        if doc["por_dia_semana"]:
            L.append("  por día de la semana: " + " · ".join("%s %d op %s" % (d["dia"], d["operaciones"], usd(d["pnl"], 0)) for d in doc["por_dia_semana"]))
    L.append("")
    L.append("Tres cosas bien:")
    for i, b in enumerate(doc["bien"], 1):
        L.append("  %d. %s" % (i, b))
    if len(doc["bien"]) < 3:
        L.append("  (solo encuentro %d con evidencia en el archivo)" % len(doc["bien"]))
    L.append("Dos rupturas del plan:")
    for i, r in enumerate(doc["rupturas"], 1):
        L.append("  %d. %s: %s, coste %s (%s%s)" % (i, r["etiqueta"], _pl(r["n"], "operación", "operaciones"), usd(r["coste"], 0), "; ".join(r["operaciones"]), " …" if r["n"] > 4 else ""))
    if not doc["rupturas"]:
        L.append("  ninguna en lo que el archivo deja medir")
    elif len(doc["rupturas"]) < 2:
        L.append("  (solo una en lo que el archivo deja medir)")
    L.append("Una corrección para mañana:")
    L.append("  " + doc["correccion"])
    L.append("")
    L.append("Con menos de 100 operaciones por regla lo que se ve es ruido: una semana no juzga una regla. Esto cuenta hechos, no califica.")
    return "\n".join(L)


# ---------------------------------------------------------------- subcomandos

def cmd_revisar(a):
    ahora = comun.parse_ahora(a.ahora)
    ops, avisos = leer_csv(a.csv, a.decimal, a.fechas)
    desde = _fecha(a.desde) if a.desde else None
    hasta = _fecha(a.hasta) if a.hasta else None
    if a.desde and not desde or a.hasta and not hasta:
        raise KemetError("--desde y --hasta van como AAAA-MM-DD")
    ops = [o for o in ops if (not desde or o["fecha"] >= desde) and (not hasta or o["fecha"] <= hasta)]
    if not ops:
        raise KemetError("ninguna operación entre %s y %s" % (a.desde or "el principio", a.hasta or "el final"))
    cfg = comun.leer_json("config.json", obligatorio=False)
    agenda = comun.leer_json("agenda.json", obligatorio=False)
    doc = revisar(ops, cfg, agenda, a.stop_habitual)
    doc["archivo"] = a.csv
    doc["avisos"] = avisos
    print(json.dumps(doc, ensure_ascii=False, indent=1, default=str) if a.json else informe(doc, a.csv, ahora, avisos))
    return 1 if doc["rupturas"] else 0


def cmd_plantilla(a):
    print(PLANTILLA)
    print("# fecha AAAA-MM-DD · hora HH:MM de Nueva York (o llama a la columna hora_madrid) · simbolo MNQ/NQ/MES/ES/MCL/MGC · lado largo/corto")
    print("# contratos entero · entrada, salida y stop en puntos del contrato · pnl en dólares (si falta se calcula) · nota libre")
    print("# acciones: el ticker en simbolo (TSLA), la cantidad en acciones en contratos (o una columna acciones), precios en dólares por acción")
    print("# ejemplo de acción: 2026-11-11,10:15,TSLA,largo,9,393.08,389.51,389.51,-32.13,ruptura del rango de 15 min; el stop saltó a las 15:50")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Revisión del diario: cumplimiento antes que resultado (kemet-diario).")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("revisar", help="revisa un CSV de operaciones")
    p.add_argument("csv")
    p.add_argument("--desde", help="AAAA-MM-DD")
    p.add_argument("--hasta", help="AAAA-MM-DD")
    p.add_argument("--decimal", choices=["coma", "punto"], help="separador decimal de las cifras si el archivo no lo deja claro (punto: exportación de EE. UU.)")
    p.add_argument("--fechas", choices=["dmy", "mdy"], help="orden de las fechas con barra si el archivo no lo deja claro (mdy: EE. UU.)")
    p.add_argument("--stop-habitual", dest="stop_habitual", type=float, help="stop en puntos que supone para las operaciones sin stop (solo métricas)")
    p.add_argument("--ahora", help="hora de Nueva York, AAAA-MM-DD HH:MM (solo para la cabecera)")
    p.add_argument("--json", action="store_true")
    sub.add_parser("plantilla", help="la cabecera del CSV")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    try:
        return {"revisar": cmd_revisar, "plantilla": cmd_plantilla}[a.cmd](a)
    except KemetError as e:
        print("diario.py: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
