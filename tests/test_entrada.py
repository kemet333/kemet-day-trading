"""kemet-entrada: la ruptura del balance inicial sobre el fixture real de NQ (tests/fixtures/yahoo/NQ=F-60d-5m.json.gz), sin red.

Día de referencia: miércoles 2026-11-11 (IB 60 min 28.199 a 28.426; la vela de 10:40 cerró en 28.429,75, por encima del
IB alto: disparo largo a las 10:45, barra 15). Día sin disparo: miércoles 2026-10-28 (IB 29.767,25 a 29.952,75, ninguna
vela cerró fuera antes de las 15:00). Las velas alteradas (mecha sin cierre fuera, cierre exacto en el nivel, cierre
fuera antes de las 09:45) son SINTÉTICAS: se construyen en memoria sobre las velas reales.

Acciones: TSLA, miércoles 2026-11-11 (fixture real tests/fixtures/yahoo/TSLA-60d-5m.json.gz): IB de 15 minutos 386,35 a
392,67 (3 velas); la vela de 10:10 cerró en 393,08, por encima del IB alto: disparo largo a las 10:15, barra 9. La watchlist
de la prueba es SINTÉTICA (tres símbolos escritos a mano con el contrato de kemet-scanner).
"""
import copy
import datetime
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, ROOT, YAHOO

entrada = load("kemet-entrada", "entrada")
comun = entrada.comun
TOOL = os.path.join(ROOT, "kemet-entrada", "entrada.py")

_CH = {}


def chart(codigo="NQ"):
    if codigo not in _CH:
        _CH[codigo] = comun.velas(codigo, "60d" if codigo in ("NQ", "ES") else "5d", "5m", YAHOO)
    return _CH[codigo]


def ny(texto):
    return comun.parse_ahora(texto)


def en(texto, codigo="NQ", ch=None, cfg=None, ib_minutos=60):
    return entrada.evaluar(codigo, ch or chart(codigo), ny(texto), cfg, ib_minutos)


def con_vela(ch, dia_hora, **cambios):
    """Una copia del chart con una vela (inicio en hora NY) alterada: o, h, l, c."""
    ch = copy.deepcopy(ch)
    ts = comun.ts_de_utc(ny(dia_hora))
    idx = {"o": 1, "h": 2, "l": 3, "c": 4}
    for i, b in enumerate(ch["velas"]):
        if b[0] == ts:
            v = list(b)
            for k, val in cambios.items():
                v[idx[k]] = val
            ch["velas"][i] = tuple(v)
            return ch
    raise AssertionError("no hay vela a las %s" % dia_hora)


def correr(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        codigo = entrada.main(argv)
    return codigo, out.getvalue(), err.getvalue()


class KemetDirTemporal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kemet = os.path.join(self.tmp, "kemet")
        self._old = comun.KEMET_DIR
        comun.KEMET_DIR = self.kemet

    def tearDown(self):
        comun.KEMET_DIR = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)


class IBDelOnce(unittest.TestCase):
    def test_ib_de_60_minutos_del_11_11(self):
        r = en("2026-11-11 16:30")
        ib = r["ib"]
        self.assertEqual((ib["alto"], ib["bajo"], ib["ancho"], ib["velas"], ib["minutos"]), (28426.0, 28199.0, 227.0, 12, 60))
        self.assertEqual(ib["medio"], 28312.5)
        self.assertEqual(r["sistema"], "ruptura-ib")

    def test_ib_de_15_y_30_minutos(self):
        r = en("2026-11-11 16:30", ib_minutos=15)
        self.assertEqual((r["ib"]["alto"], r["ib"]["bajo"], r["ib"]["velas"]), (28426.0, 28254.25, 3))
        self.assertEqual((r["estado"], r["lado"], r["hora"], r["barra"], r["precio"]), ("disparado", "corto", "09:50", 4, 28246.75))
        r = en("2026-11-11 10:05", ib_minutos=30)
        self.assertEqual((r["ib"]["alto"], r["ib"]["bajo"], r["ib"]["velas"]), (28426.0, 28199.0, 6))
        self.assertEqual(r["estado"], "esperando")
        with self.assertRaises(comun.KemetError):
            en("2026-11-11 10:05", ib_minutos=45)


