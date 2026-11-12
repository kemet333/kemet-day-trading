"""kemet-resultados: los hechos XBRL reales de Apple y Coca-Cola. Sin red.

Fixtures en tests/fixtures/kemet-resultados/: copia tal cual de tests/fixtures/trader-analyst/ del pack de referencia
day-trader-skill (MIT, Jake Schincariol): company_tickers.json recortado a AAPL, KO y BAC; companyfacts y submissions
reales de Apple (CIK 320193) y Coca-Cola (CIK 21344) leídos de EDGAR en octubre de 2026; el index.json del 8-K de
resultados de Apple. El flujo de caja acumulado se prueba con un fragmento sintético dentro de este archivo."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _load import FIX, load  # noqa: E402

resultados = load("kemet-resultados", "resultados")
comun = sys.modules["comun"]
DIR = os.path.join(FIX, "kemet-resultados")
AHORA = "2026-11-11 16:30"


def companyfacts(cik):
    with open(os.path.join(DIR, "companyfacts-CIK%s.json" % cik), encoding="utf-8") as fh:
        return json.load(fh)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = resultados.main(argv)
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="kemet-resultados-")
        self.kemet = os.path.join(self.dir, "kemet")
        self._kemet_dir = comun.KEMET_DIR
        comun.KEMET_DIR = self.kemet
        self._ua = os.environ.pop("SEC_USER_AGENT", None)

    def tearDown(self):
        comun.KEMET_DIR = self._kemet_dir
        if self._ua is not None:
            os.environ["SEC_USER_AGENT"] = self._ua
        shutil.rmtree(self.dir, ignore_errors=True)


class Cik(Base):
    def test_cik_desde_el_ticker(self):
        ciks = resultados.ciks_por_ticker(resultados.Edgar(offline=DIR))
        self.assertEqual(ciks["AAPL"], ("0000320193", "Apple Inc."))
        self.assertEqual(ciks["KO"], ("0000021344", "COCA COLA CO"))
        self.assertEqual(ciks["BAC"][1], "BANK OF AMERICA CORP")      # el /DE/ del título se limpia

    def test_ticker_sin_cik(self):
        code, _, err = run(["ZZZZ", "--offline", DIR, "--ahora", AHORA])
        self.assertEqual(code, 2)
        self.assertIn("no tiene CIK para ZZZZ", err)


class Apple(Base):
    def setUp(self):
        super().setUp()
        self.r = resultados.analizar(companyfacts("0000320193"), trimestres=8)

    def test_ultimo_trimestre_a_mano(self):
        t = self.r["trimestres"][0]
        self.assertEqual(t["fin"], "2026-06-27")
        self.assertEqual(t["fiscal"], "T3 2026")
        self.assertEqual(t["ingresos"], 109417000000)
        self.assertEqual(t["beneficio_neto"], 29789000000)
        self.assertEqual(t["bpa_diluido"], 2.02)
        # interanual: 109.417 frente a 94.036 del trimestre cerrado el 2025-06-28 = +16,4 %
        self.assertEqual(t["ingresos_interanual"], round(100.0 * (109417 - 94036) / 94036, 1))
        self.assertEqual(t["ingresos_interanual"], 16.4)
        # BPA 2,02 frente a 1,57 = +28,7 %
        self.assertEqual(t["bpa_interanual"], round(100.0 * (2.02 - 1.57) / 1.57, 1))
        self.assertEqual(t["bpa_interanual"], 28.7)
        # márgenes: bruto 54.770 / 109.417, neto 29.789 / 109.417
        self.assertEqual(t["margen_bruto"], round(100.0 * 54770 / 109417, 1))
        self.assertEqual(t["margen_neto"], 27.2)
        self.assertEqual(t["margen_operativo"], 32.6)
        self.assertFalse(t["derivado"])
        self.assertIsNone(t["flujo_caja_operativo"])                   # Apple no lo trae en este fixture

    def test_ocho_trimestres_y_etiquetas_de_la_primera_presentacion(self):
        self.assertEqual(len(self.r["trimestres"]), 8)
        self.assertEqual([t["fiscal"] for t in self.r["trimestres"]][:6],
                         ["T3 2026", "T2 2026", "T1 2026", "T4 2025", "T3 2025", "T2 2025"])

    def test_cuarto_trimestre_derivado_del_10k(self):
        t4 = next(t for t in self.r["trimestres"] if t["fin"] == "2025-09-27")
        self.assertTrue(t4["derivado"])
        # ejercicio 2025 416.161 menos T1 124.300, T2 95.359 y T3 94.036
        self.assertEqual(t4["ingresos"], 416161000000 - 124300000000 - 95359000000 - 94036000000)
        self.assertEqual(t4["ingresos"], 102466000000)
        self.assertEqual(t4["ingresos_interanual"], round(100.0 * (102466 - 94930) / 94930, 1))

    def test_ultimos_cuatro_trimestres(self):
        suma = sum(t["ingresos"] for t in self.r["trimestres"][:4])
        self.assertEqual(self.r["ultimos_4"]["ingresos"], suma)
        self.assertEqual(self.r["ultimos_4"]["ingresos"], 466823000000)
        self.assertEqual(self.r["ultimos_4"]["beneficio_neto"], 128930000000)
        self.assertEqual(self.r["ultimos_4"]["bpa_diluido"], 8.71)

    def test_que_cambio_en_espanol(self):
        lineas = resultados.cambios(self.r)
        self.assertIn("ingresos 109.417 M$ (+16,4 % interanual)", lineas[0])
        self.assertIn("BPA diluido 2,02 $ (+28,7 %)", lineas[0])
        self.assertTrue(any(l.startswith("Margen bruto 50,1 % (+0,8 puntos") for l in lineas))

    def test_manda_la_reexpresion_pero_la_etiqueta_es_la_primera(self):
        hechos = [
            {"start": "2025-01-01", "end": "2025-03-31", "val": 100, "fy": 2025, "fp": "Q1", "form": "10-Q", "filed": "2025-05-01", "accn": "a"},
            {"start": "2025-01-01", "end": "2025-03-31", "val": 90, "fy": 2026, "fp": "Q1", "form": "10-Q", "filed": "2026-05-01", "accn": "b"},
            {"start": "2025-01-01", "end": "2025-03-31", "val": 1, "fy": 2025, "fp": "Q1", "form": "8-K", "filed": "2025-04-20", "accn": "c"},
        ]
        q = resultados.trimestral(hechos)
        self.assertEqual(q["2025-03-31"]["valor"], 90)
        self.assertEqual((q["2025-03-31"]["fy"], q["2025-03-31"]["fp"]), (2025, "Q1"))


class FlujoDeCaja(Base):
    def test_acumulado_del_anio_a_trimestres(self):
        """Sintético: la SEC publica el flujo de caja acumulado (T1, semestre, nueve meses, año); el trimestre es la diferencia."""
        hechos = [
            {"start": "2025-01-01", "end": "2025-03-31", "val": 100, "fy": 2025, "fp": "Q1", "form": "10-Q", "filed": "2025-05-01", "accn": "a"},
            {"start": "2025-01-01", "end": "2025-06-30", "val": 250, "fy": 2025, "fp": "Q2", "form": "10-Q", "filed": "2025-08-01", "accn": "b"},
            {"start": "2025-01-01", "end": "2025-09-30", "val": 420, "fy": 2025, "fp": "Q3", "form": "10-Q", "filed": "2025-11-01", "accn": "c"},
            {"start": "2025-01-01", "end": "2025-12-31", "val": 600, "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2026-02-01", "accn": "d"},
        ]
        q = resultados.trimestral_acumulado(hechos)
        self.assertEqual({k: v["valor"] for k, v in q.items()}, {"2025-03-31": 100, "2025-06-30": 150, "2025-09-30": 170, "2025-12-31": 180})
        self.assertFalse(q["2025-03-31"]["derivado"])
        self.assertTrue(q["2025-12-31"]["derivado"])


class Informes(Base):
    def test_ultimo_10q_y_nota_de_prensa(self):
        with open(os.path.join(DIR, "submissions-CIK0000320193.json"), encoding="utf-8") as fh:
            sub = json.load(fh)
        inf = resultados.ultimos_informes(sub, "0000320193", resultados.Edgar(offline=DIR))
        self.assertEqual(inf["informe"]["formulario"], "10-Q")
        self.assertEqual(inf["informe"]["periodo"], "2026-06-27")
        self.assertTrue(inf["informe"]["url"].endswith("/000032019326000020/aapl-20260627.htm"))
        e = inf["resultados_8k"]
        self.assertEqual(e["presentado"], "2026-07-30")
        self.assertEqual(e["anexo"], "https://www.sec.gov/Archives/edgar/data/320193/000032019326000018/a8-kex991q3202606272026.htm")

    def test_proximo_informe_estimado(self):
        import datetime as dt
        with open(os.path.join(DIR, "submissions-CIK0000320193.json"), encoding="utf-8") as fh:
            sub = json.load(fh)
        inf = resultados.ultimos_informes(sub, "0000320193")
        # el fixture solo trae un 10-Q: la estimación es 91 días después del 2026-07-31 y el 11/11 ya pasó
        p = resultados.proximo_informe(sub, inf, dt.date(2026, 11, 11), "T3")
        self.assertEqual(p["estimado"], "2026-10-30")
        self.assertEqual(p["formulario"], "10-K")                      # tras el T3 toca el 10-K
        self.assertEqual(p["dias"], -12)
        self.assertTrue(p["estimacion"])
        # con el mismo informe del año pasado en la lista, su fecha más 52 semanas
        sub2 = json.loads(json.dumps(sub))
        rec = sub2["filings"]["recent"]
        for col in rec:
            rec[col].append({"form": "10-K", "filingDate": "2025-10-31", "reportDate": "2025-09-27", "accessionNumber": "0000320193-25-000079",
                             "primaryDocument": "aapl-20250927.htm", "items": ""}.get(col, ""))
        p2 = resultados.proximo_informe(sub2, inf, dt.date(2026, 10, 1), "T3")
        self.assertEqual(p2["estimado"], "2026-10-30")
        self.assertIn("del año pasado", p2["base"])
        self.assertEqual(p2["dias"], 29)

    def test_nombres_de_anexos_vistos_en_edgar(self):
        pick = resultados.nombre_anexo
        self.assertEqual(pick(["axp-20260724.htm", "q226exhibit991.htm", "q226exhibit992.htm", "R1.htm"], "axp-20260724.htm"), "q226exhibit991.htm")
        self.assertEqual(pick(["a2026q2earningsreleaseex-9.htm", "ko-20260728.htm"], "ko-20260728.htm"), "a2026q2earningsreleaseex-9.htm")
        self.assertIsNone(pick(["only-8k.htm"], "only-8k.htm"))


class CocaCola(Base):
    def test_avisa_cuando_los_hechos_van_por_detras_del_10q(self):
        code, out, err = run(["KO", "--offline", DIR, "--ahora", AHORA])
        self.assertEqual(code, 0, err)
        self.assertIn("RESULTADOS KO, COCA COLA CO", out)
        self.assertIn("AVISO: los hechos XBRL de la SEC llegan hasta el 2026-04-03, pero hay un 10-Q del periodo cerrado el 2026-07-03 "
                      "presentado el 2026-07-29", out)

    def test_senala_el_beneficio_por_encima_del_operativo(self):
        r = {"trimestres": [{"fin": "2026-06-30", "fiscal": "T2 2026", "derivado": False, "ingresos": 100.0, "beneficio_neto": 90.0,
                             "resultado_operativo": 30.0, "bpa_diluido": 1.0, "flujo_caja_operativo": None, "ingresos_interanual": 10.0,
                             "beneficio_neto_interanual": 200.0, "bpa_interanual": 200.0, "margen_bruto": None, "margen_operativo": 30.0,
                             "margen_neto": 90.0}]}
        self.assertTrue(any("supera el resultado operativo" in l for l in resultados.cambios(r)))


class Cli(Base):
    def test_sin_user_agent_lo_pide_y_para(self):
        code, out, err = run(["AAPL", "--ahora", AHORA])
        self.assertEqual(code, 2)
        self.assertIn("User-Agent", err)
        self.assertIn("sec_user_agent", err)
        self.assertEqual(out, "")
        self.assertIsNone(resultados.user_agent("Nombre Apellido correo@ejemplo.com"))   # el marcador no vale
        self.assertIsNone(resultados.user_agent("sin arroba"))
        self.assertEqual(resultados.user_agent("Diego Kemet diego@dominio.com"), "Diego Kemet diego@dominio.com")

    def test_user_agent_desde_config(self):
        comun.escribir_json(os.path.join(self.kemet, "config.json"), {"sec_user_agent": "Diego Kemet diego@dominio.com"})
        self.assertEqual(resultados.user_agent(), "Diego Kemet diego@dominio.com")

    def test_tabla_en_espanol_y_escribir(self):
        code, out, err = run(["AAPL", "--trimestres", "8", "--offline", DIR, "--ahora", AHORA, "--escribir"])
        self.assertEqual(code, 0, err)
        self.assertIn("RESULTADOS AAPL, Apple Inc., CIK 0000320193 · 22:30 Madrid / 16:30 NY", out)
        self.assertIn("2026-06-27  T3 2026       109.417    +16,4 %   50,1 %   32,6 %   27,2 %     29.789     2,02    +28,7 %", out)
        self.assertIn("derivado", out)
        self.assertIn("Últimos cuatro trimestres: ingresos 466.823 M$, beneficio neto 128.930 M$, BPA diluido 8,71 $.", out)
        self.assertIn("Próximo informe: por el calendario tocaba un 10-K hacia el 2026-10-30", out)
        self.assertNotIn(chr(0x2014), out)
        p = os.path.join(self.kemet, "resultados.json")
        self.assertTrue(os.path.isfile(p))
        with open(p, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["generado"], "2026-11-11T21:30:00Z")
        self.assertIn("SEC EDGAR", doc["fuente"])
        self.assertEqual(doc["empresas"][0]["ticker"], "AAPL")
        self.assertEqual(len(doc["empresas"][0]["resultado"]["trimestres"]), 8)
        self.assertEqual(doc["empresas"][0]["proximo"]["estimado"], "2026-10-30")

    def test_metricas_una_fila_por_empresa(self):
        ruta = os.path.join(self.kemet, "metricas.json")
        code, out, err = run(["AAPL", "KO", "--offline", DIR, "--ahora", AHORA, "--metricas", ruta])
        self.assertEqual(code, 0, err)
        with open(ruta, encoding="utf-8") as fh:
            datos = json.load(fh)
        filas = {r["ticker"]: r for r in datos["empresas"]}
        self.assertEqual(sorted(filas), ["AAPL", "KO"])
        self.assertEqual(filas["AAPL"]["bpa_12m"], 8.71)
        self.assertEqual(filas["AAPL"]["ingresos_interanual"], 16.4)
        self.assertEqual(filas["KO"]["fin_periodo"], "2026-04-03")
        self.assertEqual(datos["fecha"], "2026-11-11")
        self.assertIn("Escrito", out)
        # el ejemplo de la carpeta tiene las mismas claves
        with open(os.path.join(os.path.dirname(resultados.__file__), "metricas.example.json"), encoding="utf-8") as fh:
            ejemplo = json.load(fh)
        self.assertEqual(sorted(ejemplo["empresas"][0]), sorted(filas["AAPL"]))

    def test_json(self):
        code, out, err = run(["AAPL", "--offline", DIR, "--json", "--trimestres", "4", "--ahora", AHORA])
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        self.assertEqual(len(doc["empresas"][0]["resultado"]["trimestres"]), 4)
        self.assertEqual(doc["empresas"][0]["resultado"]["conceptos"]["ingresos"], ["RevenueFromContractWithCustomerExcludingAssessedTax"])


if __name__ == "__main__":
    unittest.main()
