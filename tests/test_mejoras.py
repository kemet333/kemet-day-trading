"""Mejoras del 13/11/2026 tras la auditoría: lo que queda de drawdown (tamano.py cuenta) baja el tamaño, la puerta y el plan."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_broker as tb  # noqa: E402
import test_riesgo as tr  # noqa: E402
from _load import load  # noqa: E402

tamano = load("kemet-tamano", "tamano")
diario = load("kemet-diario", "diario")
plan = load("kemet-plan", "plan")
broker = tb.broker
comun = sys.modules["comun"]


class DrawdownRestante(unittest.TestCase):
    def test_un_cuarto_de_lo_que_queda_baja_la_perdida_del_dia(self):
        entero = tamano.calcular(2000, 1000, 20, "NQ", 18)
        poco = tamano.calcular(2000, 1000, 20, "NQ", 18, queda=800)
        self.assertEqual((entero["perdida_max_dia"], poco["perdida_max_dia"]), (500, 200))
        self.assertEqual(poco["contratos"], 1)                              # 66,67 $ por operación / 36 $ por micro
        self.assertEqual(tamano.calcular(2000, 1000, 20, "NQ", 18, queda=5000)["perdida_max_dia"], 500)   # nunca sube
        self.assertEqual(tamano.calcular(2000, 1000, 20, "NQ", 18, queda=0)["contratos"], 0)
        self.assertEqual(tamano.calcular(2000, 1000, 20, "NQ", 18, "ambar", queda=800)["perdida_max_dia"], 100)

    def test_la_perdida_del_usuario_nunca_pasa_de_lo_que_queda(self):
        r = tamano.calcular(2000, 1000, 20, "NQ", 18, "verde", 600, queda=400)
        self.assertEqual(r["perdida_max_dia"], 400)
        self.assertEqual(tamano.calcular(2000, 1000, 20, "NQ", 18, "verde", 300, queda=400)["perdida_max_dia"], 300)

    def test_config_con_drawdown_restante(self):
        cfg = dict(tr.CONFIG)
        nuevo, avisos = comun.con_drawdown_restante(cfg, {"fecha": "2026-11-11", "drawdown_restante": 1200}, "2026-11-11")
        self.assertEqual(nuevo["perdida_max_dia"], 300)
        self.assertTrue(any("baja de" in a for a in avisos))
        viejo, avisos = comun.con_drawdown_restante(cfg, {"fecha": "2026-11-09", "drawdown_restante": 1200}, "2026-11-11")
        self.assertEqual(viejo["perdida_max_dia"], 300)                    # uno viejo se sigue usando: solo puede bajar
        self.assertTrue(any("no hoy" in a for a in avisos))
        cero, _ = comun.con_drawdown_restante(cfg, {"fecha": "2026-11-11", "drawdown_restante": -50}, "2026-11-11")
        self.assertEqual(cero["perdida_max_dia"], 0)
        propia, avisos = comun.con_drawdown_restante(dict(tr.CONFIG_PROPIA), {"fecha": "2026-11-11", "drawdown_restante": 10}, "2026-11-11")
        self.assertEqual(propia["perdida_max_dia"], tr.CONFIG_PROPIA["perdida_max_dia"])
        nan, avisos = comun.con_drawdown_restante(cfg, {"fecha": "2026-11-11", "drawdown_restante": "nan"}, "2026-11-11")
        self.assertEqual(nan["perdida_max_dia"], 1000)
        self.assertTrue(avisos)

    def test_el_plan_de_sesion_lo_cuenta(self):
        t = plan.tamano("NQ", "verde", 18, 2000.0, 1000.0, 20, queda=800)
        self.assertEqual(t["perdida_max_dia"], 200)
        self.assertEqual(plan.tamano("NQ", "verde", 18, 2000.0, 1000.0, 20)["perdida_max_dia"], 500)


class FirmasNuevas(unittest.TestCase):
    """Las cuentas leídas el 13/11/2026 en las webs oficiales: Tradeify Select Flex/Daily y 300K, Alpha Direct y LucidDaily."""

    def cuenta(self, firma, cuenta):
        f, acc = tamano.buscar(tamano.cargar_reglas(), firma, cuenta)
        self.assertIsNotNone(acc, "%s / %s" % (firma, cuenta))
        return f, acc

    def test_tradeify_select_fondeada(self):
        _, flex = self.cuenta("tradeify", "select-flex-100")
        _, daily = self.cuenta("tradeify", "select-daily-100")
        self.assertEqual((flex["max_loss"], flex.get("daily_loss_limit"), flex["max_mini"]), (3000, None, 3))   # empieza con 3 minis
        self.assertEqual((daily["max_loss"], daily["daily_loss_limit"], daily["max_mini"]), (2500, 1250, 3))
        _, ev = self.cuenta("tradeify", "select-eval-300")
        self.assertEqual((ev["max_loss"], ev["daily_loss_limit"], ev["max_micro"]), (8000, 4000, 160))
        cfg, notas = tamano.construir_config(*self.cuenta("tradeify", "select-daily-50"), "NQ")
        self.assertEqual(cfg["perdida_max_dia"], 500)                       # un cuarto de 2.000, por debajo del límite diario de 1.000
        self.assertTrue(any("escalado" in n for n in notas))

    def test_alpha_direct_y_lucid_daily(self):
        _, d = self.cuenta("alpha", "direct-150")
        self.assertEqual((d["max_loss"], d["daily_loss_limit"], d["max_mini"], d["consistency"]), (4500, 3000, 10, "mejor día ≤ 20% para cobrar"))
        _, l = self.cuenta("lucid", "daily-funded-50")
        self.assertEqual((l["max_loss"], l["daily_loss_limit"], l["max_micro"], l["max_loss_type"]), (2000, 1200, 40, "intraday_trailing"))
        self.assertIn("noticias rojas", l["news"])

    def test_cada_cuenta_tiene_lo_que_usa_el_tamano(self):
        for f in tamano.cargar_reglas()["firms"]:
            for a in f["accounts"]:
                self.assertGreater(a["max_loss"], 0, a["id"])
                self.assertIn(a["phase"], ("evaluation", "funded"), a["id"])
                self.assertTrue(a.get("flat_by", {}).get("time"), a["id"])
                if a.get("daily_loss_limit"):
                    self.assertLess(a["daily_loss_limit"], a["max_loss"] + 1, a["id"])


class PuertaConDrawdown(tr.Base):
    def test_la_puerta_bloquea_lo_que_ya_no_cabe(self):
        code, res = self.check("2026-11-11 10:45")
        self.assertEqual(res["resultados"][0]["veredicto"], "PASS")
        comun.escribir_json(os.path.join(self.kemet, "estado", "cuenta.json"), {"fecha": "2026-11-11", "drawdown_restante": 600})
        code, res = self.check("2026-11-11 10:45")                       # un cuarto: 150 $ al día, 50 $ por operación
        self.assertEqual(res["resultados"][0]["veredicto"], "BLOCK", self.motivos(res))
        self.assertTrue(any("te quedan 600 $ de drawdown" in a for a in res["avisos"]))

    def test_sin_drawdown_no_pasa_nada(self):
        # revisión del 13/11: con 0 (o 1 $, cuyo cuarto se redondea a 0) la pérdida del día era 0 y la puerta lo leía como «sin límite»
        for queda in (0, 1, -50):
            comun.escribir_json(os.path.join(self.kemet, "estado", "cuenta.json"), {"fecha": "2026-11-11", "drawdown_restante": queda})
            code, res = self.check("2026-11-11 10:45")
            self.assertEqual(res["resultados"][0]["veredicto"], "BLOCK", queda)
            self.assertIn("límite de pérdida", self.motivos(res))
        code, out, err = tr.run(["hoy", "--ahora", "2026-11-11 10:45"])
        self.assertEqual(code, 1)
        self.assertIn("Toca parar", out)

    def test_registrar_cuenta_lo_que_queda(self):
        comun.escribir_json(os.path.join(self.kemet, "estado", "cuenta.json"), {"fecha": "2026-11-11", "drawdown_restante": 600})
        self.dia([{"hora": "10:45", "simbolo": "MNQ", "lado": "compra", "contratos": 1, "entrada": 28429.75, "stop": 28312.5, "riesgo_usd": 234.5}])
        code, out, err = tr.run(["registrar", "--resultado", "-200", "--ahora", "2026-11-11 11:30"])
        self.assertEqual(code, 0, err)
        self.assertIn("Toca parar", out)                                    # 150 $ al día con 600 de drawdown: 200 perdidos lo agotan

    def test_un_pass_no_vale_si_cambia_lo_que_queda(self):
        code, res = self.check("2026-11-11 10:45", escribir=True)
        rec = self.leer("estado", "riesgo.json")
        self.assertIn("cuenta_huella", rec)
        self.assertIsNone(broker.validez_del_pass(dict(rec, simulado=False), comun.de_iso(rec["comprobado"]), False, None, None))
        otra = {"fecha": "2026-11-11", "drawdown_restante": 900}
        self.assertIn("cuenta.json", broker.validez_del_pass(dict(rec, simulado=False), comun.de_iso(rec["comprobado"]), False, None, otra))


class Orden(unittest.TestCase):
    def test_cuenta_apunta_y_borra(self):
        import shutil
        import tempfile
        d = tempfile.mkdtemp()
        viejo = comun.KEMET_DIR
        comun.KEMET_DIR = os.path.join(d, "kemet")
        try:
            comun.escribir_json("config.json", dict(tr.CONFIG))
            self.assertEqual(tamano.main(["cuenta", "--saldo", "151000", "--suelo", "149800", "--ahora", "2026-11-11 09:00", "--json"]), 0)
            doc = comun.leer_json(comun.ruta(comun.CUENTA))
            self.assertEqual((doc["drawdown_restante"], doc["fecha"]), (1200, "2026-11-11"))
            self.assertEqual(tamano.main(["cuenta", "--queda", "1", "--saldo", "2"]), 2)
            comun.escribir_json(comun.ruta(comun.CUENTA), {"fecha": "2026-11-11", "drawdown_restante": 0})
            comun.escribir_json("plan.json", {"fecha": "2026-11-11", "lado": "largo", "mercado": "NQ", "entrada": 28429.75, "stop": 28312.5,
                                              "objetivo": 28547.0, "plano_a": "15:55"})
            code, out, err = correr(tamano, ["orden", "--ahora", "2026-11-11 10:45", "--json"])
            self.assertEqual(code, 1, err)
            self.assertIn("hoy no se opera", json.loads(out)["tamano"]["rechazo"])
            with self.assertRaises(comun.KemetError):
                tamano.calcular(2000, 1000, 20, "NQ", 18, queda=float("inf"))
            self.assertEqual(tamano.main(["cuenta", "--borrar"]), 0)
            self.assertIsNone(comun.leer_json(comun.ruta(comun.CUENTA), obligatorio=False))
        finally:
            comun.KEMET_DIR = viejo
            shutil.rmtree(d, ignore_errors=True)


def correr(mod, argv):
    import contextlib
    import io
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mod.main(argv)
    return code, out.getvalue(), err.getvalue()


class DiarioPorSesion(unittest.TestCase):
    CSV = ("fecha,hora,simbolo,lado,contratos,entrada,salida,stop,pnl\n"
           "2026-11-08,18:30,MNQ,largo,1,25000,25010,24990,20\n"       # domingo por la tarde: sesión del lunes 9
           "2026-11-09,10:00,MNQ,corto,1,25100,25120,25110,-40\n"
           "2026-11-09,19:00,MNQ,largo,1,25050,25040,25030,-20\n")      # lunes por la tarde: sesión del martes 10

    def setUp(self):
        import tempfile
        self.d = tempfile.mkdtemp()
        self.viejo = comun.KEMET_DIR
        comun.KEMET_DIR = os.path.join(self.d, "kemet")
        self.csv = os.path.join(self.d, "ops.csv")
        with open(self.csv, "w", encoding="utf-8") as fh:
            fh.write(self.CSV)

    def tearDown(self):
        import shutil
        comun.KEMET_DIR = self.viejo
        shutil.rmtree(self.d, ignore_errors=True)

    def test_desde_y_hasta_por_sesion(self):
        code, out, err = correr(diario, ["revisar", self.csv, "--desde", "2026-11-09", "--hasta", "2026-11-09", "--json"])
        doc = json.loads(out)
        self.assertEqual(doc["operaciones"], 2, err)                        # la del domingo 18:30 entra; la del lunes 19:00, no
        self.assertEqual((doc["desde"], doc["hasta"]), ("2026-11-09", "2026-11-09"))
        self.assertEqual([d["dia"] for d in doc["por_dia_semana"]], ["lunes"])

    def escribe(self, texto):
        with open(self.csv, "w", encoding="utf-8") as fh:
            fh.write(texto)

    def test_informe_de_operaciones_de_ninjatrader_en_hora_de_chicago(self):
        self.escribe("Trade number,Instrument,Account,Strategy,Market pos.,Qty,Entry price,Exit price,Entry time,Exit time,Profit\n"
                     "1,MNQ 12-26,Sim101,,Long,2,25000.25,25010.25,11/9/2026 9:00:13 AM,11/9/2026 9:20:00 AM,$40.00\n"
                     "2,MNQ 12-26,Sim101,,Short,1,25100.00,25120.00,11/10/2026 5:30:00 PM,11/10/2026 5:40:00 PM,($40.00)\n")
        code, out, err = correr(diario, ["revisar", self.csv, "--zona", "America/Chicago", "--json"])
        doc = json.loads(out)
        self.assertEqual(doc["operaciones"], 2, err)
        self.assertEqual([d["fecha"] for d in doc["dias"]], ["2026-11-09", "2026-11-11"])    # 17:30 Chicago = 18:30 NY: sesión siguiente
        code, out, err = correr(diario, ["revisar", self.csv, "--json"])
        self.assertTrue(any("--zona" in a for a in json.loads(out)["avisos"]))

    def test_hora_con_desfase_y_lado_en_type(self):
        self.escribe("ContractName,EnteredAt,ExitedAt,EntryPrice,ExitPrice,PnL,Size,Type\n"
                     "MNQZ6,2026-11-09T23:30:00Z,2026-11-09T23:40:00Z,25000,25010,20,1,Long\n")
        code, out, err = correr(diario, ["revisar", self.csv, "--json"])
        doc = json.loads(out)
        self.assertEqual((doc["operaciones"], doc["desde"]), (1, "2026-11-10"), err)       # 23:30 UTC = 18:30 NY
        self.assertFalse(any("--zona" in a for a in doc["avisos"]))

    def test_fechas_de_eeuu_despues_del_12_en_la_columna_de_la_hora(self):
        self.escribe("Instrument,Market pos.,Qty,Entry price,Exit price,Entry time,Profit\n"
                     "MNQ 12-26,Long,1,25000,25010,11/13/2026 10:00:13 AM,$20.00\n")
        code, out, err = correr(diario, ["revisar", self.csv, "--json"])
        self.assertEqual(json.loads(out)["desde"], "2026-11-13", err)

    def test_fecha_con_barra_y_desfase(self):
        self.escribe("ContractName,EnteredAt,EntryPrice,ExitPrice,PnL,Size,Type,TradeDay\n"
                     "MNQZ6,11/12/2026 23:30:00 +00:00,25000,25010,20,1,Long,11/13/2026\n")
        code, out, err = correr(diario, ["revisar", self.csv, "--json"])
        self.assertEqual(json.loads(out)["desde"], "2026-11-13", err)      # 23:30 UTC = 18:30 NY: sesión del 13

    def test_ejecuciones_sueltas_se_rechazan_con_motivo(self):
        self.escribe("Timestamp,Symbol,B/S,Qty,Price\n2026-11-09 10:00,MNQZ6,Buy,1,25000\n")
        code, out, err = correr(diario, ["revisar", self.csv])
        self.assertEqual(code, 2)
        self.assertIn("ejecuciones", err)

    def test_dia_de_la_semana_de_la_sesion(self):
        code, out, err = correr(diario, ["revisar", self.csv, "--json"])
        doc = json.loads(out)
        self.assertEqual({d["dia"]: d["operaciones"] for d in doc["por_dia_semana"]}, {"lunes": 2, "martes": 1})


if __name__ == "__main__":
    unittest.main()
