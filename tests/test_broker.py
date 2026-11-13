"""kemet-broker: el ticket LISTO solo con PASS de hoy y la misma huella, el sí explícito, el registro del fill en
broker.json y portfolio.json, la orden de cierre y el ticket de un futuro (a mano). Sin red. Las órdenes y los
veredictos de riesgo de acciones son sintéticos (la de TSLA sale del rango de apertura real del 11/11/2026 en el
fixture TSLA-60d-5m.json.gz: 386,35 a 392,67, vela de las 10:10 cerrada en 393,08); el veredicto del futuro lo
escribe el propio kemet-riesgo/riesgo.py."""
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

broker = load("kemet-broker", "broker")
riesgo = load("kemet-riesgo", "riesgo")
comun = sys.modules["comun"]

CONFIG_PROPIA = {"mercado": "TSLA", "cuenta": "propia", "tipo_cuenta": "propia", "cuenta_nombre": "Cuenta propia · 5.000 $ papel",
                 "presupuesto": 5000, "efectivo_pct": 10, "max_posicion_pct": 75, "max_orden_usd": 4000, "min_orden_usd": 5,
                 "perdida_max_dia": 150, "riesgo_por_operacion": 50, "fallos_y_paras": 3, "sin_entradas_antes": "09:45",
                 "sin_entradas_despues": "15:00", "plano_a": "15:55", "papel": True, "permitir_cortos": False, "permitir_margen": False,
                 "permitir_opciones": False, "bloqueados": []}
CONFIG_APEX = {"mercado": "NQ", "firma": "apex", "cuenta": "eod-pa-150", "cuenta_nombre": "Apex Trader Funding · 150K EOD fondeada (PA)",
               "fase": "financiada", "drawdown": 4000, "drawdown_tipo": "eod_trailing", "limite_diario_firma": 2000, "max_micro": 170,
               "max_mini": 17, "hora_limite": "16:59", "hora_limite_tz": "America/New_York", "consistencia": None, "perdida_max_dia": 1000,
               "fallos_y_paras": 3, "semaforo": "verde", "sin_entradas_antes": "09:45", "sin_entradas_despues": "15:00", "plano_a": "15:55",
               "zona_usuario": "Europe/Madrid", "papel": True}
TSLA = {"instrumento": "accion", "symbol": "TSLA", "side": "buy", "qty": "8", "type": "market", "time_in_force": "day", "order_class": "bracket",
        "take_profit_limit_price": "396.65", "stop_loss_stop_price": "389.51",
        "why": "ruptura del rango de apertura de TSLA: 8 acciones, 3,57 $ de riesgo por acción, 28,56 $ al stop dentro de tus 50 $ por operación",
        "plan": {"fecha": "2026-11-11", "lado": "largo", "entrada": 393.08, "hora_entrada": "10:15", "stop": 389.51, "objetivo": 396.65,
                 "riesgo_pts": 3.57, "plano_a": "15:55", "ib": {"alto": 392.67, "bajo": 386.35, "ancho": 6.32, "minutos": 15}}}
MNQ = {"instrumento": "futuro", "simbolo": "MNQ", "lado": "compra", "contratos": 1, "tipo": "stop", "precio": 28429.75, "stop": 28312.5,
       "objetivo": 28547.0, "riesgo_pts": 117.25, "perdida_max_usd": 234.5,
       "por_que": "ruptura del balance inicial de NQ: 1 MNQ, manda el riesgo por operación", "plan": {"fecha": "2026-11-11", "lado": "largo", "plano_a": "15:55"}}
HOY = "2026-11-11"


