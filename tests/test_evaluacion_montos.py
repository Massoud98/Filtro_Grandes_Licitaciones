"""Tests for estimated tender amount evaluation."""

import unittest

from aplicacion.servicios.evaluacion_montos import evaluar_monto


SNAPSHOT = {
    "tasas": {
        "USD": {
            "valor_clp": "969.8",
            "fecha_tasa": "2026-11-10",
        },
        "CLF": {
            "valor_clp": "41302.33",
            "fecha_tasa": "2026-11-10",
        },
        "UTM": {
            "valor_clp": "72440",
            "fecha_tasa": "2026-11-01",
        },
    }
}

MINIMO = 20000000


class PruebasEvaluacionMontos(unittest.TestCase):

    def evaluar(self, monto, moneda="CLP", snapshot=SNAPSHOT):
        return evaluar_monto(
            {"MontoEstimado": monto, "Moneda": moneda},
            MINIMO,
            snapshot,
        )

    def test_clp_bajo_minimo(self):
        resultado = self.evaluar(19999999)
        self.assertTrue(resultado["excluir"])
        self.assertEqual(resultado["estado_monto"], "bajo_minimo")

    def test_clp_exactamente_minimo(self):
        resultado = self.evaluar(20000000)
        self.assertFalse(resultado["excluir"])
        self.assertEqual(resultado["estado_monto"], "cumple_minimo")

    def test_clp_sobre_minimo(self):
        resultado = self.evaluar(25000000)
        self.assertFalse(resultado["excluir"])

    def test_monto_ausente(self):
        resultado = self.evaluar(None)
        self.assertFalse(resultado["excluir"])
        self.assertFalse(resultado["revision_manual"])
        self.assertEqual(resultado["estado_monto"], "sin_monto")

    def test_monto_vacio(self):
        resultado = self.evaluar("")
        self.assertEqual(resultado["estado_monto"], "sin_monto")

    def test_usd_bajo_minimo(self):
        resultado = self.evaluar(10000, "USD")
        self.assertEqual(resultado["monto_clp"], "9698000.0")
        self.assertTrue(resultado["excluir"])

    def test_usd_sobre_minimo(self):
        resultado = self.evaluar(25000, "USD")
        self.assertEqual(resultado["monto_clp"], "24245000.0")
        self.assertFalse(resultado["excluir"])

    def test_uf_conversion(self):
        resultado = self.evaluar(500, "CLF")
        self.assertEqual(resultado["monto_clp"], "20651165.00")
        self.assertFalse(resultado["excluir"])

    def test_utm_conversion(self):
        resultado = self.evaluar(200, "UTM")
        self.assertEqual(resultado["monto_clp"], "14488000")
        self.assertTrue(resultado["excluir"])

    def test_conversion_unavailable(self):
        resultado = self.evaluar(10000, "USD", None)
        self.assertFalse(resultado["excluir"])
        self.assertTrue(resultado["revision_manual"])
        self.assertEqual(
            resultado["estado_monto"],
            "conversion_no_disponible",
        )

    def test_invalid_amount(self):
        resultado = self.evaluar("not-a-number")
        self.assertFalse(resultado["excluir"])
        self.assertTrue(resultado["revision_manual"])
        self.assertEqual(resultado["estado_monto"], "monto_invalido")

    def test_negative_amount(self):
        resultado = self.evaluar(-10)
        self.assertFalse(resultado["excluir"])
        self.assertTrue(resultado["revision_manual"])


    def test_missing_currency_with_amount(self):
        resultado = evaluar_monto(
            {"MontoEstimado": 25000},
            MINIMO,
            SNAPSHOT,
        )
        self.assertFalse(resultado["excluir"])
        self.assertTrue(resultado["revision_manual"])
        self.assertEqual(
            resultado["estado_monto"],
            "conversion_no_disponible",
        )

    def test_unsupported_currency(self):
        resultado = self.evaluar(25000, "EUR")
        self.assertFalse(resultado["excluir"])
        self.assertTrue(resultado["revision_manual"])
        self.assertEqual(
            resultado["estado_monto"],
            "conversion_no_disponible",
        )

    def test_missing_amount_and_currency(self):
        resultado = evaluar_monto(
            {"MontoEstimado": None},
            MINIMO,
            SNAPSHOT,
        )
        self.assertEqual(resultado["estado_monto"], "sin_monto")
        self.assertFalse(resultado["excluir"])
        self.assertFalse(resultado["revision_manual"])


if __name__ == "__main__":
    unittest.main()
