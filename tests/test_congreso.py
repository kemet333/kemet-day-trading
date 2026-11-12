"""kemet-congreso: el índice del House Clerk y PTR reales. Sin red.

Fixtures en tests/fixtures/kemet-congreso/: copia tal cual de tests/fixtures/trader-pelosi/ del pack de referencia
day-trader-skill (MIT, Jake Schincariol): 2026FD.zip es un recorte real del índice 2026FD.xml del Clerk (leído el
2026-10-13, con los cuatro PTR de Nancy Pelosi de 2026 y otros de octubre); los ptr-*.txt son la salida de
`pdftotext -layout` de PTR reales (20035143 y 20035590 enteros; 20033725 y 20035562 recortados)."""
import contextlib
import datetime
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _load import FIX, load  # noqa: E402

congreso = load("kemet-congreso", "congreso")
comun = sys.modules["comun"]
DIR = os.path.join(FIX, "kemet-congreso")
ZIP = os.path.join(DIR, "2026FD.zip")


def texto(nombre):
    with open(os.path.join(DIR, nombre), encoding="utf-8") as fh:
        return fh.read()


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = congreso.main(argv)
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="kemet-congreso-")
        self.kemet = os.path.join(self.dir, "kemet")
        self._kemet_dir = comun.KEMET_DIR
        comun.KEMET_DIR = self.kemet

    def tearDown(self):
        comun.KEMET_DIR = self._kemet_dir
        shutil.rmtree(self.dir, ignore_errors=True)


class Indice(Base):
    def setUp(self):
        super().setUp()
        self.filas = congreso.cargar_indice(2026, offline=ZIP)

    def test_los_cuatro_ptr_de_pelosi_de_2026(self):
        suyos = congreso.seleccionar(self.filas, ["pelosi"])
        self.assertEqual([r["doc_id"] for r in suyos], ["20035553", "20035143", "20034836", "20033725"])
        self.assertEqual([r["presentado"] for r in suyos], ["2026-10-02", "2026-08-21", "2026-06-23", "2026-01-23"])
        self.assertEqual(suyos[1]["url"], "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/20035143.pdf")
        self.assertEqual(suyos[0]["distrito"], "CA11")
        self.assertEqual(suyos[0]["miembro"], "Hon. Nancy Pelosi")
        self.assertEqual(suyos[0]["tipo_nombre"], "PTR (operaciones)")

    def test_el_miembro_en_cualquier_orden(self):
        for m in ("pelosi", "Nancy Pelosi", "Pelosi, Nancy", "PELOSI"):
            self.assertEqual(len(congreso.seleccionar(self.filas, [m])), 4, m)
        self.assertEqual(congreso.seleccionar(self.filas, ["Paul Pelosi"]), [])
        self.assertEqual(len(congreso.seleccionar(self.filas, ["pelosi", "gottheimer"])), 5)

    def test_solo_ptr_salvo_que_se_pida_todo(self):
        ptrs = congreso.seleccionar(self.filas)
        self.assertTrue(all(r["tipo"] == "P" for r in ptrs))
        todo = congreso.seleccionar(self.filas, tipo=None)
        self.assertGreater(len(todo), len(ptrs))
        otro = next(r for r in todo if r["tipo"] == "C")
        self.assertIn("/financial-pdfs/2026/", otro["url"])
        self.assertEqual(otro["tipo_nombre"], "informe de candidato")

    def test_desde_y_mas_reciente_primero(self):
        recientes = congreso.seleccionar(self.filas, desde="2026-10-07")
        self.assertTrue({r["presentado"] for r in recientes} <= {"2026-10-07", "2026-10-12"})
        self.assertEqual(recientes[0]["presentado"], "2026-10-12")
        self.assertIn("Salazar", [r["apellido"] for r in recientes])

    def test_lee_el_xml_del_zip_o_suelto_y_la_carpeta(self):
        with zipfile.ZipFile(ZIP) as z:
            crudo = z.read("2026FD.xml")
        self.assertTrue(crudo.startswith(b"\xef\xbb\xbf"))    # el archivo del Clerk lleva BOM
        self.assertEqual(len(congreso.parsear_indice(congreso.bytes_del_indice(crudo), 2026)), len(self.filas))
        self.assertEqual(len(congreso.cargar_indice(2026, offline=DIR)), len(self.filas))
        with self.assertRaises(comun.KemetError):
            congreso.parsear_indice(b"no es xml", 2026)
        with self.assertRaises(comun.KemetError):
            congreso.cargar_indice(2019, offline=DIR)

    def test_fechas(self):
        self.assertEqual(congreso.iso("8/21/2026"), "2026-08-21")
        self.assertEqual(congreso.iso("6/17/27"), "2027-06-17")
        self.assertIsNone(congreso.iso("13/45/2026"))


