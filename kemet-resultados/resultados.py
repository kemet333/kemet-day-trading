#!/usr/bin/env python3
"""Los resultados que una empresa presentó en la SEC, trimestre a trimestre, en español.

    python3 resultados.py TSLA                                   # los últimos 6 trimestres
    python3 resultados.py AAPL KO --trimestres 8                 # dos años, varias empresas
    python3 resultados.py TSLA --escribir                        # y guarda kemet/resultados.json
    python3 resultados.py AAPL NVDA --metricas kemet/metricas.json   # una fila por empresa para tus notas
    python3 resultados.py AAPL --offline tests/fixtures/kemet-resultados --json

Lee los datos XBRL que la empresa etiquetó en sus 10-Q y 10-K (la API "companyfacts" de EDGAR) y los pone en
fila: ingresos, beneficio bruto, resultado operativo, beneficio neto, BPA diluido y, si la empresa lo etiqueta,
flujo de caja operativo; cada trimestre frente al mismo trimestre del año anterior; los últimos cuatro
trimestres sumados. De la lista de presentaciones saca el último 10-Q o 10-K, el último 8-K de resultados
(punto 2.02) con su nota de prensa (anexo EX-99) y una estimación de cuándo toca el próximo informe.

Fuentes (SEC; exige un User-Agent con tu nombre y correo, de `sec_user_agent` en kemet/config.json, de la
variable SEC_USER_AGENT o de --user-agent):
  https://www.sec.gov/files/company_tickers.json              ticker a CIK
  https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
  https://data.sec.gov/submissions/CIK##########.json          presentaciones
  https://www.sec.gov/Archives/edgar/data/<cik>/<accesion>/index.json

Cómo se montan los trimestres:
  - Un trimestre es un valor que cubre unos tres meses (de 80 a 100 días). Si un periodo se presentó más de
    una vez (un 10-Q posterior lo repite como comparación), manda la presentación más reciente, así que las
    reexpresiones cuentan. La etiqueta fiscal (T1 2026) es la de la primera presentación.
  - No hay 10-Q del cuarto trimestre. El cuarto es el año del 10-K menos los tres trimestres de dentro, y va
    marcado como «derivado». El BPA derivado es aproximado: el número de acciones cambia durante el año.
  - El flujo de caja operativo se presenta acumulado en el año; el del trimestre es la diferencia con el
    acumulado anterior.
  - Los ingresos salen del primer concepto que use la empresa de una lista (RevenueFromContractWithCustomer...,
    Revenues, ...). Bancos y aseguradoras los presentan de otra forma: sus márgenes pueden quedar en blanco.

Sin red: --offline CARPETA lee company_tickers.json, companyfacts-CIK##########.json,
submissions-CIK##########.json y <accesion>/index.json de esa carpeta (los tests lo usan).

Solo números: esta herramienta nunca dice si una acción es compra o venta.
Código de salida 0 si todo salió, 1 si alguna empresa falló y otra no, 2 si hay un error.
"""
import argparse
import datetime as dt
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

import comun
from comun import KemetError

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK%s.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK%s.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/%d/%s/"
FUENTE = "SEC EDGAR, XBRL companyfacts y submissions"
MARCADORES = ("correo@ejemplo.com", "you@example.com", "nombre apellido")
SIN_UA = ("EDGAR exige un User-Agent con tu nombre y correo: pon \"sec_user_agent\": \"Nombre Apellido correo@dominio.com\" "
          "en kemet/config.json, exporta SEC_USER_AGENT o pasa --user-agent, y repite")
INFORMES = ("10-Q", "10-K", "20-F", "40-F")
TRIMESTRE_DIAS = 91

CONCEPTOS = {
    "ingresos": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "RevenuesNetOfInterestExpense",
                 "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet", "SalesRevenueGoodsNet", "SalesRevenueServicesNet"],
    "coste_ingresos": ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"],
    "beneficio_bruto": ["GrossProfit"],
    "resultado_operativo": ["OperatingIncomeLoss"],
    "beneficio_neto": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "bpa_diluido": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"],
    "flujo_caja_operativo": ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
}
ACUMULADOS = ("flujo_caja_operativo",)      # conceptos que las empresas presentan acumulados en el año
UNIDAD = {"bpa_diluido": "USD/shares"}


