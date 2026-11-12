"""kemet-riesgo: PASS y BLOCK por orden, un cierre nunca se bloquea por el día, registrar y hoy. Sin red."""
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

riesgo = load("kemet-riesgo", "riesgo")
comun = sys.modules["comun"]

# Apex 150K EOD financiada (PA): 1.000 $ al día, 333,33 $ por operación, 170 micros, hora límite 16:59 NY.
CONFIG = {"mercado": "NQ", "firma": "apex", "cuenta": "eod-pa-150", "cuenta_nombre": "Apex Trader Funding · 150K EOD fondeada (PA)",
          "fase": "financiada", "drawdown": 4000, "drawdown_tipo": "eod_trailing", "limite_diario_firma": 2000, "max_micro": 170, "max_mini": 17,
          "hora_limite": "16:59", "hora_limite_tz": "America/New_York", "noticias": "permitido",
          "consistencia": "mejor día ≤ 50% del beneficio para cobrar", "perdida_max_dia": 1000, "perdida_max_dia_origen": "regla-kemet",
          "fallos_y_paras": 3, "semaforo": "verde", "sin_entradas_antes": "09:45", "sin_entradas_despues": "15:00", "plano_a": "15:55",
          "zona_usuario": "Europe/Madrid", "papel": True, "comprobado": "30/10/2026", "fuente": "https://apextraderfunding.com/"}
# La orden de tamano.py para la ruptura del balance inicial del 11/11 (vela de las 10:40 cerrada en 28.429,75, stop en el
# punto medio del IB, objetivo 1R): 1 MNQ, 234,50 $ al stop.
ORDEN = {"simbolo": "MNQ", "lado": "compra", "contratos": 1, "tipo": "stop", "precio": 28429.75, "stop": 28312.5, "objetivo": 28547.0,
         "riesgo_pts": 117.25, "perdida_max_usd": 234.5, "por_que": "largo NQ: 1 MNQ, manda riesgo por operación",
         "plan": {"fecha": "2026-11-11", "lado": "largo", "plano_a": "15:55"}}
CIERRE = {"simbolo": "MNQ", "lado": "venta", "contratos": 2, "tipo": "mercado", "precio": 28500.0, "cierre": True}


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = riesgo.main(argv)
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="kemet-riesgo-")
        self.kemet = os.path.join(self.dir, "kemet")
        comun.KEMET_DIR = self.kemet
        comun.escribir_json(os.path.join(self.kemet, "config.json"), CONFIG)
        self.ordenes([ORDEN])

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def ordenes(self, lista):
        comun.escribir_json(os.path.join(self.kemet, "orden.json"), {"generado": "2026-11-11T15:40:00Z", "ordenes": lista, "cuenta": CONFIG["cuenta_nombre"], "papel": True})

    def dia(self, ops, fecha="2026-11-11"):
        comun.escribir_json(os.path.join(self.kemet, "estado", "dia.json"), {"fecha": fecha, "operaciones": ops})

    def leer(self, *partes):
        with open(os.path.join(self.kemet, *partes), encoding="utf-8") as fh:
            return json.load(fh)

    def check(self, ahora, escribir=False):
        code, out, err = run(["check", "--ahora", ahora, "--json"] + ([] if escribir else ["--sin-escribir"]))
        self.assertIn(code, (0, 1), err)
        return code, json.loads(out)

    def motivos(self, res, i=0):
        return " | ".join(res["resultados"][i]["motivos"])


