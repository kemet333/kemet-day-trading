"""kemet-scanner sin red: el universo sobre los directorios recortados de Nasdaq Trader, las reglas diarias sobre un spark
real, la ruptura del rango de apertura sobre la pared de 234 gráficos del 19/10/2026 y el modo futuros sobre el fixture
real de NQ del 11/11/2026.

Los fixtures de `tests/fixtures/kemet-scanner/` (symdir/*.txt, daily-spark-2026-10-19.json, wall5m-2026-10-19.json.gz y
spark-5m-live-2026-10-20-1001.json) vienen tal cual del pack day-trader-skill de Jake Schincariol (MIT): datos reales de
Yahoo Finance y de Nasdaq Trader de octubre de 2026. Los de `tests/fixtures/yahoo/` son los del pack (NQ y ES de 60 días,
CL y GC de 5 días)."""
import datetime as dt
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX, YAHOO

scanner = load("kemet-scanner", "scanner")
comun = scanner.comun

SDIR = os.path.join(FIX, "kemet-scanner")
SYMDIR = os.path.join(SDIR, "symdir")
DAILY = os.path.join(SDIR, "daily-spark-2026-10-19.json")
WALL = os.path.join(SDIR, "wall5m-2026-10-19.json.gz")
SPARK5 = os.path.join(SDIR, "spark-5m-live-2026-10-20-1001.json")


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = scanner.main(argv)
    return code, out.getvalue(), err.getvalue()


class ConKemetTemporal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kemet = os.path.join(self.tmp, "kemet")
        self._old = comun.KEMET_DIR
        comun.KEMET_DIR = self.kemet

    def tearDown(self):
        comun.KEMET_DIR = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)


class Universo(unittest.TestCase):
    def setUp(self):
        self.textos = {}
        self.filas = {}
        for f in scanner.NASDAQ_ARCHIVOS:
            with open(os.path.join(SYMDIR, f), encoding="utf-8") as fh:
                self.textos[f] = fh.read()
            for r in scanner.parse_symdir(self.textos[f])[0]:
                self.filas[r.get("Symbol") or r.get("ACT Symbol")] = r
        self.dentro, self.recuento, self.creado = scanner.construir_universo(self.textos)

    def test_el_filtro_sobre_los_directorios_reales(self):
        self.assertEqual(self.recuento["filas"], 36)
        self.assertEqual(len(self.dentro), 17)
        self.assertEqual(self.creado, "2026-10-19 10:01")
        self.assertEqual(dict(self.dentro)["TSLA"], "Tesla, Inc. - Common Stock")
        self.assertIn("BRK.B", dict(self.dentro))
        self.assertNotIn("SPY", dict(self.dentro))

    def test_un_caso_por_regla(self):
        casos = {"AAAP": "ETF", "ZAZZT": "valor de prueba", "ABR$D": "ticker no llano", "AAC.U": "sufijo de unidad / warrant / derecho",
                 "AACIW": "warrant", "HAVAR": "unidad o derecho", "ATMP": "nota", "EAI": "cupón", "CDZIP": "depositary",
                 "AACIU": "unidad", "AACPR": "derecho", "BHK": "bono", "CHTRP": "preferente",
                 "AMX": "dentro", "AME": "dentro", "PRT": "dentro", "ARLP": "dentro"}
        for sym, quiero in casos.items():
            self.assertEqual(scanner.clasificar(self.filas[sym]), quiero, sym)

    def test_un_archivo_que_no_es_un_directorio(self):
        with self.assertRaises(comun.KemetError):
            scanner.parse_symdir("hola\nmundo\n")


