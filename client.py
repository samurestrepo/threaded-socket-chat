"""Cliente de chat por consola.

Uso:
    python client.py [--host 127.0.0.1] [--port 5000]

Se usan dos hilos porque recv() e input() son bloqueantes: si un solo hilo
esperara lo que escribe el usuario con input(), no podría mostrar los
mensajes que llegan de los demás mientras tanto (y al revés). Por eso:
  - un hilo receptor (daemon) se queda en recv() e imprime lo que llega;
  - el hilo principal se queda en input() y envía lo que se escribe.
"""

import argparse
import os
import socket
import sys
import threading

CODIFICACION = "utf-8"


def recibir(sock):
    """Hilo receptor: imprime cada línea que envía el servidor.

    Los mensajes vienen delimitados por '\\n'; se acumulan en un buffer hasta
    tener líneas completas porque TCP puede partir o pegar mensajes.
    """
    buffer = b""
    try:
        while True:
            datos = sock.recv(4096)
            if not datos:
                break
            buffer += datos
            while b"\n" in buffer:
                linea, buffer = buffer.split(b"\n", 1)
                print(linea.decode(CODIFICACION, errors="replace").rstrip("\r"), flush=True)
    except OSError:
        pass
    print("*** Conexión con el servidor cerrada ***", flush=True)
    # El hilo principal está bloqueado en input() y no se puede interrumpir
    # desde otro hilo, así que se termina el proceso directamente.
    os._exit(0)


def main():
    parser = argparse.ArgumentParser(description="Cliente de chat TCP")
    parser.add_argument("--host", default="127.0.0.1", help="IP del servidor (por defecto 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="puerto (por defecto 5000)")
    args = parser.parse_args()

    sys.stdout.reconfigure(errors="replace")

    try:
        sock = socket.create_connection((args.host, args.port), timeout=5)
    except OSError as error:
        print(f"No se pudo conectar a {args.host}:{args.port}: {error}")
        sys.exit(1)
    sock.settimeout(None)

    threading.Thread(target=recibir, args=(sock,), daemon=True).start()

    try:
        while True:
            linea = input()
            sock.sendall((linea + "\n").encode(CODIFICACION))
            if linea.strip() == "/salir":
                break
    except (EOFError, KeyboardInterrupt):
        # Ctrl+C o fin de la entrada: avisar al servidor antes de salir.
        try:
            sock.sendall(b"/salir\n")
        except OSError:
            pass
    except OSError:
        print("*** El servidor no está disponible ***")
        sock.close()
        sys.exit(1)

    # Dar un momento al receptor para mostrar la despedida del servidor.
    try:
        sock.shutdown(socket.SHUT_WR)
    except OSError:
        pass
    threading.Event().wait(1.0)
    sock.close()


if __name__ == "__main__":
    main()