# ---------------------------------------------------------------- EDGAR

def user_agent(cli=None):
    """El User-Agent para la SEC: --user-agent, SEC_USER_AGENT o `sec_user_agent` de kemet/config.json. None si no vale."""
    ua = (cli or os.environ.get("SEC_USER_AGENT") or "").strip()
    if not ua:
        cfg = comun.leer_json("config.json", obligatorio=False) or {}
        ua = str(cfg.get("sec_user_agent") or "").strip()
    if not ua or "@" not in ua or any(m in ua.lower() for m in MARCADORES):
        return None
    return ua


class Edgar(object):
    """GET con pausa (la SEC corta por encima de 10 peticiones por segundo) o lectura de una carpeta guardada."""

    def __init__(self, ua=None, offline=None, pausa=0.15):
        self.ua, self.offline, self.pausa, self._ultima = ua, offline, pausa, 0.0

    def json(self, url, nombre):
        if self.offline:
            ruta = os.path.join(self.offline, nombre)
            if not os.path.isfile(ruta):
                raise KemetError("sin red: no existe %s" % ruta)
            with open(ruta, encoding="utf-8") as fh:
                return json.load(fh)
        if not self.ua:
            raise KemetError(SIN_UA)
        hueco = time.time() - self._ultima
        if hueco < self.pausa:
            time.sleep(self.pausa - hueco)
        self._ultima = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": self.ua, "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                datos = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    datos = gzip.decompress(datos)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise KemetError("la SEC no tiene datos en %s (sin presentaciones XBRL para ese CIK)" % url)
            if e.code == 403:
                raise KemetError("la SEC rechazó la petición (HTTP 403): revisa el User-Agent, tiene que llevar nombre y correo")
            raise KemetError("la SEC respondió HTTP %s en %s" % (e.code, url))
        except urllib.error.URLError as e:
            raise KemetError("no llego a %s: %s" % (url, e.reason))
        try:
            return json.loads(datos.decode("utf-8"))
        except ValueError:
            raise KemetError("la SEC devolvió algo que no es JSON en %s" % url)


def limpiar_titulo(titulo):
    return re.sub(r"\s*/[A-Z]{2,5}/?\s*$", "", titulo or "").strip() or None


def ciks_por_ticker(edgar):
    """ticker -> (CIK de 10 dígitos, nombre) desde company_tickers.json."""
    datos = edgar.json(TICKERS_URL, "company_tickers.json")
    out = {}
    for v in datos.values():
        out.setdefault(str(v["ticker"]).upper().replace("-", "."), (str(v["cik_str"]).zfill(10), limpiar_titulo(v.get("title"))))
    return out


# ---------------------------------------------------------------- los hechos XBRL

def _fecha(s):
    return dt.date.fromisoformat(s)


def hechos(companyfacts, concepto, unidad=None):
    """Los hechos de un concepto us-gaap (USD, o USD/shares para el BPA)."""
    nodo = companyfacts.get("facts", {}).get("us-gaap", {}).get(concepto)
    if not nodo:
        return []
    unidades = nodo.get("units", {})
    u = unidad if unidad in unidades else next(iter(unidades), None)
    return unidades.get(u, []) if u else []


def periodos(hechos_):
    """{(inicio, fin): hecho} de los hechos con duración presentados en 10-Q/10-K. El valor es el de la presentación
    más reciente (manda la reexpresión); la etiqueta fiscal (fy, fp), la de la primera que presentó el periodo."""
    ultimo, primero = {}, {}
    for f in hechos_:
        if "start" not in f or str(f.get("form", "")).split("/")[0] not in INFORMES:
            continue
        clave = (f["start"], f["end"])
        sello = (f.get("filed", ""), f.get("accn", ""))
        if clave not in ultimo or sello > (ultimo[clave].get("filed", ""), ultimo[clave].get("accn", "")):
            ultimo[clave] = f
        if clave not in primero or sello < (primero[clave].get("filed", ""), primero[clave].get("accn", "")):
            primero[clave] = f
    out = {}
    for clave, f in ultimo.items():
        g = dict(f)
        g["fy"], g["fp"] = primero[clave].get("fy"), primero[clave].get("fp")
        out[clave] = g
    return out


