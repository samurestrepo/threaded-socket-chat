"""Pruebas del chat: levantan server.py en un puerto libre y conectan clientes por socket.

Ejecutar desde la raíz del proyecto:
    python -m unittest -v
"""

import os
import re
import socket
import struct
import subprocess
import sys
import time
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVIDOR = os.path.join(RAIZ, "server.py")
TIEMPO = 3.0  # segundos máximos para esperar una línea


def puerto_libre():
    """Pide al sistema operativo un puerto TCP que no esté en uso."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ClientePrueba:
    """Cliente mínimo que lee líneas delimitadas por '\\n'."""

    def __init__(self, puerto):
        self.sock = socket.create_connection(("127.0.0.1", puerto), timeout=TIEMPO)
        self.buffer = b""

    def enviar(self, texto):
        self.sock.sendall((texto + "\n").encode("utf-8"))

    def linea(self):
        while b"\n" not in self.buffer:
            datos = self.sock.recv(4096)
            if not datos:
                raise ConnectionError("el servidor cerró la conexión")
            self.buffer += datos
        linea, self.buffer = self.buffer.split(b"\n", 1)
        return linea.decode("utf-8")

    def esperar(self, patron):
        """Lee líneas hasta encontrar una que cumpla el regex; la devuelve."""
        limite = time.time() + TIEMPO
        while time.time() < limite:
            linea = self.linea()
            if re.search(patron, linea):
                return linea
        raise AssertionError(f"no llegó una línea con {patron!r}")

    def registrar(self, nombre):
        self.esperar("nombre")
        self.enviar(nombre)
        self.esperar(f"Hola {re.escape(nombre)}")

    def cerrar_abruptamente(self):
        """Cierra con SO_LINGER=0: el sistema envía RST (ConnectionResetError)."""
        formato = "HH" if os.name == "nt" else "ii"
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack(formato, 1, 0))
        self.sock.close()

    def cerrar(self):
        self.sock.close()


class TestChat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.puerto = puerto_libre()
        cls.servidor = subprocess.Popen(
            [sys.executable, SERVIDOR, "--host", "127.0.0.1", "--port", str(cls.puerto)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        limite = time.time() + 10
        while True:  # esperar a que el servidor acepte conexiones
            try:
                socket.create_connection(("127.0.0.1", cls.puerto), timeout=1).close()
                break
            except OSError:
                if time.time() > limite:
                    cls.servidor.kill()
                    raise
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.servidor.kill()
        cls.servidor.wait()

    def setUp(self):
        self.abiertos = []

    def tearDown(self):
        for cliente in self.abiertos:
            cliente.cerrar()

    def nuevo(self, nombre=None):
        cliente = ClientePrueba(self.puerto)
        self.abiertos.append(cliente)
        if nombre:
            cliente.registrar(nombre)
        return cliente

    def test_pide_nombre(self):
        cliente = self.nuevo()
        self.assertIn("nombre", cliente.linea())

    def test_rechaza_nombre_vacio(self):
        cliente = self.nuevo()
        cliente.esperar("nombre")
        cliente.enviar("   ")
        cliente.esperar("inválido")

    def test_rechaza_nombre_repetido(self):
        self.nuevo("ana")
        segundo = self.nuevo()
        segundo.esperar("nombre")
        segundo.enviar("ana")
        segundo.esperar("ya está en uso")
        segundo.enviar("ana2")
        segundo.esperar("Hola ana2")

    def test_broadcast_llega_a_los_tres(self):
        a, b, c = self.nuevo("b1"), self.nuevo("b2"), self.nuevo("b3")
        a.esperar(r"\*\*\* b3 se unió al chat \*\*\*")
        b.enviar("hola a todos ñandú")
        patron = r"^\[\d\d:\d\d:\d\d\] b2: hola a todos ñandú$"
        for cliente in (a, b, c):  # remitente incluido
            cliente.esperar(patron)

    def test_usuarios(self):
        a, b, c = self.nuevo("u1"), self.nuevo("u2"), self.nuevo("u3")
        a.enviar("/usuarios")
        lista = a.esperar("^Conectados")
        for nombre in ("u1", "u2", "u3"):
            self.assertIn(nombre, lista)
        # La lista solo la recibe quien la pidió: b ve el siguiente mensaje, no la lista.
        a.enviar("fin")
        siguiente = b.esperar(r"u1: fin$|^Conectados")
        self.assertIn("u1: fin", siguiente)

    def test_aviso_de_salida(self):
        a, b = self.nuevo("s1"), self.nuevo("s2")
        b.enviar("/salir")
        b.esperar("Hasta luego")
        a.esperar(r"^\*\*\* s2 salió del chat \*\*\*$")

    def test_desconexion_abrupta_no_tumba_el_servidor(self):
        a, b = self.nuevo("d1"), self.nuevo("d2")
        self.abiertos.remove(b)
        b.cerrar_abruptamente()
        a.esperar(r"\*\*\* d2 salió del chat \*\*\*")
        self.assertIsNone(self.servidor.poll(), "el servidor terminó")
        # El servidor sigue atendiendo: entra alguien nuevo y el chat funciona.
        c = self.nuevo("d3")
        c.enviar("sigo aquí")
        a.esperar("d3: sigo aquí")


if __name__ == "__main__":
    unittest.main(verbosity=2)