class LeerUnPtr(Base):
    def test_las_calls_de_bloom_energy(self):
        inf = congreso.parsear_ptr(texto("ptr-20035143.txt"))
        self.assertEqual(inf["miembro"], "Hon. Nancy Pelosi")
        self.assertEqual(inf["estatus"], "Member")
        self.assertEqual(inf["distrito"], "CA11")
        self.assertEqual(inf["doc_id"], "20035143")
        self.assertEqual(inf["presentado"], "2026-08-21")            # de la firma digital
        self.assertEqual(len(inf["operaciones"]), 7)
        calls = [o for o in inf["operaciones"] if o["ticker"] == "BE" and o["tipo_activo"] == "OP"]
        self.assertEqual(len(calls), 2)
        grande = calls[0]
        self.assertEqual(grande["titular"], "SP")
        self.assertEqual(grande["titular_nombre"], "cónyuge")
        self.assertEqual(grande["tipo"], "P")
        self.assertEqual(grande["tipo_nombre"], "compra")
        self.assertEqual(grande["fecha"], "2026-07-24")
        self.assertEqual(grande["notificado"], "2026-07-24")
        self.assertEqual(grande["importe_original"], "$1,000,001 - $5,000,000")
        self.assertEqual(grande["importe"], "de 1.000.001 a 5.000.000 $")
        self.assertEqual((grande["importe_min"], grande["importe_max"]), (1000001, 5000000))
        self.assertEqual(grande["opcion"], {"contratos": 100, "clase": "call", "strike": 100.0, "vence": "2027-06-17", "ejercida": False})
        # declarada el 21/08 una operación del 24/07: 28 días, dentro de los 45
        self.assertEqual(grande["dias_retraso"], (datetime.date(2026, 8, 21) - datetime.date(2026, 7, 24)).days)
        self.assertEqual(grande["dias_retraso"], 28)
        self.assertFalse(grande["fuera_de_plazo"])
        self.assertEqual(grande["activo"], "Bloom Energy Corporation Class A Common Stock")
        acciones = [o for o in inf["operaciones"] if o["ticker"] == "BE" and o["tipo_activo"] == "ST"]
        self.assertEqual([o["acciones"] for o in acciones], [10000, 5000])
        llc = inf["operaciones"][-1]
        self.assertIsNone(llc["ticker"])
        self.assertEqual(llc["tipo_activo"], "AB")
        self.assertIn("luxury hotel", llc["descripcion"])

    def test_salida_en_espanol_y_tickers_vigilados(self):
        inf = congreso.parsear_ptr(texto("ptr-20035143.txt"))
        out = congreso.render_informe(inf, vigilar={"INTC"})
        self.assertIn("cónyuge, compra, Bloom Energy Corporation Class A Common Stock (BE): 100 opciones call con strike de 100 $ que vencen el "
                      "2027-06-17, de 1.000.001 a 5.000.000 $, operada el 2026-07-24, declarada 28 días después", out)
        self.assertIn("10.000 acciones", out)
        self.assertIn("INTC está en tu lista", out)
        self.assertIn("No es información privilegiada", out)
        self.assertIn("45 días", out)
        self.assertNotIn(chr(0x2014), out)
        for linea in out.splitlines():
            self.assertLessEqual(linea.count("·"), 1, linea)

    def test_cuenta_conjunta_y_venta_parcial(self):
        inf = congreso.parsear_ptr(texto("ptr-20035590.txt"))
        self.assertEqual([(o["ticker"], o["titular"], o["tipo"], o["tipo_nombre"]) for o in inf["operaciones"]],
                         [("AMAT", "JT", "S", "venta"), ("MCD", "JT", "S (partial)", "venta parcial")])
        self.assertEqual(inf["operaciones"][0]["cuenta"], "Morgan Stanley - Select UMA Account # 1")
        self.assertEqual(inf["operaciones"][0]["notificado"], "2026-10-06")
        self.assertEqual(inf["operaciones"][0]["titular_nombre"], "cuenta conjunta")
        self.assertEqual(inf["operaciones"][0]["importe"], "de 1.001 a 15.000 $")

    def test_el_propio_miembro_y_columnas_pegadas(self):
        inf = congreso.parsear_ptr(texto("ptr-20035562-excerpt.txt"))
        self.assertEqual([o["ticker"] for o in inf["operaciones"]], ["BRK.B", "BIIB", "BA", "BEP", "CVX", "CB", "GLW", "IBM"])
        self.assertTrue(all(o["titular"] == "" and o["titular_nombre"] == "el propio miembro" for o in inf["operaciones"]))
        glw = inf["operaciones"][6]      # "Corning Incorporated Common Stock P": el tipo pegado al activo
        self.assertEqual((glw["tipo"], glw["activo"]), ("P", "Corning Incorporated Common Stock"))
        self.assertEqual(inf["operaciones"][7]["activo"], "International Business Machines Corporation Common Stock")

    def test_saltos_de_pagina_ejercicios_y_canjes(self):
        inf = congreso.parsear_ptr(texto("ptr-20033725-excerpt.txt"))
        por = {o["ticker"]: o for o in inf["operaciones"]}
        self.assertEqual(sorted(por), ["NVDA", "PYPL", "TEM", "VSNT", "VST"])
        tem = por["TEM"]                  # la fila la parte una cabecera de página
        self.assertEqual(tem["activo"], "Tempus AI, Inc. - Class A Common Stock")
        self.assertEqual(tem["importe"], "de 50.001 a 100.000 $")
        self.assertTrue(tem["opcion"]["ejercida"])
        self.assertEqual(tem["opcion"]["strike"], 20.0)
        self.assertEqual(por["PYPL"]["fecha"], "2025-12-30")
        self.assertEqual(por["PYPL"]["acciones"], 5000)
        self.assertEqual(por["VSNT"]["tipo_nombre"], "canje")
        self.assertEqual(por["VSNT"]["importe"], "15 $")

    def test_fuera_de_plazo(self):
        inf = congreso.parsear_ptr(texto("ptr-20035590.txt"), presentado="2026-11-15")
        self.assertTrue(all(o["fuera_de_plazo"] for o in inf["operaciones"]))
        self.assertIn("FUERA DE PLAZO", congreso.render_informe(inf))