def _fila(f, inicio, fin, valor, derivado, fp=None):
    return {"valor": valor, "inicio": inicio, "fin": fin, "derivado": derivado, "fy": f.get("fy"), "fp": fp or f.get("fp"),
            "formulario": f.get("form"), "presentado": f.get("filed")}


def trimestral(hechos_, derivar_t4=True):
    """{fin: {"valor", "inicio", "fin", "derivado", "fy", "fp", "formulario", "presentado"}} con valores de tres meses."""
    per = periodos(hechos_)
    q, anios = {}, []
    for (inicio, fin), f in per.items():
        dias = (_fecha(fin) - _fecha(inicio)).days
        if 80 <= dias <= 100:
            q[fin] = _fila(f, inicio, fin, f["val"], False)
        elif 350 <= dias <= 380:
            anios.append((inicio, fin, f))
    if derivar_t4:
        for inicio, fin, f in anios:
            if fin in q:
                continue
            dentro = sorted((v for v in q.values() if v["inicio"] >= inicio and v["fin"] < fin), key=lambda v: v["fin"])
            if len(dentro) != 3:
                continue
            arranque = (_fecha(dentro[-1]["fin"]) + dt.timedelta(days=1)).isoformat()
            q[fin] = _fila(f, arranque, fin, f["val"] - sum(v["valor"] for v in dentro), True, fp="Q4")
    return q


def trimestral_acumulado(hechos_):
    """Para conceptos presentados acumulados en el año (flujo de caja): el trimestre es el acumulado menos el anterior
    con el mismo inicio; el primero del año es su propio valor si dura unos tres meses."""
    per = periodos(hechos_)
    por_inicio = {}
    for (inicio, fin), f in per.items():
        por_inicio.setdefault(inicio, []).append((fin, f))
    q = {}
    for inicio, lista in por_inicio.items():
        lista.sort()
        previo = None
        for fin, f in lista:
            dias_desde = (_fecha(fin) - _fecha(previo[0] if previo else inicio)).days
            if previo is None:
                if 80 <= dias_desde <= 100:
                    q[fin] = _fila(f, inicio, fin, f["val"], False)
            elif 80 <= dias_desde <= 100:
                arranque = (_fecha(previo[0]) + dt.timedelta(days=1)).isoformat()
                q[fin] = _fila(f, arranque, fin, f["val"] - previo[1]["val"], True)
            previo = (fin, f)
    return q


def serie(companyfacts, clave, derivar_t4=True):
    """La serie trimestral de una métrica, probando sus conceptos en orden y rellenando huecos."""
    unidad = UNIDAD.get(clave, "USD")
    unida, usados = {}, []
    for concepto in CONCEPTOS[clave]:
        h = hechos(companyfacts, concepto, unidad)
        q = trimestral_acumulado(h) if clave in ACUMULADOS else trimestral(h, derivar_t4)
        if not q:
            continue
        nuevo = False
        for fin, v in q.items():
            if fin not in unida:
                unida[fin] = dict(v, concepto=concepto)
                nuevo = True
        if nuevo:
            usados.append(concepto)
    return unida, usados


def _hace_un_anio(serie_, fin, dias=365, holgura=10):
    objetivo = _fecha(fin) - dt.timedelta(days=dias)
    mejor = None
    for e in serie_:
        hueco = abs((_fecha(e) - objetivo).days)
        if hueco <= holgura and (mejor is None or hueco < mejor[0]):
            mejor = (hueco, e)
    return serie_[mejor[1]] if mejor else None


def variacion(a, b):
    """Variación porcentual de a frente a b, con un decimal; None si falta algo o b es 0."""
    if a is None or b in (None, 0):
        return None
    return round(100.0 * (a - b) / abs(b), 1)


def margen(parte, total):
    if parte is None or not total:
        return None
    return round(100.0 * parte / total, 1)


