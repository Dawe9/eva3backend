"""Utilidades para leer y guardar datos JSON auxiliares de la tienda."""

import json
from pathlib import Path


# La ruta se calcula desde este archivo para funcionar desde cualquier carpeta.
DATA_FILE = Path(__file__).resolve().parent.parent / 'data' / 'data.json'


def load_store_data():
    """Lee los datos locales almacenados en el archivo JSON auxiliar."""

    # Este archivo no es la base de datos relacional que utiliza la API.
    with DATA_FILE.open(encoding='utf-8') as file:
        return json.load(file)


def save_store_data(data):
    """Guarda datos auxiliares en el archivo JSON local del proyecto."""

    # El formato indentado facilita la lectura e inspeccion manual del archivo.
    with DATA_FILE.open('w', encoding='utf-8') as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


