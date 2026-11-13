"""Tests for preliminary tender filter configuration."""

import json
import tempfile
import unittest
from pathlib import Path

from aplicacion.servicios.configuracion_filtros import (
    ErrorConfiguracionFiltros,
    cargar_configuracion,
)


CONFIGURACION_VALIDA = {
    "version": 1,
    "excluir_tipos": ["O1"],
    "filtro_l1": {
        "activo": True,
        "categorias_permitidas": ["alimentos", "vestimenta"],
        "clasificacion_ambigua": "revision_manual",
    },
    "dias_minimos_para_cierre": 7,
    "monto_minimo_clp": 20000000,
}


class PruebasConfiguracionFiltros(unittest.TestCase):

    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        self.ruta = Path(self.temporal.name) / "filtros.json"

    def guardar(self, datos):
        self.ruta.write_text(
            json.dumps(datos),
            encoding="utf-8",
        )

    def test_configuracion_valida(self):
        self.guardar(CONFIGURACION_VALIDA)
        resultado = cargar_configuracion(self.ruta)
        self.assertEqual(resultado["monto_minimo_clp"], 20000000)

    def test_archivo_inexistente(self):
        with self.assertRaises(ErrorConfiguracionFiltros):
            cargar_configuracion(self.ruta)

    def test_json_invalido(self):
        self.ruta.write_text("{invalid", encoding="utf-8")
        with self.assertRaises(ErrorConfiguracionFiltros):
            cargar_configuracion(self.ruta)

    def test_monto_incorrecto(self):
        datos = json.loads(json.dumps(CONFIGURACION_VALIDA))
        datos["monto_minimo_clp"] = 10000000
        self.guardar(datos)

        with self.assertRaises(ErrorConfiguracionFiltros):
            cargar_configuracion(self.ruta)

    def test_monto_booleano(self):
        datos = json.loads(json.dumps(CONFIGURACION_VALIDA))
        datos["monto_minimo_clp"] = True
        self.guardar(datos)

        with self.assertRaises(ErrorConfiguracionFiltros):
            cargar_configuracion(self.ruta)

    def test_reglas_l1_modificadas(self):
        datos = json.loads(json.dumps(CONFIGURACION_VALIDA))
        datos["filtro_l1"]["categorias_permitidas"] = ["servicios"]
        self.guardar(datos)

        with self.assertRaises(ErrorConfiguracionFiltros):
            cargar_configuracion(self.ruta)

    def test_dias_modificados(self):
        datos = json.loads(json.dumps(CONFIGURACION_VALIDA))
        datos["dias_minimos_para_cierre"] = 3
        self.guardar(datos)

        with self.assertRaises(ErrorConfiguracionFiltros):
            cargar_configuracion(self.ruta)


if __name__ == "__main__":
    unittest.main()
