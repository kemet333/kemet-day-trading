"""kemet-tamano: config con la regla Kemet, calc como el tamano.py anterior, orden con topes y rechazos; la cuenta propia y las
acciones (TSLA del 11/11/2026, ruptura del rango de 15 minutos del fixture real). Sin red."""
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
        self.assertEqual((cfg["max_micro"], cfg["max_mini"]), (20, 2))          # nivel 1 de la PA de 50K (Apex, 13/11/2026)
        self.assertEqual((cfg["sin_entradas_antes"], cfg["sin_entradas_despues"]), ("09:45", "15:00"))
        self.assertTrue(cfg["papel"])
        self.assertEqual(cfg["comprobado"], "13/11/2026")
        self.assertTrue(cfg["fuente"].startswith("https://apextraderfunding.com"))

    def test_limite_diario_menor_que_el_cuarto(self):
        # Ninguna de las 99 cuentas publica un límite diario menor que el cuarto del drawdown; se prueba con una cuenta sintética.
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
        self.assertEqual(out.count("\n   "), 99)


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
        self.assertIn("Contratos: 20 MNQ (tope de la cuenta: 20)", out)


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
        self.assertEqual(set(o), {"simbolo", "lado", "contratos", "tipo", "precio", "stop", "objetivo", "riesgo_pts", "perdida_max_usd", "por_que", "plan", "instrumento"})
        self.assertEqual(o["instrumento"], "futuro")
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


# TSLA, 11/11/2026 (fixture real): rango de 15 minutos 09:30–09:45 = 386,35 a 392,67; la primera vela de 5 min cerrada fuera es la de las
# 10:10, que cierra a las 10:15 en 393,08. Stop en el punto medio del rango (389,51), objetivo 1R (396,65): 3,57 $ por acción.
PLAN_TSLA = {"generado": "2026-11-11T15:15:00Z", "mercado": "TSLA", "micro": "TSLA", "fecha": "2026-11-11", "lado": "largo", "entrada": 393.08,
             "hora_entrada": "10:15", "barra": 9, "stop": 389.51, "regla_stop": "ib-medio", "objetivo": 396.65, "regla_objetivo": "R:1",
             "riesgo_pts": 3.57, "rr": 1.0, "plano_a": "15:55", "ib": {"alto": 392.67, "bajo": 386.35, "ancho": 6.32, "minutos": 15}}
CLAVES_PROPIA = {"mercado", "tipo_cuenta", "firma", "cuenta", "cuenta_nombre", "presupuesto", "efectivo_pct", "max_posicion_pct", "max_orden_usd",
                 "min_orden_usd", "perdida_max_dia", "riesgo_por_operacion", "fallos_y_paras", "semaforo", "max_micro", "hora_limite", "hora_limite_tz",
                 "sin_entradas_antes", "sin_entradas_despues", "plano_a", "zona_usuario", "papel", "permitir_cortos", "permitir_margen",
                 "permitir_opciones", "bloqueados", "sec_user_agent"}
PROPIA = ["--propia", "--presupuesto", "5000", "--max-perdida-operacion", "50", "--max-perdida-dia", "150", "--mercado", "TSLA"]