def run(mod, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mod.main(argv)
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="kemet-broker-")
        self.kemet = os.path.join(self.dir, "kemet")
        comun.KEMET_DIR = self.kemet
        comun.escribir_json(os.path.join(self.kemet, "config.json"), CONFIG_PROPIA)
        self.ordenes([TSLA])
        self.veredicto(TSLA)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def ordenes(self, lista, **extra):
        doc = {"generado": "2026-11-11T15:15:00Z", "ordenes": lista, "cuenta": CONFIG_PROPIA["cuenta_nombre"], "papel": True}
        doc.update(extra)
        comun.escribir_json(os.path.join(self.kemet, "orden.json"), doc)

    def veredicto(self, orden, fecha=HOY, veredicto="PASS", motivos=(), hora_utc="15:15"):
        """Un kemet/estado/riesgo.json como el que escribe riesgo.py check, con la huella de esa orden."""
        comun.escribir_json(os.path.join(self.kemet, "estado", "riesgo.json"), {
            "fecha": fecha, "ahora_ny": fecha + " 10:16", "papel": True, "cuenta": CONFIG_PROPIA["cuenta_nombre"],
            "comprobado": fecha + "T" + hora_utc + ":00Z", "simulado": True,
            "resultados": [{"indice": 1, "simbolo": "TSLA", "lado": "compra", "clase": "cierre" if orden.get("cierre") else "entrada",
                            "huella": broker.huella(orden), "veredicto": veredicto, "motivos": list(motivos), "avisos": [], "info": [], "orden": orden}],
            "pass": 1 if veredicto == "PASS" else 0, "block": 0 if veredicto == "PASS" else 1, "avisos": []})

    def leer(self, *partes):
        with open(os.path.join(self.kemet, *partes), encoding="utf-8") as fh:
            return json.load(fh)

    def mostrar(self, ahora=HOY + " 10:16"):
        code, out, err = run(broker, ["mostrar", "--ahora", ahora, "--json"])
        self.assertIn(code, (0, 1), err)
        return code, json.loads(out)


class TestTicket(Base):
    def test_huella_de_un_futuro_es_la_de_kemet_riesgo(self):
        self.assertEqual(broker.huella(MNQ), riesgo.huella(MNQ))
        self.assertEqual(broker.huella(MNQ), "f2328b1ec6e1")           # la del ejemplo de kemet-riesgo
        self.assertEqual(len(broker.huella(TSLA)), 12)
        self.assertNotEqual(broker.huella(TSLA), broker.huella(dict(TSLA, qty="9")))
        self.assertEqual(broker.huella(TSLA), broker.huella(dict(TSLA, why="otro texto")))   # el por qué no cambia la orden

    def test_lista_con_pass_de_hoy(self):
        code, tickets = self.mostrar()
        self.assertEqual(code, 0)
        t = tickets[0]
        self.assertTrue(t["lista"])
        self.assertTrue(t["estado"].startswith("LISTA"))
        self.assertEqual(t["instrumento"], "accion")
        self.assertEqual(t["herramienta"], "place_stock_order")
        self.assertEqual(t["entrada_herramienta"], {"symbol": "TSLA", "side": "buy", "qty": "8", "type": "market", "time_in_force": "day",
                                                    "order_class": "bracket", "take_profit_limit_price": "396.65", "stop_loss_stop_price": "389.51",
                                                    "client_order_id": "kemet-" + broker.huella(TSLA) + "-20261111-1"})
        self.assertNotIn("why", t["entrada_herramienta"])
        self.assertEqual(t["perdida_al_stop"], 28.56)
        self.assertIn("COMPRA 8 TSLA, a mercado, válida hoy", t["llano"])
        code, out, err = run(broker, ["mostrar", "--ahora", HOY + " 10:16"])
        self.assertEqual(code, 0)
        self.assertIn("cuenta PAPEL, Alpaca", out)
        self.assertIn("pérdida al stop unos 28,56 $ si se llena justo en 389,51", out)
        self.assertIn("Responde «sí» para poner esta orden", out)
        self.assertNotIn("\u2014", out)          # sin guion largo en lo que lee el usuario

    def test_no_lista_sin_pass(self):
        os.remove(os.path.join(self.kemet, "estado", "riesgo.json"))
        code, tickets = self.mostrar()
        self.assertEqual(code, 1)
        self.assertFalse(tickets[0]["lista"])
        self.assertIn("sin comprobación de kemet-riesgo", tickets[0]["estado"])

    def test_no_lista_con_pass_de_ayer(self):
        self.veredicto(TSLA, fecha="2026-11-10")
        code, tickets = self.mostrar()
        self.assertEqual(code, 1)
        self.assertIn("es del 2026-11-10, no de hoy", tickets[0]["estado"])

    def test_no_lista_si_la_orden_se_edito(self):
        self.ordenes([dict(TSLA, qty="9")])
        code, tickets = self.mostrar()
        self.assertEqual(code, 1)
        self.assertIn("no está en la última comprobación (se editó o es nueva)", tickets[0]["estado"])

    def test_bloqueada_por_riesgo(self):
        self.veredicto(TSLA, veredicto="BLOCK", motivos=["pérdida: 9 × 3,57 = 32,13 $ al stop, más que tu riesgo por operación"])
        code, tickets = self.mostrar()
        self.assertEqual(code, 1)
        self.assertIn("BLOQUEADA por kemet-riesgo: pérdida: 9 × 3,57", tickets[0]["estado"])