def analizar(companyfacts, trimestres=6, nombre=None):
    """Todo el informe, como dict: entidad, cik, trimestres (el más reciente primero), últimos cuatro y conceptos usados."""
    s, conceptos = {}, {}
    for clave in CONCEPTOS:
        s[clave], conceptos[clave] = serie(companyfacts, clave, derivar_t4=True)
    ing, neto = s["ingresos"], s["beneficio_neto"]
    if not ing and not neto:
        raise KemetError("los hechos XBRL no traen ingresos ni beneficio neto trimestrales")
    fines = sorted(set(ing) | set(neto), reverse=True)[:trimestres]
    filas = []
    for fin in fines:
        r = ing.get(fin, {}).get("valor")
        bruto = s["beneficio_bruto"].get(fin, {}).get("valor")
        if bruto is None and r is not None and fin in s["coste_ingresos"]:
            bruto = r - s["coste_ingresos"][fin]["valor"]
        oper = s["resultado_operativo"].get(fin, {}).get("valor")
        ni = neto.get(fin, {}).get("valor")
        bpa = s["bpa_diluido"].get(fin, {}).get("valor")
        caja = s["flujo_caja_operativo"].get(fin, {}).get("valor")
        previo = {k: _hace_un_anio(s[k], fin) for k in ("ingresos", "beneficio_neto", "bpa_diluido")}
        base = ing.get(fin) or neto.get(fin) or {}
        filas.append({
            "fin": fin, "inicio": base.get("inicio"),
            "fiscal": etiqueta_fiscal(base.get("fp"), base.get("fy")),
            "derivado": any(s[k].get(fin, {}).get("derivado") for k in ("ingresos", "beneficio_neto")),
            "ingresos": r, "beneficio_bruto": bruto, "resultado_operativo": oper, "beneficio_neto": ni,
            "bpa_diluido": round(bpa, 2) if bpa is not None else None,
            "flujo_caja_operativo": caja,
            "margen_bruto": margen(bruto, r), "margen_operativo": margen(oper, r), "margen_neto": margen(ni, r),
            "ingresos_interanual": variacion(r, (previo["ingresos"] or {}).get("valor")),
            "beneficio_neto_interanual": variacion(ni, (previo["beneficio_neto"] or {}).get("valor")),
            "bpa_interanual": variacion(bpa, (previo["bpa_diluido"] or {}).get("valor")),
            "presentado": base.get("presentado"), "formulario": base.get("formulario"),
        })
    ultimos = {}
    for clave in ("ingresos", "beneficio_neto", "bpa_diluido", "flujo_caja_operativo"):
        cuatro = sorted(s[clave])[-4:]
        if len(cuatro) == 4 and (_fecha(cuatro[-1]) - _fecha(cuatro[0])).days < 300:
            ultimos[clave] = sum(s[clave][e]["valor"] for e in cuatro)
    if "bpa_diluido" in ultimos:
        ultimos["bpa_diluido"] = round(ultimos["bpa_diluido"], 2)
    return {"entidad": nombre or companyfacts.get("entityName"), "cik": str(companyfacts.get("cik", "")).zfill(10),
            "trimestres": filas, "ultimos_4": ultimos, "conceptos": conceptos}


def etiqueta_fiscal(fp, fy):
    """Q3 2026 -> T3 2026; FY -> ejercicio."""
    fp = str(fp or "").upper()
    if fp.startswith("Q"):
        fp = "T" + fp[1:]
    elif fp == "FY":
        fp = "ejercicio"
    return ("%s %s" % (fp, fy or "")).strip()


# ---------------------------------------------------------------- presentaciones

ANEXOS = [r"ex(?:hibit)?[-_]?99[-_.]?0?1(?!\d)", r"ex(?:hibit)?[-_]?99", r"earnings|release|press", r"ex(?:hibit)?[-_]?\d"]


def nombre_anexo(nombres, principal=None):
    """La nota de prensa entre los archivos de un 8-K (el EX-99.1, con los nombres que suele llevar)."""
    docs = [n for n in nombres if n.lower().endswith((".htm", ".html", ".txt", ".pdf")) and n != principal
            and not re.match(r"^(R\d+\.htm|\d{10}-\d{2}-\d{6})", n)]
    for rx in ANEXOS:
        aciertos = sorted(n for n in docs if re.search(rx, n, re.I))
        if aciertos:
            return aciertos[0]
    return None