class Cli(Base):
    def test_index_por_miembro_y_escribir(self):
        code, out, err = run(["index", "--miembro", "pelosi", "--anio", "2026", "--offline", ZIP, "--ahora", "2026-11-11 16:30", "--escribir"])
        self.assertEqual(code, 0, err)
        self.assertIn("CONGRESO, índice 2026 del House Clerk, 4 declaraciones de pelosi · 22:30 Madrid / 16:30 NY", out)
        self.assertIn("2026-08-21  Hon. Nancy Pelosi            CA11  P    doc 20035143", out)
        self.assertIn("No es información privilegiada", out)
        p = os.path.join(self.kemet, "congreso.json")
        with open(p, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["generado"], "2026-11-11T21:30:00Z")
        self.assertIn("House Clerk", doc["fuente"])
        self.assertEqual(doc["comando"], "index")
        self.assertEqual([d["doc_id"] for d in doc["declaraciones"]], ["20035553", "20035143", "20034836", "20033725"])
        code, out, _ = run(["index", "--miembro", "nadie", "--anio", "2026", "--offline", ZIP])
        self.assertEqual(code, 1)
        self.assertIn("Ninguna declaración coincide", out)

    def test_ptr_sin_red_desde_la_carpeta_y_escribir(self):
        code, out, err = run(["ptr", "20035143", "--anio", "2026", "--offline", DIR, "--ahora", "2026-11-11 16:30", "--escribir"])
        self.assertEqual(code, 0, err)
        self.assertIn("Hon. Nancy Pelosi (CA11), Member. PTR 20035143, presentado el 2026-08-21.", out)
        self.assertIn("declarada 28 días después", out)
        with open(os.path.join(self.kemet, "congreso.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["comando"], "ptr")
        self.assertEqual(len(doc["informes"][0]["operaciones"]), 7)
        self.assertEqual(doc["informes"][0]["url"], "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/20035143.pdf")
        code, _, err = run(["ptr", "99999999", "--anio", "2026", "--offline", DIR])
        self.assertEqual(code, 2)
        self.assertIn("ptr-99999999.txt", err)

    def test_texto_y_json(self):
        ruta = os.path.join(DIR, "ptr-20035143.txt")
        code, out, _ = run(["texto", ruta, "--tickers", "BE"])
        self.assertEqual(code, 0)
        self.assertIn("BE está en tu lista", out)
        code, out, _ = run(["texto", ruta, "--json"])
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertEqual(len(doc["informes"][0]["operaciones"]), 7)

    def test_recientes_marca_nuevos_una_sola_vez(self):
        base = ["recientes", "--dias", "45", "--miembro", "pelosi", "--anio", "2026", "--offline", ZIP, "--ahora", "2026-10-13 09:00"]
        code, out, err = run(base + ["--escribir"])
        self.assertEqual(code, 0, err)
        self.assertIn("PTR de los últimos 45 días (desde el 2026-08-29) de pelosi: 1, 1 sin ver", out)
        self.assertIn("NUEVO 2026-10-02  Hon. Nancy Pelosi", out)
        self.assertNotIn("20035143", out)                              # el de agosto queda fuera de los 45 días
        estado = os.path.join(self.kemet, "estado", "congreso.json")
        self.assertTrue(os.path.isfile(estado))
        with open(estado, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["vistos"], ["20035553"])
        with open(os.path.join(self.kemet, "congreso.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["nuevas"], ["20035553"])
        self.assertEqual(doc["dias"], 45)
        code, out, _ = run(base)
        self.assertEqual(code, 0)
        self.assertIn(": 1, 0 sin ver", out)
        self.assertNotIn("NUEVO", out)
        self.assertEqual(congreso.nuevos(congreso.seleccionar(congreso.cargar_indice(2026, offline=ZIP), ["pelosi"]),
                                         {"vistos": ["20033725", "20034836", "20035553"]})[0]["doc_id"], "20035143")

    def test_recientes_sin_nada(self):
        code, out, _ = run(["recientes", "--dias", "5", "--miembro", "pelosi", "--anio", "2026", "--offline", ZIP, "--ahora", "2026-11-11 16:30"])
        self.assertEqual(code, 1)
        self.assertIn("Nada presentado en ese plazo", out)

    def test_recientes_leer_sin_red_toma_el_texto_de_la_carpeta(self):
        comun.escribir_json(os.path.join(self.kemet, "watchlist.json"), {"aciertos": [{"simbolo": "AMAT"}]})
        code, out, err = run(["recientes", "--dias", "7", "--miembro", "gottheimer", "--anio", "2026", "--offline", DIR,
                              "--ahora", "2026-10-13 09:00", "--leer"])
        self.assertEqual(code, 0, err)
        self.assertIn("NUEVO 2026-10-07  Hon. Josh Gottheimer", out)
        self.assertIn("Hon. Josh Gottheimer (NJ05), Member. PTR 20035590, presentado el 2026-10-07.", out)
        self.assertIn("AMAT está en tu lista", out)


if __name__ == "__main__":
    unittest.main()
