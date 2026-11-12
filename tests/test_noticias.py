"""kemet-noticias sin red: el RSS de Yahoo y el Atom de EDGAR parseados con etiquetas, el orden por hora, lo visto una sola
vez, la agenda macro de kemet/agenda.json en la salida y los tickers de kemet/watchlist.json cuando no se dan.

Los fixtures de `tests/fixtures/kemet-noticias/` (yahoo-*.xml, sec-8-K-*.xml, chart-TSLA.json, company_tickers.json)
vienen tal cual del pack day-trader-skill de Jake Schincariol (MIT): feeds reales de Yahoo Finance y de la SEC de octubre
de 2026 (los titulares de TSLA son los del lunes 19/10/2026 por la mañana)."""
import datetime as dt
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

noticias = load("kemet-noticias", "noticias")
comun = noticias.comun

DIR = os.path.join(FIX, "kemet-noticias")
AHORA = "2026-10-14 00:00"   # medianoche en Nueva York (04:00 UTC): las 10 noticias de AAPL y KO del 13/10 caben en 24 horas


def crudo(nombre):
    with open(os.path.join(DIR, nombre), "rb") as fh:
        return fh.read()


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = noticias.main(argv)
    return code, out.getvalue(), err.getvalue()


class Feeds(unittest.TestCase):
    def test_rss_de_yahoo(self):
        items = noticias.parse_rss(crudo("yahoo-AAPL.xml"), "AAPL")
        self.assertEqual(len(items), 6)
        primero = items[0]
        self.assertEqual(primero["titulo"], "Apple may have a way to dominate the smart home space")
        self.assertEqual(primero["hora"], dt.datetime(2026, 10, 13, 19, 46, 52))      # UTC naive, como comun
        self.assertEqual(comun.hhmm(comun.a_ny(primero["hora"])), "15:46")
        self.assertTrue(primero["enlace"].startswith("https://finance.yahoo.com/"))
        self.assertTrue(primero["id"].startswith("rss:"))
        self.assertEqual(primero["fuente"], "Yahoo Finance")

    def test_atom_8k_de_edgar(self):
        items = noticias.parse_sec_atom(crudo("sec-8-K-0000320193.xml"), "AAPL")
        self.assertEqual([i["formulario"] for i in items], ["8-K/A", "8-K", "8-K"])
        res = items[1]
        self.assertEqual(res["items"], ["2.02", "9.01"])
        self.assertTrue(res["importante"])
        self.assertEqual(res["titulo"], "Apple Inc. presentó un 8-K: resultados")
        self.assertEqual(res["id"], "sec:0000320193-26-000018")
        self.assertIn("000032019326000018", res["enlace"])
        self.assertEqual(comun.iso(res["hora"]), "2026-07-30T20:30:28Z")                 # 16:30:28 NY
        self.assertEqual(items[0]["titulo"], "Apple Inc. presentó un 8-K/A: cambio de consejero o directivo")

    def test_horas(self):
        self.assertEqual(noticias.parse_tiempo("Tue, 13 Oct 2026 20:02:03 +0000").hour, 20)
        self.assertEqual(noticias.parse_tiempo("2026-09-01T16:30:35-04:00").hour, 20)
        self.assertIsNone(noticias.parse_tiempo("pronto"))
        self.assertEqual(noticias.simbolo_yahoo("BRK.B"), "BRK-B")

    def test_el_movimiento(self):
        m = noticias.parse_chart(crudo("chart-TSLA.json"), "TSLA")
        self.assertEqual((m["precio"], m["cierre_ayer"], m["pct"]), (366.48, 354.72, 3.31))
        self.assertEqual(comun.hhmm(comun.a_ny(m["hora"])), "10:52")
        linea = noticias.lineas_movimientos([m])[0]
        self.assertEqual(linea, "  TSLA   366,48 $  +3,31 % (cierre de ayer 354,72 $, a las 10:52 NY)  SE MUEVE")
        self.assertNotIn("SE MUEVE", noticias.lineas_movimientos([dict(m, pct=1.2)])[0])
        self.assertIn("SE MUEVE", noticias.lineas_movimientos([dict(m, pct=1.2)], pct=1.0)[0])
        with self.assertRaises(comun.KemetError):
            noticias.parse_chart(b'{"chart": {"result": null}}', "ZZZZ")