def _recientes(submissions):
    rec = submissions.get("filings", {}).get("recent", {})
    n = len(rec.get("form", []))
    columnas = ("form", "filingDate", "reportDate", "accessionNumber", "primaryDocument", "items")
    return [{c: (rec.get(c) or [""] * n)[i] for c in columnas} for i in range(n)]


def ultimos_informes(submissions, cik, edgar=None):
    """El 10-Q/10-K más reciente y el 8-K de resultados (punto 2.02) más reciente con su anexo EX-99."""
    out = {"informe": None, "resultados_8k": None}
    base_cik = int(cik)
    for f in _recientes(submissions):
        acc = f["accessionNumber"]
        carpeta = ARCHIVE_URL % (base_cik, acc.replace("-", ""))
        if out["informe"] is None and f["form"] in INFORMES:
            out["informe"] = {"formulario": f["form"], "presentado": f["filingDate"], "periodo": f["reportDate"], "accesion": acc,
                              "url": carpeta + f["primaryDocument"]}
        if out["resultados_8k"] is None and f["form"] == "8-K" and "2.02" in (f.get("items") or ""):
            e = {"formulario": "8-K", "presentado": f["filingDate"], "accesion": acc, "url": carpeta + f["primaryDocument"],
                 "anexo": None, "indice": carpeta + "%s-index.htm" % acc}
            if edgar is not None:
                try:
                    idx = edgar.json(carpeta + "index.json", os.path.join(acc.replace("-", ""), "index.json"))
                    nombres = [it["name"] for it in idx.get("directory", {}).get("item", [])]
                    elegido = nombre_anexo(nombres, f["primaryDocument"])
                    if elegido:
                        e["anexo"] = carpeta + elegido
                except KemetError:
                    pass
            out["resultados_8k"] = e
        if out["informe"] and out["resultados_8k"]:
            break
    return out


def proximo_informe(submissions, informes, hoy, fp_ultimo=None):
    """Cuándo toca el próximo informe, estimado. La SEC no publica el calendario: si en la lista está el mismo informe
    del año pasado, su fecha más 52 semanas; si no, unos 91 días después del último. Siempre va marcado como estimación."""
    ult = (informes or {}).get("informe")
    if not ult or not ult.get("periodo"):
        return None
    periodo = _fecha(ult["periodo"])
    objetivo = periodo + dt.timedelta(days=TRIMESTRE_DIAS)
    formulario = "10-K" if str(fp_ultimo or "").upper() in ("Q3", "T3") and ult["formulario"] == "10-Q" else "10-Q"
    if ult["formulario"] in ("10-K", "20-F", "40-F"):
        formulario = "10-Q"
    candidatos = []
    for f in _recientes(submissions):
        if f["form"] not in INFORMES or not f["reportDate"]:
            continue
        hueco = abs((_fecha(f["reportDate"]) - (objetivo - dt.timedelta(days=365))).days)
        if hueco <= 12:
            candidatos.append((hueco, f))
    if candidatos:
        f = sorted(candidatos, key=lambda x: x[0])[0][1]
        estimado = _fecha(f["filingDate"]) + dt.timedelta(weeks=52)
        base = "el %s equivalente del año pasado se presentó el %s" % (f["form"], f["filingDate"])
    else:
        estimado = _fecha(ult["presentado"]) + dt.timedelta(days=TRIMESTRE_DIAS)
        base = "unos 91 días después del último %s, presentado el %s" % (ult["formulario"], ult["presentado"])
    dias = (estimado - hoy).days
    return {"formulario": formulario, "estimado": estimado.isoformat(), "dias": dias, "base": base, "estimacion": True}


def nota_desfase(resultado, informes):
    """Aviso cuando los hechos de la SEC van por detrás de un informe ya presentado."""
    inf = (informes or {}).get("informe")
    if not inf or not resultado["trimestres"] or not inf.get("periodo"):
        return None
    ultimo = resultado["trimestres"][0]["fin"]
    if inf["periodo"] > ultimo and (_fecha(inf["periodo"]) - _fecha(ultimo)).days > 20:
        return ("los hechos XBRL de la SEC llegan hasta el %s, pero hay un %s del periodo cerrado el %s presentado el %s. "
                "Léelo directamente: %s" % (ultimo, inf["formulario"], inf["periodo"], inf["presentado"], inf["url"]))
    return None


# ---------------------------------------------------------------- formato español

