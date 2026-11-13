"""kemet-riesgo: PASS y BLOCK por orden, un cierre nunca se bloquea por el día, registrar y hoy; las acciones con la cuenta propia
(TSLA del 11/11/2026, ruptura del rango de 15 minutos del fixture real) y la huella idéntica a la de kemet-broker. Sin red."""
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


# Cuenta propia: 5.000 $, 50 $ por operación, 150 $ al día (tamano.py config --propia). La orden de kemet-tamano para TSLA el 11/11/2026:
# rango de 15 min 386,35 a 392,67, la vela de las 10:10 cerró en 393,08 (10:15), stop en el punto medio 389,51, objetivo 1R 396,65:
# 9 acciones (manda la posición máxima, 3.750 $), 32,13 $ al stop.
CONFIG_PROPIA = {"mercado": "TSLA", "tipo_cuenta": "propia", "firma": None, "cuenta": "propia", "cuenta_nombre": "Cuenta propia · 5.000 $", "presupuesto": 5000,
                 "efectivo_pct": 10, "max_posicion_pct": 75, "max_orden_usd": 4000, "min_orden_usd": 5, "perdida_max_dia": 150, "riesgo_por_operacion": 50,
                 "fallos_y_paras": 3, "semaforo": "verde", "max_micro": None, "hora_limite": None, "hora_limite_tz": None, "sin_entradas_antes": "09:45",
                 "sin_entradas_despues": "15:00", "plano_a": "15:55", "zona_usuario": "Europe/Madrid", "papel": True, "permitir_cortos": False,
                 "permitir_margen": False, "permitir_opciones": False, "bloqueados": [], "sec_user_agent": "Nombre correo@ejemplo.com"}
ORDEN_TSLA = {"symbol": "TSLA", "side": "buy", "qty": "9", "type": "market", "time_in_force": "day", "order_class": "bracket",
              "take_profit_limit_price": "396.65", "stop_loss_stop_price": "389.51",
              "why": "largo TSLA: 9 acciones, manda posición máxima (9 × 3,57 $ = 32,13 $ al stop)",
              "plan": {"fecha": "2026-11-11", "lado": "largo", "entrada": 393.08, "stop": 389.51, "objetivo": 396.65, "hora_entrada": "10:15",
                       "plano_a": "15:55", "riesgo_por_accion": 3.57, "perdida_max_usd": 32.13, "coste": 3537.72},
              "instrumento": "accion"}
CIERRE_TSLA = {"symbol": "TSLA", "side": "sell", "qty": "9", "type": "market", "time_in_force": "day", "instrumento": "accion"}


