"""Prueba automatica de la reserva temporal (pruebas 1, 2, 3, 5, 8 y 9).

Uso:
  1) Deja corriendo la app:        python app.py
  2) En otra terminal:             python probar_reservas.py
  Para probar la version publicada: python probar_reservas.py https://TU-APP.onrender.com

Simula dos navegadores distintos (usuario A y usuario B) con cookies
separadas. Crea un producto de prueba y lo borra al terminar.
La prueba 4 (vencimiento) se hace a mano: hay que esperar el tiempo.
"""
import json
import sys
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import (HTTPCookieProcessor, HTTPRedirectHandler,
                            Request, build_opener)

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000").rstrip("/")


class Navegador:
    def __init__(self, nombre):
        self.nombre = nombre
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()),
                                   HTTPRedirectHandler())

    def pedir(self, metodo, ruta, datos=None, json_=None):
        cuerpo, cabeceras = None, {}
        if json_ is not None:
            cuerpo = json.dumps(json_).encode()
            cabeceras["Content-Type"] = "application/json"
        elif datos is not None:
            cuerpo = urlencode(datos).encode()
        peticion = Request(BASE + ruta, data=cuerpo, method=metodo,
                           headers=cabeceras)
        try:
            with self.opener.open(peticion, timeout=60) as r:
                return r.status, r.read(), r.geturl()
        except HTTPError as e:
            return e.code, e.read(), e.geturl()


resultados = []


def comprobar(nombre, condicion, detalle=""):
    resultados.append(condicion)
    print(("  OK   " if condicion else "  FALLA") + " " + nombre
          + ("" if condicion else "  -> " + str(detalle)))


def texto(cuerpo):
    return cuerpo.decode("utf-8", "replace")


A, B = Navegador("A"), Navegador("B")

print("Creando producto de prueba por la API...")
c, cuerpo, _ = A.pedir("POST", "/api/productos", json_={
    "nombre": "Prueba reservas", "categoria": "Prueba", "estado": "Disponible"})
assert c == 201, "No se pudo crear el producto: " + texto(cuerpo)
pid = json.loads(cuerpo)["id"]
folios = []

try:
    # La primera reserva asigna existencias iniciales (10) al producto nuevo
    print("\nPrueba 1: A reserva todas las unidades libres")
    c, cuerpo, url = A.pedir("POST", "/producto/" + pid + "/apartar",
                             {"cantidad": "10"})
    comprobar("A llega a la pagina de la reserva", "/reserva/ZK-" in url, url)
    folio = url.rsplit("/", 1)[-1]
    folios.append(folio)
    comprobar("La pagina muestra el contador",
              "contador-reserva" in texto(cuerpo))

    c, cuerpo, _ = A.pedir("GET", "/api/productos/" + pid)
    comprobar("Atlas descontó las unidades (existencias = 0)",
              json.loads(cuerpo).get("existencias") == 0, texto(cuerpo))

    print("\nPrueba 2: B intenta reservar el mismo producto")
    c, cuerpo, url = B.pedir("POST", "/producto/" + pid + "/apartar",
                             {"cantidad": "1"})
    comprobar("B vuelve a la ficha sin reserva", "/reserva/" not in url, url)
    comprobar("B ve el mensaje de unidades apartadas",
              "apartadas por otros clientes" in texto(cuerpo))

    print("\nPrueba: B no puede cancelar la reserva de A")
    c, cuerpo, _ = B.pedir("POST", "/reserva/" + folio + "/cancelar")
    comprobar("B recibe 403", c == 403, c)

    print("\nPrueba 3: A cancela y B ya puede reservar")
    c, cuerpo, _ = A.pedir("POST", "/reserva/" + folio + "/cancelar")
    comprobar("La reserva queda cancelada", "Cancelada" in texto(cuerpo))
    c, cuerpo, url = B.pedir("POST", "/producto/" + pid + "/apartar",
                             {"cantidad": "1"})
    comprobar("B logra reservar", "/reserva/ZK-" in url, url)
    folio_b = url.rsplit("/", 1)[-1]
    folios.append(folio_b)

    print("\nPrueba 5: B confirma antes de vencer")
    c, cuerpo, _ = B.pedir("POST", "/reserva/" + folio_b + "/confirmar")
    comprobar("La reserva queda confirmada", "Confirmada" in texto(cuerpo))
    c, cuerpo, _ = B.pedir("GET", "/api/reservas/" + folio_b)
    datos = json.loads(cuerpo)
    comprobar("Ya no cuenta tiempo", datos["estado"] == "confirmada"
              and datos["segundos_restantes"] == 0, datos)

    print("\nPrueba 8: el mismo comprobante muestra el estado nuevo")
    c, cuerpo, _ = A.pedir("GET", "/reserva/" + folio)
    comprobar("La reserva de A ahora dice Cancelada",
              c == 200 and "Cancelada" in texto(cuerpo))
    c, cuerpo, _ = A.pedir("GET", "/reserva/" + folio + "/qr.png")
    comprobar("El QR es una imagen PNG", cuerpo[:4] == b"\x89PNG", cuerpo[:20])

    print("\nPrueba 9: identificadores que no existen")
    c, cuerpo, _ = A.pedir("GET", "/reserva/ZK-000000")
    comprobar("Folio inexistente: 404 con mensaje",
              c == 404 and "No existe una reserva" in texto(cuerpo), c)
    c, cuerpo, _ = A.pedir("GET", "/reserva/%%%malo")
    comprobar("Folio con formato raro: 404 (no se rompe)", c == 404, c)
    c, cuerpo, _ = A.pedir("POST", "/producto/000000000000000000000000/apartar",
                           {"cantidad": "1"})
    comprobar("Producto inexistente: 404", c == 404, c)
finally:
    print("\nLimpiando producto de prueba...")
    A.pedir("DELETE", "/api/productos/" + pid)

print("\n%d de %d comprobaciones correctas." % (sum(resultados), len(resultados)))
if not all(resultados):
    sys.exit(1)
