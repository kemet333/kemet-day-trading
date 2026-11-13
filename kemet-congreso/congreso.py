#!/usr/bin/env python3
"""Las operaciones en bolsa que declaran los miembros de la Cámara de Representantes de EE. UU., en español.

    python3 congreso.py index --miembro pelosi                  # los PTR de este año de un miembro
    python3 congreso.py index --anio 2026 --desde 2026-10-01    # todos los PTR presentados desde una fecha
    python3 congreso.py recientes --dias 45 --miembro pelosi    # los de los últimos 45 días, marcando los nuevos
    python3 congreso.py ptr 20035143                            # baja un PTR y lo lee
    python3 congreso.py texto ptr.txt --presentado 2026-08-21   # filas desde el texto de `pdftotext -layout`

De dónde salen los datos:
  - El índice: https://disclosures-clerk.house.gov/public_disc/financial-pdfs/<AÑO>FD.zip
    (un ZIP con <AÑO>FD.xml: un <Member> por declaración; FilingType P = PTR, Periodic Transaction Report).
  - Cada PTR: https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/<AÑO>/<DocID>.pdf
  - Para sacar las filas de un PDF hace falta `pdftotext` (poppler). Sin él, la herramienta guarda el PDF y dice
    dónde está; Claude puede leerlo directamente.

Qué es un PTR y qué no es:
  - Una declaración PÚBLICA obligada por la STOCK Act: se presenta en los 30 días siguientes a que el miembro
    conozca la operación y nunca más de 45 días después de hacerla. Llega días o semanas tarde y los importes son
    rangos, no precios.
  - Leerla rápido no es información privilegiada. Aquí no hay ninguna.
  - Cubre la Cámara. Los PTR del Senado están en efdsearch.senate.gov detrás de un acuerdo que tiene que aceptar
    el usuario; el SKILL.md explica la vía manual.

Memoria: `recientes` apunta en kemet/estado/congreso.json los DocID que ya enseñó, para que cada PTR salga como
nuevo una sola vez. Sin red: --offline RUTA lee un <AÑO>FD.zip guardado (o el .xml de dentro, o una carpeta que lo
contenga junto a los textos ptr-<DocID>.txt). Los tests lo usan.

Código de salida 0 si hay declaraciones u operaciones que enseñar, 1 si no hay nada, 2 si hay un error.
"""
import argparse
import datetime as dt
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

import comun
from comun import KemetError

INDICE_URL = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/%d%s.zip"
PTR_URL = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/%d/%s.pdf"
FD_URL = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/%d/%s.pdf"
FUENTE = "House Clerk, Financial Disclosure (disclosures-clerk.house.gov)"
TIPOS_DECLARACION = {
    "P": "PTR (operaciones)", "O": "informe anual", "A": "enmienda", "C": "informe de candidato", "X": "prórroga",
    "T": "informe de cese", "W": "exención", "D": "declaración de nuevo miembro o candidato", "H": "informe de nuevo declarante",
}
TIPOS_OPERACION = {"P": "compra", "S": "venta", "S (partial)": "venta parcial", "E": "canje"}
TITULARES = {"SP": "cónyuge", "JT": "cuenta conjunta", "DC": "hijo a cargo", "": "el propio miembro"}
PLAZO_DIAS = 45


# ---------------------------------------------------------------- red