class Diario(unittest.TestCase):
    ESPERADO = {
        "BLK": ["ruptura-20d"], "CI": ["ruptura-20d"], "XOM": ["ruptura-20d"], "HD": ["ruptura-20d"], "KO": ["ruptura-20d"],
        "CCL": ["bandera"], "RCL": ["bandera"],
        "F": ["recupera-media-20"], "JPM": ["recupera-media-20"], "GE": ["recupera-media-20"],
        "BAC": ["sobreventa"], "PLUG": ["sobreventa"], "MS": ["sobreventa"], "RIVN": ["sobreventa"],
        "PNC": ["rebote"],
    }

    def setUp(self):
        self.datos, self.errores = scanner.cargar_offline(DAILY)
        self.syms = sorted(self.datos)

    def test_las_reglas_antes_de_la_apertura(self):
        self.assertEqual(len(self.syms), 19)
        aciertos, recuento, ultima = scanner.escanear_diario(self.datos, self.syms, comun.parse_ahora("2026-10-19 09:00"), 0, 0)
        self.assertEqual({h["simbolo"]: h["reglas"] for h in aciertos}, self.ESPERADO)
        self.assertEqual(ultima, dt.date(2026, 10, 16))
        self.assertEqual(recuento, {"pedidos": 19, "recibidos": 19, "sin_liquidez": 0, "cortos": 0, "escaneados": 19, "aciertos": 15})
        blk = [h for h in aciertos if h["simbolo"] == "BLK"][0]
        self.assertEqual((blk["precio"], blk["rsi"], blk["hora"], blk["regla"]), (1134.38, 63.7, "cierre 2026-10-16", "ruptura-20d"))
        self.assertIn("máximo de cierre de 20 días", blk["detalle"])
        self.assertEqual(aciertos[0]["simbolo"], "BAC")                      # el más negociado primero

    def test_la_vela_de_hoy_no_cuenta_hasta_el_cierre(self):
        velas = scanner.cierres_diarios(self.datos["TSLA"], comun.parse_ahora("2026-10-19 15:59"))
        self.assertEqual(velas[-1][0], dt.date(2026, 10, 16))
        velas = scanner.cierres_diarios(self.datos["TSLA"], comun.parse_ahora("2026-10-19 16:00"))
        self.assertEqual(velas[-1][0], dt.date(2026, 10, 19))

    def test_el_filtro_de_liquidez(self):
        aciertos, recuento, _ = scanner.escanear_diario(self.datos, self.syms, comun.parse_ahora("2026-10-19 10:50"), 5, 1000000)
        self.assertEqual(sorted(h["simbolo"] for h in aciertos), ["BAC", "CCL", "F", "JPM", "KO", "RIVN", "XOM"])
        self.assertEqual((recuento["sin_liquidez"], recuento["escaneados"]), (8, 11))

    def test_rsi_de_wilder(self):
        self.assertEqual(scanner.rsi([float(x) for x in range(1, 40)]), 100.0)
        cierres = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
        self.assertAlmostEqual(scanner.rsi(cierres), 70.46, places=1)

    def test_salida_llana_y_codigo(self):
        code, out, _ = run(["diario", "--offline", DAILY, "--ahora", "2026-10-19 09:00", "--min-precio", "0", "--min-volumen", "0", "--sin-escribir"])
        self.assertEqual(code, 0)
        self.assertIn("15 gráficos cumplen una regla: 5 ruptura del máximo de cierre de 20 días, 2 bandera alcista", out)
        self.assertIn("BLK      1.134,38 $  RSI  63,7  ruptura del máximo de cierre de 20 días", out)
        self.assertIn("15:00 Madrid / 09:00 NY", out)
        code, out, _ = run(["diario", "--offline", DAILY, "--ahora", "2026-10-19 09:00", "--simbolos", "TSLA", "--sin-escribir"])
        self.assertEqual(code, 1)
        self.assertIn("Ningún gráfico cumple una regla.", out)


