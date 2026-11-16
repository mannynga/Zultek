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
