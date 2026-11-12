"""kemet-niveles sobre el fixture real de NQ (y ES, CL, GC), sin red. Día de ejemplo: miércoles 2026-11-11.
Acciones: TSLA (fixture real TSLA-60d-5m.json.gz): sin noche, apertura y balance inicial de 15 minutos, niveles al céntimo."""
import datetime as dt
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, YAHOO

niveles = load("kemet-niveles", "niveles")
comun = niveles.comun


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = niveles.main(argv)
    return code, out.getvalue(), err.getvalue()


def doc(ahora, *extra):
    code, out, _ = run(["--ahora", ahora, "--offline", YAHOO, "--json"] + list(extra))
    return code, json.loads(out)


def a_mano(codigo, dia, desde, hasta):
    """Las velas del fixture entre dos horas de Nueva York de un día, calculadas sin pasar por el tool."""
    ch = comun.velas(codigo, "60d", "5m", YAHOO)
    out = []
    for b in ch["velas"]:
        ny = comun.a_ny(comun.utc_de_ts(b[0]))
        if ny.date() == dia and desde <= ny.time() < hasta:
            out.append(b)
    return out


class SesionAnterior(unittest.TestCase):
    def test_pdh_pdl_pdc_del_10_de_noviembre_coinciden_con_el_calculo_a_mano(self):
        rth = a_mano("NQ", dt.date(2026, 11, 10), dt.time(9, 30), dt.time(16, 0))
        self.assertEqual(len(rth), 78)                       # 6,5 h de velas de 5 min
        code, d = doc("2026-11-11 16:30")
        self.assertEqual(code, 0)
        self.assertEqual(d["sesion_anterior"], "2026-11-10")
        self.assertEqual(d["pdh"], max(b[2] for b in rth))
        self.assertEqual(d["pdl"], min(b[3] for b in rth))
        self.assertEqual(d["pdc"], rth[-1][4])
        self.assertEqual((d["pdh"], d["pdl"], d["pdc"]), (28090.0, 27516.0, 27835.25))

    def test_sin_sesion_anterior_devuelve_1(self):
        code, out, _ = run(["--ahora", "2026-09-03 10:00", "--offline", YAHOO])
        self.assertEqual(code, 1)
        self.assertIn("sin sesión anterior", out)


class BalanceInicial(unittest.TestCase):
    def test_ib_del_11_de_noviembre(self):
        ib = a_mano("NQ", dt.date(2026, 11, 11), dt.time(9, 30), dt.time(10, 30))
        self.assertEqual(len(ib), 12)
        code, d = doc("2026-11-11 16:30")
        self.assertEqual((d["ibh"], d["ibl"]), (max(b[2] for b in ib), min(b[3] for b in ib)))
        self.assertEqual((d["ibh"], d["ibl"], d["ib_ancho"], d["ib_velas"]), (28426.0, 28199.0, 227.0, 12))
        for k in ("escala", "ib_ratio", "filtro"):           # el pack no filtra días: ni escala ni ratio
            self.assertNotIn(k, d)

    def test_antes_de_las_10_30_no_hay_ib(self):
        _, d = doc("2026-11-11 10:29")
        self.assertNotIn("ibh", d)
        self.assertIn("orh", d)                               # la apertura de 15 min sí cerró
        self.assertEqual(d["sesion"], "rth")
        _, d = doc("2026-11-11 10:30")                        # la vela de las 10:25 cierra a las 10:30
        self.assertEqual(d["ibh"], 28426.0)

    def test_texto_del_ib(self):
        _, out, _ = run(["--ahora", "2026-11-11 16:30", "--offline", YAHOO])
        self.assertIn("Balance inicial 1 h                máximo 28.426   mínimo 28.199   ancho 227 (12 velas)", out)
        self.assertNotIn("escala", out)
        self.assertIn("22:30 Madrid / 16:30 NY", out)
        self.assertIn("sesión regular cerrada", out)


