"""kemet-maquina: la máquina del tiempo sobre el fixture real de NQ (60 días de velas de 5 min, hasta el 2026-11-12), sin red.
El plan de ejemplo es la ruptura del balance inicial real del miércoles 2026-11-11: IB 28.199 a 28.426 (60 minutos), la vela
de 10:40 cierra en 28.429,75, por encima del IB alto, así que entrada 28.429,75 a las 10:45, stop en el punto medio del IB
(28.312,50, 117,25 pts) y objetivo 1R (28.547).

Acciones: TSLA, 2026-11-11 (fixture real TSLA-60d-5m.json.gz, 60 sesiones de 09:30 a 16:00): IB de 15 minutos 386,35 a 392,67,
la vela de 10:10 cierra en 393,08: entrada 393,08 a las 10:15 (vela 9), stop en el medio del IB 389,51 (3,57 $), objetivo 1R 396,65."""
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


PLAN_TSLA = ["--mercado", "TSLA", "--fecha", "2026-11-11", "--lado", "largo", "--entrada", "393.08", "--stop", "389.51",
             "--objetivo", "396.65", "--hora-entrada", "10:15"]


def correr(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = maquina.main(args)
    return code, out.getvalue(), err.getvalue()


def documento(extra=(), reps="1500"):
    code, out, err = correr(["run", "--json", "--offline", YAHOO, "--ahora", AHORA, "--repeticiones", reps] + PLAN + list(extra))
    assert code == 0, err
    return json.loads(out)


def documento_tsla(extra=(), reps="1500"):
    code, out, err = correr(["run", "--json", "--offline", YAHOO, "--ahora", AHORA, "--repeticiones", reps] + PLAN_TSLA + list(extra))
    assert code == 0, err
    return json.loads(out)


class MaquinaTsla(unittest.TestCase):
    """La máquina con una acción: pool de sesiones completas de 78 velas por fecha de Nueva York, IB de 15 minutos, dólares por acción."""

    @classmethod
    def setUpClass(cls):
        cls.cwd = os.getcwd()
        cls.tmp = tempfile.mkdtemp(prefix="kemet-maquina-tsla-")
        os.chdir(cls.tmp)
        cls.kemet_dir = comun.KEMET_DIR
        comun.KEMET_DIR = os.path.join(cls.tmp, "kemet")
        cls.doc = documento_tsla()

    @classmethod
    def tearDownClass(cls):
        comun.KEMET_DIR = cls.kemet_dir
        os.chdir(cls.cwd)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_plan_y_pool_de_una_accion(self):
        p, d, m = self.doc["plan"], self.doc["datos"], self.doc["mc"]
        self.assertEqual((p["mercado"], p["instrumento"], p["micro"], p["ib_minutos"]), ("TSLA", "accion", "TSLA", 15))
        self.assertEqual((p["barra"], p["hora_entrada"], p["riesgo_pts"], p["rr"], p["riesgo_usd_micro"]), (9, "10:15", 3.57, 1.0, 3.57))
        self.assertEqual((p["regla_stop"], p["regla_objetivo"], p["plano_a"]), ("ib-medio", "R:1", "15:55"))   # 389,51 es el medio del IB del día
        self.assertEqual((d["sesiones_pool"], d["pool_desde"], d["pool_hasta"]), (57, "2026-08-20", "2026-11-10"))
        self.assertEqual([x["fecha"] for x in d["cortas_fuera"]], ["2026-11-05"])               # 59 velas: con huecos
        self.assertEqual((m["velas_restantes"], m["hasta"], len(m["bandas"]), m["r_objetivo"]), (68, "15:55", 69, 1.0))

    def test_odds_suman_cien_y_se_repiten(self):
        m = self.doc["mc"]
        self.assertAlmostEqual(m["objetivo_primero"] + m["stop_primero"] + m["ninguno"], 1.0, places=3)
        self.assertGreaterEqual(m["verde"], m["objetivo_primero"])
        otra = documento_tsla()
        self.assertEqual((otra["mc"]["objetivo_primero"], otra["mc"]["stop_primero"], otra["mc"]["mediana_cierre"]),
                         (m["objetivo_primero"], m["stop_primero"], m["mediana_cierre"]))
        distinta = documento_tsla(["--semilla", "7"])
        self.assertNotEqual((distinta["mc"]["objetivo_primero"], distinta["mc"]["mediana_cierre"]), (m["objetivo_primero"], m["mediana_cierre"]))

    def test_historia_con_ib_de_15_minutos_al_centimo(self):
        h = self.doc["historia"]
        self.assertEqual((h["sesiones"], h["ib_minutos"]), (57, 15))
        self.assertEqual(h["disparos"] + h["sin_disparo"], 57)
        self.assertEqual(h["disparos"], h["objetivo"] + h["stop"] + h["ninguno"])
        self.assertGreater(h["cortos"], 0)
        ch = comun.velas("TSLA", "60d", "5m", YAHOO)
        dias = comun.por_dia(ch["velas"], "TSLA")
        for op in h["operaciones"]:
            self.assertTrue("09:50" <= op["hora"] <= "15:00", op)
            d = dt.date.fromisoformat(op["fecha"])
            rth = [(b[0],) + tuple(comun.al_tick(x, 0.01) for x in b[1:5]) for b in comun.regular("TSLA", dias[d], d)]
            self.assertEqual(len(rth), 78)
            self.assertEqual(op["entrada"], rth[op["barra"] - 1][4])                  # la entrada es el cierre de la vela del disparo
            ib = rth[:3]
            self.assertEqual((op["ib"]["alto"], op["ib"]["bajo"]), (max(b[2] for b in ib), min(b[3] for b in ib)))
            for b in rth[3:op["barra"] - 1]:
                self.assertTrue(op["ib"]["bajo"] <= b[4] <= op["ib"]["alto"], (op["fecha"], b))
            for v in (op["entrada"], op["stop"], op["objetivo"]):
                self.assertEqual(v, round(v, 2))                                        # al céntimo
            self.assertEqual(op["stop"], comun.al_tick((op["ib"]["alto"] + op["ib"]["bajo"]) / 2, 0.01))
        dia = [o for o in h["operaciones"] if o["fecha"] == "2026-11-10"]
        self.assertEqual(len(dia), 1)
        self.assertEqual((dia[0]["ib"], dia[0]["lado"], dia[0]["hora"], dia[0]["entrada"], dia[0]["stop"], dia[0]["resultado"]),
                         ({"alto": 377.53, "bajo": 370.43, "ancho": 7.1}, "largo", "11:10", 378.02, 373.98, "stop"))

    def test_informe_en_dolares_por_accion(self):
        code, out, err = correr(["run", "--offline", YAHOO, "--ahora", AHORA, "--repeticiones", "300"] + PLAN_TSLA)
        self.assertEqual(code, 0, err)
        self.assertIn("Máquina del tiempo de TSLA, miércoles 11/11/2026", out)
        self.assertIn("TSLA largo: entrada 393,08 a las 10:15 (vela 9), stop 389,51 (3,57 $), objetivo 396,65 (3,57 $, 1R).", out)
        self.assertIn("1R = 3,57 $ por acción. Es contexto del tamaño, no un resultado esperado.", out)
        self.assertIn("de 10:15 a 15:55 (68 velas de 5 minutos)", out)
        self.assertIn("la misma regla (IB de 15 minutos", out)
        self.assertIn("cuántas acciones", out)
        self.assertNotIn("por MNQ", out)
        self.assertNotIn("—", out)

    def test_plan_json_de_kemet_salida_con_ib_de_15(self):
        comun.escribir_json("plan.json", {"mercado": "TSLA", "instrumento": "accion", "micro": "TSLA", "fecha": "2026-11-11", "ib_minutos": 15,
                                          "lado": "largo", "entrada": 393.08, "hora_entrada": "10:15", "barra": 9, "stop": 389.51, "regla_stop": "ib-medio",
                                          "objetivo": 396.65, "regla_objetivo": "R:1", "plano_a": "15:55", "ib": {"alto": 392.67, "bajo": 386.35, "ancho": 6.32}})
        code, out, err = correr(["run", "--json", "--offline", YAHOO, "--ahora", AHORA, "--repeticiones", "200"])
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual((d["plan"]["ib_minutos"], d["historia"]["ib_minutos"], d["plan"]["barra"], d["plan"]["instrumento"]), (15, 15, 9, "accion"))
        code, out, err = correr(["run", "--offline", YAHOO, "--ahora", AHORA, "--repeticiones", "100", "--simbolo", "X1", "--fecha", "2026-11-11",
                                 "--lado", "largo", "--entrada", "393.08", "--stop", "389.51", "--objetivo", "396.65", "--hora-entrada", "10:15"])
        self.assertEqual(code, 2)
        self.assertIn("el plan necesita un mercado", err)


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