class Estados(unittest.TestCase):
    def test_formando_a_las_10_20(self):
        r = en("2026-11-11 10:20")
        self.assertEqual(r["estado"], "formando")
        self.assertEqual(r["ib_provisional"]["velas"], 10)
        self.assertEqual((r["ib_provisional"]["alto"], r["ib_provisional"]["bajo"]), (28426.0, 28199.0))
        self.assertIn("faltan 10 minutos", r["motivo"])
        self.assertIsNone(r["ib"])

    def test_formando_antes_de_la_apertura(self):
        r = en("2026-11-11 09:10")
        self.assertEqual(r["estado"], "formando")
        self.assertIn("abre a las 09:30", r["motivo"])

    def test_esperando_a_las_10_40(self):
        r = en("2026-11-11 10:40")
        self.assertEqual(r["estado"], "esperando")
        self.assertEqual(r["ultimo"]["vela"], "10:35")
        self.assertEqual(r["ultimo"]["cierre"], 28392.0)
        self.assertEqual(r["ultimo"]["a_alto"], 34.0)
        self.assertEqual(r["ultimo"]["a_bajo"], 193.0)

    def test_disparado_a_las_10_45(self):
        r = en("2026-11-11 10:45")
        self.assertEqual(r["estado"], "disparado")
        self.assertEqual(r["lado"], "largo")
        self.assertEqual(r["hora"], "10:45")
        self.assertEqual(r["barra"], 15)
        self.assertEqual(r["precio"], 28429.75)                 # el cierre de la vela de 10:40, no el nivel
        self.assertEqual(r["minutos_desde"], 0)
        self.assertEqual((r["stop_defecto"], r["objetivo_defecto"]), (28312.5, 28547.0))

    def test_el_disparo_no_cambia_con_el_dia_y_dice_que_paso(self):
        r = en("2026-11-11 16:30")
        self.assertEqual((r["estado"], r["lado"], r["hora"], r["precio"]), ("disparado", "largo", "10:45", 28429.75))
        self.assertEqual(r["despues"]["objetivo_tocado"], "11:00")
        self.assertIsNone(r["despues"]["stop_tocado"])
        self.assertEqual(r["despues"]["minimo"], 28413.75)
        texto = "\n".join(entrada.describir(r))
        self.assertIn("se habría tocado a las 11:00", texto)
        self.assertIn("entrada tardía", texto)

    def test_caducado_a_las_15_05_del_28_10(self):
        r = en("2026-10-28 15:05")
        self.assertEqual(r["estado"], "caducado")
        self.assertEqual((r["ib"]["alto"], r["ib"]["bajo"]), (29952.75, 29767.25))
        self.assertIn("15:00", r["motivo"])
        self.assertEqual(en("2026-10-28 14:50")["estado"], "esperando")

    def test_la_vela_de_las_14_55_cuenta_y_la_de_las_15_00_no(self):
        ch = con_vela(chart(), "2026-10-28 14:55", c=29953.0)
        r = en("2026-10-28 15:05", ch=ch)
        self.assertEqual((r["estado"], r["lado"], r["hora"], r["barra"], r["precio"]), ("disparado", "largo", "15:00", 66, 29953.0))
        ch = con_vela(chart(), "2026-10-28 15:00", c=29953.0)
        self.assertEqual(en("2026-10-28 15:05", ch=ch)["estado"], "caducado")

    def test_sin_entradas_despues_del_config(self):
        r = en("2026-11-11 10:45", cfg={"sin_entradas_despues": "10:40"})
        self.assertEqual(r["estado"], "caducado")
        self.assertEqual(r["sin_entradas_despues"], "10:40")

    def test_sin_entradas_antes_de_las_09_45(self):
        # SINTÉTICO: con IB de 15 minutos la vela de 09:45 cierra a las 09:50, y con sin_entradas_antes 10:00 no vale
        r = en("2026-11-11 10:05", cfg={"sin_entradas_antes": "10:00"}, ib_minutos=15)
        self.assertNotEqual(r["hora"], "09:50")
        self.assertTrue(any("antes de las 10:00" in a for a in r["avisos"]))
        r = en("2026-11-11 10:05", ib_minutos=15)
        self.assertEqual(r["hora"], "09:50")

    def test_cerrado_en_fin_de_semana(self):
        r = en("2026-11-14 11:00")
        self.assertEqual(r["estado"], "cerrado")
        self.assertIn("sábado", r["motivo"])
        self.assertIn("domingo 15/11/2026 18:00", r["proxima_apertura"])

    def test_una_mecha_no_dispara_ni_un_cierre_exacto(self):
        # SINTÉTICO: la vela de 10:40 con el mismo máximo (28.444,25) pero cerrando dentro del IB
        ch = con_vela(chart(), "2026-11-11 10:40", c=28400.0)
        r = en("2026-11-11 10:45", ch=ch)
        self.assertEqual(r["estado"], "esperando")
        ch = con_vela(chart(), "2026-11-11 10:40", c=28426.0)
        self.assertEqual(en("2026-11-11 10:45", ch=ch)["estado"], "esperando")
        ch = con_vela(chart(), "2026-11-11 10:40", c=28426.25)
        r = en("2026-11-11 10:45", ch=ch)
        self.assertEqual((r["estado"], r["precio"]), ("disparado", 28426.25))

    def test_el_lado_es_el_del_cierre(self):
        # SINTÉTICO: una vela con mechas por los dos lados del IB que cierra por debajo
        ch = con_vela(chart(), "2026-11-11 10:35", h=28500.0, l=28100.0, c=28150.0)
        r = en("2026-11-11 10:40", ch=ch)
        self.assertEqual((r["estado"], r["lado"], r["hora"], r["barra"], r["precio"]), ("disparado", "corto", "10:40", 14, 28150.0))
        self.assertEqual(r["avisos"], [])

    def test_una_operacion_al_dia_la_primera(self):
        ch = con_vela(chart(), "2026-11-11 10:35", c=28150.0)   # SINTÉTICO: cierre por debajo antes del cierre real por encima
        r = en("2026-11-11 16:30", ch=ch)
        self.assertEqual((r["lado"], r["hora"]), ("corto", "10:40"))


