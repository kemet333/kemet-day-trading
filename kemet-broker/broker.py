#!/usr/bin/env python3
"""El ticket de cada orden y el registro de lo que se puso (kemet-broker). Solo biblioteca estándar, sin red.

Esta herramienta no habla con ningún bróker y no pone nada. Trabaja alrededor del único momento que importa, tu sí:

  mostrar    cada orden de kemet/orden.json como un ticket en palabras llanas. Para una acción, además el JSON exacto
             que Claude pasará a place_stock_order (el conector de Alpaca). Una orden está LISTA solo si kemet-riesgo
             le dio PASS hoy a ESA orden exacta (misma huella) y nadie ha decidido aún sobre ella.
  aprobar    apunta tu sí explícito para UNA orden, con tu respuesta palabra por palabra. Rechaza «sí a todas», «vale»,
             «ok», un sí que nombra otro símbolo u otra cifra, y cualquier orden que no esté LISTA.
  rechazar   apunta un no.
  registrar  apunta lo que pasó tras la tarjeta del conector (colocada con su id y su precio, denegada o fallida) y,
             si se colocó, el fill en kemet/portfolio.json (efectivo y posiciones). Para un futuro solo la posición, sin
             efectivo. Sin --huella apunta un fill suelto: la pata de la bracket que se llenó, o un cierre a mano.
  plano      construye en kemet/orden.json la orden que cierra la posición de un símbolo, con "cierre": true.
             Vuelve a pasar por kemet-riesgo y por tu sí.
  hoy        lo apuntado hoy.

    python3 broker.py mostrar                                  # todas las órdenes, LISTAS o no
    python3 broker.py mostrar --indice 1 --json
    python3 broker.py aprobar --huella 3f1c2a9b0d4e --respuesta "sí"
    python3 broker.py registrar --huella 3f1c2a9b0d4e --id-broker 61e6... --precio 393.10
    python3 broker.py registrar --huella 3f1c2a9b0d4e --estado denegada
    python3 broker.py registrar --simbolo TSLA --lado venta --cantidad 8 --precio 389.51 --id-broker ID   # la pata que se llenó
    python3 broker.py plano --simbolo TSLA
    python3 broker.py hoy

Lee y escribe en `kemet/` del directorio actual (variable KEMET_DIR). Las fechas son de Nueva York;
`--ahora "2026-11-11 10:16"` fija el reloj. Código de salida: `mostrar` 0 si alguna orden está LISTA, 1 si ninguna;
`aprobar` 1 si la respuesta no vale; errores en una línea, código 2.
"""
import argparse
import hashlib
import json
import os
import re
import sys

import comun
from comun import KemetError, num, pts, usd

# Los campos de una orden de futuro que forman la huella: la misma lista que kemet-riesgo/riesgo.py (CAMPOS_HUELLA).
CAMPOS_HUELLA = ("simbolo", "lado", "contratos", "tipo", "precio", "stop", "objetivo", "cierre")
# Los parámetros de place_stock_order del servidor MCP de Alpaca (alpaca-mcp-server 2.4.0). Solo estos se envían.
CAMPOS_ALPACA = ("symbol", "side", "qty", "notional", "type", "time_in_force", "limit_price", "stop_price", "trail_price",
                 "trail_percent", "extended_hours", "client_order_id", "order_class", "take_profit_limit_price",
                 "stop_loss_stop_price", "stop_loss_limit_price", "advanced_instructions")
CAMPOS_TEXTO = ("qty", "notional", "limit_price", "stop_price", "trail_price", "trail_percent", "take_profit_limit_price",
                "stop_loss_stop_price", "stop_loss_limit_price")
# Una orden de acción lleva en la huella los campos de Alpaca más `cierre`; una de futuro, los de kemet-riesgo.
CAMPOS_HUELLA_ACCION = CAMPOS_ALPACA + ("cierre",)
VALIDEZ = {"day": "válida hoy", "gtc": "válida hasta cancelarla", "opg": "en la apertura", "cls": "en el cierre",
           "ioc": "inmediata o se cancela", "fok": "entera o nada"}
TIPO_FUTURO = {"stop": "orden stop a", "limite": "orden límite a", "limit": "orden límite a", "mercado": "a mercado, referencia", "market": "a mercado, referencia"}
PALABRAS_SI = ("sí", "si", "yes")
PALABRAS_LOTE = {"todas", "todos", "todo", "ambas", "ambos", "dos", "resto", "demás", "demas", "cada", "lote", "también", "tambien"}
PALABRAS_DUDA = {"no", "pero", "espera", "cancela", "cancelar", "para", "quizá", "quizás", "quiza", "quizas", "luego", "después",
                 "despues", "mañana", "salvo", "menos", "excepto", "mejor", "antes", "cuando", "si", "cambia", "cámbialo", "cambialo",
                 "mitad", "baja", "sube", "ni", "tampoco", "igual", "creo"}
BROKER = os.path.join("estado", "broker.json")
RIESGO = os.path.join("estado", "riesgo.json")


# ---------------------------------------------------------------- utilidades