class TestCheck(Base):
    def test_pass_con_el_ejemplo(self):
        code, res = self.check("2026-11-11 10:45", escribir=True)
        self.assertEqual(code, 0)
        r = res["resultados"][0]
        self.assertEqual(r["veredicto"], "PASS")
        self.assertEqual(r["perdida_max_usd"], 234.5)
        self.assertEqual(len(r["huella"]), 12)
        self.assertEqual(r["huella"], riesgo.huella(ORDEN))
        self.assertTrue(any("consistencia" in a for a in res["avisos"]))      # aviso, no bloqueo
        rec = self.leer("estado", "riesgo.json")
        self.assertEqual(rec["resultados"][0]["huella"], r["huella"])
        self.assertEqual(rec["fecha"], "2026-11-11")

    def test_block_por_perdida(self):
        self.ordenes([dict(ORDEN, contratos=2)])
        code, res = self.check("2026-11-11 10:45")
        self.assertEqual(code, 1)
        self.assertIn("pérdida: 2 × 117,25 pts × 2 $/pt = 469,00 $ al stop", self.motivos(res))

    def test_block_por_suma_del_dia(self):
        self.dia([{"hora": "10:00", "simbolo": "MNQ", "lado": "compra", "contratos": 2, "riesgo_usd": 320.0, "resultado_usd": None, "cerrada": None},
                  {"hora": "09:50", "simbolo": "MNQ", "lado": "venta", "contratos": 2, "riesgo_usd": 320.0, "resultado_usd": -500.0, "cerrada": "09:58"}])
        code, res = self.check("2026-11-11 10:45")
        self.assertEqual(code, 1)
        self.assertIn("día: 820,00 $ abierto y perdido hoy más 234,50 $ de esta = 1.054,50 $", self.motivos(res))

    def test_block_por_ventana_de_datos(self):
        comun.escribir_json(os.path.join(self.kemet, "agenda.json"), {"fecha": "2026-11-11", "datos": [
            {"hora": "14:00", "nombre": "Subasta del Tesoro", "fuerte": False}, {"hora": "10:30", "nombre": "Inventarios EIA", "fuerte": False, "mercados": ["CL"]}]})
        code, res = self.check("2026-11-11 13:52")
        self.assertEqual(code, 1)
        self.assertIn("ventana: Subasta del Tesoro a las 14:00 (±10 min), de 13:50 a 14:10 NY", self.motivos(res))
        code, res = self.check("2026-11-11 10:35")           # el dato de la EIA es de CL, no afecta a NQ
        self.assertEqual(code, 0, self.motivos(res))
        comun.escribir_json(os.path.join(self.kemet, "agenda.json"), {"fecha": "2026-11-11", "datos": [{"hora": "11:00", "nombre": "FOMC", "fuerte": True}]})
        code, res = self.check("2026-11-11 10:42")           # fuerte: ±20 minutos
        self.assertIn("FOMC a las 11:00 (fuerte, ±20 min), de 10:40 a 11:20 NY", self.motivos(res))

    def test_block_por_hora(self):
        code, res = self.check("2026-11-11 09:40")
        self.assertIn("ventana: apertura 09:30–09:45 NY", self.motivos(res))
        self.assertIn("horario: sin entradas antes de las 09:45 NY", self.motivos(res))
        code, res = self.check("2026-11-11 14:30")
        self.assertEqual(code, 0, self.motivos(res))
        code, res = self.check("2026-11-11 15:10")
        self.assertIn("horario: sin entradas después de las 15:00 NY", self.motivos(res))
        code, res = self.check("2026-11-11 15:58")
        self.assertIn("horario: a las 15:55 NY se está plano", self.motivos(res))
        code, res = self.check("2026-11-11 17:30")
        self.assertIn("globex: pausa", self.motivos(res))
        code, res = self.check("2026-11-14 10:40")           # sábado
        self.assertIn("globex: cerrado (sábado)", self.motivos(res))

    def test_hora_limite_de_topstep_en_chicago(self):
        cfg = dict(CONFIG, hora_limite="15:10", hora_limite_tz="America/Chicago", sin_entradas_despues=None, plano_a="16:30")
        comun.escribir_json(os.path.join(self.kemet, "config.json"), cfg)
        code, res = self.check("2026-11-11 16:12")
        self.assertIn("la hora límite de tu firma es 15:10 America/Chicago (16:10 NY)", self.motivos(res))
        self.assertTrue(any("15:10 Chicago = 16:10 NY" in a for a in res["avisos"]))

    def test_block_por_cuarta_operacion(self):
        op = {"hora": "10:00", "simbolo": "MNQ", "lado": "compra", "contratos": 1, "riesgo_usd": 100.0, "resultado_usd": 50.0, "cerrada": "10:10"}
        self.dia([op, op])
        code, res = self.check("2026-11-11 10:40")
        self.assertEqual(code, 0, self.motivos(res))         # la tercera entra
        self.dia([op, op, op])
        code, res = self.check("2026-11-11 10:40")
        self.assertEqual(code, 1)                             # la cuarta no
        self.assertIn("operaciones: hoy ya hay 3 y tu regla son 3 al día", self.motivos(res))

    def test_block_por_duplicado(self):
        h = riesgo.huella(ORDEN)
        self.dia([{"hora": "10:41", "simbolo": "MNQ", "lado": "compra", "contratos": 2, "riesgo_usd": 320.0, "resultado_usd": None, "cerrada": None, "huella": h}])
        code, res = self.check("2026-11-11 10:50")
        self.assertEqual(code, 1)
        self.assertIn("duplicado: esta misma orden (huella %s) ya está apuntada hoy" % h, self.motivos(res))
        self.ordenes([ORDEN, ORDEN])
        self.dia([])
        code, res = self.check("2026-11-11 10:50")
        self.assertEqual(res["resultados"][0]["veredicto"], "PASS")
        self.assertIn("duplicado: la misma orden aparece dos veces", self.motivos(res, 1))

    def test_block_por_tope_de_contratos_y_stop(self):
        cfg = dict(CONFIG, max_micro=1, perdida_max_dia=3000)
        comun.escribir_json(os.path.join(self.kemet, "config.json"), cfg)
        self.ordenes([dict(ORDEN, contratos=2)])
        code, res = self.check("2026-11-11 10:40")
        self.assertIn("contratos: 2 MNQ, más que el tope de 1 micros", self.motivos(res))
        self.ordenes([dict(ORDEN, stop=None)])
        code, res = self.check("2026-11-11 10:40")
        self.assertIn("stop: sin stop", self.motivos(res))
        self.ordenes([dict(ORDEN, stop=28500.0)])
        code, res = self.check("2026-11-11 10:40")
        self.assertIn("stop: el stop 28.500 tiene que estar debajo de la entrada 28.429,75", self.motivos(res))

    def test_un_cierre_pasa_con_el_dia_agotado(self):
        self.dia([{"hora": "10:00", "simbolo": "MNQ", "lado": "compra", "contratos": 2, "riesgo_usd": 320.0, "resultado_usd": -1000.0, "cerrada": "10:30"},
                  {"hora": "10:35", "simbolo": "MNQ", "lado": "compra", "contratos": 2, "riesgo_usd": 320.0, "resultado_usd": None, "cerrada": None},
                  {"hora": "10:36", "simbolo": "MNQ", "lado": "compra", "contratos": 1, "riesgo_usd": 160.0, "resultado_usd": None, "cerrada": None}])
        self.ordenes([ORDEN, CIERRE])
        code, res = self.check("2026-11-11 15:58")
        self.assertEqual(code, 1)
        self.assertEqual([r["veredicto"] for r in res["resultados"]], ["BLOCK", "PASS"])
        self.assertEqual(res["resultados"][1]["clase"], "cierre")
        self.assertEqual(res["resultados"][1]["motivos"], [])
        self.ordenes([CIERRE])
        code, res = self.check("2026-11-11 15:58")
        self.assertEqual(code, 0)

    def test_formato(self):
        self.ordenes([{"simbolo": "AAPL", "lado": "compra", "contratos": 1.5, "precio": 0}])
        code, res = self.check("2026-11-11 10:40")
        m = self.motivos(res)
        self.assertIn("formato: 'AAPL' no es un micro ni un mini", m)
        self.assertIn("contratos tiene que ser un entero", m)
        self.assertIn("precio tiene que ser un número mayor que 0", m)

    def test_sin_config_avisa(self):
        os.remove(os.path.join(self.kemet, "config.json"))
        code, res = self.check("2026-11-11 10:40")
        self.assertTrue(any("sin kemet/config.json" in a for a in res["avisos"]))
        self.assertEqual(code, 1)                             # por defecto 500 $ al día: 234,50 $ al stop no caben en 166,67 $
        self.assertIn("pérdida:", self.motivos(res))
        self.ordenes([dict(ORDEN, stop=28389.75, objetivo=28469.75)])   # stop de 40 puntos: 80 $
        code, res = self.check("2026-11-11 10:45")
        self.assertEqual(code, 0, self.motivos(res))

    def test_papel_false_es_aviso(self):
        comun.escribir_json(os.path.join(self.kemet, "config.json"), dict(CONFIG, papel=False))
        code, res = self.check("2026-11-11 10:40")
        self.assertEqual(code, 0)
        self.assertTrue(any("REAL" in a for a in res["avisos"]))


