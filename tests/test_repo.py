"""Forma del pack: las once carpetas, una copia idéntica de comun.py en cada tool, frontmatter y bloque de seguridad,
sin guiones largos ni emojis en lo que lee el usuario."""
import json
import os
import re
import unittest

from _load import ROOT

SKILLS = ["kemet-desk", "kemet-niveles", "kemet-plan", "kemet-entrada", "kemet-salida", "kemet-maquina",
          "kemet-tamano", "kemet-riesgo", "kemet-alertas", "kemet-diario", "kemet-geometria"]
TOOLS = {"kemet-niveles": "niveles", "kemet-plan": "plan", "kemet-entrada": "entrada", "kemet-salida": "salida", "kemet-maquina": "maquina",
         "kemet-tamano": "tamano", "kemet-riesgo": "riesgo", "kemet-alertas": "alertas", "kemet-diario": "diario"}
SEGURIDAD = "Nada de este pack envía órdenes a ningún bróker ni a ninguna firma de fondeo."
FRASE = "La mayoría de los que hacen day trading pierde dinero"


def leer(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return m.group(1) if m else ""


class Repo(unittest.TestCase):
    def test_las_once_carpetas(self):
        found = sorted(d for d in os.listdir(ROOT) if os.path.isfile(os.path.join(ROOT, d, "SKILL.md")))
        self.assertEqual(found, sorted(SKILLS))

    def test_cada_tool_existe_y_lleva_la_misma_comun(self):
        copias = {folder: leer(os.path.join(ROOT, folder, "comun.py")) for folder in TOOLS}
        maestro = copias["kemet-niveles"]
        for folder, name in TOOLS.items():
            self.assertTrue(os.path.isfile(os.path.join(ROOT, folder, name + ".py")), folder)
            self.assertEqual(copias[folder], maestro, folder + "/comun.py difiere de las demás copias")
        dev = os.path.join(ROOT, "_dev", "comun.py")
        if os.path.exists(dev):
            self.assertEqual(leer(dev), maestro, "_dev/comun.py difiere de las copias")

    def test_frontmatter_y_bloques(self):
        for folder in SKILLS:
            text = leer(os.path.join(ROOT, folder, "SKILL.md"))
            fm = frontmatter(text)
            self.assertIn("name: " + folder, fm, folder)
            self.assertIn("description:", fm, folder)
            self.assertIn("## Seguridad", text, folder)
            self.assertIn(SEGURIDAD, text, folder)
            self.assertIn(FRASE, " ".join(text.split()), folder)
            self.assertNotIn("—", text, folder + ": guion largo")
            self.assertNotRegex(text, r"[\U0001F300-\U0001FAFF☀-➿]", folder + ": emoji")

    def test_sin_guiones_largos_en_las_herramientas(self):
        for folder, name in TOOLS.items():
            self.assertNotIn("—", leer(os.path.join(ROOT, folder, name + ".py")), folder)

    def test_manifiestos(self):
        plugin = json.loads(leer(os.path.join(ROOT, ".claude-plugin", "plugin.json")))
        self.assertEqual(plugin["name"], "kemet-day-trading")
        self.assertEqual(plugin["license"], "MIT")
        market = json.loads(leer(os.path.join(ROOT, ".claude-plugin", "marketplace.json")))
        self.assertEqual(market["plugins"][0]["name"], "kemet-day-trading")
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "LICENSE")))
        self.assertIn("Jake Schincariol", leer(os.path.join(ROOT, "LICENSE")))

    def test_nada_del_sistema_de_produccion(self):
        """Demo open source (Diego, 12/11/2026): ni el IB60 ni su filtro por escala ni las cifras del banco salen del repo privado."""
        prohibido = ("IB" + "60", "escala_" + "ib60", "walk-" + "forward", "paridad exacta", "banco de Kemet")
        for base, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in ("_dev", "__pycache__", "tests", ".git")]
            for f in files:
                if f.endswith((".md", ".py", ".json")):
                    text = leer(os.path.join(base, f))
                    for palabra in prohibido:
                        self.assertNotIn(palabra, text, os.path.join(base, f) + ": " + palabra)

    def test_readme_nombra_las_once(self):
        readme = leer(os.path.join(ROOT, "README.md"))
        for folder in SKILLS:
            self.assertIn("/" + folder, readme, folder)
        self.assertIn("MIT", readme)


if __name__ == "__main__":
    unittest.main()
