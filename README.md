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