class TestSi(Base):
    def test_que_cuenta_como_si(self):
        lote = ["TSLA", "AAPL"]
        for mala in ("", "vale", "ok", "adelante", "¿sí?", "sí a las dos", "sí, todas", "sí pero espera", "sí, 10 acciones", "sí, la de AAPL", "si baja a 390 sí"):
            vale, por_que = broker.es_un_si(mala, TSLA, lote)
            self.assertFalse(vale, mala + ": " + por_que)
        for buena in ("sí", "si", "Sí.", "sí, las 8 de TSLA", "sí, a 393,08 con stop 389,51", "sí, 28,56 $ de riesgo"):
            vale, por_que = broker.es_un_si(buena, TSLA, lote)
            self.assertTrue(vale, buena + ": " + por_que)

    def test_aprobar_apunta_el_si_y_la_orden_deja_de_estar_lista(self):
        h = broker.huella(TSLA)
        code, out, err = run(broker, ["aprobar", "--huella", h, "--respuesta", "vale", "--ahora", HOY + " 10:16"])
        self.assertEqual(code, 1)
        self.assertIn("No apuntado", out)
        self.assertFalse(os.path.exists(os.path.join(self.kemet, "estado", "broker.json")))
        code, out, err = run(broker, ["aprobar", "--huella", h, "--respuesta", "sí", "--ahora", HOY + " 10:16"])
        self.assertEqual(code, 0, err)
        self.assertIn("Apuntado tu sí para " + h, out)
        self.assertIn('"symbol": "TSLA"', out)
        rec = self.leer("estado", "broker.json")["ordenes"][-1]
        self.assertEqual((rec["estado"], rec["huella"], rec["respuesta"], rec["fecha"], rec["cuando"]), ("aprobada", h, "sí", HOY, "10:16"))
        code, tickets = self.mostrar(HOY + " 10:17")
        self.assertEqual(code, 1)
        self.assertIn("APROBADA por ti a las 10:16 NY", tickets[0]["estado"])
        code, out, err = run(broker, ["aprobar", "--huella", h, "--respuesta", "sí", "--ahora", HOY + " 10:18"])   # dos síes no son dos órdenes
        self.assertEqual(code, 2)
        self.assertIn("no está lista", err)

    def test_aprobar_no_acepta_una_orden_que_no_esta_lista(self):
        self.veredicto(TSLA, fecha="2026-11-10")
        code, out, err = run(broker, ["aprobar", "--huella", broker.huella(TSLA), "--respuesta", "sí", "--ahora", HOY + " 10:16"])
        self.assertEqual(code, 2)
        self.assertIn("no de hoy", err)