class RangoMedio(unittest.TestCase):
    def test_media_de_las_ultimas_20_sesiones_completas(self):
        ch = comun.velas("NQ", "60d", "5m", YAHOO)
        dias = comun.por_dia(comun.velas_cerradas(ch, comun.parse_ahora("2026-11-11 16:30")))
        rangos = []
        for d in sorted(dias, reverse=True):
            if d >= dt.date(2026, 11, 11):
                continue
            r = comun.rango_sesion("NQ", dias[d], d)      # None en una sesión con huecos (el 5 de noviembre)
            if r:
                rangos.append(r)
            if len(rangos) == 20:
                break
        _, d = doc("2026-11-11 16:30")
        self.assertEqual(d["rango_medio_sesiones"], 20)
        self.assertEqual(d["rango_medio_20"], round(sum(rangos) / 20, 2))
        self.assertEqual(d["rango_medio_20"], 514.15)
        _, out, _ = run(["--ahora", "2026-11-11 16:30", "--offline", YAHOO])
        self.assertIn("Rango medio de sesión              514,15 puntos (media de máximo menos mínimo de las últimas 20 sesiones", out)

    def test_con_pocas_sesiones_dice_cuantas(self):
        _, d = doc("2026-11-11 16:30", "--mercado", "CL")
        self.assertEqual(d["rango_medio_sesiones"], 2)
        _, out, _ = run(["--ahora", "2026-11-11 16:30", "--offline", YAHOO, "--mercado", "CL"])
        self.assertIn("de 2 sesiones, las que hay", out)


class Noche(unittest.TestCase):
    def test_a_las_3_hay_nocturno_y_no_hay_apertura(self):
        noche = a_mano("NQ", dt.date(2026, 11, 10), dt.time(18, 0), dt.time(23, 59, 59)) + \
            a_mano("NQ", dt.date(2026, 11, 11), dt.time(0, 0), dt.time(3, 0))
        code, d = doc("2026-11-11 03:00")
        self.assertEqual(code, 0)
        self.assertEqual(d["sesion"], "nocturna")
        self.assertEqual((d["onh"], d["onl"]), (max(b[2] for b in noche), min(b[3] for b in noche)))
        self.assertEqual((d["onh"], d["onl"]), (28280.0, 27847.75))
        for k in ("orh", "orl", "ibh", "ibl", "tdh", "tdl"):
            self.assertNotIn(k, d)
        self.assertEqual(d["pdh"], 28090.0)                   # ayer sigue siendo el 10

    def test_el_nocturno_completo_llega_hasta_la_apertura(self):
        _, d = doc("2026-11-11 16:30")
        self.assertEqual((d["onh"], d["onl"]), (28406.25, 27847.75))
        self.assertEqual((d["orh"], d["orl"]), (28426.0, 28254.25))
        self.assertEqual((d["tdh"], d["tdl"]), (28697.0, 28199.0))


class Posicion(unittest.TestCase):
    def test_encima_debajo_y_texto(self):
        _, d = doc("2026-11-11 16:30")
        self.assertEqual(d["ultimo"], 28457.25)
        self.assertEqual(d["posicion"]["pdh"], "encima")
        self.assertEqual(d["posicion"]["tdh"], "debajo")
        self.assertEqual(d["posicion"]["ibh"], "encima")
        _, out, _ = run(["--ahora", "2026-11-11 16:30", "--offline", YAHOO])
        self.assertIn("por encima del máximo de ayer", out)
        self.assertIn("por debajo del máximo de hoy", out)

    def test_fin_de_semana_dice_mercado_cerrado(self):
        _, d = doc("2026-11-14 12:00")
        self.assertEqual(d["sesion"], "cerrado")
        self.assertEqual(d["mercado_cerrado"], "sábado")
        self.assertNotIn("orh", d)


class Todos(unittest.TestCase):
    def test_los_cuatro_contratos(self):
        code, d = doc("2026-11-11 16:30", "--todos")
        self.assertEqual(code, 0)
        self.assertEqual(sorted(d["mercados"]), ["CL", "ES", "GC", "NQ"])
        self.assertEqual((d["mercados"]["ES"]["ibh"], d["mercados"]["ES"]["ibl"]), (7624.75, 7593.25))
        self.assertEqual(d["mercados"]["CL"]["pdh"], 86.83)   # el fixture de CL y GC es de 5 días: basta para los niveles
        self.assertEqual(d["mercados"]["GC"]["pdc"], 4030.8)
        _, out, _ = run(["--ahora", "2026-11-11 16:30", "--offline", YAHOO, "--todos"])
        self.assertEqual(out.count("Último"), 4)


