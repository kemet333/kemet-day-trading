"""Carga el tool de una carpeta de skill (los nombres llevan guion) sin instalar nada."""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")
YAHOO = os.path.join(FIX, "yahoo")


def load(folder, name):
    carpeta = os.path.join(ROOT, folder)
    if carpeta not in sys.path:
        sys.path.insert(0, carpeta)        # para que `import comun` encuentre la copia de esa carpeta
    path = os.path.join(carpeta, name + ".py")
    spec = importlib.util.spec_from_file_location("kemet_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
