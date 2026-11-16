# Pruebas obligatorias (ventana normal = usuario A, incógnito = usuario B)

**Preparación (en la URL de Render):**
1. Crea dos cuentas de cliente: A y B (`/cuenta/nueva`). Entra con A en la ventana normal y con B en incógnito.
2. Entra como administrador → `/admin` → edita un producto y pon **Existencias = 1** (última unidad). Anota su nombre: ____________.
3. Guarda las capturas en `docs/capturas/` con el nombre indicado.

| N.º | Prueba | Cómo hacerla | Resultado esperado | Captura | ¿Pasó? |
|---|---|---|---|---|---|
| 1 | A reserva un recurso disponible | A abre el producto → **Agregar al carrito** | Aparece el contador y en Atlas `reservas` hay un documento y `productos.reservadas = 1` | `01-reserva-A.png` + `01-atlas-reservas.png` | |
| 2 | B intenta reservar el mismo recurso | B abre el mismo producto | B ve “Apartado / Sin disponibilidad temporal”; el botón está desactivado | `02-bloqueo-B.png` | |
| 3 | A cancela | A pulsa **Quitar** o **Vaciar** | `reservadas` vuelve a 0; B ya puede reservar | `03-cancelar-A.png` + `03-B-disponible.png` | |
| 4 | A reserva y deja terminar el tiempo | A reserva y espera 5 min (o usa `RESERVA_MINUTOS=1` en Render **solo para probar** y vuélvelo a 5) | Al recargar, el carrito está vacío y la unidad queda libre | `04-antes.png` y `04-despues.png` | |
| 5 | A confirma antes del vencimiento | A reserva → **Continuar con el pedido** → confirma | Se crea el pedido, baja `existencias`, la reserva desaparece y el contador deja de contar | `05-confirmar-A.png` | |
| 6 | Se recarga o reabre la aplicación | Recarga (F5) y abre en otra pestaña | El carrito y el estado se conservan porque están en Atlas | `06-atlas.png` | |
| 7 | Se escanea el QR desde el celular | En el producto, escanea el QR de la ficha con el celular | Abre la ficha correcta en la URL de **Render** (no localhost) | `07-qr-celular.jpg` | |
| 8 | Se cambia el estado y se escanea el mismo QR | Con A reserva todas las unidades y vuelve a escanear el **mismo** QR (o cambia el estado del pedido desde `/admin/pedidos` y escanea el QR del comprobante) | La ficha muestra “Apartado” / el comprobante muestra el estado nuevo | `08-qr-estado-nuevo.jpg` | |
| 9 | Identificador inexistente | Abre `/producto/000000000000000000000000` y `/comprobante/abc` | Mensaje claro, la app no se detiene | `09-id-inexistente.png` | |
| 10 | Se revisa en otro equipo | Abre la URL de Render en otra computadora o celular | Funciona sin archivos personales ni localhost | `10-otro-equipo.png` | |

## Registro de prueba cruzada
| Equipo que prueba | Prueba superada | Error encontrado | Corrección realizada |
|---|---|---|---|
| | | | |