class Orb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.datos, cls.errores = scanner.cargar_offline(WALL)
        cls.syms = sorted(set(cls.datos) | set(cls.errores))

    def a_las(self, ahora, min_precio=0, syms=None):
        dia, corte = scanner.ventana_orb(comun.parse_ahora(ahora), None, 15, dt.time(15, 0))
        return scanner.escanear_orb(self.datos, syms or self.syms, dia, corte, 15, min_precio, 0)

    def test_la_pared_del_19_de_octubre_a_las_10_15(self):
        aciertos, recuento, fallidos = self.a_las("2026-10-19 10:15")
        self.assertEqual(len(self.syms), 234)
        self.assertEqual(recuento["escaneados"], 231)
        self.assertEqual(recuento["inutilizables"], 2)
        self.assertEqual(len(aciertos), 42)
        self.assertEqual(list(self.errores), ["SQ"])
        tsla = [h for h in aciertos if h["simbolo"] == "TSLA"][0]
        self.assertEqual((tsla["precio"], tsla["hora"], tsla["vela"], tsla["barra"]), (364.18, "10:15", "10:10", 9))
        self.assertEqual((tsla["rango_alto"], tsla["rango_bajo"], tsla["pct_encima"]), (362.18, 354.47, 0.55))
        self.assertEqual(tsla["regla"], "orb")
        self.assertIn("cerró en 364,18", tsla["detalle"])
        self.assertEqual(aciertos[0]["simbolo"], "AMC")                       # por hora y después por símbolo
        self.assertEqual([h["hora"] for h in aciertos], sorted(h["hora"] for h in aciertos))
        self.assertEqual(sum(1 for h in aciertos if h["hora"] == "10:15"), 11)

    def test_el_suelo_de_precio(self):
        aciertos, recuento, _ = self.a_las("2026-10-19 10:15", min_precio=5)
        self.assertEqual(len(aciertos), 41)                                   # AMC a 2,97 $ se cae
        self.assertEqual(recuento["sin_liquidez"], 9)

    def test_una_vela_sin_cerrar_no_cuenta(self):
        aciertos, _, _ = self.a_las("2026-10-19 10:14", syms=["TSLA"])
        self.assertEqual(aciertos, [])                                        # la vela de 10:10 no cierra hasta las 10:15
        aciertos, _, _ = self.a_las("2026-10-19 10:15", syms=["TSLA"])
        self.assertEqual(aciertos[0]["hora"], "10:15")

    def test_la_fase_1_es_condicion_necesaria(self):
        dia, corte = scanner.ventana_orb(comun.parse_ahora("2026-10-19 10:15"), None, 15, dt.time(15, 0))
        pedidos = []

        def confirmar(sym):
            pedidos.append(sym)
            return self.datos[sym]
        aciertos, recuento, _ = scanner.escanear_orb(self.datos, self.syms, dia, corte, 15, 0, 0, confirmar, 0)
        self.assertEqual(len(aciertos), 42)
        self.assertEqual(recuento["candidatos"], len(pedidos))
        self.assertEqual(recuento["candidatos"], 95)

    def test_el_tope_de_la_fase_2_coge_los_mas_negociados(self):
        dia, corte = scanner.ventana_orb(comun.parse_ahora("2026-10-19 10:15"), None, 15, dt.time(15, 0))
        pedidos = []

        def confirmar(sym):
            pedidos.append(sym)
            return self.datos[sym]
        aciertos, recuento, _ = scanner.escanear_orb(self.datos, self.syms, dia, corte, 15, 0, 0, confirmar, 10)
        self.assertEqual((recuento["confirmados"], recuento["sin_confirmar"]), (10, 85))
        self.assertIn("TSLA", pedidos)
        code, out, _ = run(["orb", "--offline", WALL, "--ahora", "2026-10-19 10:15", "--min-precio", "0", "--sin-escribir"])
        self.assertEqual(code, 0)
        self.assertNotIn("PARCIAL", out)                                      # offline no hay fase 2 que recortar

    def test_mensajes_de_ventana(self):
        def msg(ahora, a=None, hasta=dt.time(15, 0)):
            with self.assertRaises(scanner.SinSesion) as cm:
                scanner.ventana_orb(comun.parse_ahora(ahora), a, 15, hasta)
            return str(cm.exception)
        self.assertIn("fin de semana", msg("2026-10-17 10:15"))
        self.assertIn("Thanksgiving", msg("2026-11-26 10:15"))
        self.assertIn("a partir de las 09:50", msg("2026-10-19 09:47"))
        self.assertIn("caducada", msg("2026-10-19 15:45"))
        self.assertIn("cerró a las 16:00", msg("2026-10-19 16:30"))
        self.assertIn("más tarde que ahora", msg("2026-10-19 10:00", a=dt.time(10, 15)))
        with self.assertRaises(comun.KemetError):
            scanner.ventana_orb(comun.parse_ahora("2026-10-19 10:15"), None, 7, None)
        code, out, _ = run(["orb", "--offline", WALL, "--ahora", "2026-10-17 10:15", "--sin-escribir"])
        self.assertEqual(code, 1)
        self.assertIn("fin de semana", out)

    def test_spark_en_vivo_con_el_tick_fuera_de_la_rejilla(self):
        datos, _ = scanner.cargar_offline(SPARK5)
        self.assertEqual(len(datos), 20)
        self.assertIn("BRK.B", datos)
        t = datos["TSLA"]
        self.assertEqual(scanner.ny_de_ts(t["t"][-1]), dt.datetime(2026, 10, 20, 10, 1, 47))
        dia, corte = scanner.ventana_orb(comun.parse_ahora("2026-10-20 10:01"), None, 15, dt.time(15, 0))
        velas = scanner.velas_sesion(t, dia, corte)
        self.assertEqual([b["inicio"].strftime("%H:%M") for b in velas], ["09:30", "09:35", "09:40", "09:45", "09:50", "09:55"])

    def test_la_salida_llana(self):
        code, out, _ = run(["orb", "--offline", WALL, "--ahora", "2026-10-19 10:15", "--min-precio", "0", "--sin-escribir", "--mostrar", "50"])
        self.assertEqual(code, 0)
        self.assertIn("Recibidos 233 de 234 gráficos (1 fallaron o sin datos); 231 utilizables; 95 candidatos, 95 confirmados", out)
        self.assertIn("42 de 231 gráficos cerraron por encima del máximo de su rango de apertura a las 10:15:", out)
        self.assertIn("  10:15  TSLA       364,18 $  rango 354,47 a 362,18  +0,55 % por encima", out)
        self.assertNotIn(chr(0x2014), out)


