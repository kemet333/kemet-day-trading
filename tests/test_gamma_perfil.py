"""kemet-niveles: perfiles de volumen por sesión (velas reales del 11/11/2026) y niveles de gamma (cadenas reales de QQQ y NDX del
25/11/2026, recortadas a ±10 %). Sin red."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _load import FIX, YAHOO, load  # noqa: E402

perfil = load("kemet-niveles", "perfil")
gamma = load("kemet-niveles", "gamma")
comun = sys.modules["comun"]
OPC = os.path.join(FIX, "opciones")


def correr(mod, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mod.main(argv)
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.viejo = comun.KEMET_DIR
        comun.KEMET_DIR = os.path.join(self.d, "kemet")

    def tearDown(self):
        comun.KEMET_DIR = self.viejo
        shutil.rmtree(self.d, ignore_errors=True)


class Perfil(Base):
    def doc(self, mercado="NQ", ahora="2026-11-11 10:45", *extra):
        code, out, err = correr(perfil, ["--mercado", mercado, "--offline", YAHOO, "--ahora", ahora, "--json", *extra])
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_tres_sesiones_de_hoy_y_nueva_york_de_ayer(self):
        d = self.doc()
        self.assertEqual([s["nombre"] for s in d["sesiones"]], ["Asia", "Londres", "Nueva York", "Nueva York de ayer"])
        self.assertEqual([s["color"] for s in d["sesiones"]], ["naranja", "azul", "rojo", "rojo"])
        ayer = d["sesiones"][3]
        self.assertEqual((ayer["dia"], ayer["alto"], ayer["bajo"]), ("2026-11-10", 28090.0, 27516.0))   # los niveles de ayer del reel
        self.assertTrue(d["sesiones"][2]["en_curso"])

    def test_poc_y_zona_de_valor_dentro_del_rango_y_al_tick(self):
        for mercado in ("NQ", "ES"):
            for s in self.doc(mercado)["sesiones"]:
                self.assertTrue(s["bajo"] <= s["val"] <= s["poc"] <= s["vah"] <= s["alto"], (mercado, s["nombre"]))
                tick = comun.tick_de(mercado, micro=False)
                for k in ("poc", "vah", "val"):
                    self.assertAlmostEqual(s[k] / tick, round(s[k] / tick), places=6)
                dentro = sum(v for p, v in s["filas"] if s["val"] <= p <= s["vah"])
                self.assertGreaterEqual(dentro, 0.69 * s["volumen"])

    def test_filas_redondas_y_fila_pedida(self):
        self.assertTrue(all(s["fila"] in (1.25, 2.5, 5.0, 12.5, 25.0) for s in self.doc()["sesiones"]))
        self.assertTrue(all(s["fila"] == 10.0 for s in self.doc("NQ", "2026-11-11 10:45", "--fila", "10")["sesiones"]))

    def test_una_accion_no_tiene_asia_ni_londres(self):
        code, out, err = correr(perfil, ["--mercado", "TSLA", "--offline", YAHOO, "--ahora", "2026-11-11 10:45"])
        self.assertEqual(code, 2)
        self.assertIn("acción", err)


class Gamma(Base):
    def doc(self, *extra):
        code, out, err = correr(gamma, ["--mercado", "NQ", "--offline", OPC, "--precio", "26030", "--ahora", "2026-11-25 15:20", "--json", *extra])
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_black_scholes(self):
        # S=K=100, σ=20 %, T=1, r=0: gamma = φ(0,1)/(100·0,2) = 0,019848
        self.assertAlmostEqual(gamma.gamma_bs(100, 100, 0.2, 1.0, r=0.0), 0.019848, places=5)
        self.assertEqual(gamma.gamma_bs(100, 100, 0, 1.0), 0.0)

    def test_muros_a_cada_lado_y_gamma_0(self):
        d = self.doc()
        self.assertEqual([s["simbolo"] for s in d["subyacentes"]], ["QQQ", "^NDX"])
        self.assertGreaterEqual(d["muro_calls"], 26030)
        self.assertLessEqual(d["muro_puts"], 26030)
        self.assertEqual((d["muro_calls"] % 25, d["muro_puts"] % 25), (0, 0))       # filas de 25 puntos en el NQ
        self.assertIsNotNone(d["gamma_0"])
        self.assertIn(d["regimen"], ("positiva", "negativa"))
        self.assertEqual(d["vencimiento_esperado"], "2026-11-27")                     # lo que vence hoy queda fuera
        lo, hi = d["rango_esperado"]
        self.assertAlmostEqual((hi - lo) / 2, d["movimiento_esperado"], delta=0.5)

    def test_lo_que_vence_hoy_solo_con_la_opcion(self):
        sin, con = self.doc(), self.doc("--con-0dte")
        self.assertGreater(con["opciones_usadas"], sin["opciones_usadas"])
        self.assertEqual(con["vencimiento_esperado"], "2026-11-25")

    def test_sin_opciones_gratis_de_la_cme(self):
        code, out, err = correr(gamma, ["--mercado", "CL", "--offline", OPC])
        self.assertEqual(code, 2)
        self.assertIn("CME", err)

    def test_texto_con_supuesto_y_fuente(self):
        code, out, err = correr(gamma, ["--mercado", "NQ", "--offline", OPC, "--precio", "26030", "--ahora", "2026-11-25 15:20"])
        self.assertEqual(code, 0, err)
        for t in ("Muro de calls", "Muro de puts", "Gamma 0", "Supuesto", "no incluye las opciones sobre futuros de la CME"):
            self.assertIn(t, out)


if __name__ == "__main__":
    unittest.main()