def descargar(url, timeout=60):
    # La Cámara no pide contacto: el nombre y el correo del User-Agent de la SEC se quedan para la SEC
    req = urllib.request.Request(url, headers={"User-Agent": comun.UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise KemetError("el House Clerk respondió HTTP %s en %s" % (e.code, url))
    except urllib.error.URLError as e:
        raise KemetError("no llego a %s: %s" % (url, e.reason))


# ---------------------------------------------------------------- el índice

def iso(mdy):
    """'8/21/2026' o '08/21/2026' -> '2026-08-21' (años de dos cifras -> 20xx). None si no es una fecha."""
    m = re.match(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s*$", mdy or "")
    if not m:
        return None
    mes, dia, anio = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if anio < 100:
        anio += 2000
    try:
        return dt.date(anio, mes, dia).isoformat()
    except ValueError:
        return None


def bytes_del_indice(datos):
    """El XML del índice desde el ZIP (o el propio XML)."""
    if datos[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            nombres = [n for n in z.namelist() if n.lower().endswith(".xml")]
            if not nombres:
                raise KemetError("el ZIP del índice no trae ningún XML (archivos: %s)" % ", ".join(z.namelist()))
            return z.read(nombres[0])
    return datos


def parsear_indice(xml_bytes, anio):
    """Cada declaración de un <AÑO>FD.xml como dict, la más reciente primero."""
    try:
        raiz = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise KemetError("el índice no es XML válido: %s" % e)
    out = []
    for m in raiz.iter("Member"):
        f = {c.tag: (c.text or "").strip() for c in m}
        doc = f.get("DocID", "")
        tipo = f.get("FilingType", "")
        y = int(f.get("Year") or anio)
        url = (PTR_URL if tipo == "P" else FD_URL) % (y, doc)
        nombre = " ".join(x for x in (f.get("Prefix"), f.get("First"), f.get("Last"), f.get("Suffix")) if x)
        out.append({"doc_id": doc, "tipo": tipo, "tipo_nombre": TIPOS_DECLARACION.get(tipo, tipo), "apellido": f.get("Last", ""),
                    "nombre": f.get("First", ""), "miembro": nombre, "distrito": f.get("StateDst", ""), "anio": y,
                    "presentado": iso(f.get("FilingDate", "")), "url": url})
    out.sort(key=lambda r: (r["presentado"] or "", r["doc_id"]), reverse=True)
    return out


def _ruta_offline_indice(offline, anio):
    if os.path.isdir(offline):
        for n in ("%dFD.zip" % anio, "%dFD.xml" % anio):
            p = os.path.join(offline, n)
            if os.path.exists(p):
                return p
        raise KemetError("sin red: no hay %dFD.zip en %s" % (anio, offline))
    if not os.path.exists(offline):
        raise KemetError("no existe el archivo %s" % offline)
    return offline


def cargar_indice(anio, offline=None):
    if offline:
        with open(_ruta_offline_indice(offline, anio), "rb") as fh:
            datos = fh.read()
    else:
        datos = descargar(INDICE_URL % (anio, "FD"))
    return parsear_indice(bytes_del_indice(datos), anio)


def coincide_miembro(fila, miembro):
    """'pelosi', 'Nancy Pelosi' o 'Pelosi, Nancy' contra una fila del índice."""
    miembro = (miembro or "").strip().lower()
    if not miembro:
        return True
    if "," in miembro:
        apellido, nombre = [x.strip() for x in miembro.split(",", 1)]
    else:
        partes = miembro.split()
        apellido, nombre = partes[-1], " ".join(partes[:-1])
    if fila["apellido"].lower() != apellido:
        return False
    return not nombre or fila["nombre"].lower().startswith(nombre)


def seleccionar(filas, miembros=None, tipo="P", desde=None):
    out = []
    for r in filas:
        if tipo and r["tipo"] != tipo:
            continue
        if miembros and not any(coincide_miembro(r, m) for m in miembros):
            continue
        if desde and (r["presentado"] or "") < desde:
            continue
        out.append(r)
    return out


# ---------------------------------------------------------------- memoria de lo visto

ESTADO = os.path.join("estado", "congreso.json")


def ruta_estado():
    """kemet/estado/congreso.json (comun trata un nombre con separador como ruta completa, así que se resuelve aquí)."""
    return comun.ruta(ESTADO)


def cargar_estado():
    return comun.leer_json(ruta_estado(), obligatorio=False) or {"vistos": [], "ultima_comprobacion": None}


def guardar_estado(estado):
    return comun.escribir_json(ruta_estado(), estado)


def nuevos(filas, estado):
    vistos = set(estado.get("vistos", []))
    return [r for r in filas if r["doc_id"] not in vistos]


# ---------------------------------------------------------------- leer un PTR

TXN = re.compile(
    r"^\s*(?:(?P<owner>SP|JT|DC)\s+)?(?P<asset>.*?)\s+(?P<type>S \(partial\)|P|S|E)\s+"
    r"(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<notified>\d{2}/\d{2}/\d{4})\s+(?P<amount>\S.*?)\s*$")
ETIQUETAS = [
    ("estado", re.compile(r"^\s*F(?:ILING)?\s+S(?:TATUS)?\s*:\s*(.*)$", re.I)),
    ("descripcion", re.compile(r"^\s*D(?:ESCRIPTION)?\s*:\s*(.*)$", re.I)),
    ("cuenta", re.compile(r"^\s*S(?:UBHOLDING)?\s+O(?:F)?\s*:\s*(.*)$", re.I)),
    ("ubicacion", re.compile(r"^\s*L(?:OCATION)?\s*:\s*(.*)$", re.I)),
]
# Las cabeceras de columna se repiten en cada página, a veces en mitad de una fila que sigue en la página siguiente:
# se saltan sin cerrar la fila.
CABECERA = re.compile(r"^\s*(ID\s+Owner\s+Asset|Type\s+Date\b|Type$|Date$|Gains >$|\$200\?$)", re.I)
FIN = re.compile(r"^\s*(\* For the complete|I CERTIFY|Digitally Signed|Filing ID #)", re.I)
IMPORTE = re.compile(r"\$([\d,]+)")
OPCION = re.compile(r"([\d,]+)\s+(call|put)\s+options?\b.*?strike price of \$([\d,.]+).*?expiration date of (\d{1,2}/\d{1,2}/\d{2,4})", re.I | re.S)
ACCIONES = re.compile(r"(?:purchased|sold|bought)\s+([\d,]+)\s+shares", re.I)


def _importe(texto):
    nums = [int(x.replace(",", "")) for x in IMPORTE.findall(texto or "")]
    return (nums[0] if nums else None), (nums[1] if len(nums) > 1 else None)


def importe_es(minimo, maximo, original=None):
    """'$1,000,001 - $5,000,000' -> 'de 1.000.001 a 5.000.000 $'."""
    if minimo is None:
        return original or "-"
    if maximo is None:
        return comun.usd(minimo)
    return "de %s a %s" % (comun.num(minimo, 0), comun.usd(maximo))


def _cerrar(fila, presentado):
    activo = " ".join(fila.pop("_activo").split())
    tick = re.findall(r"\(([A-Z][A-Z0-9.\-/]{0,9})\)", activo)
    codigo = re.findall(r"\[([A-Z]{2})\]", activo)
    fila["ticker"] = tick[-1] if tick else None
    fila["tipo_activo"] = codigo[-1] if codigo else None
    nombre = re.sub(r"\s*\[[A-Z]{2}\]", "", activo)
    if tick:
        nombre = re.sub(r"\s*\(%s\)" % re.escape(tick[-1]), "", nombre)
    fila["activo"] = nombre.strip(" -")
    fila["importe_original"] = " ".join(fila.pop("_importe").split())
    fila["importe_min"], fila["importe_max"] = _importe(fila["importe_original"])
    fila["importe"] = importe_es(fila["importe_min"], fila["importe_max"], fila["importe_original"])
    fila["descripcion"] = " ".join(fila.get("descripcion", "").split()) or None
    opt = OPCION.search(fila["descripcion"] or "")
    if opt:
        fila["opcion"] = {"contratos": int(opt.group(1).replace(",", "")), "clase": opt.group(2).lower(),
                          "strike": float(opt.group(3).replace(",", "")), "vence": iso(opt.group(4)),
                          "ejercida": bool(re.match(r"\s*exercised\b", fila["descripcion"], re.I))}
    acc = ACCIONES.search(fila["descripcion"] or "")
    if acc:
        fila["acciones"] = int(acc.group(1).replace(",", ""))
    if presentado and fila["fecha"]:
        dias = (dt.date.fromisoformat(presentado) - dt.date.fromisoformat(fila["fecha"])).days
        fila["dias_retraso"] = dias
        fila["fuera_de_plazo"] = dias > PLAZO_DIAS
    return fila


def parsear_ptr(texto, presentado=None):
    """Las filas de un PTR de la Cámara a partir del texto de `pdftotext -layout`.

    Devuelve {"miembro", "estatus", "distrito", "doc_id", "presentado", "operaciones": [...]}. Cada operación: titular,
    titular_nombre, activo, ticker, tipo_activo, tipo, tipo_nombre, fecha, notificado, importe, importe_min, importe_max,
    importe_original, estado, descripcion, cuenta, opcion {contratos, clase, strike, vence, ejercida}, acciones,
    dias_retraso, fuera_de_plazo."""
    cab = {"miembro": None, "estatus": None, "distrito": None, "doc_id": None, "presentado": presentado}
    filas, cur, modo = [], None, None
    importe_abierto = False
    for cruda in texto.splitlines():
        linea = cruda.rstrip()
        s = linea.strip()
        m = re.match(r"^Name:\s+(.*)$", s)
        if m and not cab["miembro"]:
            cab["miembro"] = m.group(1).strip()
            continue
        m = re.match(r"^Status:\s+(.*)$", s)
        if m and not cab["estatus"]:
            cab["estatus"] = m.group(1).strip()
            continue
        m = re.match(r"^State/District:\s*(\S+)", s)
        if m:
            cab["distrito"] = m.group(1)
            continue
        m = re.search(r"Filing ID #(\d+)", s)
        if m:
            cab["doc_id"] = m.group(1)
            continue
        m = re.match(r"^Digitally Signed:.*?,\s*(\d{2}/\d{2}/\d{4})", s)
        if m:
            cab["presentado"] = cab["presentado"] or iso(m.group(1))
            continue
        t = TXN.match(linea)
        if t and iso(t.group("date")):
            if cur:
                filas.append(cur)
            titular = t.group("owner") or ""
            cur = {"titular": titular, "titular_nombre": TITULARES.get(titular, titular), "_activo": t.group("asset"),
                   "tipo": t.group("type"), "tipo_nombre": TIPOS_OPERACION.get(t.group("type"), t.group("type")),
                   "fecha": iso(t.group("date")), "notificado": iso(t.group("notified")), "_importe": t.group("amount"),
                   "estado": None, "cuenta": None}
            importe_abierto = cur["_importe"].endswith("-")
            modo = "activo"
            continue
        if cur is None:
            continue
        if not s:
            if modo in ("descripcion", "activo"):
                modo = "etiquetas" if modo == "descripcion" or "[" in cur["_activo"] else modo
            continue
        if CABECERA.match(s):
            continue
        if FIN.match(s):
            modo = "etiquetas"
            continue
        etiqueta = next(((k, rx.match(linea)) for k, rx in ETIQUETAS if rx.match(linea)), None)
        if etiqueta:
            clave, lm = etiqueta
            valor = lm.group(1).strip()
            if clave == "descripcion":
                cur["descripcion"] = valor
                modo = "descripcion"
            elif clave in ("estado", "cuenta"):
                cur[clave] = valor
                modo = "etiquetas"
            else:
                modo = "etiquetas"
            continue
        if modo == "activo":
            partes = re.split(r"\s{2,}", s)
            if importe_abierto and re.fullmatch(r"\$[\d,]+", partes[-1]):
                cur["_importe"] += " " + partes.pop()
                importe_abierto = False
            if partes and partes[0]:
                cur["_activo"] += " " + " ".join(partes)
        elif modo == "descripcion":
            cur["descripcion"] = cur.get("descripcion", "") + " " + s
    if cur:
        filas.append(cur)
    cab["operaciones"] = [_cerrar(r, cab["presentado"]) for r in filas]
    return cab


def pdf_a_texto(ruta_pdf):
    exe = shutil.which("pdftotext")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "-layout", ruta_pdf, "-"], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.decode("utf-8", "replace") if out.returncode == 0 else None


def _texto_offline(offline, doc_id):
    carpeta = offline if os.path.isdir(offline) else os.path.dirname(offline)
    for patron in ("ptr-%s.txt", "ptr-%s-*.txt", "%s.txt"):
        rutas = sorted(glob.glob(os.path.join(carpeta, patron % doc_id)))
        if rutas:
            return comun.leer_texto(rutas[0])
    raise KemetError("sin red: no hay un texto ptr-%s.txt en %s" % (doc_id, carpeta))


def leer_ptr(doc_id, anio, presentado=None, offline=None):
    """Baja el PDF a kemet/estado/ptr/<DocID>.pdf y lo lee con pdftotext. Devuelve (ruta_pdf, informe o None)."""
    url = PTR_URL % (anio, doc_id)
    if offline:
        informe = parsear_ptr(_texto_offline(offline, doc_id), presentado=presentado)
        informe["url"], informe["pdf"] = url, None
        return None, informe
    carpeta = comun.ruta(os.path.join("estado", "ptr"))
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, "%s.pdf" % doc_id)
    if not os.path.isfile(ruta):
        datos = descargar(url)
        if not datos.startswith(b"%PDF"):
            raise KemetError("el documento %s no llegó como PDF (puede no existir en %d)" % (doc_id, anio))
        with open(ruta, "wb") as fh:
            fh.write(datos)
    texto = pdf_a_texto(ruta)
    if texto is None:
        return ruta, None
    informe = parsear_ptr(texto, presentado=presentado)
    informe["url"], informe["pdf"] = url, ruta
    return ruta, informe


# ---------------------------------------------------------------- salida

def vigilados(args):
    """Tickers que se señalan: --tickers, los aciertos de kemet/watchlist.json y las posiciones de kemet/portfolio.json."""
    tickers = {t.upper() for t in (getattr(args, "tickers", None) or [])}
    wl = comun.leer_json("watchlist.json", obligatorio=False) or {}
    for a in wl.get("aciertos", []) or []:
        if a.get("simbolo"):
            tickers.add(str(a["simbolo"]).upper())
    pf = comun.leer_json("portfolio.json", obligatorio=False) or {}
    for p in pf.get("posiciones", []) or []:
        if p.get("simbolo"):
            tickers.add(str(p["simbolo"]).upper())
    return tickers


def describir(op):
    partes = ["%s, %s" % (op["titular_nombre"], op["tipo_nombre"])]
    que = op["activo"]
    if op.get("ticker"):
        que += " (%s)" % op["ticker"]
    if op.get("opcion"):
        o = op["opcion"]
        que += ": %s%d opciones %s con strike de %s que vencen el %s" % (
            "ejercidas " if o.get("ejercida") else "", o["contratos"], o["clase"], comun.usd(o["strike"], 2 if o["strike"] % 1 else 0), o["vence"])
    elif op.get("acciones"):
        que += ": %s acciones" % comun.num(op["acciones"], 0)
    partes.append(que)
    partes.append(op["importe"])
    cuando = "operada el %s" % op["fecha"]
    if op.get("dias_retraso") is not None:
        cuando += ", declarada %d días después%s" % (op["dias_retraso"], " (FUERA DE PLAZO: más de 45)" if op.get("fuera_de_plazo") else "")
    partes.append(cuando)
    if op.get("cuenta"):
        partes.append("cuenta: %s" % op["cuenta"])
    return ", ".join(partes)


def render_informe(informe, vigilar=()):
    out = ["%s (%s), %s. PTR %s, presentado el %s." % (
        informe.get("miembro") or "?", informe.get("distrito") or "?", informe.get("estatus") or "?",
        informe.get("doc_id") or "?", informe.get("presentado") or "?")]
    for op in informe["operaciones"]:
        marca = "  <- %s está en tu lista" % op["ticker"] if op.get("ticker") in vigilar else ""
        out.append("  - %s%s" % (describir(op), marca))
        if op.get("descripcion") and not op.get("opcion") and not op.get("acciones"):
            out.append("      %s" % op["descripcion"])
    if not informe["operaciones"]:
        out.append("  sin filas de operaciones: lee el PDF directamente")
    out.append("Declaración pública por la STOCK Act, presentada hasta 45 días después de la operación. "
               "Los importes son rangos. No es información privilegiada.")
    return "\n".join(out) + "\n"


def render_indice(filas, marcar_nuevos=None):
    out = []
    for r in filas:
        nuevo = "NUEVO " if marcar_nuevos is not None and r["doc_id"] in marcar_nuevos else ""
        out.append("%s%s  %-28s %-5s %-4s doc %-9s %s" % (nuevo, r["presentado"], r["miembro"][:28], r["distrito"], r["tipo"], r["doc_id"], r["url"]))
    return "\n".join(out) + ("\n" if out else "")


# ---------------------------------------------------------------- CLI

def _parser():
    ap = argparse.ArgumentParser(description="Operaciones declaradas por miembros de la Cámara de Representantes (PTR, STOCK Act), en español.")
    sub = ap.add_subparsers(dest="cmd")

    def comunes(p):
        p.add_argument("--anio", type=int, help="año del índice (por defecto el de --ahora)")
        p.add_argument("--miembro", action="append", help="apellido, 'Nombre Apellido' o 'Apellido, Nombre'; se puede repetir")
        p.add_argument("--tipo", default="P", help="FilingType (P = PTR por defecto; '' para todos)")
        p.add_argument("--desde", help="solo declaraciones presentadas desde AAAA-MM-DD")
        p.add_argument("--offline", metavar="RUTA", help="un <AÑO>FD.zip o .xml guardado, o la carpeta que lo contiene")
        p.add_argument("--ahora", help="AAAA-MM-DD HH:MM en hora de Nueva York (para repetir un día)")
        p.add_argument("--tickers", nargs="*", help="señala operaciones en estos tickers")
        p.add_argument("--escribir", action="store_true", help="guarda kemet/congreso.json")
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("index", help="declaraciones del índice anual")
    comunes(p)
    p.add_argument("--limite", type=int, default=50)

    p = sub.add_parser("recientes", help="PTR de los últimos días, marcando los que no habías visto")
    comunes(p)
    p.add_argument("--dias", type=int, default=PLAZO_DIAS)
    p.add_argument("--leer", action="store_true", help="baja y lee cada PTR (necesita pdftotext)")

    p = sub.add_parser("ptr", help="baja un PTR y lo lee")
    p.add_argument("doc_id")
    p.add_argument("--anio", type=int)
    p.add_argument("--presentado", help="fecha de presentación AAAA-MM-DD si se sabe (si no, la de la firma)")
    p.add_argument("--offline", metavar="CARPETA", help="lee ptr-<DocID>.txt de esa carpeta en vez de bajar el PDF")
    p.add_argument("--ahora")
    p.add_argument("--tickers", nargs="*")
    p.add_argument("--escribir", action="store_true")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("texto", help="filas desde el texto de `pdftotext -layout` de un PTR")
    p.add_argument("archivo")
    p.add_argument("--presentado", help="fecha de presentación AAAA-MM-DD (si no, la de la firma)")
    p.add_argument("--ahora")
    p.add_argument("--tickers", nargs="*")
    p.add_argument("--escribir", action="store_true")
    p.add_argument("--json", action="store_true")
    return ap


def main(argv=None):
    ap = _parser()
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 2
    try:
        return _run(args)
    except (KemetError, OSError) as e:
        print("congreso: %s" % e, file=sys.stderr)
        return 2


def _documento(ahora, cmd, **extra):
    doc = {"generado": comun.iso(ahora), "fuente": FUENTE, "comando": cmd}
    doc.update(extra)
    return doc


def _salida_informe(args, informe, ahora, cmd):
    doc = _documento(ahora, cmd, informes=[informe])
    if args.json:
        print(json.dumps(doc, indent=1, ensure_ascii=False))
    else:
        sys.stdout.write(render_informe(informe, vigilados(args)))
    if args.escribir:
        p = comun.escribir_json("congreso.json", doc)
        if not args.json:
            print("Escrito %s." % p)
    return 0 if informe["operaciones"] else 1


def _run(args):
    ahora = comun.parse_ahora(getattr(args, "ahora", None))
    hoy = comun.a_ny(ahora).date()
    anio = getattr(args, "anio", None) or hoy.year

    if args.cmd == "texto":
        informe = parsear_ptr(comun.leer_texto(args.archivo), presentado=args.presentado)
        return _salida_informe(args, informe, ahora, "texto")

    if args.cmd == "ptr":
        ruta, informe = leer_ptr(args.doc_id, anio, args.presentado, args.offline)
        if informe is None:
            print("Guardado %s. pdftotext no está instalado: abre el PDF y léelo directamente (Claude puede), "
                  "o instala poppler (brew install poppler)." % ruta)
            return 0
        return _salida_informe(args, informe, ahora, "ptr")

    filas = cargar_indice(anio, args.offline)
    if args.cmd == "recientes" and not args.offline and hoy.month == 1 and anio == hoy.year:
        try:
            filas += cargar_indice(anio - 1)
        except KemetError:
            pass
    elegidas = seleccionar(filas, args.miembro, args.tipo or None, args.desde)
    quien = ", ".join(args.miembro) if args.miembro else "todos los miembros"

    if args.cmd == "index":
        elegidas = elegidas[:args.limite]
        doc = _documento(ahora, "index", anio=anio, miembros=args.miembro or [], declaraciones=elegidas)
        if args.json:
            print(json.dumps(doc, indent=1, ensure_ascii=False))
        else:
            print("CONGRESO, índice %d del House Clerk, %d declaraciones de %s · %s" % (anio, len(elegidas), quien, comun.hora_doble(ahora)))
            sys.stdout.write(render_indice(elegidas))
            if not elegidas:
                print("Ninguna declaración coincide en el índice de %d." % anio)
            else:
                print("Declaraciones públicas (STOCK Act), presentadas hasta 45 días después de operar. No es información privilegiada.")
        if args.escribir:
            p = comun.escribir_json("congreso.json", doc)
            if not args.json:
                print("Escrito %s." % p)
        return 0 if elegidas else 1

    # recientes
    corte = (hoy - dt.timedelta(days=args.dias)).isoformat()
    recientes = [r for r in elegidas if (r["presentado"] or "") >= corte]
    estado = cargar_estado()
    frescas = nuevos(recientes, estado)
    ids_nuevos = {r["doc_id"] for r in frescas}
    informes = []
    if args.leer:
        for r in recientes:
            if r["tipo"] != "P":
                continue
            try:
                ruta, informe = leer_ptr(r["doc_id"], r["anio"], r["presentado"], args.offline)
            except KemetError as e:
                informes.append({"declaracion": r, "informe": None, "error": str(e)})
                continue
            informes.append({"declaracion": r, "pdf": ruta, "informe": informe})
    doc = _documento(ahora, "recientes", anio=anio, miembros=args.miembro or [], dias=args.dias, desde=corte,
                     declaraciones=recientes, nuevas=sorted(ids_nuevos), informes=[i["informe"] for i in informes if i.get("informe")])
    if args.json:
        print(json.dumps(doc, indent=1, ensure_ascii=False))
    else:
        print("CONGRESO, PTR de los últimos %d días (desde el %s) de %s: %d, %d sin ver · %s" % (
            args.dias, corte, quien, len(recientes), len(frescas), comun.hora_doble(ahora)))
        if not recientes:
            print("Nada presentado en ese plazo%s." % (" desde la última comprobación (%s)" % estado["ultima_comprobacion"] if estado.get("ultima_comprobacion") else ""))
        sys.stdout.write(render_indice(recientes, ids_nuevos))
        vig = vigilados(args)
        for i in informes:
            if i.get("error"):
                print("    %s: %s" % (i["declaracion"]["doc_id"], i["error"]))
            elif i.get("informe") is None:
                print("    lee %s (pdftotext no está instalado)" % i.get("pdf"))
            else:
                sys.stdout.write(render_informe(i["informe"], vig))
        if recientes:
            print("Declaraciones públicas (STOCK Act), presentadas hasta 45 días después de operar. No es información privilegiada.")
    if args.escribir:
        vistos = set(estado.get("vistos", []))
        vistos.update(r["doc_id"] for r in recientes)
        estado["vistos"] = sorted(vistos)
        estado["ultima_comprobacion"] = comun.iso(ahora)
        guardar_estado(estado)
        p = comun.escribir_json("congreso.json", doc)
        if not args.json:
            print("Escrito %s y la memoria de lo visto en %s." % (p, ruta_estado()))
    return 0 if recientes else 1


if __name__ == "__main__":
    sys.exit(main())