class Acciones(unittest.TestCase):
    def test_tsla_del_11_11_sin_claves_nocturnas(self):
        rth_ayer = a_mano("TSLA", dt.date(2026, 11, 10), dt.time(9, 30), dt.time(16, 0))
        ib = a_mano("TSLA", dt.date(2026, 11, 11), dt.time(9, 30), dt.time(9, 45))
        self.assertEqual((len(rth_ayer), len(ib)), (78, 3))
        code, d = doc("2026-11-11 16:30", "--mercado", "TSLA")
        self.assertEqual(code, 0)
        self.assertEqual((d["mercado"], d["instrumento"], d["ib_minutos"], d["sesion"], d["sesion_anterior"]), ("TSLA", "accion", 15, "cerrado", "2026-11-10"))
        for k in ("onh", "onl", "escala"):
            self.assertNotIn(k, d)
        self.assertEqual((d["pdh"], d["pdl"], d["pdc"]), (comun.al_tick(max(b[2] for b in rth_ayer), 0.01), comun.al_tick(min(b[3] for b in rth_ayer), 0.01),
                                                         comun.al_tick(rth_ayer[-1][4], 0.01)))
        self.assertEqual((d["pdh"], d["pdl"], d["pdc"]), (380.0, 370.43, 379.8))
        self.assertEqual((d["ibh"], d["ibl"]), (comun.al_tick(max(b[2] for b in ib), 0.01), comun.al_tick(min(b[3] for b in ib), 0.01)))
        self.assertEqual((d["orh"], d["orl"], d["ibh"], d["ibl"], d["ib_ancho"], d["ib_velas"]), (392.67, 386.35, 392.67, 386.35, 6.32, 3))
        self.assertEqual((d["tdh"], d["tdl"], d["ultimo"], d["ultimo_hora"]), (395.43, 386.35, 390.8, "16:00"))
        self.assertEqual((d["rango_medio_20"], d["rango_medio_sesiones"]), (13.11, 20))
        self.assertEqual(sorted(d["posicion"]), ["ibh", "ibl", "orh", "orl", "pdc", "pdh", "pdl", "tdh", "tdl"])
        self.assertEqual((d["posicion"]["pdh"], d["posicion"]["ibh"], d["posicion"]["tdh"]), ("encima", "debajo", "debajo"))
        _, out, _ = run(["--ahora", "2026-11-11 16:30", "--offline", YAHOO, "--mercado", "TSLA"])
        self.assertIn("TSLA · mié 2026-11-11 · 22:30 Madrid / 16:30 NY · velas de 5 min de Yahoo (gratis, pueden ir con retraso) · sesión regular cerrada", out)
        self.assertIn("Ayer (sesión regular 2026-11-10)   máximo 380   mínimo 370,43   cierre 379,80", out)
        self.assertIn("Apertura 15 min                    máximo 392,67   mínimo 386,35", out)
        self.assertIn("Balance inicial 15 min             máximo 392,67   mínimo 386,35   ancho 6,32 (3 velas)", out)
        self.assertIn("Rango medio de sesión              13,11 $ por acción", out)
        self.assertNotIn("Noche", out)
        self.assertNotIn("nocturno", out)

    def test_antes_de_la_apertura_durante_y_cerrado(self):
        _, d = doc("2026-11-11 08:00", "--mercado", "TSLA")
        self.assertEqual((d["sesion"], d.get("antes_apertura"), d["pdc"]), ("cerrado", True, 379.8))
        for k in ("orh", "ibh", "tdh", "onh"):
            self.assertNotIn(k, d)
        _, out, _ = run(["--ahora", "2026-11-11 08:00", "--offline", YAHOO, "--mercado", "TSLA"])
        self.assertIn("antes de la apertura (09:30 NY)", out)
        self.assertIn("Balance inicial 15 min             a las 09:45 NY", out)
        _, d = doc("2026-11-11 09:40", "--mercado", "TSLA")
        self.assertEqual(d["sesion"], "rth")
        self.assertNotIn("ibh", d)
        self.assertIn("tdh", d)
        _, d = doc("2026-11-11 09:45", "--mercado", "TSLA")                  # la vela de 09:40 cierra a las 09:45
        self.assertEqual((d["ibh"], d["orh"]), (392.67, 392.67))
        _, d = doc("2026-11-14 12:00", "--mercado", "TSLA")
        self.assertEqual((d["sesion"], d["mercado_cerrado"]), ("cerrado", "sábado"))
        _, d = doc("2026-11-26 12:00", "--mercado", "TSLA")
        self.assertEqual(d["mercado_cerrado"], "Thanksgiving")

    def test_ticker_por_flag_e_ib_minutos(self):
        _, d = doc("2026-11-11 16:30", "--simbolo", "tsla")
        self.assertEqual(d["mercado"], "TSLA")
        _, d = doc("2026-11-11 16:30", "--mercado", "TSLA", "--ib-minutos", "30")
        self.assertEqual((d["ib_minutos"], d["ib_velas"], d["ibh"], d["ibl"]), (30, 6, 392.67, 386.35))
        _, d = doc("2026-11-11 16:30")                                      # NQ sigue con su hora y su noche
        self.assertEqual((d["ib_minutos"], d["ib_velas"], d["ibh"], d["onh"], d["instrumento"]), (60, 12, 28426.0, 28406.25, "futuro"))
        with self.assertRaises(comun.KemetError):
            run(["--mercado", "X1", "--ahora", "2026-11-11 16:30", "--offline", YAHOO])


