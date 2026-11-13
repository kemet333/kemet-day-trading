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
diario = load("kemet-diario", "diario")
alertas = load("kemet-alertas", "alertas")
YAHOO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "yahoo")


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
        venta = dict(tr.CIERRE_TSLA, qty="5", cierre=True)              # vender lo que solo está en Alpaca: cierre, con su aviso
        v, res = self.veredicto(venta, "2026-11-11 15:52")
        self.assertEqual(v, "PASS", self.motivos(res))
        self.assertTrue(any("get_open_position" in a for a in res["resultados"][0]["avisos"]))
        comun.escribir_json(os.path.join(self.kemet, "config.json"), tr.CONFIG)
        futuro = dict(tr.CIERRE, contratos=1000, lado="compra")         # «cierre» de 1.000 MNQ: más que el tope de la cuenta
        v, res = self.veredicto(futuro, "2026-11-11 15:58")
        self.assertEqual(v, "BLOCK")
        self.assertIn("más que el tope", self.motivos(res))
        v, res = self.veredicto(dict(tr.CIERRE, contratos=1), "2026-11-11 15:58")   # cerrar 1 MNQ que el pack no conoce, sí
        self.assertEqual(v, "PASS", self.motivos(res))

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

    def test_registrar_un_resultado_despues_de_las_18(self):
        self.dia([{"hora": "10:46", "simbolo": "MNQ", "lado": "compra", "contratos": 1, "riesgo_usd": 234.5, "resultado_usd": None, "cerrada": None}])
        code, out, err = tr.run(["registrar", "--resultado", "120", "--hora", "15:50", "--ahora", "2026-11-11 18:30"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.leer("estado", "dia.json")["operaciones"][0]["resultado_usd"], 120.0)

    def test_tamano_y_riesgo_aplican_el_mismo_ambar(self):
        cfg, aviso = tamano.con_semaforo_de_hoy(dict(tr.CONFIG), {"fecha": "2026-11-11", "semaforo": "ambar"},
                                                comun.a_ny(comun.parse_ahora("2026-11-11 10:45")))
        self.assertEqual(cfg["perdida_max_dia"], 500.0)
        self.assertIn("ámbar", aviso)

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
        for r in ("sí", "Sí, 8 TSLA", "sí, TSLA", "Sí, confirmo", "sí, ponla ya", "si, perfecto", "SÍ, PONLA"):
            self.assertTrue(broker.es_un_si(r, tb.TSLA, ["TSLA"])[0], r)

    def test_client_order_id_cambia_con_el_dia_y_el_intento(self):
        a = broker.entrada_alpaca(tb.TSLA, "2026-11-11", 1)["client_order_id"]
        self.assertNotEqual(a, broker.entrada_alpaca(tb.TSLA, "2026-11-12", 1)["client_order_id"])
        self.assertNotEqual(a, broker.entrada_alpaca(tb.TSLA, "2026-11-11", 2)["client_order_id"])
        self.assertLessEqual(len(a), 48)                                   # Alpaca admite hasta 128

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
        self.assertEqual((comun.tick_de("6E", micro=False), comun.tick_de("6E")), (0.00005, 0.0001))   # 6E y M6E
        self.assertEqual(comun.al_tick(112.484375, comun.CONTRATOS["ZN"]["tick"]), 112.484375)
        self.assertEqual(comun.pts(1.11235), "1,11235")
        self.assertEqual(comun.pts(88.239998), "88,24")

    def test_cme_recortado_y_visperas(self):
        for ny, estado in (("2026-11-26 14:00", "pausa"), ("2026-11-27 13:30", "cerrado"), ("2026-12-24 19:00", "cerrado"),
                           ("2026-12-31 19:00", "cerrado"), ("2026-11-26 10:00", "abierto")):
            self.assertEqual(comun.estado_globex(comun.parse_ahora(ny))[0], estado, ny)


class Diario(unittest.TestCase):
    def leer(self, texto, **kw):
        d = tempfile.mkdtemp(prefix="kemet-diario-")
        try:
            p = os.path.join(d, "ops.csv")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(texto)
            return diario.leer_csv(p, **kw)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_una_accion_no_es_un_futuro(self):
        ops, _ = self.leer("fecha,hora,simbolo,lado,contratos,entrada,salida,stop\n2026-11-02,10:00,CLF,largo,100,12.50,12.60,12.40\n"
                           "2026-11-02,10:05,MNQZ6,largo,1,28000,28010,27990\n")
        self.assertEqual((ops[0]["mercado"], ops[0]["pnl"]), ("CLF", 10.0))   # antes CL a 1.000 $/pt: 10.000 $
        self.assertEqual(ops[1]["mercado"], "NQ")

    def test_miles_y_fechas_de_eeuu(self):
        ops, avisos = self.leer('fecha,hora,simbolo,lado,contratos,entrada,salida,stop,pnl\n11/02/2026,9:52 AM,NQ,largo,1,"26,812","26,880","26,772","1,360"\n'
                                '11/13/2026,10:05 AM,NQ,largo,1,"26,812.25","26,880","26,772","1,355"\n')
        self.assertEqual([o["fecha"].isoformat() for o in ops], ["2026-11-02", "2026-11-13"])
        self.assertEqual((ops[0]["entrada"], ops[0]["pnl"], ops[0]["hora"].strftime("%H:%M")), (26812.0, 1360.0, "09:52"))

    def test_simbolos_con_ano_de_cuatro_cifras(self):
        for s, codigo in (("MNQZ2026", "NQ"), ("NQH2027", "NQ"), ("MNQ1", "NQ"), ("ESZ6", "ES")):
            self.assertEqual(diario.contrato_de(s)[0], codigo, s)

    def test_formato_espanol_sigue_igual(self):
        ops, _ = self.leer("fecha;hora;simbolo;lado;contratos;entrada;salida;stop\n02/11/2026;10:00;MNQ;largo;2;28.426,25;28.440,50;28.400\n")
        self.assertEqual((ops[0]["fecha"].isoformat(), ops[0]["entrada"]), ("2026-11-02", 28426.25))

    def test_cantidad_rara_avisa(self):
        ops, avisos = self.leer("fecha,hora,simbolo,lado,contratos,entrada,salida,stop\n2026-11-02,10:00,MNQ,corto,-2,28000,27990,28010\n")
        self.assertEqual(ops[0]["contratos"], 2)
        self.assertTrue(any("cantidad -2" in a for a in avisos))


class Alertas(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="kemet-alertas-")
        self.viejo = comun.KEMET_DIR
        comun.KEMET_DIR = os.path.join(self.dir, "kemet")

    def tearDown(self):
        comun.KEMET_DIR = self.viejo
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = alertas.main(argv)
        return code, out.getvalue()

    def stop_puesto_a(self, hora):
        self.run_(["add", "--simbolo", "NQ", "--encima", "99999", "--ahora", "2026-11-12 07:30"])
        self.run_(["check", "--offline", YAHOO, "--ahora", "2026-11-12 08:05"])
        self.run_(["add", "--simbolo", "NQ", "--stop", "28040", "--lado", "largo", "--ahora", "2026-11-12 " + hora])
        return self.run_(["check", "--offline", YAHOO, "--ahora", "2026-11-12 09:25"])

    def test_una_mecha_anterior_a_la_regla_no_hace_saltar_el_stop(self):
        code, out = self.stop_puesto_a("09:00")
        self.assertNotIn("ALERTA", out)

    def test_una_mecha_posterior_si(self):
        code, out = self.stop_puesto_a("08:00")
        self.assertIn("mecha", out)


class Velas(unittest.TestCase):
    def test_una_vela_a_medio_formar_no_cuenta(self):
        base = comun.ts_de_utc(comun.parse_ahora("2026-11-11 10:30"))
        ch = {"paso": 300, "velas": [(base + 300 * i, 1, 2, 0, 1, 10) for i in range(4)]}   # 10:30, 10:35, 10:40, 10:45
        ahora = comun.parse_ahora("2026-11-11 10:56")
        self.assertEqual(len(comun.velas_cerradas(ch, ahora)), 4)                         # sin ts_mercado: solo el reloj
        ch["ts_mercado"] = base + 3 * 300 + 120                                           # Yahoo llega hasta las 10:47
        self.assertEqual([comun.a_ny(comun.utc_de_ts(b[0])).strftime("%H:%M") for b in comun.velas_cerradas(ch, ahora)],
                         ["10:30", "10:35", "10:40"])                                       # la de 10:45 aún se está formando


class Empaquetado(unittest.TestCase):
    def test_plugin_lista_las_dieciseis(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            plugin = json.load(fh)
        carpetas = sorted("./" + d for d in os.listdir(root) if os.path.isfile(os.path.join(root, d, "SKILL.md")))
        # con un SKILL.md en la raíz y "skills": "./", Claude Code solo veía una skill: la lista explícita carga las dieciséis
        self.assertEqual(sorted(plugin["skills"]), carpetas)
        self.assertEqual(len(carpetas), 16)


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
