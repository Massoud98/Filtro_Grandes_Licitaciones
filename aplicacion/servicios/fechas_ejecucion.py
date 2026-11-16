"""Select publication dates for scheduled Mercado Publico runs."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


ZONA_HORARIA = ZoneInfo("America/Santiago")


def fechas_publicacion_para_ejecucion(hoy=None):
    """Return publication dates in chronological order.

    Monday covers Friday through Sunday.
    All other days cover the previous calendar day.
    """
    if hoy is None:
        hoy = datetime.now(ZONA_HORARIA).date()

    if not isinstance(hoy, date) or isinstance(hoy, datetime):
        raise TypeError("hoy debe ser un objeto date.")

    if hoy.weekday() == 0:
        return [
            hoy - timedelta(days=3),
            hoy - timedelta(days=2),
            hoy - timedelta(days=1),
        ]

    if hoy.weekday() >= 5:
        return []

    return [hoy - timedelta(days=1)]