def millones(v):
    return "-" if v is None else comun.num(v / 1e6, 0)


def millones_txt(v):
    return "-" if v is None else comun.num(v / 1e6, 0) + " M$"


def pct_es(v, signo=True):
    if v is None:
        return "-"
    s = ("%+.1f" if signo else "%.1f") % v
    return s.replace(".", ",") + " %"


def puntos_es(v):
    return ("%+.1f" % v).replace(".", ",") + " puntos"


def bpa_txt(v):
    return "-" if v is None else comun.num(v, 2)


def cambios(resultado):
    """Frases llanas: qué cambió en el último trimestre."""
    filas = resultado["trimestres"]
    if not filas:
        return []
    act = filas[0]
    ant = filas[1] if len(filas) > 1 else None
    out = []
    linea = "Trimestre cerrado el %s (%s%s): ingresos %s" % (act["fin"], act["fiscal"], ", derivado del 10-K" if act["derivado"] else "",
                                                             millones_txt(act["ingresos"]))
    if act["ingresos_interanual"] is not None:
        linea += " (%s interanual)" % pct_es(act["ingresos_interanual"])
    linea += ", beneficio neto %s" % millones_txt(act["beneficio_neto"])
    if act["beneficio_neto_interanual"] is not None:
        linea += " (%s)" % pct_es(act["beneficio_neto_interanual"])
    if act["bpa_diluido"] is not None:
        linea += ", BPA diluido %s $" % bpa_txt(act["bpa_diluido"])
        if act["bpa_interanual"] is not None:
            linea += " (%s)" % pct_es(act["bpa_interanual"])
    out.append(linea + ".")
    for clave, nombre in (("margen_bruto", "Margen bruto"), ("margen_operativo", "Margen operativo"), ("margen_neto", "Margen neto")):
        if act[clave] is None:
            continue
        s = "%s %s" % (nombre, pct_es(act[clave], signo=False))
        if ant and ant[clave] is not None:
            s += " (%s frente al trimestre anterior)" % puntos_es(act[clave] - ant[clave])
        out.append(s + ".")
    if act["flujo_caja_operativo"] is not None:
        s = "Flujo de caja operativo %s" % millones_txt(act["flujo_caja_operativo"])
        if act["beneficio_neto"] is not None and act["flujo_caja_operativo"] < act["beneficio_neto"]:
            s += ", por debajo del beneficio neto: el beneficio no se está convirtiendo en caja al mismo ritmo"
        out.append(s + ".")
    if act["beneficio_neto"] is not None and act["resultado_operativo"] is not None and act["beneficio_neto"] > act["resultado_operativo"]:
        out.append("El beneficio neto supera el resultado operativo: dentro hay partidas ajenas al negocio (inversiones, impuestos). "
                   "Mira el 10-Q antes de leerlo como crecimiento.")
    if ant and act["ingresos"] is not None and ant["ingresos"]:
        out.append("Ingresos %s frente al trimestre anterior (muchos negocios son estacionales: compara primero con el mismo "
                   "trimestre del año pasado)." % pct_es(variacion(act["ingresos"], ant["ingresos"])))
    return out