def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _txt(v):
    """Un número como texto para Alpaca: 8 → "8", 393.1 → "393.1"."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        f = float(v)
        return str(int(f)) if f == int(f) else repr(f)
    return str(v)


def es_accion(orden):
    """Una orden de acción lleva "instrumento": "accion" o el formato de Alpaca (symbol, side); una de futuro, simbolo y contratos."""
    inst = str(orden.get("instrumento") or "").lower()
    if inst in ("accion", "acción", "futuro"):
        return inst != "futuro"
    return "symbol" in orden and "simbolo" not in orden


def huella(orden):
    """sha1 de 12 hex de los campos de la orden que importan para ponerla. Para un futuro es la misma función que
    kemet-riesgo/riesgo.py (los mismos campos, el mismo JSON); para una acción, los campos de place_stock_order más `cierre`."""
    campos = CAMPOS_HUELLA_ACCION if es_accion(orden) else CAMPOS_HUELLA
    core = {k: orden[k] for k in campos if k in orden and orden[k] is not None}
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def simbolo_de(orden):
    return str(orden.get("symbol") or orden.get("simbolo") or "?").strip().upper()


def lado_de(orden):
    """compra | venta, venga como venga (buy/sell o compra/venta)."""
    l = str(orden.get("side") or orden.get("lado") or "").strip().lower()
    return {"buy": "compra", "sell": "venta"}.get(l, l)


def cantidad_de(orden):
    if es_accion(orden):
        return _f(orden.get("qty"))
    n = orden.get("contratos")
    return float(n) if isinstance(n, (int, float)) and not isinstance(n, bool) else _f(n)


def plan_de(orden):
    p = orden.get("plan")
    return p if isinstance(p, dict) else {}


def por_que_de(orden):
    return orden.get("por_que") or orden.get("why") or ""


def entrada_alpaca(orden):
    """Los argumentos exactos de place_stock_order: nombres de Alpaca, números como texto. `por_que` y `plan` nunca se envían."""
    out = {}
    for k in CAMPOS_ALPACA:
        if k in orden and orden[k] is not None:
            out[k] = _txt(orden[k]) if k in CAMPOS_TEXTO else orden[k]
    return out


def es_bracket(orden):
    oc = str(orden.get("order_class") or "").lower()
    patas = orden.get("take_profit_limit_price") is not None or orden.get("stop_loss_stop_price") is not None
    return oc == "bracket" or (not oc and patas)


def precio_entrada(orden):
    """El precio desde el que se mide el riesgo: el límite si lo hay; si no, el precio del plan."""
    if es_accion(orden):
        if str(orden.get("type", "market")) == "limit" and _f(orden.get("limit_price")):
            return _f(orden["limit_price"])
        p = plan_de(orden)
        return _f(p.get("entrada")) or _f(p.get("entry")) or _f(p.get("precio")) or _f(orden.get("precio"))
    return _f(orden.get("precio"))


def stop_de(orden):
    if es_accion(orden):
        return _f(orden.get("stop_loss_stop_price")) or _f(plan_de(orden).get("stop"))
    return _f(orden.get("stop"))


def objetivo_de(orden):
    if es_accion(orden):
        return _f(orden.get("take_profit_limit_price")) or _f(plan_de(orden).get("objetivo"))
    return _f(orden.get("objetivo"))


def valor_punto(simbolo):
    """Dólares por punto y contrato (o por acción); None si no conoce el símbolo."""
    try:
        inst = comun.resolver(simbolo)
    except KemetError:
        return None, None
    s = str(simbolo).upper()
    if inst["tipo"] == "accion":
        return 1.0, inst
    return (inst["punto_micro"] if s == inst["micro"] else inst["punto_mini"]), inst


def perdida_al_stop(orden):
    """(dólares si el stop se llena justo en el stop, stop, riesgo en puntos) o (None, stop, None)."""
    stop = stop_de(orden)
    q = cantidad_de(orden)
    if not stop or not q:
        return None, stop, None
    dada = _f(orden.get("perdida_max_usd")) or _f(plan_de(orden).get("perdida_max_usd")) or _f(plan_de(orden).get("max_loss"))
    entrada = precio_entrada(orden)
    if entrada is None:
        return (round(dada, 2) if dada is not None else None), stop, None
    punto, inst = valor_punto(simbolo_de(orden))
    if punto is None:
        return (round(dada, 2) if dada is not None else None), stop, None
    riesgo = comun.al_tick(abs(entrada - stop), inst["tick"])
    return round(q * riesgo * punto, 2), stop, riesgo


# ---------------------------------------------------------------- el ticket en palabras llanas

def _p(v):
    return pts(float(v))


def partes_accion(orden):
    lado = lado_de(orden).upper()
    sim = simbolo_de(orden)
    tipo = str(orden.get("type", "market"))
    validez = VALIDEZ.get(str(orden.get("time_in_force", "day")), str(orden.get("time_in_force")))
    q = _txt(orden.get("qty")) if orden.get("qty") is not None else None
    if es_bracket(orden):
        como = ("límite %s" % _p(orden["limit_price"])) if tipo == "limit" and orden.get("limit_price") else "a mercado"
        partes = ["%s %s %s, %s, %s" % (lado, q, sim, como, validez)]
        if orden.get("stop_loss_stop_price") is not None:
            pata = "stop-loss %s" % _p(orden["stop_loss_stop_price"])
            if orden.get("stop_loss_limit_price") is not None:
                pata += " (límite %s)" % _p(orden["stop_loss_limit_price"])
            partes.append(pata)
        if orden.get("take_profit_limit_price") is not None:
            partes.append("take-profit %s" % _p(orden["take_profit_limit_price"]))
    else:
        if orden.get("notional") is not None:
            que = "%s de %s" % (usd(float(orden["notional"]), 2), sim)
        else:
            que = "%s acci%s de %s" % (q, "ón" if q == "1" else "ones", sim)
        if tipo == "limit":
            como = "orden límite a %s" % _p(orden.get("limit_price"))
        elif tipo == "stop":
            como = "orden stop a %s" % _p(orden.get("stop_price"))
        elif tipo == "stop_limit":
            como = "stop %s, límite %s" % (_p(orden.get("stop_price")), _p(orden.get("limit_price")))
        else:
            como = "a mercado"
        partes = ["%s %s, %s, %s" % (lado, que, como, validez)]
    if orden.get("cierre"):
        partes.append("cierre: solo saca de la posición")
    perdida, stop, riesgo = perdida_al_stop(orden)
    if perdida is not None and not orden.get("cierre"):
        partes.append("pérdida al stop unos %s si se llena justo en %s (en un mercado rápido se llena peor)" % (usd(perdida, 2), _p(stop)))
    return partes


def partes_futuro(orden):
    lado = lado_de(orden).upper()
    sim = simbolo_de(orden)
    n = orden.get("contratos")
    tipo = str(orden.get("tipo") or "stop").lower()
    precio = _f(orden.get("precio"))
    punto, inst = valor_punto(sim)
    nombre = ("%s, %s" % (sim, inst["nombre"])) if inst else sim
    como = TIPO_FUTURO.get(tipo, tipo)
    partes = ["%s %s %s, %s %s" % (lado, n, nombre, como, _p(precio) if precio is not None else "?")]
    if orden.get("cierre"):
        partes.append("cierre: solo saca de la posición")
    else:
        stop, objetivo = stop_de(orden), objetivo_de(orden)
        partes.append("stop %s, objetivo %s" % (_p(stop) if stop is not None else "ninguno", _p(objetivo) if objetivo is not None else "ninguno"))
        perdida, stop, riesgo = perdida_al_stop(orden)
        if perdida is not None:
            detalle = (" (%s pts × %s $/pt × %s)" % (pts(riesgo), num(punto, 0), n)) if riesgo is not None and punto else ""
            partes.append("pérdida al stop %s%s, si se llena justo en el stop" % (usd(perdida, 2), detalle))
    return partes


def partes(orden):
    return partes_accion(orden) if es_accion(orden) else partes_futuro(orden)


def llano(orden):
    """COMPRA 8 TSLA, a mercado, válida hoy / stop-loss 389,51 / take-profit 396,65 / pérdida al stop unos 28,56 $ …"""
    return " / ".join(partes(orden))


def cifras(orden):
    """Las cifras de la orden que una respuesta puede nombrar sin contradecirla."""
    out = []
    for v in (cantidad_de(orden), precio_entrada(orden), stop_de(orden), objetivo_de(orden), _f(orden.get("notional")),
              _f(orden.get("stop_loss_limit_price"))):
        if v is not None:
            out.append(float(v))
    perdida, _, _ = perdida_al_stop(orden)
    if perdida is not None:
        out.append(perdida)
    return out


def _numeros(texto):
    """Números de una respuesta, en formato español (28.426,25) o inglés (28426.25); los dos sentidos cuando hay duda."""
    out = []
    for m in re.findall(r"\d[\d.,]*", texto):
        s = m.strip(".,")
        if not s:
            continue
        cand = set()
        if "," in s and "." in s:
            cand.add(s.replace(".", "").replace(",", "."))
        elif "," in s:
            cand.add(s.replace(",", "."))
        elif "." in s:
            cand.add(s)
            cand.add(s.replace(".", ""))
        else:
            cand.add(s)
        for c in cand:
            v = _f(c)
            if v is not None:
                out.append(v)
    return out


def es_un_si(respuesta, orden, simbolos_del_lote=()):
    """¿La respuesta es un sí explícito para ESTA orden? Devuelve (vale, por qué)."""
    raw = (respuesta or "").strip()
    if not raw:
        return False, "la respuesta está vacía"
    if "?" in raw or "¿" in raw:
        return False, "la respuesta es una pregunta, no un sí"
    palabras = re.findall(r"[a-záéíóúüñ']+", raw.lower())
    if not palabras or palabras[0] not in PALABRAS_SI:
        return False, "solo cuenta una respuesta que empiece por «sí» (no vale ok, vale, adelante, hazlo)"
    if PALABRAS_LOTE & set(palabras):
        return False, "un sí cubre una orden, no un lote"
    if PALABRAS_DUDA & set(palabras[1:]):
        return False, "la respuesta lleva una condición o una duda; pregunta otra vez"
    sim = simbolo_de(orden)
    tokens = set(re.findall(r"[A-Z][A-Z.\-]{0,6}", raw.upper()))
    otros = {str(s).upper() for s in simbolos_del_lote} - {sim}
    nombrados = tokens & otros
    if nombrados:
        return False, "la respuesta nombra %s y esta orden es de %s" % (", ".join(sorted(nombrados)), sim)
    nums = _numeros(raw)
    if nums:
        quiere = cifras(orden)
        if not any(abs(n - w) < 0.005 for n in nums for w in quiere):
            return False, "la respuesta dice %s y esta orden es %s" % (", ".join(pts(n) for n in sorted(set(nums))), llano(orden))
    return True, "sí explícito para %s" % llano(orden)


# ---------------------------------------------------------------- estado

def cargar_config():
    return comun.leer_json("config.json", obligatorio=False) or {}


def cargar_estado():
    doc = comun.leer_json(comun.ruta(BROKER), obligatorio=False)
    if not doc or not isinstance(doc.get("ordenes"), list):
        return {"fecha": None, "ordenes": []}
    return doc


def guardar_estado(estado, fecha):
    estado["fecha"] = fecha
    return comun.escribir_json(comun.ruta(BROKER), estado)


def ultimo(estado, h, fecha):
    """El último apunte de hoy para esa huella, o None."""
    out = None
    for r in estado.get("ordenes", []):
        if r.get("huella") == h and str(r.get("fecha")) == fecha:
            out = r
    return out


def veredicto_de(riesgo, h, fecha):
    """(resultado de kemet-riesgo, por qué no) para esa huella hoy."""
    if not riesgo:
        return None, "sin comprobación de kemet-riesgo (ejecuta riesgo.py check)"
    if str(riesgo.get("fecha")) != fecha:
        return None, "la comprobación de riesgo es del %s, no de hoy: repite riesgo.py check" % riesgo.get("fecha")
    for r in riesgo.get("resultados", []):
        if r.get("huella") == h:
            return r, None
    return None, "esta orden exacta no está en la última comprobación (se editó o es nueva): repite riesgo.py check"


def estado_de(orden, riesgo, estado, fecha):
    """(lista, etiqueta, resultado de riesgo)."""
    h = huella(orden)
    rv, por_que = veredicto_de(riesgo, h, fecha)
    if rv is None:
        return False, "NO LISTA: " + por_que, None
    if rv.get("veredicto") != "PASS":
        return False, "BLOQUEADA por kemet-riesgo: " + "; ".join(rv.get("motivos", [])), rv
    rec = ultimo(estado, h, fecha)
    if rec:
        st = rec.get("estado")
        if st == "aprobada":
            return False, "APROBADA por ti a las %s NY, falta la llamada al conector (o apuntarla con registrar)" % rec.get("cuando"), rv
        return False, "HECHA: %s a las %s NY%s" % (st, rec.get("cuando"), (" (id %s)" % rec["id_broker"]) if rec.get("id_broker") else ""), rv
    return True, "LISTA: PASS de kemet-riesgo hoy, falta tu sí", rv


# ---------------------------------------------------------------- render

def cabecera(i, total, cfg, orden):
    papel = cfg.get("papel", True)
    cuenta = "cuenta PAPEL" if papel else "CUENTA REAL, DINERO DE VERDAD"
    via = "Alpaca" if es_accion(orden) else "futuros, a mano en tu plataforma"
    return "ORDEN %d de %d, %s, %s" % (i, total, cuenta, via)


def render(orden, i, total, cfg, riesgo, estado, fecha):
    lista, etiqueta, rv = estado_de(orden, riesgo, estado, fecha)
    lineas = [cabecera(i, total, cfg, orden)]
    for p in partes(orden):
        lineas.append("  " + p)
    if por_que_de(orden):
        lineas.append("  por qué: " + por_que_de(orden))
    lineas.append("  huella " + huella(orden))
    lineas.append("  " + etiqueta)
    for w in (rv or {}).get("avisos", []):
        lineas.append("  aviso: " + w)
    if es_accion(orden):
        lineas.append("  Claude llamará a place_stock_order exactamente con:")
        for l in json.dumps(entrada_alpaca(orden), indent=2, ensure_ascii=False).splitlines():
            lineas.append("    " + l)
        if es_bracket(orden):
            lineas.append("  Alpaca pone la entrada y después el stop-loss y el take-profit como dos órdenes que se anulan entre sí:")
            lineas.append("  cuando una se llena, la otra se cancela.")
        if lista:
            lineas.append("  Responde «sí» para poner esta orden, o «no» para dejarla pasar.")
            lineas.append("  La tarjeta de Claude vuelve a preguntar: Permitir una vez la pone, Denegar la para.")
    else:
        lineas.append("  No hay conector gratuito de futuros: esta orden la pones tú en tu plataforma, con su stop puesto antes de confirmar.")
        if lista:
            lineas.append("  Cuando esté puesta: riesgo.py registrar --abrir, y broker.py registrar --huella %s --precio PRECIO_DE_FILL." % huella(orden))
    return "\n".join(lineas), lista


def ticket_json(orden, i, cfg, riesgo, estado, fecha):
    lista, etiqueta, rv = estado_de(orden, riesgo, estado, fecha)
    perdida, stop, riesgo_pts = perdida_al_stop(orden)
    accion = es_accion(orden)
    return {"indice": i, "lista": lista, "estado": etiqueta, "llano": llano(orden), "huella": huella(orden),
            "instrumento": "accion" if accion else "futuro", "papel": bool(cfg.get("papel", True)),
            "herramienta": "place_stock_order" if accion else None, "entrada_herramienta": entrada_alpaca(orden) if accion else None,
            "a_mano": not accion, "por_que": por_que_de(orden), "bracket": es_bracket(orden) if accion else None,
            "perdida_al_stop": perdida, "stop": stop, "riesgo_pts": riesgo_pts, "cierre": bool(orden.get("cierre"))}


# ---------------------------------------------------------------- fills → cartera

def leer_cartera(cfg, crear=True):
    pf = comun.leer_json("portfolio.json", obligatorio=False)
    if pf is None:
        if not crear:
            return None
        presupuesto = _f(cfg.get("presupuesto"))
        pf = {"efectivo": round(presupuesto, 2) if presupuesto is not None else None, "posiciones": []}
    pf.setdefault("posiciones", [])
    return pf


def posicion(pf, simbolo):
    for p in pf.get("posiciones", []):
        if str(p.get("simbolo") or p.get("ticker") or "").upper() == simbolo:
            return p
    return None


def aplicar_fill(cfg, simbolo, lado, cantidad, precio, accion, cuando):
    """Apunta un fill en kemet/portfolio.json. Acciones: efectivo y posición con precio medio. Futuros: solo la posición
    (contratos con signo, compra suma y venta resta); el efectivo no se toca, el margen lo lleva tu plataforma."""
    pf = leer_cartera(cfg)
    simbolo = simbolo.upper()
    cantidad, precio = float(cantidad), float(precio)
    if cantidad <= 0 or precio <= 0:
        raise KemetError("un fill necesita cantidad y precio mayores que 0")
    pos = posicion(pf, simbolo)
    if accion:
        if pf.get("efectivo") is None:
            raise KemetError("no hay kemet/portfolio.json ni `presupuesto` en kemet/config.json para arrancar la cartera (tamano.py config --propia)")
        coste = round(cantidad * precio, 2)
        if lado == "compra":
            if pos is None:
                pos = {"simbolo": simbolo, "cantidad": 0.0, "precio_medio": precio, "instrumento": "accion"}
                pf["posiciones"].append(pos)
            total = float(pos.get("cantidad") or 0) * float(pos.get("precio_medio") or 0) + coste
            pos["cantidad"] = round(float(pos.get("cantidad") or 0) + cantidad, 6)
            pos["precio_medio"] = round(total / pos["cantidad"], 4)
            pf["efectivo"] = round(float(pf["efectivo"]) - coste, 2)
        else:
            tiene = float(pos.get("cantidad") or 0) if pos else 0.0
            if tiene + 1e-9 < cantidad:
                raise KemetError("no puedo apuntar la venta de %s %s: la cartera tiene %s (un corto necesita permitir_cortos y no lo lleva este pack)"
                                 % (_txt(cantidad), simbolo, _txt(tiene)))
            pos["cantidad"] = round(tiene - cantidad, 6)
            if pos["cantidad"] <= 1e-9:
                pf["posiciones"].remove(pos)
            pf["efectivo"] = round(float(pf["efectivo"]) + coste, 2)
    else:
        signo = 1.0 if lado == "compra" else -1.0
        if pos is None:
            pos = {"simbolo": simbolo, "cantidad": 0.0, "precio_medio": precio, "instrumento": "futuro"}
            pf["posiciones"].append(pos)
        antes = float(pos.get("cantidad") or 0)
        despues = round(antes + signo * cantidad, 6)
        if antes == 0 or (antes > 0) == (signo > 0):
            total = abs(antes) * float(pos.get("precio_medio") or 0) + cantidad * precio
            pos["precio_medio"] = round(total / (abs(antes) + cantidad), 4)
        elif (despues > 0) != (antes > 0) and despues != 0:
            pos["precio_medio"] = precio          # dio la vuelta: la nueva posición empieza en este precio
        pos["cantidad"] = despues
        if abs(despues) <= 1e-9:
            pf["posiciones"].remove(pos)
    pf["actualizado"] = cuando
    comun.escribir_json("portfolio.json", pf)
    return pf


# ---------------------------------------------------------------- subcomandos

def _reloj(a):
    ahora = comun.parse_ahora(getattr(a, "ahora", None))
    ny = comun.a_ny(ahora)
    return ahora, ny.date().isoformat(), comun.hhmm(ny)


def _ordenes(a):
    doc = comun.leer_json(comun.dada(getattr(a, "orden", None)) or "orden.json", "ejecuta tamano.py orden --escribir, o broker.py plano")
    ordenes = doc.get("ordenes") if isinstance(doc, dict) else doc
    if not isinstance(ordenes, list) or not ordenes:
        raise KemetError("no hay órdenes en %s" % (getattr(a, "orden", None) or comun.ruta("orden.json")))
    return ordenes


def _cargar(a):
    ordenes = _ordenes(a)
    cfg = cargar_config()
    riesgo = comun.leer_json(comun.ruta(RIESGO), obligatorio=False)
    estado = cargar_estado()
    ahora, fecha, hora = _reloj(a)
    return ordenes, cfg, riesgo, estado, ahora, fecha, hora


def _elegir(ordenes, indice=None, h=None):
    if h:
        for o in ordenes:
            if huella(o) == h:
                return o
        raise KemetError("ninguna orden de kemet/orden.json tiene la huella %s (mira broker.py mostrar)" % h)
    if indice is None:
        raise KemetError("di qué orden: --huella H o --indice N")
    if not 1 <= indice <= len(ordenes):
        raise KemetError("no hay orden %d (hay %d)" % (indice, len(ordenes)))
    return ordenes[indice - 1]


def cmd_mostrar(a):
    ordenes, cfg, riesgo, estado, ahora, fecha, hora = _cargar(a)
    if a.indice or a.huella:
        o = _elegir(ordenes, a.indice, a.huella)
        elegidas = [(ordenes.index(o) + 1, o)]
    else:
        elegidas = list(enumerate(ordenes, 1))
    if a.json:
        out = [ticket_json(o, i, cfg, riesgo, estado, fecha) for i, o in elegidas]
        print(json.dumps(out[0] if (a.indice or a.huella) else out, ensure_ascii=False, indent=1))
        return 0 if any(t["lista"] for t in out) else 1
    bloques, alguna = [], False
    for i, o in elegidas:
        texto, lista = render(o, i, len(ordenes), cfg, riesgo, estado, fecha)
        bloques.append(texto)
        alguna = alguna or lista
    print("TICKET %s · %s" % (fecha, comun.hora_doble(ahora)))
    print("\n\n".join(bloques))
    print("\nUna orden cada vez: un sí cubre un ticket, nunca el lote. Contenido educativo, no asesoramiento financiero.")
    return 0 if alguna else 1


def cmd_aprobar(a):
    ordenes, cfg, riesgo, estado, ahora, fecha, hora = _cargar(a)
    o = _elegir(ordenes, a.indice, a.huella)
    lista, etiqueta, rv = estado_de(o, riesgo, estado, fecha)
    if not lista:
        raise KemetError("la orden %s no está lista: %s" % (huella(o), etiqueta))
    vale, por_que = es_un_si(a.respuesta, o, [simbolo_de(x) for x in ordenes])
    if not vale:
        print("No apuntado: %s. Vuelve a enseñar el ticket %s al usuario y pregunta otra vez." % (por_que, huella(o)))
        return 1
    perdida, stop, _ = perdida_al_stop(o)
    estado.setdefault("ordenes", []).append({
        "fecha": fecha, "cuando": hora, "huella": huella(o), "simbolo": simbolo_de(o), "lado": lado_de(o), "cantidad": _txt(cantidad_de(o) or 0),
        "instrumento": "accion" if es_accion(o) else "futuro", "clase": (rv or {}).get("clase") or ("cierre" if o.get("cierre") else "entrada"),
        "perdida_al_stop": perdida, "stop": stop, "llano": llano(o), "estado": "aprobada", "respuesta": a.respuesta,
        "papel": bool(cfg.get("papel", True))})
    guardar_estado(estado, fecha)
    print("Apuntado tu sí para %s: %s." % (huella(o), llano(o)))
    if es_accion(o):
        print("Ahora llama a place_stock_order exactamente con:")
        print(json.dumps(entrada_alpaca(o), indent=2, ensure_ascii=False))
        print("La tarjeta de Claude dice Permitir una vez o Denegar. Después: broker.py registrar --huella %s --id-broker ID --precio PRECIO" % huella(o))
    else:
        print("Ponla tú en tu plataforma, con el stop puesto antes de confirmar. Después: riesgo.py registrar --abrir y broker.py registrar --huella %s --precio PRECIO" % huella(o))
    return 0


def cmd_rechazar(a):
    ordenes, cfg, riesgo, estado, ahora, fecha, hora = _cargar(a)
    o = _elegir(ordenes, a.indice, a.huella)
    estado.setdefault("ordenes", []).append({
        "fecha": fecha, "cuando": hora, "huella": huella(o), "simbolo": simbolo_de(o), "lado": lado_de(o), "cantidad": _txt(cantidad_de(o) or 0),
        "instrumento": "accion" if es_accion(o) else "futuro", "llano": llano(o), "estado": "rechazada", "respuesta": a.respuesta or "no"})
    guardar_estado(estado, fecha)
    print("Apuntado: dijiste no a %s (%s). No se envió nada." % (huella(o), llano(o)))
    return 0


def _buscar_orden(h, riesgo, estado, fecha):
    """La orden de esa huella: en kemet/orden.json, si no en la última comprobación de riesgo, si no en lo aprobado hoy."""
    doc = comun.leer_json("orden.json", obligatorio=False)
    ordenes = (doc.get("ordenes") if isinstance(doc, dict) else doc) or []
    for o in ordenes:
        if isinstance(o, dict) and huella(o) == h:
            return o
    for r in (riesgo or {}).get("resultados", []):
        if r.get("huella") == h and isinstance(r.get("orden"), dict):
            return r["orden"]
    rec = ultimo(estado, h, fecha)
    if rec:
        return {"_apunte": rec}
    raise KemetError("no encuentro una orden con la huella %s en kemet/orden.json ni en la última comprobación de riesgo" % h)


def cmd_registrar(a):
    ahora, fecha, hora = _reloj(a)
    cfg = cargar_config()
    riesgo = comun.leer_json(comun.ruta(RIESGO), obligatorio=False)
    estado = cargar_estado()
    if not a.huella:
        return _registrar_suelto(a, cfg, estado, ahora, fecha, hora)
    o = _buscar_orden(a.huella, riesgo, estado, fecha)
    if "_apunte" in o:
        ap = o["_apunte"]
        simbolo, lado, accion, cantidad_orden, texto = ap["simbolo"], ap["lado"], ap.get("instrumento") != "futuro", _f(ap.get("cantidad")), ap.get("llano", "")
        perdida, stop = ap.get("perdida_al_stop"), ap.get("stop")
    else:
        simbolo, lado, accion, cantidad_orden, texto = simbolo_de(o), lado_de(o), es_accion(o), cantidad_de(o), llano(o)
        perdida, stop, _ = perdida_al_stop(o)
    previo = ultimo(estado, a.huella, fecha)
    avisos = []
    if not previo or previo.get("estado") != "aprobada":
        avisos.append("no hay un sí apuntado hoy para esta huella (broker.py aprobar); lo apunto igual porque ya pasó")
    rec = {"fecha": fecha, "cuando": hora, "huella": a.huella, "simbolo": simbolo, "lado": lado, "cantidad": _txt(cantidad_orden or 0),
           "instrumento": "accion" if accion else "futuro", "llano": texto, "estado": a.estado, "perdida_al_stop": perdida, "stop": stop}
    if a.nota:
        rec["nota"] = a.nota
    if a.estado != "colocada":
        estado.setdefault("ordenes", []).append(rec)
        guardar_estado(estado, fecha)
        for w in avisos:
            print("AVISO: " + w)
        print("Apuntada %s como %s. Nada en la cartera cambia. Una orden fallida no se repite sin otro check y otro sí." % (a.huella, a.estado))
        return 0
    if a.precio is None:
        raise KemetError("una orden colocada necesita --precio (el del fill, de la respuesta del conector o de get_open_position)")
    if accion and not a.id_broker:
        raise KemetError("una orden colocada en Alpaca necesita --id-broker (el id de la respuesta de place_stock_order)")
    cantidad = _f(a.cantidad) if a.cantidad is not None else cantidad_orden
    if not cantidad or cantidad <= 0:
        raise KemetError("no sé cuántas van: pasa --cantidad")
    rec["id_broker"] = a.id_broker or "a mano"
    rec["precio"] = float(a.precio)
    rec["cantidad"] = _txt(cantidad)
    estado.setdefault("ordenes", []).append(rec)
    guardar_estado(estado, fecha)
    pf = aplicar_fill(cfg, simbolo, lado, cantidad, a.precio, accion, comun.iso(ahora))
    for w in avisos:
        print("AVISO: " + w)
    print("Apuntada a las %s NY: %s %s %s a %s, id %s (huella %s)." % (hora, lado, _txt(cantidad), simbolo, pts(float(a.precio)), rec["id_broker"], a.huella))
    pos = posicion(pf, simbolo)
    if accion:
        tiene = ("%s acciones a %s de media" % (_txt(pos["cantidad"]), pts(pos["precio_medio"]))) if pos else "sin posición"
        print("Cartera: efectivo %s, %s: %s." % (usd(pf["efectivo"], 2), simbolo, tiene))
    else:
        tiene = ("%s contratos a %s de media" % (_txt(pos["cantidad"]), pts(pos["precio_medio"]))) if pos else "plano"
        print("Cartera: %s %s. El efectivo no se toca en futuros: el margen lo lleva tu plataforma." % (simbolo, tiene))
    print("Apuntado en %s y %s." % (comun.ruta(BROKER), comun.ruta("portfolio.json")))
    return 0


def _registrar_suelto(a, cfg, estado, ahora, fecha, hora):
    """Un fill que no viene de un ticket: la pata de la bracket que se llenó en el bróker, o un cierre hecho a mano.
    Se apunta como `llenada` (clase cierre) y pasa a la cartera."""
    if not (a.simbolo and a.lado and a.cantidad is not None and a.precio is not None):
        raise KemetError("sin --huella necesito --simbolo, --lado compra|venta, --cantidad y --precio (la pata que se llenó, o un cierre a mano)")
    sim = a.simbolo.strip().upper()
    lado = {"buy": "compra", "sell": "venta"}.get(a.lado.strip().lower(), a.lado.strip().lower())
    if lado not in ("compra", "venta"):
        raise KemetError("--lado tiene que ser compra o venta, no %r" % a.lado)
    accion = comun.resolver(sim)["tipo"] == "accion"
    cantidad = _f(a.cantidad)
    if not cantidad or cantidad <= 0:
        raise KemetError("--cantidad tiene que ser mayor que 0")
    texto = "%s %s %s a %s" % (lado.upper(), _txt(cantidad), sim, pts(float(a.precio)))
    rec = {"fecha": fecha, "cuando": hora, "huella": None, "simbolo": sim, "lado": lado, "cantidad": _txt(cantidad),
           "instrumento": "accion" if accion else "futuro", "clase": "cierre", "llano": texto, "estado": "llenada",
           "id_broker": a.id_broker or "a mano", "precio": float(a.precio)}
    if a.nota:
        rec["nota"] = a.nota
    estado.setdefault("ordenes", []).append(rec)
    guardar_estado(estado, fecha)
    pf = aplicar_fill(cfg, sim, lado, cantidad, a.precio, accion, comun.iso(ahora))
    pos = posicion(pf, sim)
    print("Apuntado el fill de las %s NY: %s, id %s." % (hora, texto, rec["id_broker"]))
    if accion:
        tiene = ("%s acciones a %s de media" % (_txt(pos["cantidad"]), pts(pos["precio_medio"]))) if pos else "sin posición"
        print("Cartera: efectivo %s, %s: %s." % (usd(pf["efectivo"], 2), sim, tiene))
    else:
        tiene = ("%s contratos a %s de media" % (_txt(pos["cantidad"]), pts(pos["precio_medio"]))) if pos else "plano"
        print("Cartera: %s %s." % (sim, tiene))
    return 0


def cmd_plano(a):
    ahora, fecha, hora = _reloj(a)
    cfg = cargar_config()
    sim = a.simbolo.strip().upper()
    inst = comun.resolver(sim)
    accion = inst["tipo"] == "accion"
    pf = leer_cartera(cfg, crear=False) or {}
    pos = posicion(pf, sim)
    origen = "kemet/portfolio.json"
    if a.cantidad is not None:
        cantidad = _f(a.cantidad)
        if cantidad is None or cantidad == 0:
            raise KemetError("--cantidad quiere lo que tienes, por ejemplo --cantidad 8 (negativo si estás corto en un futuro)")
        origen = "--cantidad"
    else:
        cantidad = float(pos.get("cantidad") or 0) if pos else 0.0
        if abs(cantidad) <= 1e-9:
            raise KemetError("nada que cerrar: no hay %s en %s. Mira tu bróker (get_open_position %s en Alpaca, o tu plataforma) y pasa --cantidad si sí tienes"
                             % (sim, comun.ruta("portfolio.json"), sim))
    plano_a = cfg.get("plano_a") or inst["plano"]
    por_que = "plano a las %s NY: cierra la posición de %s antes del cierre (cantidad de %s)" % (plano_a, sim, origen)
    if accion:
        if cantidad < 0:
            raise KemetError("la cartera tiene %s en negativo y este pack no lleva cortos en acciones: compruébalo en el bróker" % sim)
        orden = {"instrumento": "accion", "symbol": sim, "side": "sell", "qty": _txt(cantidad), "type": "market", "time_in_force": "day",
                 "cierre": True, "por_que": por_que}
    else:
        precio = _f(a.precio)
        if precio is None:
            precios = comun.leer_json("precios.json", obligatorio=False) or {}
            for clave in (sim, inst["codigo"], inst["yahoo"]):
                v = precios.get(clave) if isinstance(precios, dict) else None
                if isinstance(v, dict):
                    v = v.get("ultimo") or v.get("precio") or v.get("price")
                if _f(v):
                    precio = _f(v)
                    break
        if precio is None:
            precio = _f(pos.get("precio_medio")) if pos else None
            if precio is None:
                raise KemetError("para un futuro necesito un precio de referencia: --precio")
            print("AVISO: sin precio actual en kemet/precios.json, uso el precio medio de la posición (%s) como referencia; pasa --precio si quieres el de ahora" % pts(precio))
        orden = {"instrumento": "futuro", "simbolo": sim, "lado": "venta" if cantidad > 0 else "compra", "contratos": int(round(abs(cantidad))),
                 "tipo": "mercado", "precio": precio, "cierre": True, "por_que": por_que}
    viejo = comun.leer_json("orden.json", obligatorio=False)
    sustituidas = len(viejo.get("ordenes", [])) if isinstance(viejo, dict) else 0
    doc = {"generado": comun.iso(ahora), "origen": "broker.py plano %s el %s" % (sim, fecha), "ordenes": [orden],
           "cuenta": cfg.get("cuenta_nombre"), "papel": bool(cfg.get("papel", True)),
           "nota": "Orden de cierre. No se pone nada hasta que kemet-riesgo la pase y el usuario diga sí en el chat."}
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    p = comun.escribir_json("orden.json", doc)
    if not a.json:
        print("Plano %s: %s (plano a las %s NY)." % (sim, llano(orden), plano_a))
        print("Escrita en %s%s." % (p, (" (sustituye %d propuesta%s anterior%s)" % (sustituidas, "" if sustituidas == 1 else "s", "" if sustituidas == 1 else "es")) if sustituidas else ""))
        if a.cantidad is None:
            print("La cantidad sale de %s: compárala con %s antes de decir sí." % (origen, "get_open_position %s" % sim if accion else "tu plataforma"))
        print("Siguiente:")
        print("  1. kemet-riesgo: riesgo.py check. Un cierre nunca se bloquea por los límites del día ni por el horario de entradas.")
        print("  2. broker.py mostrar, y el sí del usuario para esta orden.")
        if accion:
            print("  3. Si el stop-loss y el take-profit del bracket siguen abiertos, Alpaca retiene esas acciones y rechaza otra venta.")
            print("     Cancélalos antes: get_orders (status open, nested true) y cancel_order_by_id por cada pata (Necesita aprobación).")
            print("     Después place_stock_order con el ticket, y broker.py registrar.")
        else:
            print("  3. En la plataforma: cierra la posición y cancela el stop y el objetivo que queden. Después riesgo.py registrar --resultado y broker.py registrar.")
    return 0


def cmd_hoy(a):
    estado = cargar_estado()
    ahora, fecha, hora = _reloj(a)
    filas = [r for r in estado.get("ordenes", []) if a.todo or str(r.get("fecha")) == fecha]
    if not filas:
        print("Nada apuntado%s." % ("" if a.todo else " hoy"))
        return 1
    for r in filas:
        extra = (" id " + str(r["id_broker"])) if r.get("id_broker") else ""
        precio = (" a %s" % pts(float(r["precio"]))) if r.get("precio") is not None else ""
        resp = (' respuesta "%s"' % r["respuesta"]) if r.get("respuesta") and r["estado"] in ("aprobada", "rechazada") else ""
        print("%s %s  %-9s %s%s%s%s" % (r.get("fecha"), r.get("cuando"), r.get("estado"), r.get("llano"), precio, resp, extra))
    colocadas = sum(1 for r in filas if r.get("estado") == "colocada")
    print("%d colocada%s%s." % (colocadas, "" if colocadas == 1 else "s", "" if a.todo else " hoy"))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="El ticket de cada orden y tu sí (kemet-broker). No pone órdenes.")
    sub = ap.add_subparsers(dest="cmd")

    def reloj(p):
        p.add_argument("--ahora", help="hora de Nueva York, AAAA-MM-DD HH:MM")

    def cual(p):
        p.add_argument("--huella", help="la huella de la orden (la imprime mostrar)")
        p.add_argument("--indice", type=int, help="o su número en kemet/orden.json")

    p = sub.add_parser("mostrar", help="los tickets")
    p.add_argument("--orden", help="otro archivo de órdenes (por defecto kemet/orden.json)")
    cual(p)
    reloj(p)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("aprobar", help="apunta el sí explícito del usuario para una orden")
    p.add_argument("--orden")
    cual(p)
    p.add_argument("--respuesta", required=True, help="la respuesta del usuario, palabra por palabra")
    reloj(p)
    p = sub.add_parser("rechazar", help="apunta un no")
    p.add_argument("--orden")
    cual(p)
    p.add_argument("--respuesta")
    reloj(p)
    p = sub.add_parser("registrar", help="apunta lo que pasó: colocada (con id y precio), denegada o fallida; sin --huella, un fill suelto")
    p.add_argument("--huella", help="la huella del ticket; sin ella, --simbolo --lado --cantidad --precio (la pata de la bracket que se llenó)")
    p.add_argument("--simbolo")
    p.add_argument("--lado", help="compra | venta")
    p.add_argument("--estado", choices=["colocada", "denegada", "fallida"], default="colocada")
    p.add_argument("--id-broker", dest="id_broker", help="el id de la orden en el bróker")
    p.add_argument("--precio", type=float, help="precio del fill")
    p.add_argument("--cantidad", help="cantidad llenada (por defecto la de la orden)")
    p.add_argument("--nota")
    reloj(p)
    p = sub.add_parser("plano", help="la orden que cierra la posición de un símbolo, en kemet/orden.json")
    p.add_argument("--simbolo", required=True)
    p.add_argument("--cantidad", help="lo que tienes (por defecto lo de kemet/portfolio.json)")
    p.add_argument("--precio", help="(futuros) precio de referencia para la orden de cierre")
    reloj(p)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("hoy", help="lo apuntado hoy")
    p.add_argument("--todo", action="store_true", help="todos los días")
    reloj(p)
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    try:
        return {"mostrar": cmd_mostrar, "aprobar": cmd_aprobar, "rechazar": cmd_rechazar, "registrar": cmd_registrar,
                "plano": cmd_plano, "hoy": cmd_hoy}[a.cmd](a)
    except KemetError as e:
        print("broker.py: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