class OtrosMercados(unittest.TestCase):
    def test_es_con_su_sesion(self):
        r = en("2026-11-11 16:30", "ES")
        self.assertEqual((r["ib"]["alto"], r["ib"]["bajo"]), (7624.75, 7593.25))
        self.assertEqual((r["estado"], r["lado"], r["hora"], r["barra"], r["precio"]), ("disparado", "largo", "10:55", 17, 7625.0))
        self.assertNotIn("validado", "\n".join(entrada.describir(r)))

    def test_cl_y_gc_sesion_y_plano_propios(self):
        ch = chart("CL")
        ahora = comun.utc_de_ts(ch["ts_mercado"])
        r = entrada.evaluar("CL", ch, ahora)
        self.assertEqual((r["apertura"], r["cierre"], r["cierre_ib"]), ("09:00", "14:30", "10:00"))
        r = entrada.evaluar("GC", chart("GC"), comun.utc_de_ts(chart("GC")["ts_mercado"]))
        self.assertEqual((r["apertura"], r["cierre"], r["cierre_ib"]), ("08:20", "13:30", "09:20"))


class Retraso(unittest.TestCase):
    def test_vela_cerrada_que_aun_no_ha_llegado(self):
        ch = copy.deepcopy(chart())
        ts = comun.ts_de_utc(ny("2026-11-11 10:40"))
        ch["velas"] = [b for b in ch["velas"] if b[0] != ts]      # Yahoo aún no ha enviado la de 10:40
        r = en("2026-11-11 10:45:30", ch=ch)
        self.assertEqual(r["estado"], "esperando")
        self.assertEqual(r["retraso"]["vela"], "10:40")
        self.assertTrue(r["retraso"]["pendiente"])
        self.assertIn("aún no está en Yahoo", "\n".join(entrada.describir(r)))
        r = en("2026-11-11 10:47:00", ch=ch)
        self.assertFalse(r["retraso"]["pendiente"])