def render(ticker, resultado, informes, proximo, ahora_utc):
    hay_caja = any(r["flujo_caja_operativo"] is not None for r in resultado["trimestres"])
    out = ["RESULTADOS %s, %s, CIK %s · %s" % (ticker, resultado["entidad"], resultado["cik"], comun.hora_doble(ahora_utc)),
           "Fuente: %s. Millones de dólares salvo el BPA. Interanual: frente al mismo trimestre del año anterior." % FUENTE, ""]
    cab = "%-11s %-10s %10s %10s %8s %8s %8s %10s %8s %10s" % (
        "trimestre", "fiscal", "ingresos", "interanual", "m.bruto", "m.oper.", "m.neto", "beneficio", "BPA dil.", "interanual")
    if hay_caja:
        cab += " %10s" % "caja oper."
    out.append(cab)
    for r in resultado["trimestres"]:
        linea = "%-11s %-10s %10s %10s %8s %8s %8s %10s %8s %10s" % (
            r["fin"], r["fiscal"][:10], millones(r["ingresos"]), pct_es(r["ingresos_interanual"]),
            pct_es(r["margen_bruto"], False), pct_es(r["margen_operativo"], False), pct_es(r["margen_neto"], False),
            millones(r["beneficio_neto"]), bpa_txt(r["bpa_diluido"]), pct_es(r["bpa_interanual"]))
        if hay_caja:
            linea += " %10s" % millones(r["flujo_caja_operativo"])
        if r["derivado"]:
            linea += "  derivado"
        out.append(linea)
    u = resultado["ultimos_4"]
    if u:
        out.append("")
        s = "Últimos cuatro trimestres: ingresos %s, beneficio neto %s, BPA diluido %s" % (
            millones_txt(u.get("ingresos")), millones_txt(u.get("beneficio_neto")),
            (bpa_txt(u["bpa_diluido"]) + " $") if u.get("bpa_diluido") is not None else "-")
        if u.get("flujo_caja_operativo") is not None:
            s += ", flujo de caja operativo %s" % millones_txt(u["flujo_caja_operativo"])
        out.append(s + ".")
    out.append("")
    out.append("Qué cambió:")
    for linea in cambios(resultado):
        out.append("  - " + linea)
    if informes:
        out.append("")
        inf, e8 = informes.get("informe"), informes.get("resultados_8k")
        if inf:
            out.append("Último %s: periodo %s, presentado el %s  %s" % (inf["formulario"], inf["periodo"], inf["presentado"], inf["url"]))
        if e8:
            out.append("Último 8-K de resultados (punto 2.02): presentado el %s  %s" % (e8["presentado"], e8["anexo"] or e8["indice"]))
    if proximo:
        if proximo["dias"] < 0:
            out.append("Próximo informe: por el calendario tocaba un %s hacia el %s (%s); han pasado %d días y no aparece en la lista "
                       "leída. Confírmalo en la web de relación con inversores de la empresa." % (
                           proximo["formulario"], proximo["estimado"], proximo["base"], -proximo["dias"]))
        else:
            out.append("Próximo informe: %s hacia el %s, en %d días (%s). Es una estimación: la SEC no publica el calendario; "
                       "confírmalo en la web de relación con inversores." % (
                           proximo["formulario"], proximo["estimado"], proximo["dias"], proximo["base"]))
    nota = nota_desfase(resultado, informes)
    if nota:
        out.append("")
        out.append("AVISO: " + nota)
    if any(r["derivado"] for r in resultado["trimestres"]):
        out.append("")
        out.append("Los trimestres derivados son el año del 10-K menos los tres 10-Q; su BPA es aproximado.")
    return "\n".join(out) + "\n"


def fila_metricas(ticker, resultado):
    filas = resultado["trimestres"]
    act = filas[0] if filas else {}
    u = resultado["ultimos_4"]
    return {"ticker": ticker, "nombre": resultado["entidad"], "cik": resultado["cik"], "fin_periodo": act.get("fin"),
            "ingresos_12m": u.get("ingresos"), "beneficio_neto_12m": u.get("beneficio_neto"), "bpa_12m": u.get("bpa_diluido"),
            "flujo_caja_operativo_12m": u.get("flujo_caja_operativo"),
            "ingresos_interanual": act.get("ingresos_interanual"), "bpa_interanual": act.get("bpa_interanual"),
            "beneficio_neto_interanual": act.get("beneficio_neto_interanual"),
            "margen_bruto": act.get("margen_bruto"), "margen_operativo": act.get("margen_operativo"), "margen_neto": act.get("margen_neto"),
            "fuente": FUENTE}


def guardar_metricas(ruta, filas, hoy):
    existentes = {}
    if os.path.isfile(ruta):
        with open(ruta, encoding="utf-8") as fh:
            try:
                existentes = {r["ticker"]: r for r in json.load(fh).get("empresas", [])}
            except (ValueError, KeyError, TypeError):
                raise KemetError("%s no es un archivo de métricas válido" % ruta)
    for r in filas:
        existentes[r["ticker"]] = r
    comun.escribir_json(ruta if os.sep in ruta else os.path.join(".", ruta),
                        {"fecha": hoy.isoformat(), "empresas": sorted(existentes.values(), key=lambda r: r["ticker"])})
    return len(existentes)