class TestPropia(Base):
    def precios(self, precio, leido):
        comun.escribir_json(os.path.join(self.kemet, "precios.json"), {"generado": leido, "fuente": "yahoo", "precios": {
            "TSLA": {"precio": precio, "hora_vela": "2026-11-11 10:10", "intervalo": "1m", "retraso_min": 1, "leido": leido}}})

    def orden(self, *extra):
        code, out, err = run(["orden", "--ahora", "2026-11-11 10:15", "--json"] + list(extra))
        self.assertIn(code, (0, 1), err)
        return code, json.loads(out)

    def test_config_propia_con_las_claves(self):
        cfg = self.config(*PROPIA)
        self.assertEqual(set(cfg), CLAVES_PROPIA)
        self.assertEqual((cfg["tipo_cuenta"], cfg["cuenta"], cfg["mercado"], cfg["firma"]), ("propia", "propia", "TSLA", None))
        self.assertEqual((cfg["presupuesto"], cfg["perdida_max_dia"], cfg["riesgo_por_operacion"], cfg["fallos_y_paras"]), (5000, 150, 50, 3))
        self.assertEqual((cfg["max_posicion_pct"], cfg["max_orden_usd"], cfg["min_orden_usd"], cfg["efectivo_pct"]), (75, 4000, 5, 10))
        self.assertEqual((cfg["sin_entradas_antes"], cfg["sin_entradas_despues"], cfg["plano_a"]), ("09:45", "15:00", "15:55"))
        self.assertEqual((cfg["permitir_cortos"], cfg["permitir_margen"], cfg["permitir_opciones"], cfg["bloqueados"]), (False, False, False, []))
        self.assertTrue(cfg["papel"])
        self.assertIsNone(cfg["hora_limite"])
        self.assertEqual(cfg["sec_user_agent"], "Nombre correo@ejemplo.com")
        cfg = self.config(*PROPIA, "--max-posicion-pct", "100", "--max-orden", "10000", "--efectivo-pct", "0", "--permitir-cortos", "--sec-user-agent", "Ana ana@ejemplo.com")
        self.assertEqual((cfg["max_posicion_pct"], cfg["max_orden_usd"], cfg["efectivo_pct"], cfg["permitir_cortos"], cfg["sec_user_agent"]), (100, 10000, 0, True, "Ana ana@ejemplo.com"))
        code, out, err = run(["config", "--propia", "--presupuesto", "5000", "--max-perdida-operacion", "50", "--max-perdida-dia", "40"])
        self.assertEqual(code, 2)
        self.assertIn("no puede ser menor", err)
        code, out, err = run(["config", "--propia", "--presupuesto", "5000", "--max-perdida-operacion", "50", "--max-perdida-dia", "150", "--firma", "apex"])
        self.assertEqual(code, 2)
        code, out, err = run(["config"])
        self.assertEqual(code, 2)                             # ni firma ni propia

    def test_calc_en_acciones_cada_tope_manda_una_vez(self):
        self.config(*PROPIA)
        code, out, _ = run(["calc", "--stop", "3.57", "--entrada", "393.08", "--json"])
        r = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual((r["acciones"], r["manda"], r["perdida_max_usd"], r["coste"]), (9, "posición máxima", 32.13, 3537.72))
        self.assertEqual([(l["nombre"], l["acciones"]) for l in r["limites"]],
                         [("riesgo por operación", 14), ("posición máxima", 9), ("orden máxima", 10), ("efectivo", 11)])
        self.config(*PROPIA[:2], "10000", *PROPIA[3:], "--max-posicion-pct", "100", "--max-orden", "10000")   # 10.000 $: el riesgo manda
        r = json.loads(run(["calc", "--stop", "3.57", "--entrada", "393.08", "--json"])[1])
        self.assertEqual((r["acciones"], r["manda"]), (14, "riesgo por operación"))
        self.config(*PROPIA, "--max-posicion-pct", "100", "--max-orden", "2000")
        r = json.loads(run(["calc", "--stop", "3.57", "--entrada", "393.08", "--json"])[1])
        self.assertEqual((r["acciones"], r["manda"]), (5, "orden máxima"))
        self.config(*PROPIA, "--max-posicion-pct", "100", "--max-orden", "10000")
        comun.escribir_json(os.path.join(self.kemet, "portfolio.json"), {"efectivo": 1500.0, "posiciones": [], "actualizado": "2026-11-11T15:00:00Z"})
        r = json.loads(run(["calc", "--stop", "3.57", "--entrada", "393.08", "--json"])[1])
        self.assertEqual((r["acciones"], r["manda"]), (2, "efectivo"))     # (1.500 menos 500 de colchón) / 393,08
        self.assertIn("1.500 $ de efectivo en kemet/portfolio.json", r["limites"][-1]["como"])
        os.remove(os.path.join(self.kemet, "portfolio.json"))
        code, out, _ = run(["calc", "--stop", "3.57"])
        self.assertEqual(code, 0)
        self.assertIn("Acciones: 14 TSLA por el riesgo por operación", out)
        code, out, _ = run(["calc", "--stop", "60", "--entrada", "393.08"])
        self.assertEqual(code, 1)                             # 60 $ por acción no caben en 50 $
        self.assertIn("Acciones: 0 TSLA", out)
        code, out, _ = run(["calc", "--stop", "3.57", "--entrada", "393.08", "--mercado", "TSLA", "--presupuesto", "5000", "--max-perdida-operacion", "50"])
        self.assertIn("9 TSLA", out)                           # sin config, con los límites a mano
        code, out, _ = run(["calc", "--stop", "18", "--mercado", "NQ"])
        self.assertIn("Contratos: 1 MNQ", out)                 # un futuro con la cuenta propia: 50 $ / (18 × 2 $)
        code, out, err = run(["calc", "--stop", "18", "--firma", "apex", "--cuenta", "eod-pa-50", "--mercado", "TSLA"])
        self.assertEqual(code, 2)                             # una acción con una cuenta de firma no tiene sentido

    def test_orden_en_formato_alpaca(self):
        self.config(*PROPIA)
        self.plan(PLAN_TSLA)
        code, out, _ = run(["orden", "--ahora", "2026-11-11 10:15", "--escribir"])
        self.assertEqual(code, 0, out)
        self.assertIn("Tamaño: 9 acciones de TSLA = 3.537,72 $. Pérdida al stop: 9 × 3,57 $ = 32,13 $.", out)
        with open(os.path.join(self.kemet, "orden.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(set(doc), {"generado", "ordenes", "cuenta", "papel"})
        o = doc["ordenes"][0]
        self.assertEqual({k: v for k, v in o.items() if k not in ("why", "plan")},
                         {"symbol": "TSLA", "side": "buy", "qty": "9", "type": "market", "time_in_force": "day", "order_class": "bracket",
                          "take_profit_limit_price": "396.65", "stop_loss_stop_price": "389.51", "instrumento": "accion"})
        self.assertEqual(list(o)[:8], ["symbol", "side", "qty", "type", "time_in_force", "order_class", "take_profit_limit_price", "stop_loss_stop_price"])
        self.assertTrue(all(isinstance(o[k], str) for k in ("qty", "take_profit_limit_price", "stop_loss_stop_price")))
        self.assertIn("manda posición máxima", o["why"])
        self.assertEqual((o["plan"]["riesgo_por_accion"], o["plan"]["perdida_max_usd"], o["plan"]["coste"], o["plan"]["plano_a"]), (3.57, 32.13, 3537.72, "15:55"))
        code, r = self.orden("--limite", "393.00")
        self.assertEqual(code, 0)
        o = r["orden"]["ordenes"][0]
        self.assertEqual((o["type"], o["limit_price"], o["qty"]), ("limit", "393.00", "9"))
        self.assertEqual(r["tamano"]["riesgo_por_accion"], 3.49)
        code, r = self.orden("--limite")
        self.assertEqual((r["orden"]["ordenes"][0]["type"], r["orden"]["ordenes"][0]["limit_price"]), ("limit", "393.08"))

    def test_precio_fresco_sube_el_riesgo_y_baja_las_acciones(self):
        self.config(*PROPIA[:2], "10000", *PROPIA[3:], "--max-posicion-pct", "100", "--max-orden", "10000")   # manda el riesgo: 14 acciones
        self.plan(PLAN_TSLA)
        self.assertEqual(self.orden()[1]["tamano"]["acciones"], 14)
        self.precios(394.50, "2026-11-11T15:14:00Z")                                 # hace 1 minuto, por encima de la entrada
        code, r = self.orden()
        t = r["tamano"]
        self.assertEqual((t["entrada"], t["riesgo_por_accion"], t["acciones"], t["origen_entrada"]), (394.5, 4.99, 10, "precio"))
        self.assertEqual(r["orden"]["ordenes"][0]["qty"], "10")
        self.assertEqual(r["orden"]["ordenes"][0]["plan"]["entrada_plan"], 393.08)
        self.precios(392.00, "2026-11-11T15:14:00Z")                                 # por debajo: nunca sube el tamaño
        self.assertEqual(self.orden()[1]["tamano"]["acciones"], 14)
        self.precios(394.50, "2026-11-11T14:30:00Z")                                 # viejo (45 min): no cuenta
        t = self.orden()[1]["tamano"]
        self.assertEqual((t["acciones"], t["origen_entrada"]), (14, "plan"))
        self.precios(397.00, "2026-11-11T15:14:00Z")                                 # el precio ya pasó el objetivo: rechazo
        code, r = self.orden()
        self.assertEqual(code, 1)
        self.assertIn("el recorrido ya se ha hecho", r["tamano"]["rechazo"])

    def test_rechazos_en_acciones(self):
        self.config(*PROPIA)
        self.plan(dict(PLAN_TSLA, lado="corto", stop=396.65, objetivo=389.51))
        code, r = self.orden()
        self.assertEqual(code, 1)
        self.assertIn("no permite cortos", r["tamano"]["rechazo"])
        self.config(*PROPIA, "--permitir-cortos")
        code, r = self.orden()
        self.assertEqual(code, 0)
        self.assertEqual((r["orden"]["ordenes"][0]["side"], r["orden"]["ordenes"][0]["qty"]), ("sell", "9"))
        self.config(*PROPIA)
        self.plan(PLAN_TSLA)
        self.dia([{"hora": "09:50", "simbolo": "TSLA", "lado": "compra", "contratos": 9, "riesgo_usd": 32.13, "resultado_usd": -130.0, "cerrada": "10:05"}])
        code, r = self.orden()
        self.assertEqual((r["tamano"]["acciones"], r["tamano"]["manda"], r["tamano"]["queda"]), (5, "lo que queda del día", 20.0))
        self.dia([{"hora": "09:50", "simbolo": "TSLA", "lado": "compra", "contratos": 9, "riesgo_usd": 32.13, "resultado_usd": -148.0, "cerrada": "10:05"}])
        code, r = self.orden()
        self.assertEqual(code, 1)
        self.assertIn("el día está hecho", r["tamano"]["rechazo"])
        self.dia([])
        comun.escribir_json(os.path.join(self.kemet, "estado", "broker.json"), {"fecha": "2026-11-11", "ordenes": [
            {"fecha": "2026-11-11", "cuando": "09:50", "huella": "abc", "simbolo": "TSLA", "lado": "compra", "cantidad": "9", "instrumento": "accion",
             "clase": "entrada", "perdida_al_stop": 32.13, "estado": "colocada"}]})
        t = self.orden()[1]["tamano"]
        self.assertEqual((t["operaciones_hoy"], t["riesgo_abierto"]), (1, 32.13))     # lo colocado en papel cuenta
        self.config("--firma", "apex", "--cuenta", "eod-pa-150")
        code, out, err = run(["orden", "--ahora", "2026-11-11 10:15"])
        self.assertEqual(code, 2)                             # una acción con una cuenta de firma
        self.assertIn("cuenta de firma", err)


if __name__ == "__main__":
    unittest.main()
