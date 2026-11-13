"""Daily exchange-rate snapshots for reproducible tender filtering."""

import json
import msvcrt
import os
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from aplicacion.servicios.banco_central import consultar_todas_las_tasas
from aplicacion.servicios.conversion_monedas import SERIES_MONEDAS
from aplicacion.servicios.mercado_publico import guardar_json_atomico


CARPETA_TASAS = (
    Path(
        os.environ.get(
            "FILTRO_LICITACIONES_ROOT",
            Path(__file__).resolve().parents[2],
        )
    ).resolve()
    / "datos"
    / "tipos_cambio"
)
VERSION_SNAPSHOT = 1


class ErrorSnapshotMonedas(Exception):
    """Invalid or unavailable daily exchange-rate snapshot."""


def validar_snapshot(datos, fecha_revision):
    """Validate snapshot contents before allowing reuse."""

    if not isinstance(datos, dict):
        raise ErrorSnapshotMonedas("Invalid snapshot structure.")

    if datos.get("version") != VERSION_SNAPSHOT:
        raise ErrorSnapshotMonedas("Unsupported snapshot version.")

    if datos.get("fecha_revision") != fecha_revision.isoformat():
        raise ErrorSnapshotMonedas("Snapshot review date mismatch.")

    tasas = datos.get("tasas")

    if not isinstance(tasas, dict):
        raise ErrorSnapshotMonedas("Missing exchange-rate data.")

    if set(tasas) != set(SERIES_MONEDAS):
        raise ErrorSnapshotMonedas("Incomplete exchange-rate snapshot.")

    for moneda, serie_esperada in SERIES_MONEDAS.items():
        registro = tasas[moneda]

        if not isinstance(registro, dict):
            raise ErrorSnapshotMonedas("Invalid currency record.")

        if registro.get("moneda") != moneda:
            raise ErrorSnapshotMonedas("Currency mismatch.")

        if registro.get("serie") != serie_esperada:
            raise ErrorSnapshotMonedas("Series mismatch.")

        try:
            fecha_tasa = date.fromisoformat(registro["fecha_tasa"])
            valor = Decimal(str(registro["valor_clp"]))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            raise ErrorSnapshotMonedas(
                "Invalid exchange-rate observation."
            ) from None

        if fecha_tasa > fecha_revision:
            raise ErrorSnapshotMonedas("Future exchange-rate observation.")

        if not valor.is_finite() or valor <= 0:
            raise ErrorSnapshotMonedas("Invalid exchange-rate value.")

    return datos


@contextmanager
def bloqueo_snapshot(ruta, espera_maxima=90):
    """Prevent concurrent snapshot creation with a Windows OS lock."""

    ruta.parent.mkdir(parents=True, exist_ok=True)
    bloqueo = ruta.with_suffix(ruta.suffix + ".lock")
    inicio = time.monotonic()

    with open(bloqueo, "a+b") as archivo:
        adquirido = False

        while not adquirido:
            try:
                archivo.seek(0)
                msvcrt.locking(
                    archivo.fileno(),
                    msvcrt.LK_NBLCK,
                    1,
                )
                adquirido = True
            except OSError as exc:
                if getattr(exc, "winerror", None) not in (33, 36) and (
                    not isinstance(exc, PermissionError)
                ):
                    raise

                if time.monotonic() - inicio >= espera_maxima:
                    raise ErrorSnapshotMonedas(
                        "Timed out waiting for snapshot lock."
                    ) from None

                time.sleep(0.2)

        try:
            yield
        finally:
            archivo.seek(0)
            msvcrt.locking(
                archivo.fileno(),
                msvcrt.LK_UNLCK,
                1,
            )

def obtener_snapshot(fecha_revision, sesion=None):
    """Load a valid daily snapshot or retrieve and save official rates."""

    if type(fecha_revision) is not date:
        raise TypeError("Review date must be a date.")

    ruta = CARPETA_TASAS / (fecha_revision.isoformat() + ".json")

    with bloqueo_snapshot(ruta):
        if ruta.exists():
            try:
                datos = json.loads(ruta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise ErrorSnapshotMonedas(
                    "Existing snapshot cannot be read."
                ) from None

            return validar_snapshot(datos, fecha_revision)

        tasas = consultar_todas_las_tasas(
            fecha_revision,
            sesion=sesion,
        )

        datos = {
            "version": VERSION_SNAPSHOT,
            "fecha_revision": fecha_revision.isoformat(),
            "fecha_consulta_utc": datetime.now(timezone.utc).isoformat(),
            "fuente": "Banco Central de Chile - BDE API",
            "tasas": tasas,
        }

        validar_snapshot(datos, fecha_revision)
        guardar_json_atomico(ruta, datos)

        return datos