class Acciones(Base):
    def setUp(self):
        super().setUp()
        comun.escribir_json(os.path.join(self.kemet, "config.json"), CONFIG_PROPIA)
        self.ordenes([ORDEN_TSLA])

    def cartera(self, efectivo, posiciones=()):
        comun.escribir_json(os.path.join(self.kemet, "portfolio.json"), {"efectivo": efectivo, "posiciones": list(posiciones), "actualizado": "2026-11-11T15:00:00Z"})

    def broker(self, ordenes):
        comun.escribir_json(os.path.join(self.kemet, "estado", "broker.json"), {"fecha": "2026-11-11", "ordenes": ordenes})

    def test_pass_con_el_ejemplo_de_tsla(self):
        code, res = self.check("2026-11-11 10:15", escribir=True)
        self.assertEqual(code, 0, self.motivos(res))
        r = res["resultados"][0]
        self.assertEqual((r["veredicto"], r["clase"], r["instrumento"], r["simbolo"], r["lado"], r["contratos"]), ("PASS", "entrada", "accion", "TSLA", "compra", 9))
        self.assertEqual((r["precio"], r["stop"], r["objetivo"], r["riesgo_pts"], r["perdida_max_usd"], r["valor_usd"]), (393.08, 389.51, 396.65, 3.57, 32.13, 3537.72))
        self.assertEqual(res["hoy"]["queda"], 150.0)
        code, out, err = run(["check", "--ahora", "2026-11-11 10:15", "--sin-escribir"])
        self.assertIn("PASS  #1 compra 9 TSLA, entrada", out)
        self.assertIn("riesgo 3,57 $ por acción", out)
        # el usuario la pone: registrar la apunta como una operación más, en acciones
        code, out, err = run(["registrar", "--abrir", "--ahora", "2026-11-11 10:16"])
        self.assertEqual(code, 0, err)
        op = self.leer("estado", "dia.json")["operaciones"][0]
        self.assertEqual((op["simbolo"], op["contratos"], op["entrada"], op["riesgo_usd"], op["instrumento"]), ("TSLA", 9, 393.08, 32.13, "accion"))
        code, out, err = run(["hoy", "--ahora", "2026-11-11 10:20"])
        self.assertIn("Queda del día: 117,87 $ de 150 $", out)

    def test_block_por_perdida_posicion_tamano_y_efectivo(self):
        self.ordenes([dict(ORDEN_TSLA, qty="20")])
        code, res = self.check("2026-11-11 10:15")
        self.assertEqual(code, 1)
        m = self.motivos(res)
        self.assertIn("pérdida: 20 × 3,57 $ por acción = 71,40 $ al stop, más que tu riesgo por operación de 50,00 $", m)
        self.assertIn("tamaño: 7.861,60 $, más que tu orden máxima de 4.000 $", m)
        self.assertIn("posición: TSLA sería 7.861,60 $, el 157,2 % de 5.000 $, más que tu tope del 75 % (3.750 $)", m)
        self.assertIn("efectivo: hacen falta 7.861,60 $ y hay 5.000,00 $ de efectivo; eso sería margen", m)
        self.ordenes([dict(ORDEN_TSLA, qty="10")])            # 35,70 $ al stop caben; 3.930,80 $ de posición no
        code, res = self.check("2026-11-11 10:15")
        self.assertEqual(res["resultados"][0]["motivos"], ["posición: TSLA sería 3.930,80 $, el 78,6 % de 5.000 $, más que tu tope del 75 % (3.750 $)"])

    def test_block_por_efectivo_con_cartera(self):
        self.cartera(2000.0)
        code, res = self.check("2026-11-11 10:15")
        self.assertEqual(code, 1)
        self.assertIn("efectivo: hacen falta 3.537,72 $ y hay 2.000,00 $ de efectivo; eso sería margen (dinero prestado) y no lo permites", self.motivos(res))
        self.cartera(3900.0)
        code, res = self.check("2026-11-11 10:15")
        self.assertIn("efectivo: dejaría 362,28 $ de efectivo, por debajo de tu colchón del 10 % (500 $)", self.motivos(res))
        self.cartera(4500.0)
        code, res = self.check("2026-11-11 10:15")
        self.assertEqual(code, 0, self.motivos(res))

    def test_block_por_corto_bloqueado_opciones_y_festivo(self):
        corto = dict(ORDEN_TSLA, side="sell", take_profit_limit_price="389.51", stop_loss_stop_price="396.65",
                     plan=dict(ORDEN_TSLA["plan"], lado="corto", stop=396.65, objetivo=389.51))
        self.ordenes([corto])
        code, res = self.check("2026-11-11 10:15")
        self.assertEqual(code, 1)
        self.assertIn("corto: vendes 9 TSLA y tienes 0; vender en corto no está permitido", self.motivos(res))
        comun.escribir_json(os.path.join(self.kemet, "config.json"), dict(CONFIG_PROPIA, permitir_cortos=True))
        code, res = self.check("2026-11-11 10:15")
        self.assertEqual(code, 0, self.motivos(res))
        self.assertEqual(res["resultados"][0]["clase"], "entrada")
        comun.escribir_json(os.path.join(self.kemet, "config.json"), dict(CONFIG_PROPIA, bloqueados=["tsla"]))
        self.ordenes([ORDEN_TSLA])
        code, res = self.check("2026-11-11 10:15")
        self.assertIn("bloqueado: TSLA está en tu lista de bloqueados", self.motivos(res))
        comun.escribir_json(os.path.join(self.kemet, "config.json"), CONFIG_PROPIA)
        self.ordenes([dict(ORDEN_TSLA, symbol="TSLA261120C00400000")])
        code, res = self.check("2026-11-11 10:15")
        self.assertIn("opciones: TSLA261120C00400000 es un contrato de opciones y tu cuenta no las permite", self.motivos(res))
        self.ordenes([ORDEN_TSLA])
        code, res = self.check("2026-11-26 10:15")           # Thanksgiving: la NYSE no abre
        self.assertEqual(res["resultados"][0]["motivos"], ["mercado: NYSE cerrado (Thanksgiving), 10:15 NY"])
        code, res = self.check("2026-11-11 09:20")
        self.assertIn("mercado: NYSE cerrado (antes de la apertura (09:30 NY)), 09:20 NY", self.motivos(res))
        code, res = self.check("2026-11-11 09:40")
        self.assertIn("ventana: apertura 09:30–09:45 NY", self.motivos(res))
        code, res = self.check("2026-11-11 15:58")
        self.assertIn("horario: a las 15:55 NY se está plano", self.motivos(res))
        self.assertNotIn("hora límite", self.motivos(res))    # una cuenta propia no tiene hora límite de firma

    def test_duplicado_por_broker_y_por_dia(self):
        h = riesgo.huella(ORDEN_TSLA)
        self.broker([{"fecha": "2026-11-11", "cuando": "10:16", "huella": h, "simbolo": "TSLA", "lado": "compra", "cantidad": "9", "instrumento": "accion",
                      "clase": "entrada", "perdida_al_stop": 32.13, "estado": "aprobada"},
                     {"fecha": "2026-11-11", "cuando": "10:17", "huella": h, "simbolo": "TSLA", "lado": "compra", "cantidad": "9", "instrumento": "accion",
                      "clase": "entrada", "perdida_al_stop": 32.13, "estado": "colocada", "id_broker": "abc"}])
        code, res = self.check("2026-11-11 10:20")
        self.assertEqual(code, 1)
        self.assertIn("duplicado: esta misma orden (huella %s) ya está apuntada hoy" % h, self.motivos(res))
        self.assertEqual((res["hoy"]["operaciones"], res["hoy"]["riesgo_abierto"], res["hoy"]["colocadas_broker"]), (1, 32.13, 1))
        self.ordenes([dict(ORDEN_TSLA, qty="8")])            # otra huella, misma compra de TSLA colocada hoy
        code, res = self.check("2026-11-11 10:20")
        self.assertIn("duplicado: hoy ya se colocó una compra de TSLA (kemet/estado/broker.json)", self.motivos(res))
        self.broker([{"fecha": "2026-11-11", "cuando": "10:17", "huella": h, "simbolo": "TSLA", "lado": "compra", "cantidad": "9", "instrumento": "accion",
                      "clase": "entrada", "perdida_al_stop": 32.13, "estado": "denegada"}])
        self.ordenes([ORDEN_TSLA])
        code, res = self.check("2026-11-11 10:20")
        self.assertEqual(code, 0, self.motivos(res))         # una denegada no cuenta
        self.dia([{"hora": "10:16", "simbolo": "TSLA", "lado": "compra", "contratos": 9, "riesgo_usd": 32.13, "resultado_usd": None, "cerrada": None, "huella": h}])
        code, res = self.check("2026-11-11 10:20")
        self.assertIn("duplicado: esta misma orden (huella %s) ya está apuntada hoy en kemet/estado/dia.json" % h, self.motivos(res))

    def test_una_venta_de_cierre_pasa_con_el_dia_agotado(self):
        self.dia([{"hora": "10:16", "simbolo": "TSLA", "lado": "compra", "contratos": 9, "riesgo_usd": 32.13, "resultado_usd": -150.0, "cerrada": "12:00"},
                  {"hora": "13:00", "simbolo": "TSLA", "lado": "compra", "contratos": 9, "riesgo_usd": 32.13, "resultado_usd": None, "cerrada": None}])
        self.cartera(1462.28, [{"simbolo": "TSLA", "cantidad": 9, "precio_medio": 393.08}])
        self.ordenes([ORDEN_TSLA, CIERRE_TSLA])                # la entrada no cabe; la venta de las 9 que tienes, sí
        code, res = self.check("2026-11-11 15:50")
        self.assertEqual(code, 1)
        self.assertEqual([r["veredicto"] for r in res["resultados"]], ["BLOCK", "PASS"])
        self.assertIn("día:", self.motivos(res))
        self.assertEqual((res["resultados"][1]["clase"], res["resultados"][1]["motivos"]), ("cierre", []))
        self.assertTrue(any("vendes 9 acciones de TSLA" in x for x in res["resultados"][1]["info"]))
        os.remove(os.path.join(self.kemet, "portfolio.json"))
        self.ordenes([dict(CIERRE_TSLA, cierre=True)])         # sin cartera, "cierre": true ya no basta: no reduce nada, es un corto
        code, res = self.check("2026-11-11 15:58")
        self.assertEqual(code, 1)
        self.assertEqual(res["resultados"][0]["clase"], "entrada")
        self.assertTrue(any("marcada como cierre" in x for x in res["resultados"][0]["avisos"]))
        self.ordenes([CIERRE_TSLA])                            # sin cartera y sin declararlo, vender es un corto
        code, res = self.check("2026-11-11 15:50")
        self.assertEqual(code, 1)
        self.assertIn("corto:", self.motivos(res))

    def test_precio_fresco_formato_y_sin_config(self):
        comun.escribir_json(os.path.join(self.kemet, "precios.json"), {"generado": "2026-11-11T15:14:00Z", "precios": {"TSLA": {"precio": 399.0, "leido": "2026-11-11T15:14:00Z"}}})
        self.ordenes([dict(ORDEN_TSLA, qty="14")])            # 14 × 3,57 = 49,98 $ caben con la entrada del plan; con 399 no
        code, res = self.check("2026-11-11 10:15")
        m = self.motivos(res)
        self.assertIn("pérdida: 14 × 9,49 $ por acción = 132,86 $ al stop", m)
        self.assertIn("objetivo: el objetivo 396,65 $ tiene que estar encima de la entrada 399,00 $", m)
        self.assertTrue(any("se mide desde 399,00 $" in x for x in res["resultados"][0]["info"]))
        os.remove(os.path.join(self.kemet, "precios.json"))
        self.ordenes([{"symbol": "tsla", "side": "hold", "qty": "1.5", "type": "limit", "time_in_force": "week", "order_class": "bracket"}])
        code, res = self.check("2026-11-11 10:15")
        m = self.motivos(res)
        for trozo in ("side tiene que ser buy o sell", "qty tiene que ser un entero", "una orden limit necesita limit_price", "time_in_force tiene que ser day o gtc",
                      "una orden bracket lleva take_profit_limit_price y stop_loss_stop_price"):
            self.assertIn(trozo, m)
        self.ordenes([dict(ORDEN_TSLA, qty=9)])
        code, res = self.check("2026-11-11 10:15")
        self.assertEqual(code, 0)
        self.assertTrue(any("qty va como número" in a for a in res["resultados"][0]["avisos"]))
        comun.escribir_json(os.path.join(self.kemet, "config.json"), CONFIG)   # la cuenta de firma no sirve para acciones
        self.ordenes([ORDEN_TSLA])
        code, res = self.check("2026-11-11 10:15")
        self.assertIn("cuenta: tu config es de una cuenta de firma", self.motivos(res))
        os.remove(os.path.join(self.kemet, "config.json"))
        code, res = self.check("2026-11-11 10:15")
        self.assertEqual(code, 0, self.motivos(res))         # sin config: los topes por defecto de una cuenta propia
        self.assertTrue(any("valores por defecto de una cuenta propia" in a for a in res["avisos"]))

    def test_huella_identica_a_la_de_kemet_broker(self):
        broker = load("kemet-broker", "broker")
        for o in (ORDEN_TSLA, CIERRE_TSLA, dict(CIERRE_TSLA, cierre=True), ORDEN, CIERRE, dict(ORDEN, instrumento="futuro")):
            self.assertEqual(riesgo.huella(o), broker.huella(o), o)
        self.assertEqual(riesgo.huella(dict(ORDEN, instrumento="futuro")), riesgo.huella(ORDEN))   # el instrumento no cambia la huella
        self.assertEqual(riesgo.huella(dict(ORDEN_TSLA, why="otra nota")), riesgo.huella(ORDEN_TSLA))
        self.assertNotEqual(riesgo.huella(dict(ORDEN_TSLA, qty="8")), riesgo.huella(ORDEN_TSLA))


if __name__ == "__main__":
    unittest.main()
