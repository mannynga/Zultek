# Zultek · Tienda de tecnología con reserva temporal y código QR

**Proyecto final de Aplicaciones Web · CBTIS 272 · 5.º semestre (cierre del segundo parcial)**

- **Integrantes:** [Natanael Morales Gomez] · [America azul chan chuc] 
- **Grupo:** [grupo]
- **Aplicación publicada (Render):** https://TU-SERVICIO.onrender.com
- **Repositorio:** https://github.com/mannynga/Zultek

## Problema que resuelve
Zultek es un catálogo de electrónica con administrador, carrito y pedidos. Si dos clientes
quieren la última unidad al mismo tiempo, alguien se queda sin producto después de armar su
carrito. La **reserva temporal** aparta las unidades durante unos minutos para quien las
agregó; si no confirma, se liberan solas. El **código QR** permite abrir desde un celular la
ficha del producto o el comprobante de un pedido, siempre con la información actual.

## Elemento reservado (modelo "Cantidad")
Se reservan **unidades de un producto**. Cada producto tiene `existencias` y `reservadas`;
la disponibilidad es `existencias − reservadas`.

| Concepto | Cómo funciona en Zultek |
|---|---|
| Reservar | Botón **Agregar al carrito**: aparta unidades solo si siguen libres (operación atómica en MongoDB Atlas dentro de una transacción). |
| Duración | **5 minutos** (variable opcional `RESERVA_MINUTOS`). El contador se ve en el carrito y en el pedido. |
| Bloqueo | Un segundo usuario ve “Apartado” / “Sin disponibilidad temporal”; no puede exceder las existencias. |
| Vencimiento | La fecha `vence_en` se guarda en Atlas (colección `reservas`). Al vencer, la siguiente consulta libera las unidades; cerrar la pestaña no bloquea el producto. |
| Cancelación | Quitar un producto o **Vaciar** el carrito devuelve las unidades. |
| Confirmación | **Confirmar pedido** descuenta existencias, crea el pedido y cierra la reserva. |

## Función del código QR
El QR **no guarda datos**: codifica la dirección de una página real de la tienda.

| QR | Dirección que abre | Qué muestra |
|---|---|---|
| Ficha del producto | `https://…onrender.com/producto/<id>` | Nombre, precio, estado (Disponible / Apartado / Agotado) y unidades libres. |
| Comprobante del pedido | `https://…onrender.com/comprobante/<id>` | Folio, fecha, estado, productos y total. **Sin** nombre, teléfono ni dirección. |

Como la página consulta Atlas cada vez, el mismo QR muestra el estado nuevo sin generar otro.

## Instrucciones de ejecución (Windows / PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:MONGO_URI = "mongodb+srv://USUARIO:CONTRASENA@CLUSTER.mongodb.net/"
python app.py
```
Abrir http://127.0.0.1:5000. (En modo local el QR apunta a localhost; el QR válido es el de Render.)
# Zultek · Tienda de tecnología

**CBTIS 272 · Aplicaciones Web · 5.º semestre · Proyecto final (2.º parcial)**

## Integrantes
- Natanael — *(completar apellidos y participación)*
- América Azul Chan — *(completar apellidos y participación)*

## Problema que resuelve
Zultek es un catálogo de electrónica con carrito y pedidos. Con la mejora del
segundo parcial, un cliente puede **apartar unidades** de un producto durante
unos minutos mientras decide, sin que otra persona se las quite, y puede abrir
su comprobante desde el celular con un **código QR**.

## Elemento reservado
**Unidades (cantidad) de un producto.** Cada producto tiene el campo
`existencias` (unidades libres). Apartar descuenta unidades de forma atómica en
MongoDB; cancelar o vencer las devuelve.

## Duración de la reserva
**5 minutos** (variable opcional `RESERVA_MINUTOS`, valores de 3 a 5).
La fecha de vencimiento (`expira_en`) se guarda en MongoDB Atlas; el contador
de la pantalla solo la muestra. El servidor libera las reservas vencidas antes
de reservar o mostrar un producto, aunque el usuario cierre la pestaña.

## Función del QR
El QR contiene la dirección pública del **comprobante de la reserva**
(`https://…onrender.com/reserva/FOLIO`). Al escanearlo se ve el estado actual
(apartada, confirmada, cancelada o vencida) sin crear un QR nuevo. La ficha de
cada producto también tiene un QR (`/producto/ID`). La página pública no muestra
datos personales ni credenciales.

