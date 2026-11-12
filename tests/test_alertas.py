"""kemet-alertas: reglas que suenan una vez, el reloj de Globex y el precio sobre el fixture real de NQ, sin red."""
import contextlib
import datetime as dt
import io
import json
import os
import shutil
import tempfile
import unittest

from _load import YAHOO, load

alertas = load("kemet-alertas", "alertas")
comun = alertas.comun


def correr(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = alertas.main(args)
    return code, out.getvalue(), err.getvalue()


def ny(texto):
    return comun.parse_ahora(texto)


class Alertas(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp(prefix="kemet-alertas-")
        os.chdir(self.tmp)
        self.kemet_dir = comun.KEMET_DIR                      # otros tests pueden haberlo movido: aquí, dentro del temporal
        comun.KEMET_DIR = os.path.join(self.tmp, "kemet")
        os.makedirs(comun.KEMET_DIR, exist_ok=True)

    def tearDown(self):
        comun.KEMET_DIR = self.kemet_dir
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def escribir(self, nombre, doc):
        with open(comun.ruta(nombre), "w", encoding="utf-8") as fh:
            json.dump(doc, fh)

    # ---- reloj de Globex

    def test_reloj_globex(self):
        self.assertEqual(alertas.estado(ny("2026-11-13 17:30"), "NQ")["globex"], "cerrado")    # viernes, cierre semanal
        self.assertEqual(alertas.estado(ny("2026-11-15 18:30"), "NQ")["globex"], "abierto")    # domingo noche
        self.assertEqual(alertas.estado(ny("2026-11-10 17:30"), "NQ")["globex"], "pausa")      # martes, pausa diaria
        st = alertas.estado(ny("2026-11-11 10:00"), "NQ")
        self.assertEqual((st["globex"], st["regular"], st["regular_abre"], st["regular_cierra"]), ("abierto", True, "09:30", "16:00"))
        self.assertEqual(alertas.estado(ny("2026-11-13 17:30"), "NQ")["proxima_apertura"], "15/11/2026 18:00")
        self.assertEqual(alertas.estado(ny("2026-11-10 17:30"), "NQ")["proxima_apertura"], "10/11/2026 18:00")
        rec = alertas.estado(ny("2026-11-27 11:00"), "NQ")                                     # día después de Thanksgiving
        self.assertEqual((rec["globex"], rec["regular_cierra"]), ("abierto", "13:00"))
        self.assertEqual(alertas.estado(ny("2026-12-25 11:00"), "NQ")["globex"], "cerrado")
        code, out, _ = correr(["reloj", "--ahora", "2026-11-13 17:30", "--mercado", "NQ"])
        self.assertEqual(code, 1)
        self.assertIn("CERRADO", out)
        code, out, _ = correr(["reloj", "--ahora", "2026-11-15 18:30"])
        self.assertEqual(code, 0)
        self.assertIn("ABIERTO", out)

    def test_hora_limite_de_chicago_a_nueva_york(self):
        t, zona = alertas.hora_limite_ny({"hora_limite": "15:10", "hora_limite_tz": "America/Chicago"})
        self.assertEqual(comun.hhmm(t), "16:10")
        t, _ = alertas.hora_limite_ny({"hora_limite": "16:59", "hora_limite_tz": "America/New_York"})
        self.assertEqual(comun.hhmm(t), "16:59")

    # ---- precio

    def test_precio_ultimo_y_cierre_anterior(self):
        q = alertas.precio_ultimo("NQ", ny("2026-11-11 10:00"), YAHOO)
        self.assertEqual(q["precio"], 28291.5)                        # cierre de la vela de 09:55
        self.assertEqual((q["hora_vela"], q["cierra"], q["intervalo"], q["retraso_min"]), ("2026-11-11 09:55", "10:00", "5m", 0))
        self.assertEqual(q["fecha_cierre_anterior"], "2026-11-10")
        ch = comun.velas("NQ", "60d", "5m", YAHOO)
        dias = comun.por_dia(ch["velas"])
        d = dt.date(2026, 11, 10)
        self.assertEqual(q["cierre_anterior"], comun.regular("NQ", dias[d], d)[-1][4])
        tarde = alertas.precio_ultimo("NQ", ny("2026-11-11 16:30"), YAHOO)
        self.assertEqual(tarde["fecha_cierre_anterior"], "2026-11-11")   # la sesión regular del día ya ha terminado
        self.assertEqual(tarde["cierre_anterior"], 28484.25)

    def test_quote_escribe_precios(self):
        code, out, err = correr(["quote", "NQ", "MES", "--escribir", "--ahora", "2026-11-11 16:30", "--offline", YAHOO])
        self.assertEqual(code, 0, err)
        with open(comun.ruta("precios.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(sorted(doc["precios"]), ["ES", "NQ"])
        self.assertEqual(doc["precios"]["NQ"]["precio"], 28457.25)
        self.assertEqual(doc["precios"]["NQ"]["hora_vela"], "2026-11-11 16:25")
        self.assertIn("generado", doc)
        self.assertIn("retraso", out)

    # ---- reglas

    def test_stop_suena_una_vez_y_no_dos(self):
        self.escribir("alertas.json", {"reglas": [{"id": "nq-stop", "simbolo": "NQ", "tipo": "stop", "precio": 28500.0, "lado": "largo"}]})
        code, out, err = correr(["check", "--ahora", "2026-11-11 16:30", "--offline", YAHOO])
        self.assertEqual(code, 0, err)
        self.assertIn("ALERTA NQ último 28.457,25", out)
        self.assertIn("por debajo de tu stop 28.500", out)
        code, out, err = correr(["check", "--ahora", "2026-11-11 16:35", "--offline", YAHOO])
        self.assertEqual(code, 1, err)
        self.assertIn("Nada ha sonado", out)
        with open(comun.ruta(os.path.join("estado", "alertas.json")), encoding="utf-8") as fh:
            estado = json.load(fh)
        self.assertIn("nq-stop", estado["sonaron"])
        code, out, _ = correr(["reset", "nq-stop"])
        self.assertEqual(code, 0)
        code, out, err = correr(["check", "--ahora", "2026-11-11 16:40", "--offline", YAHOO])
        self.assertEqual(code, 0, err)

    def test_stop_de_un_corto_esta_por_encima(self):
        self.escribir("alertas.json", {"reglas": [
            {"id": "c-stop", "simbolo": "NQ", "tipo": "stop", "precio": 28450.0, "lado": "corto"},
            {"id": "c-obj", "simbolo": "NQ", "tipo": "objetivo", "precio": 28460.0, "lado": "corto"}]})
        code, out, err = correr(["check", "--ahora", "2026-11-11 16:30", "--offline", YAHOO, "--json"])   # último 28.457,25
        self.assertEqual(code, 0, err)
        ids = [t["id"] for t in json.loads(out)["sonaron"]]
        self.assertEqual(ids, ["c-stop", "c-obj"])

    def test_hora_respeta_la_fecha(self):
        self.escribir("alertas.json", {"reglas": [{"id": "plano", "simbolo": "NQ", "tipo": "hora", "a": "15:55", "etiqueta": "plano a", "fecha": "2026-11-12"}]})
        code, out, err = correr(["check", "--ahora", "2026-11-11 16:30", "--offline", YAHOO])
        self.assertEqual(code, 1, err)
        self.assertIn("0 regla(s) vigilada(s)", out)
        code, out, err = correr(["check", "--ahora", "2026-11-12 15:50", "--offline", YAHOO])
        self.assertEqual(code, 1, err)
        code, out, err = correr(["check", "--ahora", "2026-11-12 15:55", "--offline", YAHOO])
        self.assertEqual(code, 0, err)
        self.assertIn("ALERTA Plano a: son las 15:55 NY", out)
        code, out, err = correr(["check", "--ahora", "2026-11-12 16:00", "--offline", YAHOO])
        self.assertEqual(code, 1, err)

    def test_pct_sobre_el_cierre_regular_anterior(self):
        self.escribir("alertas.json", {"reglas": [{"id": "nq-pct", "simbolo": "NQ", "tipo": "pct", "pct": 0.05}]})
        code, out, err = correr(["check", "--ahora", "2026-11-11 10:00", "--offline", YAHOO, "--json"])
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        q = alertas.precio_ultimo("NQ", ny("2026-11-11 10:00"), YAHOO)
        mov = 100.0 * (28291.5 / q["cierre_anterior"] - 1)
        self.assertGreaterEqual(abs(mov), 0.05)
        self.assertIn(comun.num(mov, 2), doc["sonaron"][0]["mensaje"])
        self.assertIn(comun.pts(q["cierre_anterior"]), doc["sonaron"][0]["mensaje"])
        self.assertIn("10/11/2026", doc["sonaron"][0]["mensaje"])
        # con dirección contraria no suena
        self.escribir("alertas.json", {"reglas": [{"id": "nq-pct2", "simbolo": "NQ", "tipo": "pct", "pct": 0.05, "direccion": "sube" if mov < 0 else "baja"}]})
        code, out, err = correr(["check", "--ahora", "2026-11-11 10:00", "--offline", YAHOO])
        self.assertEqual(code, 1, err)

    def test_desde_plan_y_hora_limite_y_apertura(self):
        self.escribir("plan.json", {"mercado": "NQ", "micro": "MNQ", "fecha": "2026-11-11", "lado": "largo", "entrada": 28429.75,
                                    "hora_entrada": "10:45", "barra": 15, "stop": 28312.5, "regla_stop": "ib-medio",
                                    "objetivo": 28547.0, "regla_objetivo": "R:1", "plano_a": "15:55"})
        self.escribir("config.json", {"mercado": "NQ", "cuenta_nombre": "Topstep 50K Combine", "hora_limite": "15:10",
                                      "hora_limite_tz": "America/Chicago", "plano_a": "15:55"})
        code, out, err = correr(["add", "--desde-plan"])
        self.assertEqual(code, 0, err)
        with open(comun.ruta("alertas.json"), encoding="utf-8") as fh:
            reglas = json.load(fh)["reglas"]
        self.assertEqual([r["id"] for r in reglas], ["nq-plan-stop", "nq-plan-objetivo", "nq-plano-a"])
        self.assertTrue(all(r["fecha"] == "2026-11-11" for r in reglas))
        self.assertEqual(reglas[2]["a"], "15:55")
        self.assertEqual(correr(["add", "--hora-limite"])[0], 0)
        self.assertEqual(correr(["add", "--apertura"])[0], 0)
        self.assertEqual(correr(["add", "--apertura"])[0], 2)         # id repetido
        # 10:53: la apertura suena, nada más
        code, out, err = correr(["check", "--ahora", "2026-11-11 10:53", "--offline", YAHOO, "--json"])
        self.assertEqual(code, 0, err)
        self.assertEqual([t["id"] for t in json.loads(out)["sonaron"]], ["apertura-nq"])
        # 11:00: la vela de 10:55 cerró en 28.549,50, por encima del objetivo 28.547
        code, out, err = correr(["check", "--ahora", "2026-11-11 11:00", "--offline", YAHOO, "--json"])
        self.assertEqual([t["id"] for t in json.loads(out)["sonaron"]], ["nq-plan-objetivo"])
        # 16:05: cinco minutos antes de la hora límite (15:10 Chicago = 16:10 NY)
        code, out, err = correr(["check", "--ahora", "2026-11-11 16:05", "--offline", YAHOO, "--json"])
        sonaron = json.loads(out)["sonaron"]
        self.assertEqual([t["id"] for t in sonaron], ["nq-plano-a", "hora-limite"])
        self.assertIn("faltan 5 minutos", sonaron[1]["mensaje"])
        self.assertIn("16:10 NY", sonaron[1]["mensaje"])
        # al día siguiente las reglas del plan ya no se vigilan
        code, out, err = correr(["check", "--ahora", "2026-11-12 11:00", "--offline", YAHOO, "--json"])
        self.assertEqual([t["id"] for t in json.loads(out)["sonaron"]], ["apertura-nq"])

    def test_add_manual_y_validacion(self):
        code, out, err = correr(["add", "--simbolo", "MNQ", "--encima", "28500", "--fecha", "2026-11-11"])
        self.assertEqual(code, 0, err)
        self.assertIn("nq-encima-28500", out)
        code, out, err = correr(["add", "--simbolo", "XX", "--debajo", "1"])
        self.assertEqual(code, 2)
        code, out, err = correr(["add", "--a", "25:00"])
        self.assertEqual(code, 2)
        code, out, err = correr(["add", "--hora-limite"])                # sin config.json
        self.assertEqual(code, 2)
        code, out, _ = correr(["list"])
        self.assertEqual(code, 0)
        self.assertIn("nq-encima-28500", out)


if __name__ == "__main__":
    unittest.main()
