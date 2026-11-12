"""kemet-maquina: la máquina del tiempo sobre el fixture real de NQ (60 días de velas de 5 min, hasta el 2026-11-12), sin red.
El plan de ejemplo es la ruptura del balance inicial real del miércoles 2026-11-11: IB 28.199 a 28.426 (60 minutos), la vela
de 10:40 cierra en 28.429,75, por encima del IB alto, así que entrada 28.429,75 a las 10:45, stop en el punto medio del IB
(28.312,50, 117,25 pts) y objetivo 1R (28.547)."""
import contextlib
import datetime as dt
import io
import json
import os
import shutil
import tempfile
import unittest

from _load import YAHOO, load

maquina = load("kemet-maquina", "maquina")
comun = maquina.comun

AHORA = "2026-11-11 16:30"
PLAN = ["--mercado", "NQ", "--fecha", "2026-11-11", "--lado", "largo", "--entrada", "28429.75", "--stop", "28312.5",
        "--objetivo", "28547", "--hora-entrada", "10:45"]


def correr(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = maquina.main(args)
    return code, out.getvalue(), err.getvalue()


def documento(extra=(), reps="1500"):
    code, out, err = correr(["run", "--json", "--offline", YAHOO, "--ahora", AHORA, "--repeticiones", reps] + PLAN + list(extra))
    assert code == 0, err
    return json.loads(out)


class Maquina(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cwd = os.getcwd()
        cls.tmp = tempfile.mkdtemp(prefix="kemet-maquina-")
        os.chdir(cls.tmp)
        cls.kemet_dir = comun.KEMET_DIR                       # otros tests pueden haberlo movido: aquí, dentro del temporal
        comun.KEMET_DIR = os.path.join(cls.tmp, "kemet")
        cls.doc = documento()

    @classmethod
    def tearDownClass(cls):
        comun.KEMET_DIR = cls.kemet_dir
        os.chdir(cls.cwd)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_plan_normalizado(self):
        p = self.doc["plan"]
        self.assertEqual((p["barra"], p["hora_entrada"]), (15, "10:45"))
        self.assertEqual(p["riesgo_pts"], 117.25)
        self.assertEqual(p["rr"], 1.0)
        self.assertEqual(p["riesgo_usd_micro"], 234.5)
        self.assertEqual((p["regla_stop"], p["regla_objetivo"]), ("ib-medio", "R:1"))   # deducida del IB del día
        self.assertEqual((p["ib_minutos"], p["sin_entradas_antes"], p["sin_entradas_despues"]), (60, "09:45", "15:00"))

    def test_cuatro_odds_suman_cien(self):
        m = self.doc["mc"]
        self.assertAlmostEqual(m["objetivo_primero"] + m["stop_primero"] + m["ninguno"], 1.0, places=3)
        self.assertGreaterEqual(m["verde"], m["objetivo_primero"])
        self.assertEqual(m["velas_restantes"], 62)              # de la vela 16 a la que cierra a las 15:55
        self.assertEqual(m["hasta"], "15:55")
        self.assertEqual(m["r_objetivo"], 1.0)
        self.assertEqual(len(m["bandas"]), 63)
        self.assertEqual(sum(m["histograma"]["cajas"]) <= m["repeticiones"], True)

    def test_pool_de_sesiones_completas(self):
        d = self.doc["datos"]
        self.assertEqual(d["sesiones_pool"], 46)                 # 48 sesiones antes del 11/11, dos con huecos
        self.assertEqual(d["pool_desde"], "2026-09-03")
        self.assertEqual(d["pool_hasta"], "2026-11-10")
        self.assertEqual([x["fecha"] for x in d["cortas_fuera"]], ["2026-10-30", "2026-11-05"])

    def test_reproducible_con_la_misma_semilla(self):
        otra = documento()
        self.assertEqual(otra["mc"]["objetivo_primero"], self.doc["mc"]["objetivo_primero"])
        self.assertEqual(otra["mc"]["mediana_cierre"], self.doc["mc"]["mediana_cierre"])
        distinta = documento(["--semilla", "7"])
        self.assertEqual(distinta["mc"]["semilla"], 7)
        self.assertNotEqual((distinta["mc"]["objetivo_primero"], distinta["mc"]["mediana_cierre"]),
                            (self.doc["mc"]["objetivo_primero"], self.doc["mc"]["mediana_cierre"]))

    def test_plan_corto(self):
        code, out, err = correr(["run", "--json", "--offline", YAHOO, "--ahora", AHORA, "--repeticiones", "800",
                                 "--mercado", "NQ", "--fecha", "2026-11-03", "--lado", "corto", "--entrada", "28215.5",
                                 "--stop", "28385.75", "--objetivo", "28130.5", "--hora-entrada", "11:00"])
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        m = d["mc"]
        self.assertAlmostEqual(m["objetivo_primero"] + m["stop_primero"] + m["ninguno"], 1.0, places=3)
        self.assertEqual(d["plan"]["riesgo_pts"], 170.25)
        self.assertEqual(d["plan"]["regla_stop"], "ib-opuesto")           # 28.385,75 es el IB alto del 03/11
        self.assertIn("corto", d["veredicto"] + json.dumps(d["plan"]))
        # en un corto, el stop mal puesto se rechaza en una línea
        code, out, err = correr(["run", "--offline", YAHOO, "--ahora", AHORA, "--mercado", "NQ", "--fecha", "2026-11-03",
                                 "--lado", "corto", "--entrada", "28215.5", "--stop", "28100", "--objetivo", "28130.5", "--hora-entrada", "11:00"])
        self.assertEqual(code, 2)
        self.assertIn("un corto necesita objetivo < entrada < stop", err)

    def test_rechaza_con_menos_de_veinte_sesiones(self):
        code, out, err = correr(["run", "--offline", YAHOO, "--ahora", AHORA, "--mercado", "NQ", "--fecha", "2026-10-01",
                                 "--lado", "largo", "--entrada", "30857", "--stop", "30560.75", "--objetivo", "31005", "--hora-entrada", "10:45"])
        self.assertEqual(code, 2)
        self.assertIn("19 sesión(es)", err)
        self.assertIn("al menos 20", err)

    def test_historia_repite_la_regla_del_plan(self):
        h = self.doc["historia"]
        self.assertEqual(h["sesiones"], 46)
        self.assertEqual(h["regla"]["stop"], {"regla": "ib-medio"})
        self.assertEqual(h["regla"]["objetivo"], {"regla": "R", "valor": 1.0})
        self.assertGreater(h["disparos"], 0)
        self.assertEqual(h["disparos"] + h["sin_disparo"], 46)             # sin filtro: todas las sesiones cuentan
        self.assertEqual(h["disparos"], h["objetivo"] + h["stop"] + h["ninguno"])
        self.assertEqual(h["disparos"], h["largos"] + h["cortos"])
        self.assertGreater(h["cortos"], 0)
        self.assertEqual(len(h["operaciones"]), h["disparos"])
        ch = comun.velas("NQ", "60d", "5m", YAHOO)
        dias = comun.por_dia(ch["velas"])
        for op in h["operaciones"]:
            self.assertTrue("10:35" <= op["hora"] <= "15:00", op)
            d = dt.date.fromisoformat(op["fecha"])
            rth = comun.regular("NQ", dias[d], d)
            vela = rth[op["barra"] - 1]
            self.assertEqual(op["entrada"], vela[4])                        # la entrada es el cierre de la vela del disparo
            ib = rth[:12]
            self.assertEqual(op["ib"]["alto"], max(b[2] for b in ib))
            if op["lado"] == "largo":
                self.assertGreater(op["entrada"], op["ib"]["alto"])
            else:
                self.assertLess(op["entrada"], op["ib"]["bajo"])
            # ninguna vela anterior después del IB cerró fuera
            for b in rth[12:op["barra"] - 1]:
                self.assertTrue(op["ib"]["bajo"] <= b[4] <= op["ib"]["alto"], (op["fecha"], b))
            self.assertEqual(op["stop"], comun.al_tick((op["ib"]["alto"] + op["ib"]["bajo"]) / 2, 0.25))
            self.assertLess(abs(abs(op["objetivo"] - op["entrada"]) - op["riesgo_pts"]), 0.25 + 1e-9)
        # el 10/11 (IB 27.637,25 a 28.090): la primera vela que cierra fuera
        dia = [o for o in h["operaciones"] if o["fecha"] == "2026-11-10"]
        if dia:
            self.assertEqual(dia[0]["ib"], {"alto": 28090.0, "bajo": 27637.25, "ancho": 452.75})

    def test_historia_con_otra_regla_lo_dice(self):
        d = documento(["--stop", "28400", "--objetivo", "28459.5"], reps="300")
        self.assertEqual(d["historia"]["regla"]["stop"], {"regla": "pts", "pts": 29.75})
        self.assertEqual(d["historia"]["regla"]["objetivo"], {"regla": "R", "valor": 1.0})
        d = documento(["--regla-objetivo", "precio:28547", "--regla-stop", "ib-opuesto"], reps="300")
        self.assertEqual(d["historia"]["regla"]["stop"], {"regla": "ib-opuesto"})
        self.assertEqual(d["historia"]["regla"]["objetivo"], {"regla": "pts", "pts": 117.25})
        self.assertTrue(any("precio:28547" in a and "no se puede repetir" in a for a in d["avisos"]))
        d = documento(["--ib-minutos", "30"], reps="300")
        self.assertEqual(d["plan"]["ib_minutos"], 30)
        self.assertEqual(d["historia"]["ib_minutos"], 30)
        for op in d["historia"]["operaciones"]:
            self.assertGreaterEqual(op["hora"], "10:05")

    def test_veredicto_por_bandas(self):
        mk = lambda po, ps, r: {"objetivo_primero": po, "stop_primero": ps, "ninguno": 1 - po - ps, "r_objetivo": r, "r_media": 0.0, "hasta": "15:55"}
        self.assertTrue(maquina.veredicto(mk(0.30, 0.28, 1.0)).startswith("Casi una moneda al aire"))
        self.assertTrue(maquina.veredicto(mk(0.40, 0.20, 0.5)).startswith("Casi en el punto de equilibrio"))   # 67 % contra 67 %
        self.assertTrue(maquina.veredicto(mk(0.45, 0.15, 0.5)).startswith("Se inclina hacia el objetivo"))   # 75 %
        self.assertTrue(maquina.veredicto(mk(0.50, 0.10, 0.5)).startswith("Claramente hacia el objetivo"))   # 83 %
        self.assertTrue(maquina.veredicto(mk(0.20, 0.40, 1.0)).startswith("Claramente hacia el stop"))
        self.assertIn("decide todas", maquina.veredicto(mk(0.0, 0.0, 1.0)))
        notas = maquina.notas_veredicto(dict(mk(0.30, 0.25, 1.0), r_media=-0.02))
        self.assertEqual(len(notas), 1)                           # el 45 % no toca ningún lado; la R media no contradice una moneda al aire
        self.assertIn("45,0 %", notas[0])

    def test_informe_y_chart_y_escribir(self):
        code, out, err = correr(["run", "--escribir", "--offline", YAHOO, "--ahora", AHORA, "--repeticiones", "500"] + PLAN)
        self.assertEqual(code, 0, err)
        self.assertIn("1R = 117,25 pts = 234,50 $ por MNQ", out)
        self.assertIn("objetivo primero", out)
        self.assertIn("semilla 19", out)
        self.assertNotIn("—", out)
        self.assertTrue(os.path.isfile(comun.ruta("maquina.json")))
        code, out, err = correr(["chart", "--desde"])
        self.assertEqual(code, 0, err)
        self.assertIn("objetivo", out)
        self.assertIn("stop", out)
        self.assertIn("10:45", out)

    def test_sin_hora_de_entrada_simula_desde_las_10_35(self):
        code, out, err = correr(["run", "--json", "--offline", YAHOO, "--ahora", AHORA, "--repeticiones", "200",
                                 "--mercado", "NQ", "--fecha", "2026-11-11", "--entrada", "28429.75", "--stop", "28312.5", "--objetivo", "28547"])
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual((d["plan"]["barra"], d["plan"]["hora_entrada"]), (13, "10:35"))
        self.assertTrue(any("10:35" in a for a in d["avisos"]))


if __name__ == "__main__":
    unittest.main()
