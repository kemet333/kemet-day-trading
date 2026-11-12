"""kemet-diario: el CSV sintético de la carpeta (22 operaciones inventadas, del 2 al 11 de noviembre de 2026) y la revisión 3/2/1. Sin red."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _load import ROOT, load  # noqa: E402

diario = load("kemet-diario", "diario")
comun = sys.modules["comun"]
CSV = os.path.join(ROOT, "kemet-diario", "diario.example.csv")
CONFIG = {"mercado": "NQ", "firma": "apex", "cuenta": "eod-pa-50", "cuenta_nombre": "Apex Trader Funding · 50K EOD fondeada (PA)",
          "fase": "financiada", "drawdown": 2000, "drawdown_tipo": "eod_trailing", "limite_diario_firma": 1000, "max_micro": 100, "max_mini": 10,
          "hora_limite": "16:59", "hora_limite_tz": "America/New_York", "noticias": "permitido", "consistencia": "mejor día ≤ 50% del beneficio para cobrar",
          "perdida_max_dia": 500, "perdida_max_dia_origen": "regla-kemet", "fallos_y_paras": 3, "semaforo": "verde",
          "sin_entradas_antes": "09:45", "sin_entradas_despues": "15:00", "plano_a": "15:55", "zona_usuario": "Europe/Madrid", "papel": True,
          "comprobado": "30/10/2026", "fuente": "https://apextraderfunding.com/"}


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = diario.main(argv)
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="kemet-diario-")
        self.kemet = os.path.join(self.dir, "kemet")
        comun.KEMET_DIR = self.kemet
        comun.escribir_json(os.path.join(self.kemet, "config.json"), CONFIG)
        comun.escribir_json(os.path.join(self.kemet, "agenda.json"), {"fecha": "2026-11-06", "datos": [{"hora": "08:30", "nombre": "Empleo (NFP)", "fuerte": True}]})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def revisar(self, *extra):
        code, out, err = run(["revisar", CSV, "--ahora", "2026-11-11 16:30", "--json"] + list(extra))
        self.assertIn(code, (0, 1), err)
        return code, json.loads(out)


class TestDiario(Base):
    def test_cuenta_las_infracciones(self):
        code, doc = self.revisar()
        self.assertEqual(code, 1)
        self.assertEqual(doc["operaciones"], 22)
        c = {k: v["n"] for k, v in doc["cumplimiento"].items()}
        self.assertEqual(c, {"sin_stop": 2, "apertura": 2, "ventana": 1, "tamano": 2, "stop_ampliado": 1, "plano": 1, "hora_limite": 0,
                             "horario": 0, "tras_limite": 1, "tras_tercer_fallo": 1})
        self.assertEqual(doc["cumplimiento"]["sin_stop"]["coste"], 360.0)
        self.assertEqual(doc["cumplimiento"]["apertura"]["coste"], 340.0)
        self.assertEqual(doc["cumplimiento"]["stop_ampliado"]["coste"], 100.0)       # 260 $ perdidos con 160 $ de stop
        self.assertEqual(doc["cumplimiento"]["ventana"]["operaciones"], ["06/11 08:35 largo 2 MNQ -180 $"])
        self.assertTrue(all(v["medible"] for v in doc["cumplimiento"].values()))

    def test_dias_y_franjas(self):
        code, doc = self.revisar()
        d = {x["fecha"]: x for x in doc["dias"]}
        self.assertEqual(len(d), 8)
        self.assertEqual((d["2026-11-04"]["pnl"], d["2026-11-04"]["supero_limite_a_las"], d["2026-11-04"]["tercera_perdida_a_las"]), (-760.0, "11:20", "11:20"))
        self.assertEqual((d["2026-11-04"]["tras_limite"], d["2026-11-04"]["tras_tercer_fallo"]), (1, 1))
        self.assertIsNone(d["2026-11-03"]["supero_limite_a_las"])
        f = {x["franja"]: x for x in doc["por_franja"]}
        self.assertEqual((f["apertura"]["operaciones"], f["apertura"]["pnl"]), (2, -340.0))
        self.assertEqual((f["mejor franja"]["operaciones"], f["mejor franja"]["pnl"]), (12, 1279.0))
        self.assertEqual(f["cierre"]["operaciones"], 1)

    def test_metricas(self):
        code, doc = self.revisar()
        m = doc["metricas"]
        self.assertTrue(m["suficientes"])
        self.assertEqual((m["operaciones"], m["resultado_total"], m["racha_perdidas"]), (22, 509.0, 5))
        self.assertAlmostEqual(m["ganancias_entre_perdidas"], 1.27, places=2)
        self.assertEqual(m["drawdown_usd"], 980.0)
        self.assertEqual(m["drawdown_cuenta"], 2000)

    def test_tres_dos_una(self):
        code, doc = self.revisar()
        self.assertEqual(len(doc["bien"]), 3)
        self.assertIn("20 de 22 operaciones con stop puesto", doc["bien"][0])
        self.assertEqual([r["clave"] for r in doc["rupturas"]], ["sin_stop", "apertura"])
        self.assertEqual(doc["rupturas"][0]["coste"], 360.0)
        self.assertTrue(doc["correccion"].startswith("Mañana el stop va en la plataforma"))
        code, out, err = run(["revisar", CSV, "--ahora", "2026-11-11 16:30"])
        self.assertIn("Tres cosas bien:", out)
        self.assertIn("Dos rupturas del plan:", out)
        self.assertIn("Una corrección para mañana:", out)
        self.assertNotIn("$ ·  ", out)

    def test_desde_hasta(self):
        code, doc = self.revisar("--desde", "2026-11-09", "--hasta", "2026-11-11")
        self.assertEqual(doc["operaciones"], 9)
        self.assertFalse(doc["metricas"]["suficientes"])
        self.assertEqual(doc["cumplimiento"]["ventana"]["medible"], False)        # la agenda es del 06/11, fuera del rango
        self.assertEqual(doc["cumplimiento"]["plano"]["n"], 1)

    def test_sin_config_no_mide_el_tamano(self):
        os.remove(os.path.join(self.kemet, "config.json"))
        code, doc = self.revisar()
        self.assertFalse(doc["cumplimiento"]["tamano"]["medible"])
        self.assertFalse(doc["cumplimiento"]["tras_limite"]["medible"])
        self.assertEqual(doc["cumplimiento"]["plano"]["n"], 1)                     # 15:55 por defecto en índices

    def test_csv_en_ingles_con_punto_y_coma_y_hora_de_madrid(self):
        ruta = os.path.join(self.dir, "ops.csv")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write("date;time_madrid;symbol;side;qty;entry;exit;stop\n")
            fh.write("11/11/2026;16:45;MNQZ6;long;1;28.429,75;28.547,00;28.312,50\n")
            fh.write("11/11/2026;20:15;MNQ;sell;2;28560;28540;28600\n")
        code, out, err = run(["revisar", ruta, "--json"])
        doc = json.loads(out)
        ops = doc["detalle"]
        self.assertEqual((ops[0]["hora"], ops[0]["lado"], ops[0]["mercado"], ops[0]["entrada"], ops[0]["pnl"]), ("10:45", "largo", "NQ", 28429.75, 234.5))
        self.assertEqual((ops[1]["hora"], ops[1]["lado"], ops[1]["pnl"]), ("14:15", "corto", 80.0))
        self.assertEqual(doc["cumplimiento"]["tamano"]["n"], 1)                     # 234,50 $ > 166,67 $

    def test_stop_habitual_y_errores(self):
        code, doc = self.revisar("--stop-habitual", "40")
        sin = [o for o in doc["detalle"] if o["stop"] is None]
        self.assertTrue(all(o["riesgo_usd"] == 160.0 and o.get("riesgo_supuesto") for o in sin))
        self.assertEqual(doc["cumplimiento"]["sin_stop"]["n"], 2)                   # siguen contando como sin stop
        code, out, err = run(["revisar", os.path.join(self.dir, "no-existe.csv")])
        self.assertEqual(code, 2)
        ruta = os.path.join(self.dir, "mal.csv")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write("a,b,c\n1,2,3\n")
        code, out, err = run(["revisar", ruta])
        self.assertEqual(code, 2)
        self.assertIn("faltan columnas", err)

    def test_plantilla(self):
        code, out, err = run(["plantilla"])
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0], "fecha,hora,simbolo,lado,contratos,entrada,salida,stop,pnl,nota")
        with open(CSV, encoding="utf-8") as fh:
            self.assertEqual(fh.readline().strip(), out.splitlines()[0])


# Un CSV de acciones (sintético salvo la fila del 11/11, que es la ruptura del rango de 15 min de TSLA del fixture real: entrada 393,08 a
# las 10:15, stop 389,51; el stop saltó a las 15:50) con una cuenta propia de 5.000 $, 50 $ por operación y 150 $ al día.
CSV_ACCIONES = """fecha,hora,simbolo,lado,acciones,entrada,salida,stop,pnl,nota
2026-11-10,09:40,AAPL,largo,10,270.10,268.90,268.50,,entrada en la apertura
2026-11-10,10:20,TSLA,largo,9,378.40,381.10,375.80,,
2026-11-11,10:15,TSLA,largo,9,393.08,389.51,389.51,-32.13,ruptura del rango de 15 min; stop a las 15:50
2026-11-11,13:05,TSLA,largo,20,391.00,389.50,388.00,,20 acciones: 60 $ de riesgo
"""
CONFIG_PROPIA = {"mercado": "TSLA", "tipo_cuenta": "propia", "cuenta": "propia", "cuenta_nombre": "Cuenta propia · 5.000 $", "presupuesto": 5000,
                 "perdida_max_dia": 150, "riesgo_por_operacion": 50, "fallos_y_paras": 3, "sin_entradas_antes": "09:45", "sin_entradas_despues": "15:00",
                 "plano_a": "15:55", "hora_limite": None, "papel": True}


class Acciones(Base):
    def setUp(self):
        super().setUp()
        comun.escribir_json(os.path.join(self.kemet, "config.json"), CONFIG_PROPIA)
        os.remove(os.path.join(self.kemet, "agenda.json"))
        self.csv = os.path.join(self.dir, "acciones.csv")
        with open(self.csv, "w", encoding="utf-8") as fh:
            fh.write(CSV_ACCIONES)

    def test_csv_de_acciones(self):
        code, out, err = run(["revisar", self.csv, "--ahora", "2026-11-11 16:30", "--json"])
        self.assertEqual(code, 1, err)
        doc = json.loads(out)
        self.assertEqual((doc["operaciones"], doc["mercado"], doc["config"]["riesgo_por_operacion"], doc["config"]["hora_limite_ny"]), (4, "TSLA", 50.0, None))
        ops = doc["detalle"]
        self.assertEqual([o["mercado"] for o in ops], ["AAPL", "TSLA", "TSLA", "TSLA"])
        self.assertEqual((ops[0]["contratos"], ops[0]["punto"], ops[0]["pnl"], ops[0]["riesgo_usd"]), (10, 1.0, -12.0, 16.0))   # 1 $ por acción, sin micros
        self.assertEqual((ops[1]["pnl"], ops[2]["pnl"], ops[3]["pnl"], ops[3]["riesgo_usd"]), (24.3, -32.13, -30.0, 60.0))
        c = {k: v["n"] for k, v in doc["cumplimiento"].items()}
        self.assertEqual((c["sin_stop"], c["apertura"], c["tamano"], c["stop_ampliado"], c["plano"], c["tras_limite"]), (0, 1, 1, 0, 0, 0))
        self.assertEqual(doc["cumplimiento"]["tamano"]["operaciones"], ["11/11 13:05 largo 20 TSLA -30 $"])
        self.assertFalse(doc["cumplimiento"]["hora_limite"]["medible"])     # una cuenta propia no tiene hora límite
        self.assertEqual([r["clave"] for r in doc["rupturas"]], ["apertura", "tamano"])
        self.assertIn("salió en el stop con -32 $", doc["bien"][0])
        code, out, err = run(["revisar", self.csv, "--ahora", "2026-11-11 16:30", "--desde", "2026-11-11"])
        self.assertIn("Mañana como mucho 15 acciones de TSLA con stop de 3,29 $ por acción (50,00 $ de riesgo por operación)", out)   # la mediana de los stops del CSV
        self.assertNotIn("MNQ", out)

    def test_plantilla_con_el_ejemplo_de_acciones(self):
        code, out, err = run(["plantilla"])
        self.assertEqual(out.splitlines()[0], "fecha,hora,simbolo,lado,contratos,entrada,salida,stop,pnl,nota")
        self.assertIn("2026-11-11,10:15,TSLA,largo,9,393.08,389.51,389.51,-32.13", out)


if __name__ == "__main__":
    unittest.main()
