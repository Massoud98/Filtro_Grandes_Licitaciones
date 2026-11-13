"""Evaluate tender amounts against a minimum CLP threshold."""

from decimal import Decimal, InvalidOperation

from aplicacion.servicios.conversion_monedas import convertir_a_clp


def evaluar_monto(detalle, monto_minimo_clp, snapshot=None):
    """Evaluate an estimated amount without excluding unknown values."""

    monto = detalle.get("MontoEstimado")
    moneda = str(detalle.get("Moneda") or "").strip().upper()

    resultado = {
        "monto_original": monto,
        "moneda": moneda,
        "monto_clp": None,
        "tasa_clp": None,
        "fecha_tasa": None,
        "estado_monto": "sin_monto",
        "excluir": False,
        "revision_manual": False,
    }

    if monto is None or str(monto).strip() == "":
        return resultado

    try:
        valor = Decimal(str(monto))
    except (InvalidOperation, ValueError):
        resultado["estado_monto"] = "monto_invalido"
        resultado["revision_manual"] = True
        return resultado

    if not valor.is_finite() or valor < 0:
        resultado["estado_monto"] = "monto_invalido"
        resultado["revision_manual"] = True
        return resultado

    tasas = {}

    if moneda != "CLP":
        registro = (snapshot or {}).get("tasas", {}).get(moneda)

        if registro is None:
            resultado["estado_monto"] = "conversion_no_disponible"
            resultado["revision_manual"] = True
            return resultado

        tasas[moneda] = registro["valor_clp"]
        resultado["tasa_clp"] = registro["valor_clp"]
        resultado["fecha_tasa"] = registro["fecha_tasa"]

    try:
        convertido = convertir_a_clp(monto, moneda, tasas)
    except (ValueError, TypeError, KeyError):
        resultado["estado_monto"] = "conversion_no_disponible"
        resultado["revision_manual"] = True
        return resultado

    if convertido is None:
        resultado["estado_monto"] = "conversion_no_disponible"
        resultado["revision_manual"] = True
        return resultado

    resultado["monto_clp"] = str(convertido)

    if convertido < Decimal(str(monto_minimo_clp)):
        resultado["estado_monto"] = "bajo_minimo"
        resultado["excluir"] = True
    else:
        resultado["estado_monto"] = "cumple_minimo"

    return resultado
