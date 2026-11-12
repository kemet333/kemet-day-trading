"""kemet-plan con un config de ejemplo escrito en un directorio temporal (KEMET_DIR), el fixture real de NQ y sin red."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, ROOT, YAHOO, FIX

plan = load("kemet-plan", "plan")
comun = plan.comun

# Apex 50K EOD PA: drawdown 2.500 $, sin límite diario, 10 micros, hora límite 16:59 NY. Un cuarto = 625 $, entre 3 = 208,33 $.
CONFIG = {"mercado": "NQ", "firma": "apex", "cuenta": "eod-pa-50", "cuenta_nombre": "Apex 50K EOD · PA", "fase": "financiada",
          "drawdown": 2500, "drawdown_tipo": "eod_trailing", "limite_diario_firma": None, "max_micro": 10, "max_mini": 1,
          "hora_limite": "16:59", "hora_limite_tz": "America/New_York", "perdida_max_dia": 625, "fallos_y_paras": 3, "semaforo": "verde",
          "sin_entradas_antes": "09:45", "sin_entradas_despues": "14:00", "plano_a": "15:55", "zona_usuario": "Europe/Madrid", "papel": True}
CALENDARIO = os.path.join(FIX, "kemet-plan", "ff_calendar_thisweek.json")   # Forex Factory, semana del 9 al 13 de noviembre de 2026, real
AGENDA = {"fecha": "2026-11-11", "datos": [{"hora": "08:30", "nombre": "IPC", "fuerte": True},
                                            {"hora": "10:30", "nombre": "Inventarios EIA", "fuerte": False, "mercados": ["CL"]},
                                            {"hora": "14:00", "nombre": "Subasta del Tesoro a 10 años", "fuerte": False}]}


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = plan.main(argv)
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    config = CONFIG
    agenda = None

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = os.path.join(self.tmp, "kemet")
        os.makedirs(self.dir)
        self.antes = comun.KEMET_DIR
        comun.KEMET_DIR = self.dir
        if self.config:
            self.escribe("config.json", self.config)
        if self.agenda:
            self.escribe("agenda.json", self.agenda)

    def tearDown(self):
        comun.KEMET_DIR = self.antes
        shutil.rmtree(self.tmp)

    def escribe(self, nombre, doc):
        with open(os.path.join(self.dir, nombre), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)

    def doc(self, *extra, ahora="2026-11-11 08:00"):
        code, out, _ = run(["plan", "--ahora", ahora, "--offline", YAHOO, "--json"] + list(extra))
        self.assertEqual(code, 0)
        return json.loads(out)

    def texto(self, *extra, ahora="2026-11-11 08:00"):
        code, out, _ = run(["plan", "--ahora", ahora, "--offline", YAHOO] + list(extra))
        self.assertEqual(code, 0)
        return out


class SinAgenda(Base):
    def test_avisa_y_deja_la_apertura_y_el_plano(self):
        d = self.doc("--stop", "40")
        self.assertTrue(any("no hay kemet/agenda.json" in a for a in d["avisos"]))
        self.assertEqual([(v["desde"], v["hasta"]) for v in d["ventanas"]], [("09:30", "09:45"), ("15:50", "15:55")])
        self.assertEqual(d["semaforo"], "verde")

    def test_tamano_verde_con_stop_de_40(self):
        d = self.doc("--stop", "40")
        t = d["tamano"]
        self.assertEqual((t["perdida_max_dia"], t["riesgo_por_operacion"], t["riesgo_usd_micro"]), (625, 208.33, 80.0))
        self.assertEqual((t["contratos"], t["micro"]), (2, "MNQ"))   # 208,33 / (40 × 2) = 2,6 → 2
        self.assertIn("Mi tamaño: 2 MNQ por operación con stop de 40 pts", self.texto("--stop", "40"))

    def test_tope_de_micros_de_la_cuenta(self):
        t = self.doc("--stop", "2")["tamano"]
        self.assertEqual((t["contratos_sin_tope"], t["contratos"]) , (52, 10))
        self.assertIn("tope de la cuenta: 10 micros", self.texto("--stop", "2"))

    def test_sin_stop_hay_perdida_del_dia_pero_no_contratos(self):
        d = self.doc()
        self.assertEqual(d["tamano"]["perdida_max_dia"], 625)
        self.assertNotIn("contratos", d["tamano"])
        self.assertIn("dime tu stop", d["nota_tamano"])

    def test_semaforo_ambar_forzado_reduce_a_la_mitad(self):
        t = self.doc("--stop", "40", "--semaforo", "ambar")["tamano"]
        self.assertEqual((t["perdida_max_dia"], t["riesgo_por_operacion"], t["contratos"]), (312, 104.0, 1))
        self.assertIn("la mitad por ámbar", self.texto("--stop", "40", "--semaforo", "ambar"))

    def test_niveles_y_horas_en_madrid(self):
        d = self.doc()
        self.assertEqual((d["niveles"]["pdh"], d["niveles"]["pdl"], d["niveles"]["pdc"]), (28090.0, 27516.0, 27835.25))
        self.assertEqual((d["niveles"]["onh"], d["niveles"]["onl"]), (28397.5, 27847.75))   # la noche hasta las 08:00
        self.assertNotIn("ibh", d["niveles"])
        out = self.texto()
        self.assertIn("14:00 Madrid / 08:00 NY", out)
        self.assertIn("09:30–09:45 NY (15:30–15:45 Madrid)", out)
        self.assertIn("Hora límite de mi firma: 16:59 NY (22:59 Madrid) · plano a las 15:55 NY (21:55 Madrid)", out)
        self.assertEqual(d["hora_limite_ny"], "16:59")


class ConAgenda(Base):
    agenda = AGENDA

    def test_ventanas_correctas_para_nq(self):
        d = self.doc("--stop", "40")
        self.assertEqual([(v["desde"], v["hasta"]) for v in d["ventanas"]],
                         [("08:10", "08:50"), ("09:30", "09:45"), ("13:50", "14:10"), ("15:50", "15:55")])   # la EIA es solo de CL
        self.assertEqual(d["ventanas"][0]["motivo"], "IPC a las 08:30, dato fuerte")
        self.assertFalse(d["avisos"])

    def test_la_eia_entra_en_cl(self):
        d = self.doc("--mercado", "CL")
        self.assertIn(("10:20", "10:40"), [(v["desde"], v["hasta"]) for v in d["ventanas"]])
        self.assertEqual(d["plano_a"], "15:55")      # el plano_a del config manda aunque el contrato sea CL

    def test_dato_fuerte_pone_ambar_y_reduce_el_tamano(self):
        d = self.doc("--stop", "40")
        self.assertEqual(d["semaforo"], "ambar")
        self.assertIn("IPC a las 08:30", d["razones"][0])
        self.assertEqual((d["tamano"]["perdida_max_dia"], d["tamano"]["contratos"]), (312, 1))
        self.assertIn("Semáforo: ámbar porque hay un dato fuerte en la sesión: IPC a las 08:30", self.texto("--stop", "40"))

    def test_siguiente_dentro_de_una_ventana(self):
        d = self.doc(ahora="2026-11-11 08:20")
        self.assertIn("ventana sin operar (IPC a las 08:30, dato fuerte) hasta las 08:50 NY", d["siguiente"])

    def test_agenda_de_otro_dia_no_vale(self):
        d = self.doc(ahora="2026-11-12 08:00")
        self.assertTrue(any("es del 2026-11-11, no del 2026-11-12" in a for a in d["avisos"]))
        self.assertEqual(len(d["ventanas"]), 2)

    def test_escribir_guarda_plan_sesion_json(self):
        code, out, _ = run(["plan", "--ahora", "2026-11-11 08:00", "--offline", YAHOO, "--stop", "40", "--escribir"])
        self.assertEqual(code, 0)
        with open(os.path.join(self.dir, "plan-sesion.json"), encoding="utf-8") as fh:
            d = json.load(fh)
        for k in ("generado", "mercado", "fecha", "semaforo", "razones", "ventanas", "niveles", "tamano", "hora_limite", "plano_a", "siguiente"):
            self.assertIn(k, d)
        for k in ("contratos", "micro", "stop_pts", "perdida_max_dia", "riesgo_por_operacion"):
            self.assertIn(k, d["tamano"])
        self.assertEqual(d["tamano"]["contratos"], 1)


class SinConfig(Base):
    config = None

    def test_sin_config_no_hay_tamano_y_lo_dice(self):
        d = self.doc()
        self.assertTrue(any("sin kemet/config.json" in a for a in d["avisos"]))
        self.assertIsNone(d["tamano"])
        self.assertIn("no hay bloque de tamaño", d["nota_tamano"])
        self.assertEqual(d["mercado"], "NQ")
        self.assertIsNone(d["hora_limite"])

    def test_con_stop_pide_los_limites(self):
        with self.assertRaises(comun.KemetError):
            run(["plan", "--ahora", "2026-11-11 08:00", "--offline", YAHOO, "--stop", "40"])

    def test_con_stop_y_limites_a_mano(self):
        t = self.doc("--mercado", "ES", "--stop", "6", "--drawdown", "2000", "--diario", "1000")["tamano"]
        self.assertEqual((t["perdida_max_dia"], t["contratos"], t["micro"]), (500, 5, "MES"))   # 166,67 / (6 × 5) = 5,5 → 5
        self.assertIsNone(t["max_micro"])


class HoraLimite(Base):
    config = dict(CONFIG, firma="topstep", hora_limite="15:10", hora_limite_tz="America/Chicago", limite_diario_firma=1000, drawdown=2000)

    def test_chicago_a_nueva_york_y_el_menor_de_los_limites(self):
        d = self.doc("--stop", "40")
        self.assertEqual(d["hora_limite_ny"], "16:10")
        self.assertIn("16:10 NY (22:10 Madrid), 15:10 en America/Chicago", self.texto())
        self.assertEqual(d["tamano"]["perdida_max_dia"], 500)        # min(1.000, 2.000/4)

    def test_plano_despues_de_la_hora_limite_avisa(self):
        self.escribe("config.json", dict(self.config, plano_a="16:30"))
        d = self.doc()
        self.assertTrue(any("adelántalo" in a for a in d["avisos"]))


class ZonaNoMadrid(Base):
    config = dict(CONFIG, zona_usuario="America/Bogota")

    def test_solo_ny_y_lo_dice(self):
        out = self.texto()
        self.assertIn("tu zona es America/Bogota y solo sé convertir a Madrid", out)
        self.assertNotIn("Madrid)", out)


class Agenda(Base):
    def test_agenda_desde_flags(self):
        code, out, _ = run(["agenda", "--fecha", "2026-11-11", "--dato", "08:30 IPC fuerte", "--dato", "10:30 Inventarios EIA CL", "--dato", "14:00 FOMC fuerte"])
        self.assertEqual(code, 0)
        with open(os.path.join(self.dir, "agenda.json"), encoding="utf-8") as fh:
            d = json.load(fh)
        self.assertEqual(d["fecha"], "2026-11-11")
        self.assertEqual(d["datos"][0], {"hora": "08:30", "nombre": "IPC", "fuerte": True})
        self.assertEqual(d["datos"][1], {"hora": "10:30", "nombre": "Inventarios EIA", "fuerte": False, "mercados": ["CL"]})
        self.assertEqual(d["datos"][2]["nombre"], "FOMC")
        self.assertIn("ventana de 20 min", out)
        d2 = self.doc("--stop", "40")
        self.assertEqual(d2["ventanas"][-2]["desde"], "13:40")      # FOMC fuerte: ±20

    def test_auto_desde_el_calendario_guardado(self):
        code, out, _ = run(["agenda", "--auto", "--fecha", "2026-11-10", "--offline", CALENDARIO])
        self.assertEqual(code, 0)
        with open(os.path.join(self.dir, "agenda.json"), encoding="utf-8") as fh:
            d = json.load(fh)
        self.assertEqual(d["fecha"], "2026-11-10")
        ipc = [x for x in d["datos"] if x["hora"] == "08:30"]
        self.assertEqual(len(ipc), 1)                                     # Core CPI y CPI a la misma hora, un solo dato
        self.assertEqual((ipc[0]["nombre"], ipc[0]["fuerte"]), ("IPC subyacente y IPC", True))
        self.assertIn({"hora": "04:00", "nombre": "FOMC Member Waller Speaks", "fuerte": False}, d["datos"])   # Medium: no fuerte, sin traducir
        self.assertIn("08:30  IPC subyacente y IPC · fuerte (ventana de 20 min)", out)
        # el plan de ese día abre la ventana 08:10–08:50 y pone ámbar
        p = self.doc("--stop", "40", ahora="2026-11-10 08:00")
        self.assertEqual(p["ventanas"][1], {"desde": "08:10", "hasta": "08:50", "motivo": "IPC subyacente y IPC a las 08:30, dato fuerte"})
        self.assertEqual((p["semaforo"], p["tamano"]["contratos"]), ("ambar", 1))

    def test_auto_festivo_y_dia_sin_datos(self):
        code, out, _ = run(["agenda", "--auto", "--fecha", "2026-11-11", "--offline", CALENDARIO])
        self.assertEqual(code, 0)
        self.assertIn("sin datos", out)
        self.assertIn("festivo bancario: en el calendario, sin ventana", out)
        with open(os.path.join(self.dir, "agenda.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["datos"], [])

    def test_auto_low_fuera_y_medium_sin_fuerte(self):
        code, _, _ = run(["agenda", "--auto", "--fecha", "2026-11-12", "--offline", CALENDARIO])
        self.assertEqual(code, 0)
        with open(os.path.join(self.dir, "agenda.json"), encoding="utf-8") as fh:
            d = json.load(fh)
        self.assertEqual(d["datos"], [{"hora": "08:30", "nombre": "peticiones de desempleo", "fuerte": False}])

    def test_auto_sin_red_devuelve_1_y_no_toca_la_agenda(self):
        self.escribe("agenda.json", AGENDA)
        antes = comun._open_url
        def rota(url, timeout=20):
            raise plan.urllib.error.URLError("sin dns")
        comun._open_url = rota
        try:
            code, out, err = run(["agenda", "--auto", "--fecha", "2026-11-12"])
        finally:
            comun._open_url = antes
        self.assertEqual(code, 1)
        self.assertIn("no se pudo bajar el calendario", err)
        with open(os.path.join(self.dir, "agenda.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["fecha"], "2026-11-11")       # la agenda anterior sigue ahí
        self.assertEqual(len(self.doc(ahora="2026-11-11 08:00")["ventanas"]), 4)   # y el plan funciona con ella

    def test_traducciones(self):
        self.assertEqual(plan.traducir("Core CPI m/m"), ("IPC subyacente", None))
        self.assertEqual(plan.traducir("Crude Oil Inventories"), ("inventarios EIA", ["CL"]))
        self.assertEqual(plan.traducir("Non-Farm Employment Change"), ("nóminas no agrícolas", None))
        self.assertEqual(plan.traducir("Advance GDP q/q"), ("PIB adelantado", None))
        self.assertEqual(plan.traducir("Empire State Manufacturing Index"), ("Empire State Manufacturing Index", None))

    def test_dato_sin_hora_es_error(self):
        with self.assertRaises(comun.KemetError):
            run(["agenda", "--fecha", "2026-11-11", "--dato", "IPC fuerte"])

    def test_el_ejemplo_del_pack_es_valido(self):
        with open(os.path.join(ROOT, "kemet-plan", "agenda.example.json"), encoding="utf-8") as fh:
            ej = json.load(fh)
        self.escribe("agenda.json", ej)
        d = self.doc("--stop", "40")
        self.assertEqual(d["semaforo"], "ambar")
        self.assertEqual(d["ventanas"][0], {"desde": "08:10", "hasta": "08:50", "motivo": "IPC a las 08:30, dato fuerte"})


# Cuenta propia de 5.000 $, 50 $ por operación y 150 $ al día (tamano.py config --propia --mercado TSLA). TSLA el 11/11/2026 en el fixture
# real: ayer 370,43 a 380 con cierre 379,80; apertura de 15 min 386,35 a 392,67.
CONFIG_PROPIA = {"mercado": "TSLA", "tipo_cuenta": "propia", "firma": None, "cuenta": "propia", "cuenta_nombre": "Cuenta propia · 5.000 $", "presupuesto": 5000,
                 "efectivo_pct": 10, "max_posicion_pct": 75, "max_orden_usd": 4000, "min_orden_usd": 5, "perdida_max_dia": 150, "riesgo_por_operacion": 50,
                 "fallos_y_paras": 3, "semaforo": "verde", "max_micro": None, "hora_limite": None, "hora_limite_tz": None, "sin_entradas_antes": "09:45",
                 "sin_entradas_despues": "15:00", "plano_a": "15:55", "zona_usuario": "Europe/Madrid", "papel": True, "permitir_cortos": False,
                 "permitir_margen": False, "permitir_opciones": False, "bloqueados": [], "sec_user_agent": "Nombre correo@ejemplo.com"}


class CuentaPropiaAcciones(Base):
    config = CONFIG_PROPIA

    def test_plan_de_tsla_sin_hora_limite_y_en_acciones(self):
        d = self.doc("--stop", "3.57")
        self.assertEqual((d["mercado"], d["instrumento"], d["tipo_cuenta"], d["hora_limite"], d["hora_limite_ny"]), ("TSLA", "accion", "propia", None, None))
        self.assertEqual([(v["desde"], v["hasta"]) for v in d["ventanas"]], [("09:30", "09:45"), ("15:50", "15:55")])
        self.assertEqual((d["sin_entradas_antes"], d["sin_entradas_despues"], d["plano_a"]), ("09:45", "15:00", "15:55"))
        t = d["tamano"]
        self.assertEqual((t["instrumento"], t["perdida_max_dia"], t["riesgo_por_operacion"], t["stop_pts"]), ("accion", 150, 50.0, 3.57))
        self.assertEqual((t["acciones"], t["acciones_sin_tope"], t["manda"], t["precio_referencia"]), (9, 14, "posición máxima", 379.8))
        self.assertEqual([(l["nombre"], l["acciones"]) for l in t["limites"]], [("riesgo por operación", 14), ("posición máxima", 9), ("orden máxima", 10), ("efectivo", 11)])
        self.assertEqual((d["niveles"]["pdh"], d["niveles"]["pdl"], d["niveles"]["pdc"]), (380.0, 370.43, 379.8))
        self.assertNotIn("onh", d["niveles"])                 # una acción no tiene noche
        out = self.texto("--stop", "3.57")
        self.assertIn("Mi tamaño: 9 acciones de TSLA por operación con stop de 3,57 $ por acción (manda posición máxima)", out)
        self.assertIn("Hora límite: ninguna, es tu cuenta · plano a las 15:55 NY (21:55 Madrid)", out)
        self.assertIn("Sin sesión nocturna", out)
        self.assertIn("Mejor franja   09:45–11:30", out)
        self.assertNotIn("Gamma", out)

    def test_sin_niveles_el_tamano_solo_por_el_riesgo_y_con_agenda_ambar(self):
        d = self.doc("--stop", "3.57", "--sin-niveles")
        self.assertEqual((d["tamano"]["acciones"], d["tamano"]["manda"], d["tamano"]["precio_referencia"]), (14, "riesgo por operación", None))
        self.assertIn("sin precio de referencia", self.texto("--stop", "3.57", "--sin-niveles"))
        self.escribe("agenda.json", AGENDA)
        d = self.doc("--stop", "3.57")
        self.assertEqual(d["semaforo"], "ambar")
        self.assertEqual((d["tamano"]["perdida_max_dia"], d["tamano"]["riesgo_por_operacion"], d["tamano"]["acciones"], d["tamano"]["manda"]), (75, 25.0, 7, "riesgo por operación"))
        self.assertEqual([(v["desde"], v["hasta"]) for v in d["ventanas"]], [("08:10", "08:50"), ("09:30", "09:45"), ("13:50", "14:10"), ("15:50", "15:55")])   # la EIA es solo de CL
        d = self.doc()
        self.assertNotIn("acciones", d["tamano"])
        self.assertIn("en dólares por acción", d["nota_tamano"])

    def test_a_las_diez_y_media_la_apertura_y_lo_siguiente(self):
        d = self.doc(ahora="2026-11-11 10:35")
        self.assertEqual((d["niveles"]["orh"], d["niveles"]["orl"]), (392.67, 386.35))
        self.assertNotIn("ibh", d["niveles"])
        self.assertTrue(d["siguiente"].startswith("Operaciones del plan hasta las 15:00 NY"))
        d = self.doc(ahora="2026-11-11 08:00")
        self.assertTrue(d["siguiente"].startswith("Pon el stop"))      # la NYSE aún no abre, pero el plan se escribe antes
        d = self.doc(ahora="2026-11-26 08:00")                             # Thanksgiving
        self.assertIn("Mercado cerrado (Thanksgiving)", d["siguiente"])

    def test_un_futuro_con_la_cuenta_propia(self):
        d = self.doc("--mercado", "NQ", "--stop", "18")
        self.assertEqual((d["tamano"]["contratos"], d["tamano"]["micro"], d["tamano"]["perdida_max_dia"]), (1, "MNQ", 150))
        self.assertIn("Mi tamaño: 1 MNQ por operación con stop de 18 pts", self.texto("--mercado", "NQ", "--stop", "18"))
        self.assertIn("Hora límite: ninguna, es tu cuenta", self.texto("--mercado", "NQ"))
        self.assertIn("onh", d["niveles"])


class AccionConCuentaDeFirma(Base):
    def test_avisa_y_no_da_tamano_en_acciones(self):
        d = self.doc("--mercado", "TSLA", "--stop", "3.57")
        self.assertTrue(any("cuenta propia" in a for a in d["avisos"]))
        self.assertEqual(d["hora_limite"], "16:59")
        self.assertIsNone(d["tamano"])
        self.assertIn("config --propia", d["nota_tamano"])


class Proceso(unittest.TestCase):
    def test_kemet_dir_por_entorno_en_un_proceso_aparte(self):
        tmp = tempfile.mkdtemp()
        try:
            d = os.path.join(tmp, "kemet")
            os.makedirs(d)
            with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as fh:
                json.dump(CONFIG, fh)
            env = dict(os.environ, KEMET_DIR=d)
            r = subprocess.run([sys.executable, os.path.join(ROOT, "kemet-plan", "plan.py"), "--stop", "40", "--ahora", "2026-11-11 08:00",
                                "--offline", YAHOO, "--escribir"], capture_output=True, text=True, env=env, cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Mi tamaño: 2 MNQ por operación con stop de 40 pts", r.stdout)
            self.assertTrue(os.path.exists(os.path.join(d, "plan-sesion.json")))
            r = subprocess.run([sys.executable, os.path.join(ROOT, "kemet-niveles", "niveles.py"), "--ahora", "2026-11-11 16:30", "--offline", YAHOO],
                               capture_output=True, text=True, env=env, cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Balance inicial 1 h                máximo 28.426   mínimo 28.199   ancho 227 (12 velas)", r.stdout)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