class Watchlist(ConKemetTemporal):
    def test_el_contrato_del_archivo(self):
        code, out, _ = run(["orb", "--offline", WALL, "--ahora", "2026-10-19 10:15", "--min-precio", "0"])
        self.assertEqual(code, 0)
        ruta = os.path.join(self.kemet, "watchlist.json")
        self.assertTrue(os.path.exists(ruta))
        self.assertIn("Escrito %s (modo orb, 42 aciertos)." % ruta, out)
        with open(ruta, encoding="utf-8") as fh:
            doc = json.load(fh)
        for k in ("modo", "generado", "universo", "escaneados", "fallidos", "aciertos"):
            self.assertIn(k, doc)
        self.assertEqual((doc["modo"], doc["generado"], doc["universo"], doc["escaneados"], doc["fallidos"]), ("orb", "2026-10-19T14:15:00Z", 234, 231, 1))
        self.assertEqual(len(doc["aciertos"]), 42)
        for h in doc["aciertos"]:
            for k in ("simbolo", "regla", "precio", "hora", "detalle"):
                self.assertIn(k, h)
        # kemet-noticias y entrada.py watchlist leen aciertos[].simbolo; el propio scanner también
        self.assertIn("TSLA", scanner.simbolos_de_archivo(ruta))
        code, _, _ = run(["orb", "--offline", WALL, "--ahora", "2026-10-19 10:15", "--min-precio", "0", "--watchlist", ruta, "--sin-escribir"])
        self.assertEqual(code, 0)

    def test_universo_escrito_y_leido(self):
        code, out, _ = run(["universo", "--offline", SYMDIR])
        self.assertEqual(code, 0)
        ruta = os.path.join(self.kemet, "universo.txt")
        self.assertIn("Dentro 17 acciones", out)
        with open(ruta, encoding="utf-8") as fh:
            lineas = fh.read().splitlines()
        self.assertEqual(len(lineas), 17)
        self.assertIn("BRK.B|Berkshire Hathaway Inc. New Common Stock", lineas)
        self.assertEqual(len(scanner.simbolos_de_archivo(ruta)), 17)
        code, _, err = run(["diario", "--offline", DAILY, "--ahora", "2026-10-19 09:00", "--universo", os.path.join(self.tmp, "no.txt"), "--sin-escribir"])
        self.assertEqual(code, 2)
        self.assertIn("scanner.py universo", err)