class TestRegistro(Base):
    def test_registrar_actualiza_broker_y_cartera(self):
        h = broker.huella(TSLA)
        run(broker, ["aprobar", "--huella", h, "--respuesta", "sí", "--ahora", HOY + " 10:16"])
        code, out, err = run(broker, ["registrar", "--huella", h, "--id-broker", "61e69015-8549", "--precio", "393.10", "--ahora", HOY + " 10:17"])
        self.assertEqual(code, 0, err)
        self.assertNotIn("AVISO", out)
        self.assertIn("compra 8 TSLA a 393,10, id 61e69015-8549", out)
        self.assertIn("efectivo 1.855,20 $", out)
        rec = self.leer("estado", "broker.json")["ordenes"][-1]
        self.assertEqual((rec["estado"], rec["id_broker"], rec["precio"], rec["cantidad"], rec["simbolo"], rec["lado"]), ("colocada", "61e69015-8549", 393.1, "8", "TSLA", "compra"))
        self.assertEqual(rec["perdida_al_stop"], 28.56)
        pf = self.leer("portfolio.json")
        self.assertEqual(pf["efectivo"], 1855.2)
        self.assertEqual(pf["posiciones"], [{"simbolo": "TSLA", "cantidad": 8.0, "precio_medio": 393.1, "instrumento": "accion"}])
        self.assertTrue(pf["actualizado"].startswith(HOY))
        code, tickets = self.mostrar(HOY + " 10:18")
        self.assertIn("HECHA: colocada a las 10:17 NY (id 61e69015-8549)", tickets[0]["estado"])
        code, out, err = run(broker, ["hoy", "--ahora", HOY + " 10:19"])
        self.assertEqual(code, 0)
        self.assertIn("1 colocada hoy", out)

    def test_registrar_sin_si_avisa_pero_apunta(self):
        h = broker.huella(TSLA)
        code, out, err = run(broker, ["registrar", "--huella", h, "--id-broker", "x1", "--precio", "393.10", "--ahora", HOY + " 10:17"])
        self.assertEqual(code, 0, err)
        self.assertIn("AVISO: no hay un sí apuntado hoy", out)
        self.assertEqual(self.leer("portfolio.json")["efectivo"], 1855.2)

    def test_registrar_exige_id_y_precio_en_alpaca(self):
        h = broker.huella(TSLA)
        code, out, err = run(broker, ["registrar", "--huella", h, "--precio", "393.10", "--ahora", HOY + " 10:17"])
        self.assertEqual(code, 2)
        self.assertIn("--id-broker", err)
        code, out, err = run(broker, ["registrar", "--huella", h, "--id-broker", "x1", "--ahora", HOY + " 10:17"])
        self.assertEqual(code, 2)
        self.assertIn("--precio", err)
        code, out, err = run(broker, ["registrar", "--huella", "000000000000", "--id-broker", "x1", "--precio", "1", "--ahora", HOY + " 10:17"])
        self.assertEqual(code, 2)
        self.assertIn("no encuentro una orden con la huella", err)

    def test_registrar_denegada_no_toca_la_cartera(self):
        h = broker.huella(TSLA)
        code, out, err = run(broker, ["registrar", "--huella", h, "--estado", "denegada", "--ahora", HOY + " 10:17"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.leer("estado", "broker.json")["ordenes"][-1]["estado"], "denegada")
        self.assertFalse(os.path.exists(os.path.join(self.kemet, "portfolio.json")))


class TestPlano(Base):
    def setUp(self):
        super().setUp()
        run(broker, ["registrar", "--huella", broker.huella(TSLA), "--id-broker", "x1", "--precio", "393.10", "--ahora", HOY + " 10:17"])

    def test_plano_escribe_la_venta_de_cierre(self):
        code, out, err = run(broker, ["plano", "--simbolo", "TSLA", "--ahora", HOY + " 15:50"])
        self.assertEqual(code, 0, err)
        self.assertIn("Plano TSLA: VENTA 8 acciones de TSLA, a mercado, válida hoy / cierre: solo saca de la posición (plano a las 15:55 NY)", out)
        self.assertIn("riesgo.py check", out)
        self.assertIn("cancel_order_by_id", out)
        doc = self.leer("orden.json")
        o = doc["ordenes"][0]
        self.assertEqual((o["symbol"], o["side"], o["qty"], o["type"], o["time_in_force"], o["cierre"], o["instrumento"]), ("TSLA", "sell", "8", "market", "day", True, "accion"))
        self.assertTrue(doc["papel"])
        self.assertIn("plano a las 15:55 NY", o["por_que"])
        code, tickets = self.mostrar(HOY + " 15:50")           # vuelve a pasar por kemet-riesgo: sin check no está lista
        self.assertEqual(code, 1)
        self.assertIn("no está en la última comprobación", tickets[0]["estado"])
        self.assertEqual(tickets[0]["entrada_herramienta"], {"symbol": "TSLA", "side": "sell", "qty": "8", "type": "market", "time_in_force": "day",
                                                                  "client_order_id": tickets[0]["entrada_herramienta"]["client_order_id"]})
        self.assertTrue(tickets[0]["entrada_herramienta"]["client_order_id"].startswith("kemet-"))
        self.assertTrue(tickets[0]["cierre"])
        self.assertIsNone(tickets[0]["perdida_al_stop"])
        self.veredicto(o, hora_utc="20:50")                      # con el PASS del cierre (de las 15:50 NY), lista
        code, tickets = self.mostrar(HOY + " 15:51")
        self.assertEqual(code, 0)
        code, out, err = run(broker, ["registrar", "--huella", broker.huella(o), "--id-broker", "x2", "--precio", "391.00", "--ahora", HOY + " 15:52"])
        self.assertEqual(code, 0, err)
        pf = self.leer("portfolio.json")
        self.assertEqual(pf["efectivo"], 4983.2)                 # 1.855,20 + 8 × 391
        self.assertEqual(pf["posiciones"], [])

    def test_la_pata_que_se_llena_se_apunta_sin_huella(self):
        code, out, err = run(broker, ["registrar", "--simbolo", "TSLA", "--lado", "venta", "--cantidad", "8", "--precio", "389.51", "--id-broker", "pata-1", "--ahora", HOY + " 11:20"])
        self.assertEqual(code, 0, err)
        self.assertIn("Apuntado el fill de las 11:20 NY: VENTA 8 TSLA a 389,51, id pata-1", out)
        rec = self.leer("estado", "broker.json")["ordenes"][-1]
        self.assertEqual((rec["estado"], rec["clase"], rec["huella"], rec["id_broker"]), ("llenada", "cierre", None, "pata-1"))
        pf = self.leer("portfolio.json")
        self.assertEqual(pf["efectivo"], 4971.28)                # 1.855,20 + 8 × 389,51
        self.assertEqual(pf["posiciones"], [])
        code, out, err = run(broker, ["registrar", "--simbolo", "TSLA", "--lado", "venta", "--precio", "1", "--ahora", HOY + " 11:21"])
        self.assertEqual(code, 2)
        self.assertIn("sin --huella necesito", err)

    def test_plano_sin_posicion_es_un_error(self):
        code, out, err = run(broker, ["plano", "--simbolo", "AAPL", "--ahora", HOY + " 15:50"])
        self.assertEqual(code, 2)
        self.assertIn("nada que cerrar", err)
        code, out, err = run(broker, ["plano", "--simbolo", "AAPL", "--cantidad", "3", "--ahora", HOY + " 15:50"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.leer("orden.json")["ordenes"][0]["qty"], "3")

    def test_no_se_apunta_vender_lo_que_no_hay(self):
        venta = {"instrumento": "accion", "symbol": "TSLA", "side": "sell", "qty": "9", "type": "market", "time_in_force": "day"}
        self.ordenes([venta])
        code, out, err = run(broker, ["registrar", "--huella", broker.huella(venta), "--id-broker", "x3", "--precio", "391", "--ahora", HOY + " 15:52"])
        self.assertEqual(code, 2)
        self.assertIn("la cartera tiene 8", err)


class TestFuturo(Base):
    def setUp(self):
        super().setUp()
        comun.escribir_json(os.path.join(self.kemet, "config.json"), CONFIG_APEX)
        comun.escribir_json(os.path.join(self.kemet, "orden.json"), {"generado": "2026-11-11T15:40:00Z", "ordenes": [MNQ], "cuenta": CONFIG_APEX["cuenta_nombre"], "papel": True})
        code, out, err = run(riesgo, ["check", "--ahora", HOY + " 10:45"])       # el veredicto real de kemet-riesgo
        self.assertEqual(code, 0, err + out)

    def test_ticket_de_futuro_se_pone_a_mano(self):
        code, out, err = run(broker, ["mostrar", "--ahora", HOY + " 10:46"])
        self.assertEqual(code, 0, err)
        self.assertIn("cuenta PAPEL, futuros, a mano en tu plataforma", out)
        self.assertIn("COMPRA 1 MNQ, Nasdaq 100, orden stop a 28.429,75", out)
        self.assertIn("stop 28.312,50, objetivo 28.547", out)
        self.assertIn("pérdida al stop 234,50 $ (117,25 pts × 2 $/pt × 1)", out)
        self.assertIn("huella f2328b1ec6e1", out)
        self.assertIn("LISTA: PASS de kemet-riesgo hoy", out)
        self.assertIn("No hay conector gratuito de futuros: esta orden la pones tú en tu plataforma", out)
        self.assertNotIn("place_stock_order", out)
        code, tickets = self.mostrar(HOY + " 10:46")
        self.assertTrue(tickets[0]["a_mano"])
        self.assertIsNone(tickets[0]["herramienta"])
        code, tickets = self.mostrar("2026-11-12 10:46")      # el PASS de ayer no vale hoy
        self.assertEqual(code, 1)
        self.assertIn("no de hoy", tickets[0]["estado"])

    def test_registrar_y_plano_de_un_futuro(self):
        code, out, err = run(broker, ["aprobar", "--huella", "f2328b1ec6e1", "--respuesta", "sí, 1 MNQ", "--ahora", HOY + " 10:46"])
        self.assertEqual(code, 0, err)
        self.assertIn("Ponla tú en tu plataforma", out)
        code, out, err = run(broker, ["registrar", "--huella", "f2328b1ec6e1", "--precio", "28430.25", "--ahora", HOY + " 10:47"])   # sin id: a mano
        self.assertEqual(code, 0, err)
        self.assertIn("El efectivo no se toca en futuros", out)
        rec = self.leer("estado", "broker.json")["ordenes"][-1]
        self.assertEqual((rec["estado"], rec["id_broker"], rec["instrumento"], rec["cantidad"]), ("colocada", "a mano", "futuro", "1"))
        pf = self.leer("portfolio.json")
        self.assertIsNone(pf["efectivo"])                        # sin presupuesto en una cuenta de firma
        self.assertEqual(pf["posiciones"], [{"simbolo": "MNQ", "cantidad": 1.0, "precio_medio": 28430.25, "instrumento": "futuro"}])
        code, out, err = run(broker, ["plano", "--simbolo", "MNQ", "--precio", "28500", "--ahora", HOY + " 15:50"])
        self.assertEqual(code, 0, err)
        o = self.leer("orden.json")["ordenes"][0]
        self.assertEqual((o["simbolo"], o["lado"], o["contratos"], o["tipo"], o["precio"], o["cierre"], o["instrumento"]), ("MNQ", "venta", 1, "mercado", 28500.0, True, "futuro"))
        code, out, err = run(riesgo, ["check", "--ahora", HOY + " 15:58"])      # un cierre pasa aunque sea tarde
        self.assertEqual(code, 0, err + out)
        code, tickets = self.mostrar(HOY + " 15:58")
        self.assertEqual(code, 0)
        self.assertTrue(tickets[0]["lista"])
        code, out, err = run(broker, ["registrar", "--huella", broker.huella(o), "--precio", "28500", "--ahora", HOY + " 15:59"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.leer("portfolio.json")["posiciones"], [])


if __name__ == "__main__":
    unittest.main()