class Escribir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.antes = comun.KEMET_DIR
        comun.KEMET_DIR = os.path.join(self.tmp, "kemet")

    def tearDown(self):
        comun.KEMET_DIR = self.antes
        shutil.rmtree(self.tmp)

    def test_guarda_niveles_json_con_el_contrato(self):
        code, out, _ = run(["--ahora", "2026-11-11 16:30", "--offline", YAHOO, "--escribir"])
        self.assertEqual(code, 0)
        p = os.path.join(self.tmp, "kemet", "niveles.json")
        self.assertTrue(os.path.exists(p))
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
        for k in ("generado", "mercado", "fecha", "sesion", "ultimo", "pdh", "pdl", "pdc", "onh", "onl", "orh", "orl", "ibh", "ibl", "tdh", "tdl", "posicion"):
            self.assertIn(k, d)
        for k in ("escala", "ib_ratio"):
            self.assertNotIn(k, d)
        for k in ("posicion",):
            self.assertIn(k, d)
        self.assertEqual((d["mercado"], d["fecha"], d["sesion"]), ("NQ", "2026-11-11", "cerrado"))
        self.assertIn("Guardado", out)

    def test_el_mercado_sale_de_config(self):
        os.makedirs(comun.KEMET_DIR)
        with open(os.path.join(comun.KEMET_DIR, "config.json"), "w", encoding="utf-8") as fh:
            json.dump({"mercado": "ES"}, fh)
        _, d = doc("2026-11-11 16:30")
        self.assertEqual(d["mercado"], "ES")
        self.assertEqual(d["ibh"], 7624.75)

    def test_un_ticker_en_config_escribe_niveles_json_sin_noche(self):
        os.makedirs(comun.KEMET_DIR)
        with open(os.path.join(comun.KEMET_DIR, "config.json"), "w", encoding="utf-8") as fh:
            json.dump({"mercado": "TSLA", "tipo_cuenta": "propia"}, fh)
        code, out, _ = run(["--ahora", "2026-11-11 16:30", "--offline", YAHOO, "--escribir"])
        self.assertEqual(code, 0)
        with open(os.path.join(comun.KEMET_DIR, "niveles.json"), encoding="utf-8") as fh:
            d = json.load(fh)
        self.assertEqual((d["mercado"], d["instrumento"], d["ibh"], d["ib_minutos"]), ("TSLA", "accion", 392.67, 15))
        for k in ("onh", "onl"):
            self.assertNotIn(k, d)


if __name__ == "__main__":
    unittest.main()