class LineaDeComandos(KemetDirTemporal):
    def test_check_escribe_entrada_json_con_el_contrato(self):
        codigo, out, err = correr(["check", "--ahora", "2026-11-11 10:45", "--offline", YAHOO, "--escribir"])
        self.assertEqual(codigo, 0, err)
        self.assertIn("DISPARADO largo a las 10:45 NY en 28.429,75", out)
        self.assertIn("16:45 Madrid / 10:45 NY", out)
        with open(os.path.join(self.kemet, "entrada.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        for k in ("generado", "mercado", "fecha", "sistema", "estado", "motivo", "lado", "hora", "barra", "precio", "ib", "comprobado"):
            self.assertIn(k, doc)
        self.assertEqual((doc["estado"], doc["lado"], doc["hora"], doc["barra"], doc["precio"]), ("disparado", "largo", "10:45", 15, 28429.75))
        self.assertEqual(doc["ib"], {"alto": 28426.0, "bajo": 28199.0, "ancho": 227.0, "minutos": 60})
        self.assertNotIn("escala", json.dumps(doc))

    def test_check_sin_disparo_devuelve_1_y_json(self):
        codigo, out, _ = correr(["check", "--ahora", "2026-11-11 10:40", "--offline", YAHOO, "--json"])
        self.assertEqual(codigo, 1)
        doc = json.loads(out)
        self.assertEqual(doc["estado"], "esperando")
        self.assertNotIn("_velas", doc)

    def test_mercado_del_config(self):
        os.makedirs(self.kemet)
        with open(os.path.join(self.kemet, "config.json"), "w", encoding="utf-8") as fh:
            json.dump({"mercado": "ES", "sin_entradas_antes": "09:45", "sin_entradas_despues": "15:00"}, fh)
        codigo, out, _ = correr(["check", "--ahora", "2026-11-11 16:30", "--offline", YAHOO])
        self.assertTrue(out.startswith("ES, miércoles 11/11/2026"))
        self.assertNotIn("Sin kemet/config.json", out)

    def test_watch_repite_el_dia_y_para_en_el_disparo(self):
        codigo, out, err = correr(["watch", "--ahora", "2026-11-11 10:20", "--offline", YAHOO, "--escribir"])
        self.assertEqual(codigo, 0, err)
        lineas = out.splitlines()
        self.assertTrue(any(l.startswith("10:25  cierre 28.375,50  IB cerrado: 28.199 a 28.426, 227 puntos") for l in lineas), out)
        self.assertTrue(any(l.startswith("10:35  cierre 28.392  a 34 del IB alto 28.426") for l in lineas), out)
        self.assertTrue(any(l.startswith("10:40  cierre 28.429,75  cierre por encima del IB alto 28.426: DISPARADO largo a las 10:45 en 28.429,75 (barra 15)") for l in lineas), out)
        self.assertTrue(os.path.exists(os.path.join(self.kemet, "entrada.json")))

    def test_watch_caduca_a_las_15_00(self):
        codigo, out, _ = correr(["watch", "--ahora", "2026-10-28 14:40", "--offline", YAHOO])
        self.assertEqual(codigo, 1)
        self.assertIn("CADUCADO", out)
        self.assertIn("14:55  cierre 29.903,50", out)

    def test_error_sin_traza_codigo_2(self):
        codigo, out, err = correr(["check", "--ahora", "ayer", "--offline", YAHOO])
        self.assertEqual(codigo, 2)
        self.assertTrue(err.startswith("entrada.py: "))

    def test_kemet_dir_por_variable_de_entorno(self):
        env = dict(os.environ, KEMET_DIR=os.path.join(self.tmp, "otro"))
        p = subprocess.run([sys.executable, TOOL, "check", "--ahora", "2026-11-11 10:45", "--offline", YAHOO, "--escribir"],
                           cwd=self.tmp, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "otro", "entrada.json")))


