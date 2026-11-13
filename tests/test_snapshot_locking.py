"""Tests for Windows snapshot locking."""

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from aplicacion.servicios.snapshots_monedas import (
    ErrorSnapshotMonedas,
    bloqueo_snapshot,
)


WORKER = """
import sys
import time
from pathlib import Path
from aplicacion.servicios.snapshots_monedas import bloqueo_snapshot

ruta = Path(sys.argv[1])

with bloqueo_snapshot(ruta, espera_maxima=5):
    print("LOCK_ACQUIRED", flush=True)
    time.sleep(30)
"""


class PruebasBloqueoSnapshot(unittest.TestCase):

    def test_lock_can_be_reused(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "test.json"

            with bloqueo_snapshot(ruta):
                pass

            with bloqueo_snapshot(ruta):
                pass

            self.assertTrue(
                ruta.with_suffix(".json.lock").exists()
            )

    def test_lock_timeout(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "test.json"

            with bloqueo_snapshot(ruta):
                with self.assertRaises(ErrorSnapshotMonedas):
                    with bloqueo_snapshot(ruta, espera_maxima=0.3):
                        pass

    def test_multiprocess_crash_recovery(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "test.json"

            proceso = subprocess.Popen(
                [sys.executable, "-c", WORKER, str(ruta)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            try:
                mensaje = proceso.stdout.readline().strip()

                self.assertEqual(mensaje, "LOCK_ACQUIRED")

                with self.assertRaises(ErrorSnapshotMonedas):
                    with bloqueo_snapshot(ruta, espera_maxima=0.3):
                        pass

                self.assertIsNone(proceso.poll())

            finally:
                if proceso.poll() is None:
                    proceso.terminate()

                try:
                    proceso.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proceso.kill()
                    proceso.wait(timeout=5)

                proceso.stdout.close()
                proceso.stderr.close()

            with bloqueo_snapshot(ruta, espera_maxima=5):
                pass


if __name__ == "__main__":
    unittest.main()