class Etiquetas(unittest.TestCase):
    def test_a_quien_toca_y_etiquetas(self):
        items = noticias.parse_rss(crudo("yahoo-KO.xml"), "KO")
        tickers = {"KO": "Coca-Cola", "CVX": "Chevron", "AAPL": "Apple"}
        noticias.etiquetar(items, tickers)
        por = {i["titulo"][:20]: i for i in items}
        chevron = por["Coca-Cola or Chevron"]
        self.assertEqual(chevron["toca"], ["CVX", "KO"])
        self.assertIn("dividendo", chevron["etiquetas"])
        self.assertEqual(por["Is Coca-Cola (KO) St"]["toca"], ["KO"])

    def test_un_8k_de_resultados_lleva_la_etiqueta(self):
        items = noticias.etiquetar(noticias.parse_sec_atom(crudo("sec-8-K-0000021344.xml"), "KO"), {"KO": None})
        self.assertEqual(items[0]["etiquetas"][0], "resultados")
        self.assertFalse(items[1]["importante"])                                           # 8.01 otros hechos

    def test_las_etiquetas_en_espanol(self):
        it = [{"id": "x", "fuente": "Yahoo Finance", "tipo": "titular", "ticker": "TSLA", "resumen": "", "enlace": "", "hora": None,
               "titulo": "Trading halted in XYZ after FDA approval; CEO resigns, lawsuit filed, futures rise before CPI, merger guidance cut"}]
        etiquetas = noticias.etiquetar(it, {"TSLA": None})[0]["etiquetas"]
        for e in ("guía", "demanda", "fusión", "dirección", "parada", "regulador", "macro"):
            self.assertIn(e, etiquetas)
        self.assertNotIn("earnings", etiquetas)

    def test_la_misma_historia_sale_una_vez(self):
        a = noticias.parse_rss(crudo("yahoo-AAPL.xml"), "AAPL")
        b = noticias.parse_rss(crudo("yahoo-AAPL.xml"), "GOOGL")
        items = noticias.sin_duplicados(noticias.etiquetar(a + b, {"AAPL": None, "GOOGL": None}))
        self.assertEqual(len(items), 6)
        self.assertEqual(items[0]["toca"], ["AAPL", "GOOGL"])


class ConKemetTemporal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kemet = os.path.join(self.tmp, "kemet")
        self._old = comun.KEMET_DIR
        comun.KEMET_DIR = self.kemet
        self._ua = os.environ.pop("SEC_USER_AGENT", None)

    def tearDown(self):
        comun.KEMET_DIR = self._old
        if self._ua is not None:
            os.environ["SEC_USER_AGENT"] = self._ua
        shutil.rmtree(self.tmp, ignore_errors=True)

    def escribe(self, nombre, doc):
        comun.escribir_json(nombre, doc)


