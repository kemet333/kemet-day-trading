"""kemet-salida: stop y objetivo sobre el disparo real de la ruptura del IB del miércoles 2026-11-11 en NQ (fixture real
tests/fixtures/yahoo/NQ=F-60d-5m.json.gz, sin red): entrada 28.429,75 largo a las 10:45 (barra 15), IB 28.199 a 28.426.
El entrada.json se escribe con el propio entrada.py en un KEMET_DIR temporal.
"""
import datetime
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, ROOT, YAHOO

entrada = load("kemet-entrada", "entrada")
salida = load("kemet-salida", "salida")
comun = salida.comun
TOOL = os.path.join(ROOT, "kemet-salida", "salida.py")
AHORA = "2026-11-11 10:46"
MANUAL = ["--entrada", "28195", "--lado", "corto", "--ib-alto", "28426", "--ib-bajo", "28199"]


def correr(mod, argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        codigo = mod.main(argv)
    return codigo, out.getvalue(), err.getvalue()


class ConDisparoReal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kemet = os.path.join(self.tmp, "kemet")
        self._old = comun.KEMET_DIR
        comun.KEMET_DIR = self.kemet
        codigo, out, err = correr(entrada, ["check", "--ahora", "2026-11-11 10:45", "--offline", YAHOO, "--escribir"])
        self.assertEqual(codigo, 0, err)

    def tearDown(self):
        comun.KEMET_DIR = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def plan(self, *extra):
        codigo, out, err = correr(salida, ["plan", "--ahora", AHORA, "--json"] + list(extra))
        self.assertEqual(codigo, 0, out + err)
        return json.loads(out)

    def rechazo(self, *extra):
        codigo, out, err = correr(salida, ["plan", "--ahora", AHORA] + list(extra))
        self.assertEqual(codigo, 1, out + err)
        self.assertTrue(out.startswith("RECHAZADO  "), out)
        return out

    def test_el_plan_por_defecto_medio_ib_y_1r(self):
        p = self.plan()
        self.assertEqual((p["lado"], p["entrada"], p["hora_entrada"], p["barra"]), ("largo", 28429.75, "10:45", 15))
        self.assertEqual((p["stop"], p["regla_stop"]), (28312.5, "ib-medio"))      # (28.426 + 28.199) / 2
        self.assertEqual((p["objetivo"], p["regla_objetivo"]), (28547.0, "R:1"))   # 28.429,75 + 117,25
        self.assertEqual(p["riesgo_pts"], 117.25)
        self.assertEqual(p["riesgo_usd_micro"], 234.5)      # 117,25 x 2 $ (MNQ)
        self.assertEqual(p["riesgo_usd_mini"], 2345.0)      # 117,25 x 20 $ (NQ)
        self.assertEqual(p["rr"], 1.0)
        self.assertEqual(p["plano_a"], "15:55")
        self.assertEqual(p["ib"], {"alto": 28426.0, "bajo": 28199.0, "ancho": 227.0})
        self.assertEqual((p["micro"], p["ib_minutos"]), ("MNQ", 60))
        for k in ("generado", "mercado", "micro", "fecha", "lado", "entrada", "hora_entrada", "barra", "stop", "regla_stop",
                  "objetivo", "regla_objetivo", "riesgo_pts", "riesgo_usd_micro", "riesgo_usd_mini", "rr", "plano_a", "ib"):
            self.assertIn(k, p)
        self.assertNotIn("escala", json.dumps(p))

    def test_texto_y_escritura(self):
        codigo, out, err = correr(salida, ["plan", "--ahora", AHORA, "--escribir"])
        self.assertEqual(codigo, 0, err)
        self.assertIn("Entrada   28.429,75 a las 10:45 NY (barra 15)", out)
        self.assertIn("Stop      28.312,50  punto medio del IB: (28.426 + 28.199) / 2", out)
        self.assertIn("Objetivo  28.547  1 R (1 vez el riesgo)", out)
        self.assertIn("117,25 puntos, 234,50 $ por micro (MNQ), 2.345 $ por mini (NQ)", out)
        self.assertIn("21:55 Madrid / 15:55 NY", out)
        self.assertNotIn("P&L", out)
        with open(os.path.join(self.kemet, "plan.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["stop"], 28312.5)
        codigo, out, _ = correr(salida, ["show", "--ahora", AHORA])
        self.assertEqual(codigo, 0)
        self.assertIn("Plan de salida: NQ largo, miércoles 11/11/2026", out)

    def test_show_sin_plan(self):
        codigo, out, _ = correr(salida, ["show"])
        self.assertEqual(codigo, 1)
        self.assertIn("No hay", out)

    def test_rechaza_stop_del_lado_equivocado(self):
        out = self.rechazo("--stop", "precio:28500")
        self.assertIn("el stop de un largo va debajo", out)
        out = self.rechazo("--stop", "precio:28429.75")
        self.assertIn("al nivel", out)

    def test_rechaza_objetivo_detras_de_la_entrada(self):
        out = self.rechazo("--objetivo", "precio:28400")
        self.assertIn("el objetivo de un largo va encima", out)

    def test_rechaza_riesgo_menor_de_4_ticks(self):
        out = self.rechazo("--stop", "pts:0.75")
        self.assertIn("menos de 4 ticks", out)
        p = self.plan("--stop", "pts:1")                   # 4 ticks justos pasan
        self.assertEqual(p["riesgo_pts"], 1.0)

    def test_ib_opuesto_y_2r(self):
        p = self.plan("--stop", "ib-opuesto", "--objetivo", "R:2")
        self.assertEqual((p["stop"], p["riesgo_pts"], p["objetivo"], p["rr"]), (28199.0, 230.75, 28891.25, 2.0))

    def test_pts_y_precio(self):
        p = self.plan("--stop", "pts:60", "--objetivo", "R:2")
        self.assertEqual((p["stop"], p["objetivo"], p["riesgo_pts"], p["rr"]), (28369.75, 28549.75, 60.0, 2.0))
        p = self.plan("--objetivo", "precio:28500")
        self.assertEqual((p["objetivo"], p["rr"]), (28500.0, 0.6))

    def test_atr_con_las_velas_del_fixture(self):
        p = self.plan("--stop", "atr:1.5", "--offline", YAHOO)
        self.assertEqual(p["atr_velas"], 14)
        self.assertAlmostEqual(p["atr"], 69.1786, places=3)     # ATR 14 de las velas de 09:35 a 10:40 (la de 09:30 con su propio rango)
        self.assertEqual(p["stop"], 28326.0)                    # 28.429,75 - 1,5 x 69,18 = 28.325,98 al tick
        self.assertEqual(p["riesgo_pts"], 103.75)
        self.assertEqual(p["objetivo"], 28533.5)
        self.assertEqual(p["regla_stop"], "atr:1.5")

    def test_atr_sin_velas_es_error(self):
        codigo, out, err = correr(salida, ["plan", "--ahora", AHORA, "--stop", "atr:1", "--offline", os.path.join(self.tmp, "nada")])
        self.assertEqual(codigo, 2)
        self.assertTrue(err.startswith("salida.py: "))

    def test_objetivo_ib_ya_no_existe(self):
        codigo, out, err = correr(salida, ["plan", "--ahora", AHORA, "--objetivo", "ib:0.5"])
        self.assertEqual(codigo, 2)
        self.assertIn("--objetivo es R:1, R:2 o precio:X", err)

    def test_plano_a_explicito_rechaza_entrada_posterior(self):
        out = self.rechazo("--plano-a", "10:40")
        self.assertIn("hora de estar plano", out)
        p = self.plan("--plano-a", "15:30")
        self.assertEqual(p["plano_a"], "15:30")

    def test_plano_a_y_hora_limite_del_config(self):
        with open(os.path.join(self.kemet, "config.json"), "w", encoding="utf-8") as fh:
            json.dump({"mercado": "NQ", "firma": "topstep", "max_mini": 0, "plano_a": "15:30",
                       "hora_limite": "15:10", "hora_limite_tz": "America/Chicago", "sin_entradas_despues": "15:00"}, fh)
        p = self.plan()
        self.assertEqual(p["plano_a"], "15:30")                 # 15:10 Chicago = 16:10 NY, no manda
        codigo, out, _ = correr(salida, ["plan", "--ahora", AHORA])
        self.assertNotIn("por mini", out)                       # max_mini 0: solo micros
        with open(os.path.join(self.kemet, "config.json"), "w", encoding="utf-8") as fh:
            json.dump({"mercado": "NQ", "firma": "apex", "max_mini": 1, "plano_a": "15:55",
                       "hora_limite": "15:50", "hora_limite_tz": "America/New_York"}, fh)
        p = self.plan()
        self.assertEqual(p["plano_a"], "15:45")                 # hora límite menos 5 minutos
        self.assertTrue(any("la firma (apex)" in n for n in p["notas"]))

    def test_kemet_dir_por_variable_de_entorno(self):
        otro = os.path.join(self.tmp, "otro")
        os.makedirs(otro)
        shutil.copy(os.path.join(self.kemet, "entrada.json"), otro)
        with open(os.path.join(otro, "config.json"), "w", encoding="utf-8") as fh:
            json.dump({"mercado": "NQ", "plano_a": "15:20"}, fh)
        env = dict(os.environ, KEMET_DIR=otro)
        p = subprocess.run([sys.executable, TOOL, "plan", "--ahora", AHORA, "--escribir", "--json"], cwd=self.tmp, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["plano_a"], "15:20")
        self.assertTrue(os.path.exists(os.path.join(otro, "plan.json")))

    def test_entrada_json_sin_disparo(self):
        codigo, _, _ = correr(entrada, ["check", "--ahora", "2026-11-11 10:40", "--offline", YAHOO, "--escribir"])
        self.assertEqual(codigo, 1)
        out = self.rechazo()
        self.assertIn("esperando", out)
        p = self.plan("--entrada", "28429.75", "--lado", "largo")     # por adelantado, con el IB del archivo
        self.assertEqual((p["stop"], p["objetivo"]), (28312.5, 28547.0))
        self.assertIsNone(p["hora_entrada"])


class SinEntradaJson(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = comun.KEMET_DIR
        comun.KEMET_DIR = os.path.join(self.tmp, "kemet")

    def tearDown(self):
        comun.KEMET_DIR = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_falta_entrada_json(self):
        codigo, out, err = correr(salida, ["plan", "--ahora", AHORA])
        self.assertEqual(codigo, 2)
        self.assertIn("falta", err)

    def test_corto_manual(self):
        codigo, out, err = correr(salida, ["plan", "--ahora", "2026-11-11 11:21", "--json", "--hora", "11:20", "--fecha", "2026-11-11"] + MANUAL)
        self.assertEqual(codigo, 0, err)
        p = json.loads(out)
        self.assertEqual((p["stop"], p["objetivo"], p["riesgo_pts"], p["rr"]), (28312.5, 28077.5, 117.5, 1.0))
        codigo, out, _ = correr(salida, ["plan", "--ahora", "2026-11-11 11:21", "--stop", "precio:28100"] + MANUAL)
        self.assertEqual(codigo, 1)
        self.assertIn("el stop de un corto va encima", out)

    def test_entrada_despues_de_las_15_00(self):
        codigo, out, _ = correr(salida, ["plan", "--ahora", "2026-11-11 15:06", "--hora", "15:05", "--fecha", "2026-11-11"] + MANUAL)
        self.assertEqual(codigo, 1)
        self.assertIn("posterior a las 15:00", out)
        codigo, out, _ = correr(salida, ["plan", "--ahora", "2026-11-11 15:01", "--hora", "15:00", "--fecha", "2026-11-11"] + MANUAL)
        self.assertEqual(codigo, 0, out)                        # la vela que cierra a las 15:00 todavía vale

    def test_calculo_al_tick_en_otros_contratos(self):
        c = salida.calcular("CL", "largo", 60.0, "pts", 0.5, "R", 1.0)
        self.assertEqual((c["stop"], c["objetivo"], c["riesgo_usd_micro"], c["riesgo_usd_mini"]), (59.5, 60.5, 50.0, 500.0))
        c = salida.calcular("GC", "corto", 4000.0, "ib-opuesto", None, "R", 1.0, 4010.0, 3990.0)
        self.assertEqual((c["stop"], c["objetivo"], c["riesgo_pts"]), (4010.0, 3990.0, 10.0))
        c = salida.calcular("ES", "largo", 7625.0, "ib-medio", None, "R", 1.0, 7624.75, 7593.25)
        self.assertEqual((c["stop"], c["objetivo"], c["riesgo_usd_micro"]), (7609.0, 7641.0, 80.0))
        with self.assertRaises(salida.Rechazo):
            salida.calcular("NQ", "largo", 28429.75, "pts", 0.5, "R", 1.0)       # 2 ticks

    def test_sesion_recortada_adelanta_el_plano(self):
        t, origen, notas = salida.resolver_plano("NQ", datetime.date(2026, 11, 27), None, None)
        self.assertEqual(comun.hhmm(t), "12:55")
        self.assertTrue(notas and "13:00" in notas[0])


if __name__ == "__main__":
    unittest.main()
