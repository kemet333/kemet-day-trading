"""kemet-tamano: config con la regla Kemet, calc como el tamano.py anterior, orden con topes y rechazos. Sin red."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _load import load  # noqa: E402

tamano = load("kemet-tamano", "tamano")
comun = sys.modules["comun"]

# La ruptura del balance inicial del 11/11 (fixture real): primera vela de 5 min cerrada fuera del IB 28.199–28.426 después de
# las 10:30 es la de las 10:40 (cierre 28.429,75); stop en el punto medio del IB, objetivo 1R.
PLAN = {"generado": "2026-11-11T15:45:00Z", "mercado": "NQ", "micro": "MNQ", "fecha": "2026-11-11", "lado": "largo",
        "entrada": 28429.75, "hora_entrada": "10:45", "barra": 14, "stop": 28312.5, "regla_stop": "ib-medio",
        "objetivo": 28547.0, "regla_objetivo": "R:1", "riesgo_pts": 117.25, "riesgo_usd_micro": 234.5,
        "riesgo_usd_mini": 2345.0, "rr": 1.0, "plano_a": "15:55", "ib": {"alto": 28426.0, "bajo": 28199.0, "ancho": 227.0, "minutos": 60}}
# La misma entrada con un stop de 40 puntos (pts:40), para probar los topes con más micros.
PLAN_40 = dict(PLAN, stop=28389.75, regla_stop="pts:40", objetivo=28469.75, riesgo_pts=40.0, riesgo_usd_micro=80.0, riesgo_usd_mini=800.0)
CLAVES_CONFIG = {"mercado", "firma", "cuenta", "cuenta_nombre", "fase", "drawdown", "drawdown_tipo", "limite_diario_firma", "max_micro",
                 "max_mini", "hora_limite", "hora_limite_tz", "noticias", "consistencia", "perdida_max_dia", "perdida_max_dia_origen",
                 "fallos_y_paras", "semaforo", "sin_entradas_antes", "sin_entradas_despues", "plano_a", "zona_usuario", "papel",
                 "comprobado", "fuente"}


def run(argv):
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = tamano.main(argv)
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="kemet-tamano-")
        self.kemet = os.path.join(self.dir, "kemet")
        comun.KEMET_DIR = self.kemet

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def config(self, *extra):
        code, out, err = run(["config"] + list(extra))
        self.assertEqual(code, 0, err)
        with open(os.path.join(self.kemet, "config.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def plan(self, doc):
        comun.escribir_json(os.path.join(self.kemet, "plan.json"), doc)

    def dia(self, ops, fecha="2026-11-11"):
        comun.escribir_json(os.path.join(self.kemet, "estado", "dia.json"), {"fecha": fecha, "operaciones": ops})


class TestConfig(Base):
    def test_apex_50k_eod_financiada(self):
        cfg = self.config("--firma", "apex", "--cuenta", "eod-pa-50", "--mercado", "NQ")
        self.assertEqual(set(cfg), CLAVES_CONFIG)
        self.assertEqual(cfg["fase"], "financiada")
        self.assertEqual(cfg["drawdown"], 2000)
        self.assertEqual(cfg["limite_diario_firma"], 1000)
        self.assertEqual(cfg["perdida_max_dia"], 500)            # el cuarto del drawdown, menor que el límite diario
        self.assertEqual(cfg["perdida_max_dia_origen"], "regla-kemet")
        self.assertEqual(cfg["fallos_y_paras"], 3)
        self.assertEqual((cfg["hora_limite"], cfg["hora_limite_tz"]), ("16:59", "America/New_York"))
        self.assertEqual(cfg["plano_a"], "15:55")
        self.assertEqual((cfg["max_micro"], cfg["max_mini"]), (100, 10))
        self.assertEqual((cfg["sin_entradas_antes"], cfg["sin_entradas_despues"]), ("09:45", "15:00"))
        self.assertTrue(cfg["papel"])
        self.assertEqual(cfg["comprobado"], "30/10/2026")
        self.assertTrue(cfg["fuente"].startswith("https://apextraderfunding.com"))

    def test_limite_diario_menor_que_el_cuarto(self):
        # Ninguna de las 76 cuentas publica un límite diario menor que el cuarto del drawdown; se prueba con una cuenta sintética.
        firma = {"id": "x", "name": "Firma X", "checked": "01/11/2026", "source": "https://x"}
        cuenta = {"id": "y", "label": "Y 50K", "phase": "evaluation", "max_loss": 2000, "max_loss_type": "eod_trailing",
                  "daily_loss_limit": 300, "max_mini": 2, "max_micro": 20, "flat_by": {"time": "16:00", "tz": "America/New_York"}, "news": "permitido"}
        cfg, _ = tamano.construir_config(firma, cuenta, "NQ")
        self.assertEqual(cfg["perdida_max_dia"], 300)
        self.assertEqual(cfg["fase"], "evaluacion")
        cfg, _ = tamano.construir_config(firma, cuenta, "NQ", semaforo="ambar")
        self.assertEqual(cfg["perdida_max_dia"], 150)
        self.assertEqual(tamano.perdida_maxima_dia(2000, 300), (300, 500))
        self.assertEqual(tamano.perdida_maxima_dia(2000, None, "rojo"), (250, 500))

    def test_topstep_hora_limite_en_chicago(self):
        cfg = self.config("--firma", "topstep", "--cuenta", "combine-50", "--mercado", "NQ", "--plano-a", "16:30")
        self.assertEqual((cfg["hora_limite"], cfg["hora_limite_tz"]), ("15:10", "America/Chicago"))
        self.assertEqual(cfg["plano_a"], "16:05")                 # 15:10 Chicago = 16:10 NY, menos 5 minutos
        cfg = self.config("--firma", "topstep", "--cuenta", "combine-50", "--mercado", "NQ")
        self.assertEqual(cfg["plano_a"], "15:55")                 # la del contrato, ya es antes
        self.assertEqual(cfg["perdida_max_dia"], 500)

    def test_perdida_dia_del_usuario(self):
        cfg = self.config("--firma", "apex", "--cuenta", "eod-pa-50", "--perdida-dia", "900")
        self.assertEqual(cfg["perdida_max_dia"], 900)
        self.assertEqual(cfg["perdida_max_dia_origen"], "usuario")
        code, out, err = run(["calc", "--stop", "18"])
        self.assertIn("riesgo por operación: 300 $", out)
        self.assertIn("Contratos: 8 MNQ", out)

    def test_perdida_dia_por_encima_de_la_firma_se_rechaza(self):
        code, out, err = run(["config", "--firma", "apex", "--cuenta", "eod-pa-50", "--perdida-dia", "1200"])
        self.assertEqual(code, 2)
        self.assertIn("supera el límite diario de la firma", err)
        self.assertFalse(os.path.exists(os.path.join(self.kemet, "config.json")))

    def test_semaforo_ambar(self):
        cfg = self.config("--firma", "apex", "--cuenta", "eod-pa-50", "--semaforo", "ambar")
        self.assertEqual(cfg["perdida_max_dia"], 250)

    def test_cuenta_sin_tope_publicado(self):
        cfg = self.config("--firma", "topstep", "--cuenta", "xfa-50")
        self.assertIsNone(cfg["max_micro"])
        cfg = self.config("--firma", "topstep", "--cuenta", "xfa-50", "--max-micro", "6")
        self.assertEqual(cfg["max_micro"], 6)

    def test_listar(self):
        code, out, _ = run(["listar"])
        self.assertEqual(code, 0)
        self.assertIn("eod-pa-50", out)
        self.assertEqual(out.count("\n   "), 76)


class TestCalc(Base):
    def test_reproduce_el_tamano_anterior(self):
        code, out, _ = run(["calc", "--firma", "apex", "--cuenta", "eod-pa-50", "--mercado", "NQ", "--stop", "18"])
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[:5], [
            "Cuenta: Apex Trader Funding · 50K EOD · fondeada (PA)",
            "Drawdown 2.000 $ · límite diario de la firma 1.000 $ · regla Kemet: 25% del drawdown = 500 $",
            "Pérdida máxima de hoy (verde): 500 $ · riesgo por operación: 167 $ (tres fallos y paras)",
            "Stop 18 pts × 2 $/pt del MNQ = 36,00 $ por micro",
            "Contratos: 4 MNQ"])
        code, out, _ = run(["calc", "--firma", "topstep", "--cuenta", "combine-50", "--mercado", "ES", "--stop", "6", "--semaforo", "ambar"])
        self.assertIn("Pérdida máxima de hoy (ambar): 250 $ · riesgo por operación: 83 $", out)
        self.assertIn("Contratos: 2 MES", out)
        code, out, _ = run(["calc", "--drawdown", "2000", "--diario", "1000", "--mercado", "ES", "--stop", "6"])
        self.assertIn("Cuenta: propia", out)
        self.assertIn("Contratos: 5 MES", out)

    def test_stop_del_ejemplo_no_cabe_en_50k(self):
        code, out, _ = run(["calc", "--firma", "apex", "--cuenta", "eod-pa-50", "--mercado", "NQ", "--stop", "117.25"])
        self.assertEqual(code, 1)
        self.assertIn("Contratos: 0 MNQ · no cabe ninguno", out)

    def test_calc_desde_config(self):
        self.config("--firma", "apex", "--cuenta", "eod-pa-50")
        code, out, _ = run(["calc", "--stop", "18"])
        self.assertEqual(code, 0)
        self.assertIn("Contratos: 4 MNQ", out)

    def test_tope_de_la_cuenta(self):
        code, out, _ = run(["calc", "--firma", "apex", "--cuenta", "eod-pa-50", "--mercado", "NQ", "--stop", "0.5"])
        self.assertIn("Contratos: 100 MNQ (tope de la cuenta: 100)", out)


class TestOrden(Base):
    def test_en_50k_es_un_rechazo(self):
        self.config("--firma", "apex", "--cuenta", "eod-pa-50")
        self.plan(PLAN)
        code, out, _ = run(["orden", "--ahora", "2026-11-11 10:45", "--escribir"])
        self.assertEqual(code, 1)
        self.assertIn("Sin orden: un MNQ arriesga 234,50 $ al stop", out)
        self.assertFalse(os.path.exists(os.path.join(self.kemet, "orden.json")))

    def test_orden_escrita_con_el_contrato(self):
        self.config("--firma", "apex", "--cuenta", "eod-pa-150")
        self.plan(PLAN)
        code, out, _ = run(["orden", "--ahora", "2026-11-11 10:45", "--escribir"])
        self.assertEqual(code, 0, out)
        with open(os.path.join(self.kemet, "orden.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(set(doc), {"generado", "ordenes", "cuenta", "papel"})
        o = doc["ordenes"][0]
        self.assertEqual(set(o), {"simbolo", "lado", "contratos", "tipo", "precio", "stop", "objetivo", "riesgo_pts", "perdida_max_usd", "por_que", "plan"})
        self.assertEqual((o["simbolo"], o["lado"], o["contratos"], o["tipo"]), ("MNQ", "compra", 1, "stop"))
        self.assertEqual((o["precio"], o["stop"], o["objetivo"], o["riesgo_pts"], o["perdida_max_usd"]), (28429.75, 28312.5, 28547.0, 117.25, 234.5))
        self.assertIn("manda riesgo por operación", o["por_que"])
        self.assertTrue(doc["papel"])

    def test_respeta_max_micro(self):
        self.config("--firma", "apex", "--cuenta", "eod-pa-150", "--max-micro", "1")
        self.plan(PLAN_40)
        code, out, _ = run(["orden", "--ahora", "2026-11-11 10:40", "--json"])
        self.assertEqual(code, 0)
        t = json.loads(out)["tamano"]
        self.assertEqual((t["contratos"], t["manda"]), (1, "tope de la cuenta"))

    def test_respeta_lo_que_queda_del_dia(self):
        self.config("--firma", "apex", "--cuenta", "eod-pa-150")      # 1.000 $ al día
        self.plan(PLAN_40)
        self.dia([{"hora": "10:00", "simbolo": "MNQ", "lado": "compra", "contratos": 2, "riesgo_usd": 320.0, "resultado_usd": None, "cerrada": None},
                  {"hora": "09:50", "simbolo": "MNQ", "lado": "venta", "contratos": 2, "riesgo_usd": 320.0, "resultado_usd": -500.0, "cerrada": "09:58"}])
        code, out, _ = run(["orden", "--ahora", "2026-11-11 10:40", "--json"])
        self.assertEqual(code, 0)
        t = json.loads(out)["tamano"]
        self.assertEqual((t["riesgo_abierto"], t["perdida_realizada"], t["queda"]), (320.0, 500.0, 180.0))
        self.assertEqual((t["contratos"], t["manda"]), (2, "lo que queda del día"))
        # con menos margen, 0 contratos: rechazo
        self.dia([{"hora": "10:00", "simbolo": "MNQ", "lado": "compra", "contratos": 2, "riesgo_usd": 320.0, "resultado_usd": None, "cerrada": None},
                  {"hora": "09:50", "simbolo": "MNQ", "lado": "venta", "contratos": 2, "riesgo_usd": 320.0, "resultado_usd": -620.0, "cerrada": "09:58"}])
        code, out, _ = run(["orden", "--ahora", "2026-11-11 10:40", "--escribir"])
        self.assertEqual(code, 1)
        self.assertIn("el día está hecho", out)
        self.assertFalse(os.path.exists(os.path.join(self.kemet, "orden.json")))

    def test_dia_de_otra_fecha_no_cuenta(self):
        self.config("--firma", "apex", "--cuenta", "eod-pa-150")
        self.plan(PLAN_40)
        self.dia([{"hora": "10:00", "simbolo": "MNQ", "lado": "compra", "contratos": 2, "riesgo_usd": 900.0, "resultado_usd": None, "cerrada": None}], fecha="2026-11-10")
        code, out, _ = run(["orden", "--ahora", "2026-11-11 10:40", "--json"])
        self.assertEqual(json.loads(out)["tamano"]["contratos"], 4)

    def test_plan_de_otra_fecha(self):
        self.config("--firma", "apex", "--cuenta", "eod-pa-150")
        self.plan(dict(PLAN, fecha="2026-11-10"))
        code, out, _ = run(["orden", "--ahora", "2026-11-11 10:40"])
        self.assertEqual(code, 1)
        self.assertIn("el plan es del 2026-11-10 y hoy es 2026-11-11", out)

    def test_stop_del_lado_equivocado(self):
        self.config("--firma", "apex", "--cuenta", "eod-pa-150")
        self.plan(dict(PLAN, stop=28500.0, riesgo_pts=None))
        code, out, _ = run(["orden", "--ahora", "2026-11-11 10:40"])
        self.assertEqual(code, 1)
        self.assertIn("no está debajo de la entrada", out)

    def test_nota_de_minis(self):
        self.config("--firma", "apex", "--cuenta", "eod-pa-150")      # 333,33 $ por operación, hasta 17 minis
        self.plan(dict(PLAN, stop=28419.75, objetivo=28439.75, riesgo_pts=10.0, riesgo_usd_micro=20.0))
        code, out, _ = run(["orden", "--ahora", "2026-11-11 10:40", "--json"])
        t = json.loads(out)["tamano"]
        self.assertEqual(t["contratos"], 16)
        self.assertEqual(t["minis"], {"n": 1, "micros_sueltos": 6, "mini": "NQ"})
        self.assertIn("equivale a 1 NQ y 6 MNQ", json.loads(out)["orden"]["ordenes"][0]["por_que"])

    def test_sin_config_es_error(self):
        self.plan(PLAN_40)
        code, out, err = run(["orden", "--ahora", "2026-11-11 10:40"])
        self.assertEqual(code, 2)
        self.assertIn("config", err)


if __name__ == "__main__":
    unittest.main()