class Comprobacion(ConKemetTemporal):
    def test_lo_nuevo_una_vez_y_lo_mas_reciente_primero(self):
        code, out, err = run(["--tickers", "AAPL,KO", "--horas", "24", "--json", "--offline", DIR, "--ahora", AHORA])
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        horas = [i["hora"] for i in doc["items"]]
        self.assertEqual(horas, sorted(horas, reverse=True))
        self.assertEqual(len(doc["items"]), 10)                                            # 6 de Apple y 4 de Coca-Cola; los 8-K son más viejos
        self.assertEqual(doc["tickers"], ["AAPL", "KO"])
        self.assertTrue(os.path.exists(os.path.join(self.kemet, "estado", "noticias.json")))
        code, out, _ = run(["--tickers", "AAPL", "KO", "--horas", "24", "--offline", DIR, "--ahora", AHORA])
        self.assertEqual(code, 1)
        self.assertIn("Nada nuevo en las últimas 24 horas.", out)
        code, out, _ = run(["--tickers", "AAPL", "--horas", "24", "--offline", DIR, "--ahora", AHORA, "--todo", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(len(json.loads(out)["items"]), 6)

    def test_los_8k_salen_con_una_ventana_ancha(self):
        code, out, err = run(["--tickers", "AAPL", "--horas", "2400", "--offline", DIR, "--ahora", AHORA, "--sin-movimiento"])
        self.assertEqual(code, 0, err)
        self.assertIn("! 30/07/2026 16:30  AAPL        EDGAR         Apple Inc. presentó un 8-K: resultados", out)
        self.assertIn("etiquetas: resultados", out)
        self.assertIn("No es asesoramiento financiero.", out)
        self.assertIn("06:00 Madrid / 00:00 NY", out)

    def test_la_manana_de_tsla_del_19_de_octubre(self):
        code, out, err = run(["--tickers", "TSLA", "--horas", "6", "--sin-edgar", "--sin-movimiento", "--offline", DIR, "--ahora", "2026-10-19 10:15"])
        self.assertEqual(code, 0, err)
        lineas = out.splitlines()
        self.assertEqual(len([l for l in lineas if l.startswith("  19/10/2026")]), 16)      # 18 en el feed, 2 después de las 10:15
        self.assertNotIn("10:32", out)
        self.assertIn("19/10/2026 08:04  TSLA        Yahoo Finance Tesla-SpaceX Merger Mania Strikes Wall Street Ahead of Earnings", out)
        i = next(k for k, l in enumerate(lineas) if "Merger Mania" in l)
        self.assertIn("etiquetas: resultados, fusión", lineas[i + 1])
        self.assertIn("Comprobado a las 10:15 NY.", out)
        self.assertTrue(lineas[0].startswith("Noticias de TSLA, lunes 19/10/2026, 16:15 Madrid / 10:15 NY"))
        self.assertNotIn("Nota: sin CIK", out)                                             # --sin-edgar no pide CIK
        # el movimiento, del gráfico bajado a las 10:52
        code, out, _ = run(["--tickers", "TSLA", "--horas", "6", "--sin-edgar", "--offline", DIR, "--ahora", "2026-10-19 10:52", "--sin-estado"])
        self.assertIn("  TSLA   366,48 $  +3,31 % (cierre de ayer 354,72 $, a las 10:52 NY)  SE MUEVE", out)
        self.assertEqual(len([l for l in out.splitlines() if l.startswith("  19/10/2026")]), 18)

    def test_la_agenda_del_dia_va_en_la_salida(self):
        self.escribe("agenda.json", {"fecha": "2026-10-19", "datos": [
            {"hora": "14:00", "nombre": "FOMC", "fuerte": True},
            {"hora": "08:30", "nombre": "Peticiones de desempleo", "fuerte": False},
            {"hora": "10:30", "nombre": "Inventarios EIA", "fuerte": False, "mercados": ["CL"]}]})
        code, out, _ = run(["--tickers", "TSLA", "--horas", "6", "--sin-edgar", "--sin-movimiento", "--offline", DIR, "--ahora", "2026-10-19 10:15", "--json"])
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertEqual([d["hora"] for d in doc["agenda"]], ["08:30", "10:30", "14:00"])      # ordenada por hora
        fomc = doc["agenda"][2]
        self.assertEqual((fomc["fuerte"], fomc["ventana"], fomc["pasado"], fomc["minutos"]), (True, "13:40 a 14:20", False, 225))
        self.assertEqual((doc["agenda"][0]["pasado"], doc["agenda"][1]["mercados"]), (True, ["CL"]))
        code, out, _ = run(["--tickers", "TSLA", "--horas", "6", "--sin-edgar", "--sin-movimiento", "--offline", DIR, "--ahora", "2026-10-19 10:15", "--todo"])
        self.assertIn("Agenda macro de hoy (kemet/agenda.json), hora de Nueva York:", out)
        self.assertIn("  14:00  FOMC                         fuerte        ventana sin operar 13:40 a 14:20  (dentro de 3 h 45 min)", out)
        self.assertIn("  10:30  Inventarios EIA              solo CL       ventana sin operar 10:20 a 10:40  (dentro de 15 min)", out)
        self.assertIn("(pasado)", out)
        self.assertNotIn("Nota: sin kemet/agenda.json", out)

    def test_la_agenda_de_otro_dia_no_se_ensena(self):
        self.escribe("agenda.json", {"fecha": "2026-10-16", "datos": [{"hora": "14:00", "nombre": "FOMC", "fuerte": True}]})
        code, out, _ = run(["--tickers", "TSLA", "--horas", "6", "--sin-edgar", "--sin-movimiento", "--offline", DIR, "--ahora", "2026-10-19 10:15"])
        self.assertNotIn("FOMC", out)
        self.assertIn("Nota: kemet/agenda.json es del 2026-10-16, no de hoy", out)
        code, out, _ = run(["--tickers", "TSLA", "--horas", "6", "--sin-edgar", "--sin-movimiento", "--offline", DIR, "--ahora", "2026-10-19 10:15", "--sin-estado"])
        self.assertIn("Nota: kemet/agenda.json es del 2026-10-16", out)

    def test_sin_tickers_toma_la_watchlist(self):
        self.escribe("watchlist.json", {"modo": "orb", "generado": "2026-10-13T14:15:00Z", "universo": 3, "escaneados": 3, "fallidos": 0,
                                        "aciertos": [{"simbolo": "KO", "regla": "orb", "precio": 93.9, "hora": "10:15", "detalle": "x"},
                                                     {"simbolo": "NQ", "regla": "ib-arriba", "precio": 28429.75, "hora": "10:45", "detalle": "x"}]})
        self.assertEqual(sorted(noticias.tickers_de_archivos()), ["KO"])                   # NQ es un futuro: sin titulares por ticker
        code, out, err = run(["--horas", "24", "--json", "--offline", DIR, "--ahora", AHORA, "--sin-estado"])
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        self.assertEqual(doc["tickers"], ["KO"])
        self.assertEqual({t for i in doc["items"] for t in i["toca"]}, {"KO"})
        self.assertFalse(os.path.exists(os.path.join(self.kemet, "estado", "noticias.json")))

    def test_sin_tickers_ni_watchlist_es_error(self):
        code, _, err = run(["--offline", DIR, "--ahora", AHORA])
        self.assertEqual(code, 2)
        self.assertIn("sin tickers", err)
        code, _, err = run(["--tickers", "NQ", "--offline", DIR, "--ahora", AHORA])
        self.assertEqual(code, 2)
        self.assertIn("no es un ticker de acciones", err)

    def test_edgar_pide_user_agent(self):
        self.assertIsNone(noticias.sec_user_agent(None))
        self.assertIsNone(noticias.sec_user_agent("Nombre correo@ejemplo.com"))
        self.assertEqual(noticias.sec_user_agent("Ada ada@example.org"), "Ada ada@example.org")
        self.escribe("config.json", {"mercado": "TSLA", "sec_user_agent": "Ada ada@example.org"})
        self.assertEqual(noticias.sec_user_agent(None), "Ada ada@example.org")
        with self.assertRaises(comun.KemetError):
            noticias.Descarga(None).get("https://www.sec.gov/x", "x", sec=True)

    def test_escribir_guarda_noticias_json(self):
        code, out, _ = run(["--tickers", "AAPL", "--horas", "2400", "--offline", DIR, "--ahora", AHORA, "--escribir", "--sin-estado"])
        self.assertEqual(code, 0)
        ruta = os.path.join(self.kemet, "noticias.json")
        self.assertIn("Escrito %s." % ruta, out)
        with open(ruta, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["generado"], "2026-10-14T04:00:00Z")
        self.assertIn("EDGAR", doc["fuente"])
        self.assertEqual(doc["items"][-1]["hora_ny"], "16:30")
        self.assertIn("agenda", doc)

    def test_lo_visto_se_olvida_a_los_30_dias(self):
        estado = {"vistos": {"viejo": "2026-08-01T00:00:00Z"}}
        ahora = comun.parse_ahora(AHORA)
        noticias.recordar([], estado, ahora)
        self.assertNotIn("viejo", estado["vistos"])
        self.assertEqual(estado["ultima_comprobacion"], "2026-10-14T04:00:00Z")


if __name__ == "__main__":
    unittest.main()
