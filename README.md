# threaded-socket-chat

Chat multicliente por consola en Python, hecho con **sockets TCP** e **hilos**.
Un servidor acepta varios clientes a la vez, les pide un nombre y reenvía cada
mensaje a todos los conectados (broadcast).

Trabajo de la unidad de hilos y sockets del curso *Programación Concurrente y
Distribuida* — Universidad de Caldas.

## Requisitos

- Python 3.8 o superior.
- Solo librería estándar (`socket`, `threading`, `argparse`, `datetime`). No hay que instalar nada.

## Cómo correrlo

### 1. Servidor

```bash
python server.py                 # escucha en 0.0.0.0:5000
python server.py --port 6000     # otro puerto
```

Al iniciar muestra la IP que deben usar los compañeros, por ejemplo:

```
[12:06:48] Servidor escuchando en 0.0.0.0:5000 (Ctrl+C para salir)
[12:06:48]   IP para compartir con tus compañeros: 192.168.1.20:5000
```

`Ctrl+C` cierra el servidor de forma limpia (cierra todos los sockets).

### 2. Cliente en el mismo equipo

```bash
python client.py                 # se conecta a 127.0.0.1:5000
```

### 3. Compañero en la misma red (Wi-Fi o LAN)

En el equipo del compañero, con la IP que imprimió el servidor:

```bash
python client.py --host 192.168.1.20 --port 5000
```

> **Firewall de Windows:** la primera vez que corre `server.py`, Windows pregunta si
> permite a Python comunicarse en la red. Marca **Redes privadas** y acepta. Si ya lo
> rechazaste, ve a *Seguridad de Windows → Firewall y protección de red → Permitir una
> aplicación a través del firewall* y habilita Python en redes privadas. La red Wi-Fi
> debe estar configurada como *privada*.

## Uso

1. Al conectarse, el servidor pide un nombre. Si está vacío o ya lo usa otra
   persona, lo vuelve a pedir.
2. Todos ven `*** nombre se unió al chat ***`.
3. Cada mensaje llega a todos (también a quien lo envió) con el formato
   `[HH:MM:SS] nombre: mensaje`.

| Comando     | Qué hace                                                    |
|-------------|-------------------------------------------------------------|
| `/usuarios` | Muestra quiénes están conectados (solo a quien lo pide).    |
| `/salir`    | Sale del chat; los demás ven `*** nombre salió del chat ***`. |

## Pruebas

```bash
python -m unittest -v
```

`tests/test_chat.py` levanta el servidor en un puerto libre, conecta varios clientes
por socket y verifica: que pide el nombre, que rechaza nombres vacíos y repetidos,
que el broadcast llega a los tres clientes, `/usuarios`, el aviso de salida y que una
desconexión abrupta (RST) no tumba el servidor.

## Diseño concurrente

```
                    SERVIDOR (server.py)
 ┌─────────────────────────────────────────────────────┐
 │  Hilo principal                                     │
 │  while True: accept()  ──┬── crea Thread(cliente 1) │
 │                          ├── crea Thread(cliente 2) │
 │                          └── crea Thread(cliente N) │
 │                                                     │
 │  Hilo cliente i:  recv → pedir nombre → mensajes    │
 │        │                                            │
 │        ▼                                            │
 │  ┌──────────────────────────────┐                   │
 │  │ clientes {nombre: socket}    │ ◄── threading.Lock│
 │  └──────────────────────────────┘                   │
 │        │ broadcast: copia bajo lock, envía fuera    │
 └────────┼────────────────────────────────────────────┘
          ▼  TCP
 ┌──────────────────────────────┐
 │ CLIENTE (client.py)          │
 │  Hilo principal: input() ──► sendall()
 │  Hilo receptor:  recv()  ──► print()
 └──────────────────────────────┘
```

- **Servidor:** 1 hilo que solo hace `accept()` en bucle + 1 hilo (`daemon`) por cada
  cliente conectado. Así un cliente que no escribe no bloquea a los demás.
- **Cliente:** 2 hilos, porque `recv()` e `input()` son bloqueantes. Si un solo hilo
  esperara el teclado, no podría mostrar lo que escriben los demás mientras tanto.

### La condición de carrera y cómo se resolvió

El diccionario `clientes` (nombre → socket) es compartido por todos los hilos:

1. **Modificar mientras se recorre:** un hilo agrega o elimina un cliente mientras otro
   recorre el diccionario para el broadcast. Python lanza
   `RuntimeError: dictionary changed size during iteration`, o se intenta enviar a un
   socket que otro hilo ya cerró.
2. **Nombres duplicados:** dos clientes piden el mismo nombre casi a la vez; ambos hilos
   comprueban que está libre y ambos lo registran.

**Solución:** un `threading.Lock` protege todo acceso al diccionario. La comprobación
del nombre y su registro ocurren dentro de la **misma** sección crítica, de modo que
ningún otro hilo puede intercalarse entre ellas. En el broadcast, la lista de sockets se
**copia dentro del lock** y el `sendall()` se hace **fuera**: así un cliente lento no
deja a todos esperando el lock. Si un envío falla, ese cliente se elimina.

### ¿Por qué TCP y no UDP?

Un chat necesita que los mensajes lleguen **completos, sin pérdidas y en orden**, y
saber cuándo alguien se conecta o se desconecta. TCP ofrece conexión, entrega fiable y
orden; UDP no garantiza nada de eso y habría que implementarlo a mano.

### ¿Por qué el delimitador `\n`?

TCP es un **flujo de bytes**, no de mensajes: un `recv()` puede traer medio mensaje o
varios mensajes pegados. Cada mensaje termina en `\n` y cada conexión tiene su propio
buffer donde se acumulan los bytes hasta tener una línea completa. Se separa sobre los
bytes antes de decodificar en UTF-8 para no partir caracteres como `ñ` o tildes.

## Autor

Samuel Restrepo Ramírez — 2026. Licencia [MIT](LICENSE).
