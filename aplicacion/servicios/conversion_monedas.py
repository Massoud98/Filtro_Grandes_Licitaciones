"""Currency conversion helpers for Mercado Publico filtering."""

from decimal import Decimal, InvalidOperation


MONEDAS_SOPORTADAS = {
    "CLP",
    "USD",
    "CLF",
    "UTM",
}

SERIES_MONEDAS = {
    "USD": "F073.TCO.PRE.Z.D",
    "CLF": "F073.UFF.PRE.Z.D",
    "UTM": "F073.UTR.PRE.Z.M",
}


def convertir_a_clp(monto, moneda, tasas):
    """Convert an estimated amount to CLP using validated rates.

    Returns None when the amount is missing or conversion is unavailable.
    Raises ValueError for invalid amounts, currencies or exchange rates.
    """

    if monto is None or str(monto).strip() == "":
        return None

    moneda = str(moneda or "").strip().upper()

    if moneda not in MONEDAS_SOPORTADAS:
        raise ValueError("Unsupported currency.")

    try:
        valor = Decimal(str(monto))
    except InvalidOperation as exc:
        raise ValueError("Invalid amount.") from exc

    if not valor.is_finite() or valor < 0:
        raise ValueError("Invalid amount.")

    if moneda == "CLP":
        return valor

    tasa_original = tasas.get(moneda)

    if tasa_original is None:
        return None

    try:
        tasa = Decimal(str(tasa_original))
    except InvalidOperation as exc:
        raise ValueError("Invalid exchange rate.") from exc

    if not tasa.is_finite() or tasa <= 0:
        raise ValueError("Invalid exchange rate.")

    return valor * tasa
