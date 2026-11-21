"""Servidor de chat multicliente sobre TCP con un hilo por cliente.

Uso:
    python server.py [--host 0.0.0.0] [--port 5000]
"""

import argparse
import signal
import socket
import sys
import threading
from datetime import datetime

CODIFICACION = "utf-8"

# Estado compartido entre hilos: nombre de usuario -> socket del cliente.
#
# CONDICION DE CARRERA: este diccionario lo usan al mismo tiempo el hilo de
# cada cliente. Sin protección pueden pasar dos cosas:
#   1. Un hilo agrega o elimina un cliente mientras otro hilo recorre el dict
#      para hacer el broadcast. Python lanza "RuntimeError: dictionary changed
#      size during iteration", o el broadcast termina enviando a un socket que
#      otro hilo ya cerró.
#   2. Nombres duplicados: dos clientes piden "ana" casi a la vez. Ambos hilos
#      revisan "¿'ana' está libre?", ambos ven que sí, y ambos lo registran;
#      el segundo pisa al primero en el dict.
#
# SOLUCION: un threading.Lock. Solo un hilo a la vez puede estar dentro de un
# bloque "with clientes_lock", así que nadie modifica el dict mientras otro lo
# recorre, y la revisión del nombre + su registro ocurren en la MISMA sección
# crítica (operación atómica): ningún otro hilo puede colarse entre las dos.
clientes = {}
clientes_lock = threading.Lock()


def log(texto):
    """Imprime un mensaje en la consola del servidor con la hora."""
    print(f"[{datetime.now():%H:%M:%S}] {texto}", flush=True)


def enviar(sock, texto):
    """Envía una línea de texto terminada en '\\n' (ver leer_lineas)."""
    sock.sendall((texto + "\n").encode(CODIFICACION))


def leer_lineas(sock):
    """Generador que entrega, una por una, las líneas que llegan por el socket.

    TCP es un flujo de bytes, no de mensajes: un recv() puede traer medio
    mensaje o varios pegados. Por eso cada mensaje termina en '\\n' y se guarda
    lo recibido en un buffer propio de esta conexión hasta tener una línea
    completa. Se separa sobre bytes antes de decodificar para no partir un
    carácter UTF-8 de varios bytes (tildes, ñ, emojis).
    """
    buffer = b""
    while True:
        datos = sock.recv(4096)
        if not datos:  # el otro extremo cerró la conexión
            return
        buffer += datos
        while b"\n" in buffer:
            linea, buffer = buffer.split(b"\n", 1)
            yield linea.decode(CODIFICACION, errors="replace").rstrip("\r")


def cerrar(sock):
    """Cierra un socket ignorando errores (puede estar ya cerrado)."""
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    sock.close()


def eliminar_cliente(nombre, sock):
    """Quita al cliente del dict (si sigue siendo ese socket) y lo cierra."""
    with clientes_lock:
        if clientes.get(nombre) is sock:
            del clientes[nombre]
    cerrar(sock)


def broadcast(texto):
    """Envía una línea a todos los clientes conectados (remitente incluido).

    La lista de destinatarios se copia DENTRO del lock y el envío se hace
    FUERA de él: sendall() puede tardar si un cliente es lento o tiene la red
    llena, y si se enviara con el lock tomado ese cliente bloquearía a todos
    los demás hilos (nadie podría entrar ni salir del chat).
    """
    with clientes_lock:
        destinatarios = list(clientes.items())
    for nombre, sock in destinatarios:
        try:
            enviar(sock, texto)
        except OSError:
            log(f"No se pudo enviar a {nombre}; se elimina.")
            eliminar_cliente(nombre, sock)


def pedir_nombre(sock, lineas):
    """Pide un nombre hasta que sea válido y lo registra. None si se desconecta."""
    enviar(sock, "Bienvenido. Escribe tu nombre:")
    for nombre in lineas:
        nombre = nombre.strip()
        if not nombre or nombre.startswith("/"):
            enviar(sock, "Nombre inválido. Escribe otro nombre:")
            continue
        # Revisión y registro en la MISMA sección crítica (ver comentario arriba).
        with clientes_lock:
            libre = nombre not in clientes
            if libre:
                clientes[nombre] = sock
        if libre:
            return nombre
        enviar(sock, f"El nombre '{nombre}' ya está en uso. Escribe otro nombre:")
    return None