class Acciones(KemetDirTemporal):
    """TSLA, 2026-11-11: el IB de 15 minutos recalculado a mano sobre el fixture, el disparo real, el reloj de la NYSE y la watchlist."""

    def velas_11_11(self):
        """Las velas de la sesión regular de TSLA del 11/11 sacadas del fixture sin pasar por el tool, al céntimo."""
        out = []
        for b in chart("TSLA")["velas"]:
            ny = comun.a_ny(comun.utc_de_ts(b[0]))
            if ny.date() == datetime.date(2026, 11, 11) and datetime.time(9, 30) <= ny.time() < datetime.time(16, 0):
                out.append((b[0],) + tuple(comun.al_tick(x, 0.01) for x in b[1:5]))
        return out

    def test_resolver_un_ticker(self):
        self.assertEqual(entrada.mercado_de("tsla", None), "TSLA")
        self.assertEqual(entrada.mercado_de("MNQ", None), "NQ")
        self.assertEqual(entrada.mercado_de(None, {"mercado": "AAPL"}), "AAPL")
        self.assertEqual(entrada.mercado_de(None, None), "NQ")
        with self.assertRaises(comun.KemetError):
            entrada.mercado_de("X1", None)

    def test_ib_de_15_minutos_de_tsla_a_mano(self):
        rth = self.velas_11_11()
        self.assertEqual(len(rth), 78)
        ib = rth[:3]                                            # 09:30, 09:35 y 09:40
        alto, bajo = max(b[2] for b in ib), min(b[3] for b in ib)
        r = en("2026-11-11 16:30", "TSLA", ib_minutos=None)     # None: el del instrumento, 15 en una acción
        self.assertEqual((r["instrumento"], r["unidad"], r["ib_minutos"]), ("accion", "$", 15))
        self.assertEqual((r["ib"]["alto"], r["ib"]["bajo"], r["ib"]["velas"]), (alto, bajo, 3))
        self.assertEqual((r["ib"]["alto"], r["ib"]["bajo"], r["ib"]["ancho"], r["ib"]["medio"]), (392.67, 386.35, 6.32, 389.51))
        self.assertEqual((r["apertura"], r["cierre"], r["cierre_ib"]), ("09:30", "16:00", "09:45"))
        self.assertEqual(en("2026-11-11 16:30", "TSLA", ib_minutos=60)["ib"]["velas"], 12)   # pedido a mano, también vale

    def test_estados_y_disparo_del_11_11(self):
        r = en("2026-11-11 08:00", "TSLA", ib_minutos=None)
        self.assertEqual(r["estado"], "formando")
        self.assertIn("abre a las 09:30", r["motivo"])
        r = en("2026-11-11 10:10", "TSLA", ib_minutos=None)
        self.assertEqual(r["estado"], "esperando")
        self.assertEqual((r["ultimo"]["vela"], r["ultimo"]["cierre"], r["ultimo"]["a_alto"], r["ultimo"]["a_bajo"]), ("10:05", 392.12, 0.55, 5.77))
        r = en("2026-11-11 10:15", "TSLA", ib_minutos=None)
        self.assertEqual((r["estado"], r["lado"], r["hora"], r["barra"], r["precio"]), ("disparado", "largo", "10:15", 9, 393.08))
        self.assertEqual(r["precio"], self.velas_11_11()[8][4])            # el cierre de la vela de 10:10
        self.assertEqual((r["stop_defecto"], r["objetivo_defecto"]), (389.51, 396.65))
        r = en("2026-11-11 16:30", "TSLA", ib_minutos=None)                 # después del cierre sigue siendo el día, no «cerrado»
        self.assertEqual((r["estado"], r["hora"], r["precio"]), ("disparado", "10:15", 393.08))
        d = r["despues"]
        self.assertEqual((d["stop_tocado"], d["objetivo_tocado"], d["maximo"], d["minimo"], d["velas"]), ("15:55", None, 395.43, 388.75, 69))
        texto = "\n".join(entrada.describir(r))
        self.assertIn("IB 09:30 a 09:45: alto 392,67, bajo 386,35, 6,32 $ (3 velas), medio 389,51.", texto)
        self.assertIn("(389,51) se habría tocado a las 15:55", texto)
        self.assertIn("puede ir con retraso", texto)

    def test_reloj_de_la_nyse(self):
        r = en("2026-11-14 11:00", "TSLA", ib_minutos=None)
        self.assertEqual((r["estado"], r["motivo"], r["proxima_apertura"]), ("cerrado", "NYSE cerrada (sábado)", "lunes 16/11/2026 09:30"))
        r = en("2026-11-26 11:00", "TSLA", ib_minutos=None)
        self.assertEqual((r["estado"], r["motivo"], r["proxima_apertura"]), ("cerrado", "NYSE cerrada (Thanksgiving)", "viernes 27/11/2026 09:30"))
        self.assertNotEqual(en("2026-11-26 11:00")["estado"], "cerrado")   # Globex sí abre ese día
        r = en("2026-11-27 10:00", "TSLA", ib_minutos=None)
        self.assertNotEqual(r["estado"], "cerrado")
        self.assertEqual((r["cierre"], r["sin_entradas_despues"], r["recortado"]), ("13:00", "12:55", "Día después de Thanksgiving"))
        self.assertNotIn("globex", r)
        self.assertIn("globex", en("2026-11-11 10:45"))

    def test_check_y_watch_por_linea_de_comandos(self):
        codigo, out, err = correr(["check", "--simbolo", "TSLA", "--ahora", "2026-11-11 10:15", "--offline", YAHOO, "--escribir"])
        self.assertEqual(codigo, 0, err)
        self.assertIn("TSLA, miércoles 11/11/2026, 16:15 Madrid / 10:15 NY · ruptura del IB de 15 minutos", out)
        self.assertIn("DISPARADO largo a las 10:15 NY en 393,08: la vela de 10:10 (barra 9) cerró en 393,08, por encima del IB alto 392,67.", out)
        with open(os.path.join(self.kemet, "entrada.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual((doc["mercado"], doc["instrumento"], doc["micro"], doc["precio"], doc["hora"], doc["barra"]), ("TSLA", "accion", "TSLA", 393.08, "10:15", 9))
        self.assertEqual(doc["ib"], {"alto": 392.67, "bajo": 386.35, "ancho": 6.32, "minutos": 15})
        codigo, out, _ = correr(["check", "--ahora", "2026-11-11 10:45", "--offline", YAHOO, "--json"])
        self.assertEqual((json.loads(out)["ib_minutos"], json.loads(out)["instrumento"]), (60, "futuro"))   # NQ sigue con su hora
        codigo, out, err = correr(["watch", "--mercado", "TSLA", "--ahora", "2026-11-11 09:40", "--offline", YAHOO])
        self.assertEqual(codigo, 0, err)
        self.assertIn("09:40  cierre 388,07  IB cerrado: 386,35 a 392,67, 6,32 $", out)
        self.assertIn("10:05  cierre 392,12  a 0,55 del IB alto 392,67 y a 5,77 del IB bajo 386,35", out)
        self.assertIn("10:10  cierre 393,08  cierre por encima del IB alto 392,67: DISPARADO largo a las 10:15 en 393,08 (barra 9)", out)

    def test_watchlist(self):
        codigo, out, _ = correr(["watchlist", "--offline", YAHOO, "--ahora", "2026-11-11 10:15"])
        self.assertEqual(codigo, 1)
        self.assertIn("No hay watchlist", out)
        os.makedirs(self.kemet, exist_ok=True)
        with open(os.path.join(self.kemet, "watchlist.json"), "w", encoding="utf-8") as fh:
            json.dump({"modo": "orb", "generado": "2026-11-11T15:05:00Z", "universo": "kemet/universo.txt", "escaneados": 3, "fallidos": 0,
                       "aciertos": [{"simbolo": "TSLA", "regla": "orb", "precio": 393.08, "hora": "10:15", "detalle": "ruptura del rango de 15 min"},
                                    {"simbolo": "AAPL", "regla": "orb", "precio": 353.68, "hora": "09:50", "detalle": "ruptura del rango de 15 min"},
                                    {"simbolo": "NQ", "regla": "futuros", "precio": 28429.75, "hora": "10:45", "detalle": "ruptura del balance inicial"}]}, fh)
        codigo, out, err = correr(["watchlist", "--offline", YAHOO, "--ahora", "2026-11-11 10:15"])
        self.assertEqual(codigo, 0, err)
        lineas = out.splitlines()
        self.assertTrue(lineas[0].startswith("Watchlist ") and "modo orb, 3 símbolos" in lineas[0], out)
        self.assertTrue(any(l.startswith("TSLA   DISPARADO largo a las 10:15 NY en 393,08 (vela de 10:10, barra 9); IB de 15 min 386,35 a 392,67; stop por defecto 389,51, objetivo 1R 396,65.") for l in lineas), out)
        self.assertTrue(any(l.startswith("AAPL   DISPARADO largo a las 09:50 NY en 353,68 (vela de 09:45, barra 4); IB de 15 min") for l in lineas), out)
        self.assertTrue(any(l.startswith("NQ     FORMANDO  IB en formación, 9 de 12 velas cerradas") for l in lineas), out)
        self.assertIn("2 disparos. No se ha enviado ninguna orden.", out)
        codigo, out, _ = correr(["watchlist", "--offline", YAHOO, "--ahora", "2026-11-11 16:30", "--json"])
        self.assertEqual(codigo, 0)
        doc = json.loads(out)
        self.assertEqual((doc["modo"], doc["disparados"], [s["mercado"] for s in doc["simbolos"]]), ("orb", 3, ["TSLA", "AAPL", "NQ"]))
        self.assertEqual([s["ib_minutos"] for s in doc["simbolos"]], [15, 15, 60])
        with open(os.path.join(self.kemet, "watchlist.json"), "w", encoding="utf-8") as fh:
            json.dump({"modo": "diario", "aciertos": []}, fh)
        codigo, out, _ = correr(["watchlist", "--offline", YAHOO])
        self.assertEqual(codigo, 1)
        self.assertIn("no tiene aciertos", out)


if __name__ == "__main__":
    unittest.main()