class TestRegistrarHoy(Base):
    def test_abrir_cerrar_y_hoy(self):
        code, out, err = run(["registrar", "--abrir", "--ahora", "2026-11-11 10:41"])
        self.assertEqual(code, 2)                             # sin check previo
        self.check("2026-11-11 10:45", escribir=True)
        code, out, err = run(["registrar", "--abrir", "--ahora", "2026-11-11 10:46"])
        self.assertEqual(code, 0, err)
        dia = self.leer("estado", "dia.json")
        self.assertEqual(dia["fecha"], "2026-11-11")
        self.assertEqual(len(dia["operaciones"]), 1)
        op = dia["operaciones"][0]
        self.assertEqual((op["hora"], op["simbolo"], op["lado"], op["contratos"], op["entrada"], op["stop"], op["objetivo"], op["riesgo_usd"]),
                         ("10:46", "MNQ", "compra", 1, 28429.75, 28312.5, 28547.0, 234.5))
        self.assertIsNone(op["resultado_usd"])
        self.assertEqual((dia["riesgo_abierto"], dia["perdida_realizada"]), (234.5, 0.0))
        code, out, err = run(["registrar", "--abrir", "--ahora", "2026-11-11 10:47"])
        self.assertEqual(code, 2)                             # ya apuntada: no se duplica
        code, out, err = run(["hoy", "--ahora", "2026-11-11 10:45"])
        self.assertEqual(code, 0)
        self.assertIn("Queda del día: 765,50 $ de 1.000 $", out)
        code, out, err = run(["registrar", "--resultado", "-234.5", "--hora", "11:05", "--ahora", "2026-11-11 11:05"])
        self.assertEqual(code, 0, err)
        dia = self.leer("estado", "dia.json")
        self.assertEqual((dia["operaciones"][0]["cerrada"], dia["operaciones"][0]["resultado_usd"]), ("11:05", -234.5))
        self.assertEqual((dia["riesgo_abierto"], dia["perdida_realizada"]), (0.0, 234.5))
        code, out, err = run(["registrar", "--resultado", "100", "--ahora", "2026-11-11 11:06"])
        self.assertEqual(code, 2)                             # no queda nada abierto

    def test_hoy_dice_cuando_parar(self):
        op = {"hora": "10:00", "simbolo": "MNQ", "lado": "compra", "contratos": 2, "entrada": 28400.0, "stop": 28320.0, "riesgo_usd": 320.0, "resultado_usd": -320.0, "cerrada": "10:20"}
        self.dia([op, dict(op, resultado_usd=-320.0), dict(op, resultado_usd=-400.0)])
        code, out, err = run(["hoy", "--ahora", "2026-11-11 12:00"])
        self.assertEqual(code, 1)
        self.assertIn("Toca parar", out)
        self.assertIn("pérdida máxima del día (1.000 $) está agotada", out)
        code, out, err = run(["hoy", "--ahora", "2026-11-12 09:00"])     # otro día: limpio
        self.assertEqual(code, 0)
        self.assertIn("sin operaciones apuntadas", out)


if __name__ == "__main__":
    unittest.main()