def atender_cliente(sock, direccion):
    """Hilo de un cliente: registra su nombre y procesa sus mensajes."""
    nombre = None
    try:
        lineas = leer_lineas(sock)
        nombre = pedir_nombre(sock, lineas)
        if nombre is None:
            return
        log(f"{direccion[0]}:{direccion[1]} se registró como '{nombre}'")
        enviar(sock, f"Hola {nombre}. Comandos: /usuarios, /salir")
        broadcast(f"*** {nombre} se unió al chat ***")

        for mensaje in lineas:
            if not mensaje.strip():
                continue
            if mensaje == "/salir":
                enviar(sock, "Hasta luego.")
                break
            if mensaje == "/usuarios":
                with clientes_lock:
                    nombres = sorted(clientes)
                enviar(sock, f"Conectados ({len(nombres)}): {', '.join(nombres)}")
            elif mensaje.startswith("/"):
                enviar(sock, "Comando desconocido. Usa /usuarios o /salir.")
            else:
                broadcast(f"[{datetime.now():%H:%M:%S}] {nombre}: {mensaje}")
    except OSError as error:
        # Incluye ConnectionResetError: el cliente se cerró sin avisar.
        log(f"Conexión perdida con {nombre or direccion}: {error.__class__.__name__}")
    finally:
        if nombre is not None:
            eliminar_cliente(nombre, sock)
            log(f"'{nombre}' se desconectó")
            broadcast(f"*** {nombre} salió del chat ***")
        else:
            cerrar(sock)


def ips_locales():
    """Devuelve (IP principal, otras IPv4 del equipo) para compartir."""
    principal = None
    try:
        # connect() en UDP no envía paquetes: solo elige la interfaz de salida.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            principal = s.getsockname()[0]
    except OSError:
        pass
    try:
        todas = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        todas = []
    otras = sorted(ip for ip in set(todas) if ip != principal and not ip.startswith("127."))
    return principal or "127.0.0.1", otras


def main():
    parser = argparse.ArgumentParser(description="Servidor de chat TCP multicliente")
    parser.add_argument("--host", default="0.0.0.0", help="interfaz (por defecto 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5000, help="puerto (por defecto 5000)")
    args = parser.parse_args()

    sys.stdout.reconfigure(errors="replace")  # nombres con emojis no tumban los logs
    if hasattr(signal, "SIGBREAK"):  # en Windows, Ctrl+Break también cierra limpio
        signal.signal(signal.SIGBREAK, signal.default_int_handler)

    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    servidor.bind((args.host, args.port))
    servidor.listen()
    # Timeout corto en accept() para que Ctrl+C se atienda también en Windows.
    servidor.settimeout(1.0)

    log(f"Servidor escuchando en {args.host}:{args.port} (Ctrl+C para salir)")
    principal, otras = ips_locales()
    log(f"  IP para compartir con tus compañeros: {principal}:{args.port}")
    if otras:
        log(f"  Otras interfaces de este equipo: {', '.join(otras)}")

    try:
        while True:  # hilo principal: solo acepta conexiones
            try:
                sock, direccion = servidor.accept()
            except socket.timeout:
                continue
            sock.settimeout(None)
            log(f"Nueva conexión desde {direccion[0]}:{direccion[1]}")
            hilo = threading.Thread(target=atender_cliente, args=(sock, direccion), daemon=True)
            hilo.start()
    except KeyboardInterrupt:
        log("Cerrando servidor...")
    finally:
        with clientes_lock:
            sockets = list(clientes.values())
            clientes.clear()
        for sock in sockets:
            cerrar(sock)
        servidor.close()
        log("Servidor cerrado.")


if __name__ == "__main__":
    main()