# ---------------------------------------------------------------- CLI

def _parser():
    ap = argparse.ArgumentParser(description="Resultados de una empresa desde la SEC (XBRL), trimestre a trimestre, en español.")
    ap.add_argument("tickers", nargs="*", help="tickers, por ejemplo AAPL KO")
    ap.add_argument("--cik", help="usa este CIK en vez de buscar el ticker (una sola empresa)")
    ap.add_argument("--trimestres", type=int, default=6)
    ap.add_argument("--sin-informes", action="store_true", help="no busca el 10-Q, el 8-K ni el próximo informe")
    ap.add_argument("--metricas", metavar="ARCHIVO", help="añade o actualiza una fila por empresa en este JSON")
    ap.add_argument("--escribir", action="store_true", help="guarda kemet/resultados.json")
    ap.add_argument("--user-agent", help="Nombre Apellido correo@dominio.com (si no, SEC_USER_AGENT o kemet/config.json)")
    ap.add_argument("--offline", metavar="CARPETA", help="lee los JSON de EDGAR de una carpeta guardada")
    ap.add_argument("--ahora", help="AAAA-MM-DD HH:MM en hora de Nueva York (para repetir un día)")
    ap.add_argument("--json", action="store_true")
    return ap


def main(argv=None):
    ap = _parser()
    args = ap.parse_args(argv)
    if not args.tickers and not args.cik:
        ap.print_help()
        return 2
    try:
        return _run(args)
    except KemetError as e:
        print("resultados: %s" % e, file=sys.stderr)
        return 2


def _run(args):
    ahora = comun.parse_ahora(args.ahora)
    hoy = comun.a_ny(ahora).date()
    ua = user_agent(args.user_agent)
    if not ua and not args.offline:
        raise KemetError(SIN_UA)
    edgar = Edgar(ua, offline=args.offline)
    ciks = {} if args.cik else ciks_por_ticker(edgar)
    pedidos = args.tickers or [args.cik]
    empresas, filas, fallos = [], [], 0
    for t in pedidos:
        tick = t.upper()
        if args.cik:
            cik, nombre = str(args.cik).zfill(10), None
        else:
            cik, nombre = ciks.get(tick.replace("-", "."), (None, None))
        if not cik:
            print("resultados: la SEC no tiene CIK para %s (los ETF y las empresas extranjeras pueden no tener hechos XBRL)" % tick,
                  file=sys.stderr)
            fallos += 1
            continue
        try:
            cf = edgar.json(FACTS_URL % cik, "companyfacts-CIK%s.json" % cik)
            resultado = analizar(cf, trimestres=args.trimestres, nombre=nombre)
            informes = proximo = None
            if not args.sin_informes:
                sub = edgar.json(SUBMISSIONS_URL % cik, "submissions-CIK%s.json" % cik)
                informes = ultimos_informes(sub, cik, edgar)
                fp = None
                if resultado["trimestres"]:
                    fp = resultado["trimestres"][0]["fiscal"].split(" ")[0]
                proximo = proximo_informe(sub, informes, hoy, fp)
        except KemetError as e:
            print("resultados: %s: %s" % (tick, e), file=sys.stderr)
            fallos += 1
            continue
        empresas.append({"ticker": tick, "resultado": resultado, "informes": informes, "proximo": proximo,
                         "cambios": cambios(resultado), "aviso": nota_desfase(resultado, informes)})
        filas.append(fila_metricas(tick, resultado))
        if not args.json:
            sys.stdout.write(render(tick, resultado, informes, proximo, ahora))
            sys.stdout.write("\n")
    doc = {"generado": comun.iso(ahora), "fuente": FUENTE, "empresas": empresas}
    if args.json:
        print(json.dumps(doc, indent=1, ensure_ascii=False))
    if args.escribir and empresas:
        p = comun.escribir_json("resultados.json", doc)
        if not args.json:
            print("Escrito %s (%d empresas)." % (p, len(empresas)))
    if args.metricas and filas:
        n = guardar_metricas(args.metricas, filas, hoy)
        if not args.json:
            print("Escrito %s (%d empresas)." % (args.metricas, n))
    return 0 if empresas and not fallos else (1 if empresas else 2)


if __name__ == "__main__":
    sys.exit(main())
