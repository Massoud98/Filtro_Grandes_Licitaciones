import unittest
from decimal import Decimal

from aplicacion.servicios.conversion_monedas import (
    convertir_a_clp,
    SERIES_MONEDAS,
)


class PruebasConversionMonedas(unittest.TestCase):

    def setUp(self):
        self.tasas = {
            "USD": Decimal("979.88"),
            "CLF": Decimal("41302.33"),
            "UTM": Decimal("72440"),
        }

    def test_series_oficiales(self):
        self.assertEqual(
            SERIES_MONEDAS["USD"],
            "F073.TCO.PRE.Z.D",
        )
        self.assertEqual(
            SERIES_MONEDAS["CLF"],
            "F073.UFF.PRE.Z.D",
        )
        self.assertEqual(
            SERIES_MONEDAS["UTM"],
            "F073.UTR.PRE.Z.M",
        )

    def test_clp_sin_conversion(self):
        self.assertEqual(
            convertir_a_clp(20000000, "CLP", self.tasas),
            Decimal("20000000"),
        )

    def test_conversion_usd(self):
        self.assertEqual(
            convertir_a_clp(30000, "USD", self.tasas),
            Decimal("29396400.00"),
        )

    def test_conversion_uf(self):
        self.assertEqual(
            convertir_a_clp(400, "CLF", self.tasas),
            Decimal("16520932.00"),
        )

    def test_conversion_utm(self):
        self.assertEqual(
            convertir_a_clp(350, "UTM", self.tasas),
            Decimal("25354000"),
        )

    def test_monto_ausente(self):
        for monto in (None, "", "  "):
            with self.subTest(monto=monto):
                self.assertIsNone(
                    convertir_a_clp(monto, "CLP", self.tasas)
                )

    def test_tasa_ausente(self):
        self.assertIsNone(
            convertir_a_clp(100, "USD", {})
        )

    def test_moneda_no_soportada(self):
        with self.assertRaises(ValueError):
            convertir_a_clp(100, "EUR", self.tasas)

    def test_montos_invalidos(self):
        for monto in ("abc", "-1", "NaN", "Infinity"):
            with self.subTest(monto=monto):
                with self.assertRaises(ValueError):
                    convertir_a_clp(monto, "CLP", self.tasas)

    def test_tasas_invalidas(self):
        for tasa in ("abc", "-1", "0", "NaN", "Infinity"):
            with self.subTest(tasa=tasa):
                with self.assertRaises(ValueError):
                    convertir_a_clp(
                        100,
                        "USD",
                        {"USD": tasa},
                    )

    def test_moneda_normalizada(self):
        self.assertEqual(
            convertir_a_clp(100, " usd ", self.tasas),
            Decimal("97988.00"),
        )


if __name__ == "__main__":
    unittest.main()
