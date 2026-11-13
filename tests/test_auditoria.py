"""Regresiones de la auditoría del 13/11/2026: cada caso es un PASS que tenía que ser BLOCK, un tamaño que no cabía o una cifra
mal leída que se reprodujo ejecutando el pack. Sin red."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_broker as tb  # noqa: E402
import test_riesgo as tr  # noqa: E402

from _load import load  # noqa: E402

riesgo, broker, comun = tr.riesgo, tb.broker, tr.comun
tamano = load("kemet-tamano", "tamano")


class Puerta(tr.Base):
    """kemet-riesgo con la cuenta propia (acciones) y la de Apex (futuros)."""

    def propia(self, **extra):
        comun.escribir_json(os.path.join(self.kemet, "config.json"), dict(tr.CONFIG_PROPIA, **extra))

    def veredicto(self, orden, ahora="2026-11-11 10:20"):
        self.ordenes([orden])
        code, res = self.check(ahora)
        return res["resultados"][0]["veredicto"], res

    def test_cierre_declarado_no_se_salta_las_reglas(self):
        self.propia()
        compra = dict(tr.ORDEN_TSLA, qty="500", cierre=True)
        compra.pop("stop_loss_stop_price", None)
        self.assertEqual(self.veredicto(compra)[0], "BLOCK")
        corto = dict(tr.CIERRE_TSLA, qty="500", cierre=True)
        v, res = self.veredicto(corto)
        self.assertEqual(v, "BLOCK")
        self.assertIn("corto:", self.motivos(res))
        comun.escribir_json(os.path.join(self.kemet, "config.json"), tr.CONFIG)
        futuro = dict(tr.CIERRE, contratos=100, lado="compra")          # «cierre» de 100 MNQ sin nada abierto a las 15:58
        v, res = self.veredicto(futuro, "2026-11-11 15:58")
        self.assertEqual(v, "BLOCK")
        self.assertTrue(any("marcada como cierre" in a for a in res["resultados"][0]["avisos"]))

    def test_un_cierre_de_verdad_sigue_pasando_tarde(self):
        self.dia([{"hora": "10:46", "simbolo": "MNQ", "lado": "compra", "contratos": 2, "riesgo_usd": 469.0, "resultado_usd": None, "cerrada": None}])
        v, res = self.veredicto(tr.CIERRE, "2026-11-11 15:58")
        self.assertEqual(v, "PASS", self.motivos(res))

    def test_notional_extended_hours_y_order_class(self):
        self.propia()
        for extra, trozo in (({"qty": "1", "notional": "50000"}, "notional no se admite"),
                             ({"extended_hours": True}, "extended_hours no se admite"),
                             ({"order_class": "simple"}, "order_class 'simple'")):
            v, res = self.veredicto(dict(tr.ORDEN_TSLA, **extra))
            self.assertEqual(v, "BLOCK", extra)
            self.assertIn(trozo, self.motivos(res))

    def test_el_stop_tiene_que_ir_en_el_broker(self):
        self.propia()
        o = {k: v for k, v in tr.ORDEN_TSLA.items() if k not in ("order_class", "take_profit_limit_price", "stop_loss_stop_price")}
        o["plan"] = dict(tr.ORDEN_TSLA.get("plan") or {}, stop=389.51, entrada=393.08)
        v, res = self.veredicto(o)
        self.assertEqual(v, "BLOCK")
        self.assertIn("está en el plan, no en la orden", self.motivos(res))

    def test_nan_cierra_la_puerta(self):
        self.propia()
        comun.escribir_json(os.path.join(self.kemet, "precios.json"), {"generado": "2026-11-11T15:19:00Z", "precios": {"TSLA": {"precio": float("nan")}}})
        o = dict(tr.ORDEN_TSLA, qty="9000")
        o["plan"] = {k: v for k, v in (tr.ORDEN_TSLA.get("plan") or {}).items() if k != "entrada"}
        self.assertEqual(self.veredicto(o)[0], "BLOCK")
        comun.escribir_json(os.path.join(self.kemet, "config.json"), tr.CONFIG)
        self.assertEqual(self.veredicto(dict(tr.ORDEN, stop="nan"), "2026-11-11 10:45")[0], "BLOCK")
        self.assertEqual(self.veredicto(dict(tr.ORDEN, precio="nan"), "2026-11-11 10:45")[0], "BLOCK")

    def test_stop_a_menos_de_un_tick(self):
        v, res = self.veredicto(dict(tr.ORDEN, contratos=100, stop=tr.ORDEN["precio"] - 0.1), "2026-11-11 10:45")
        self.assertEqual(v, "BLOCK")
        self.assertIn("a menos de un tick", self.motivos(res))

    def test_cinco_minutos_antes_de_estar_plano_y_cierre_de_cl(self):
        v, res = self.veredicto(tr.ORDEN, "2026-11-11 15:52")
        self.assertIn("los 5 minutos antes de estar plano", self.motivos(res))
        cl = {"simbolo": "MCL", "lado": "compra", "contratos": 1, "tipo": "stop", "precio": 60.10, "stop": 59.80, "objetivo": 60.40}
        v, res = self.veredicto(cl, "2026-11-11 14:22")                # CL está plano a las 14:25 aunque la config diga 15:55
        self.assertEqual(v, "BLOCK")
        self.assertIn("14:25", self.motivos(res))

    def test_semaforo_ambar_del_plan_baja_el_dia_a_la_mitad(self):
        comun.escribir_json(os.path.join(self.kemet, "plan-sesion.json"), {"fecha": "2026-11-11", "semaforo": "ambar"})
        self.dia([{"hora": "10:00", "simbolo": "MNQ", "lado": "compra", "contratos": 1, "riesgo_usd": 300.0, "resultado_usd": -300.0, "cerrada": "10:20"}])
        code, out, err = tr.run(["check", "--ahora", "2026-11-11 10:45", "--json", "--sin-escribir"])
        res = json.loads(out)
        self.assertEqual(res["resultados"][0]["veredicto"], "BLOCK")      # 300 + 234,50 > 500 (la mitad de 1.000)
        self.assertTrue(any("semáforo ámbar" in a for a in res["avisos"]))

    def test_el_dia_de_futuros_empieza_a_las_18(self):
        self.dia([{"hora": "20:10", "simbolo": "MNQ", "lado": "compra", "contratos": 3, "riesgo_usd": 700.0, "resultado_usd": -900.0, "cerrada": "20:40"}],
                 fecha="2026-11-12")                                      # jueves 20:10 NY: ya es la sesión del 12
        code, out, err = tr.run(["check", "--ahora", "2026-11-12 10:45", "--json", "--sin-escribir"])
        res = json.loads(out)
        self.assertEqual(res["resultados"][0]["veredicto"], "BLOCK")
        self.assertIn("día:", " ".join(res["resultados"][0]["motivos"]))


class Bróker(tb.Base):
    def test_pass_caducado_simulado_o_con_el_dia_cambiado(self):
        code, tickets = self.mostrar(tb.HOY + " 10:16")
        self.assertTrue(tickets[0]["lista"])
        code, tickets = self.mostrar(tb.HOY + " 14:00")                   # cuatro horas después ya no vale
        self.assertFalse(tickets[0]["lista"])
        self.assertIn("un PASS vale 10 minutos", tickets[0]["estado"])
        code, out, err = tb.run(broker, ["mostrar", "--json"])            # check con --ahora y ticket con el reloj real
        self.assertFalse(json.loads(out)[0]["lista"])
        rec = self.leer("estado", "riesgo.json")
        rec["dia_huella"] = comun.huella_dia(None)
        comun.escribir_json(os.path.join(self.kemet, "estado", "riesgo.json"), rec)
        comun.escribir_json(os.path.join(self.kemet, "estado", "dia.json"), {"fecha": tb.HOY, "operaciones": [{"simbolo": "TSLA", "resultado_usd": -140}]})
        code, tickets = self.mostrar(tb.HOY + " 10:16")
        self.assertIn("dia.json cambió", tickets[0]["estado"])

    def test_el_si_no_admite_lo_que_no_es_un_si(self):
        for r in ("sí, de ninguna manera", "sí, nunca", "sí, ponla en real", "sí, sin stop", "sí, vende", "sí, en corto",
                  "sí, compra AAPL", "sí, 8 de TSLA a 500"):
            vale, por_que = broker.es_un_si(r, tb.TSLA, ["TSLA"])
            self.assertFalse(vale, r)
        for r in ("sí", "Sí, 8 TSLA", "sí, TSLA"):
            self.assertTrue(broker.es_un_si(r, tb.TSLA, ["TSLA"])[0], r)

    def test_el_si_por_la_entrada_estandar(self):
        viejo = sys.stdin
        sys.stdin = io.StringIO('sí $(echo INYECTADO)\n')
        try:
            code, out, err = tb.run(broker, ["aprobar", "--huella", broker.huella(tb.TSLA), "--respuesta", "-", "--ahora", tb.HOY + " 10:16"])
        finally:
            sys.stdin = viejo
        self.assertEqual(code, 1)                                         # «$(echo…)» no es un sí para esta orden, y no se ejecutó nada
        sys.stdin = io.StringIO("sí\n")
        try:
            code, out, err = tb.run(broker, ["aprobar", "--huella", broker.huella(tb.TSLA), "--respuesta", "-", "--ahora", tb.HOY + " 10:16"])
        finally:
            sys.stdin = viejo
        self.assertEqual(code, 0, err)
        self.assertEqual(self.leer("estado", "broker.json")["ordenes"][-1]["respuesta"], "sí")


class Tamano(unittest.TestCase):
    def cuenta(self, firma, cuenta):
        f, acc = tamano.buscar(tamano.cargar_reglas(), firma, cuenta)
        return acc

    def test_apex_con_los_topes_oficiales(self):
        topes = {c: (self.cuenta("apex", c)["max_mini"], self.cuenta("apex", c)["max_micro"]) for c in
                 ("eod-eval-25", "eod-eval-50", "eod-eval-100", "eod-eval-150", "eod-pa-25", "eod-pa-50", "eod-pa-100", "eod-pa-150")}
        self.assertEqual(topes, {"eod-eval-25": (4, 40), "eod-eval-50": (6, 60), "eod-eval-100": (8, 80), "eod-eval-150": (12, 120),
                                 "eod-pa-25": (1, 10), "eod-pa-50": (2, 20), "eod-pa-100": (3, 30), "eod-pa-150": (4, 40)})
        acc = self.cuenta("apex", "eod-pa-50")
        r = tamano.calcular(acc["max_loss"], acc["daily_loss_limit"], acc["max_micro"], "ES", 1.5, cap_mini=acc["max_mini"])
        self.assertEqual(r["contratos"], 20)                               # antes 22 MES con un tope de 100

    def test_zn_cuenta_con_el_tope_de_minis(self):
        acc = self.cuenta("apex", "eod-pa-50")
        r = tamano.calcular(acc["max_loss"], acc["daily_loss_limit"], acc["max_micro"], "ZN", 0.015625, cap_mini=acc["max_mini"])
        self.assertEqual(r["contratos"], 2)
        self.assertNotIn("ZN", comun.MICRO_A_CODIGO)

    def test_el_semaforo_baja_la_perdida_del_usuario(self):
        verde = tamano.calcular(2000, 1000, 20, "NQ", 18, "verde", 200)
        ambar = tamano.calcular(2000, 1000, 20, "NQ", 18, "ambar", 200)
        self.assertEqual((verde["perdida_max_dia"], ambar["perdida_max_dia"]), (200, 100))
        self.assertLessEqual(ambar["contratos"], verde["contratos"])

    def test_stop_de_menos_de_un_tick(self):
        with self.assertRaises(comun.KemetError):
            tamano.calcular(2000, 1000, 20, "NQ", 0.01)

    def test_contratos_y_tick(self):
        self.assertEqual(comun.CONTRATOS["NG"]["punto_micro"], 1000.0)    # MNG: 1.000 MMBtu
        self.assertEqual(comun.CONTRATOS["6E"]["tick"], 0.0001)            # el tick de M6E, válido también en 6E
        self.assertEqual(comun.al_tick(112.484375, comun.CONTRATOS["ZN"]["tick"]), 112.484375)
        self.assertEqual(comun.pts(1.11235), "1,11235")
        self.assertEqual(comun.pts(88.239998), "88,24")

    def test_cme_recortado_y_visperas(self):
        for ny, estado in (("2026-11-26 14:00", "pausa"), ("2026-11-27 13:30", "cerrado"), ("2026-12-24 19:00", "cerrado"),
                           ("2026-12-31 19:00", "cerrado"), ("2026-11-26 10:00", "abierto")):
            self.assertEqual(comun.estado_globex(comun.parse_ahora(ny))[0], estado, ny)


class Rutas(unittest.TestCase):
    def test_un_config_del_directorio_de_trabajo_no_tapa_el_de_kemet(self):
        d = tempfile.mkdtemp(prefix="kemet-rutas-")
        viejo_dir, viejo_cwd = comun.KEMET_DIR, os.getcwd()
        try:
            comun.KEMET_DIR = os.path.join(d, "kemet")
            comun.escribir_json(os.path.join(d, "kemet", "config.json"), {"mercado": "ES"})
            with open(os.path.join(d, "config.json"), "w") as fh:
                json.dump({"name": "my-app", "mercado": "GC"}, fh)
            os.chdir(d)
            self.assertEqual(comun.leer_json("config.json")["mercado"], "ES")
            self.assertEqual(comun.leer_json(comun.dada("config.json"))["mercado"], "GC")   # una ruta dada por el usuario, sí
        finally:
            os.chdir(viejo_cwd)
            comun.KEMET_DIR = viejo_dir
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