class Futuros(unittest.TestCase):
    def fila(self, codigo, ahora, **kw):
        filas, fallidos = scanner.escanear_futuros([codigo], comun.parse_ahora(ahora), YAHOO, **kw)
        self.assertEqual(fallidos, {})
        return filas[0]

    def test_nq_el_11_de_noviembre_a_las_10_45(self):
        f = self.fila("NQ", "2026-11-11 10:45")
        self.assertEqual((f["ib"]["alto"], f["ib"]["bajo"], f["ib"]["ancho"], f["ib"]["velas"]), (28426.0, 28199.0, 227.0, 12))
        self.assertEqual(f["ruptura"], {"lado": "arriba", "precio": 28429.75, "hora": "10:45", "vela": "10:40"})
        self.assertEqual((f["ayer"]["fecha"], f["ayer"]["pdh"], f["ayer"]["pdl"], f["ayer"]["pdc"]), ("2026-11-10", 28090.0, 27516.0, 27835.25))
        self.assertEqual(f["reglas"], ["ib-arriba", "sobre-pdh"])
        self.assertEqual((f["ultimo"], f["hora_ultimo"], f["rango_sesiones"]), (28429.75, "10:45", 20))
        self.assertEqual(f["rango_hoy"], 245.25)
        self.assertEqual(f["notas"], [])
        h = scanner.acierto_futuro(f)
        self.assertEqual((h["simbolo"], h["regla"], h["precio"], h["hora"]), ("NQ", "ib-arriba + sobre-pdh", 28429.75, "10:45"))
        self.assertIn("la vela de 10:40 cerró en 28.429,75, por encima del balance inicial 28.199 a 28.426 (227 puntos)", h["detalle"])

    def test_antes_de_la_ruptura_y_con_el_ib_abierto(self):
        f = self.fila("NQ", "2026-11-11 10:40")
        self.assertNotIn("ruptura", f)
        self.assertEqual(f["reglas"], ["sobre-pdh"])                         # 28.392 ya está por encima de 28.090
        self.assertEqual(f["ultimo"], 28392.0)
        f = self.fila("NQ", "2026-11-11 10:29")
        self.assertNotIn("ib", f)
        self.assertIn("balance inicial de 60 minutos aún abierto", f["notas"])
        f = self.fila("NQ", "2026-11-11 10:45", ib_minutos=30)
        self.assertEqual(f["ib"]["velas"], 6)

    def test_un_ib_que_no_rompe_no_es_acierto(self):
        f = self.fila("ES", "2026-11-11 10:45")
        self.assertNotIn("ruptura", f)
        self.assertEqual(f["reglas"], ["sobre-pdh"])
        self.assertEqual((f["ib"]["alto"], f["ib"]["bajo"]), (7624.75, 7593.25))

    def test_los_doce_con_el_fixture_son_parciales(self):
        code, out, _ = run(["futuros", "--offline", YAHOO, "--ahora", "2026-11-11 10:45", "--sin-escribir"])
        self.assertEqual(code, 0)
        self.assertIn("4 de 12 contratos con datos (8 sin datos: YM, RTY, SI, HG, NG, 6E, ZN, ZB). PARCIAL.", out)
        self.assertIn("  NQ   último 28.429,75 (10:45)   IB 28.199 a 28.426, 227 pts: CIERRE POR ENCIMA a las 10:45 en 28.429,75", out)
        self.assertIn("ayer 27.516 a 28.090: por encima del máximo de ayer. Rango de hoy 245,25 pts, el 48 % del medio de 20 sesiones", out)
        self.assertIn("GC   último 4.013,10 (10:45)   IB 4.035,30 a 4.052,90, 17,60 pts: CIERRE POR DEBAJO a las 09:35 en 4.029", out)
        self.assertIn("medio de 2 sesiones", out)                             # CL y GC solo traen 5 días
        self.assertIn("16:45 Madrid / 10:45 NY", out)
        self.assertNotIn(chr(0x2014), out)


class FuturosWatchlist(ConKemetTemporal):
    def test_escribe_el_contrato_y_el_json(self):
        code, out, _ = run(["futuros", "--simbolos", "NQ,ES", "--offline", YAHOO, "--ahora", "2026-11-11 10:45", "--json"])
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertEqual((doc["modo"], doc["universo"], doc["escaneados"], doc["fallidos"]), ("futuros", 2, 2, 0))
        self.assertEqual([h["simbolo"] for h in doc["aciertos"]], ["NQ", "ES"])
        for h in doc["aciertos"]:
            for k in ("simbolo", "regla", "precio", "hora", "detalle"):
                self.assertIn(k, h)
        with open(os.path.join(self.kemet, "watchlist.json"), encoding="utf-8") as fh:
            escrito = json.load(fh)
        self.assertEqual(escrito["aciertos"], doc["aciertos"])
        self.assertEqual(escrito["contratos"][0]["simbolo"], "NQ")
        for palabra in ("escala", "IB" + "60", "factor"):
            self.assertNotIn(palabra, out)

    def test_un_simbolo_desconocido_es_error(self):
        code, _, err = run(["futuros", "--simbolos", "TSLA", "--offline", YAHOO, "--ahora", "2026-11-11 10:45"])
        self.assertEqual(code, 2)
        self.assertIn("futuros solo acepta contratos", err)
        code, _, err = run(["futuros", "--simbolos", "NQ=X", "--offline", YAHOO, "--ahora", "2026-11-11 10:45"])
        self.assertEqual(code, 2)
        self.assertIn("no conozco el instrumento", err)


if __name__ == "__main__":
    unittest.main()