## Cómo funciona
1. El cliente elige producto y cantidad y pulsa **Apartar**.
2. El servidor descuenta las unidades solo si todavía alcanzan (operación atómica) y guarda la reserva con `expira_en`.
3. La pantalla muestra el contador y los botones **Confirmar** / **Cancelar**.
4. Confirmar → estado `confirmada`. Cancelar o vencer → las unidades regresan.
5. El QR abre `/reserva/FOLIO` con la información actual.

Estados: `temporal` → `confirmada` | `cancelada` | `vencida`.
Colecciones: `productos` (con `existencias`), `reservas`, `usuarios`, `pedidos`, `imagenes`.

## Ejecutar en local
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export MONGO_URI="mongodb+srv://USUARIO:CLAVE@CLUSTER.mongodb.net/"   # Windows: set MONGO_URI=...
python app.py                    # http://127.0.0.1:5000
```
Prueba automática de la reserva (con la app encendida): `python probar_reservas.py`

## Variables de entorno
| Variable | Uso |
|---|---|
| `MONGO_URI` | Cadena completa de MongoDB Atlas (obligatoria en Render). |
| `SECRET_KEY` | Clave privada de sesión (obligatoria en Render). |
| `ADMIN_CODIGO` | Código para crear administradores en `/admin/registro`. |
| `RESERVA_MINUTOS` | Opcional. Minutos de la reserva (por defecto 5). |
| `APP_BASE_URL` | Opcional. Solo si el QR sale con localhost. |

Ver `.env.example`. El archivo `.env` está en `.gitignore`.

## Publicación en Render
Build: `pip install -r requirements.txt` · Start: `gunicorn app:app` · Python: ver `.python-version`.

## Estructura
```
app.py            CRUD original y API (/api/productos)
extras.py         cuentas, admin, reserva temporal, pedidos, QR y comprobante
templates/        páginas HTML (Jinja)
static/           CSS, JS, imágenes y Bootstrap (solo los archivos usados)
pruebas/          probar_api.py (prueba de la API)
docs/PRUEBAS.md   las 10 pruebas obligatorias y la prueba cruzada
docs/capturas/    evidencias (ver LEEME.md)
```
Colecciones en Atlas (`catalogo_electronica`): `productos`, `reservas`, `pedidos`, `usuarios`, `imagenes`.

## Capturas principales
Las evidencias están en [`docs/capturas/`](docs/capturas/LEEME.md) y se explican en [`docs/PRUEBAS.md`](docs/PRUEBAS.md).
| `MONGO_URI` | Cadena completa de MongoDB Atlas (**obligatoria**, nunca en el código). |
| `SECRET_KEY` | Frase larga y privada para las sesiones (**obligatoria** en Render). |
| `ADMIN_CODIGO` | Código para crear administradores. |
| `APP_BASE_URL` | URL pública de Render. Solo si el QR muestra localhost. |
| `RESERVA_MINUTOS` | Duración de la reserva, 3 a 5 (por defecto 5). |

## Publicación en Render
Build Command: `pip install -r requirements.txt` · Start Command: `gunicorn app:app`

**Enlace de Render:** *(pegar aquí la URL final)*
**Repositorio:** *(pegar aquí la URL de GitHub)*

## Capturas principales
*(agregar: producto con existencias, reserva con contador, segundo usuario rechazado, QR en el celular, colección `reservas` en Atlas)*
