"""Tienda Zultek: cuentas, administrador, precios, carrito y pedidos.

Este archivo solo AGREGA rutas. No modifica el CRUD de la pagina
(/agregar, /editar, /eliminar) ni la API (/api/productos...):
- Las rutas /agregar, /editar y /eliminar siguen existiendo, pero ahora
  solo las puede usar un administrador (ver proteger_crud).
- El panel de administrador (/admin) agrega y edita productos con su
  precio, descripcion e imagen escribiendo en la misma coleccion
  "productos". Otras colecciones: usuarios, imagenes, pedidos.
- El carrito vive en la sesion; el pedido guarda los precios del momento.
- No hay cobro real: el pago es simulado y NO se piden datos de tarjeta.
"""
import hmac
import io
import os
import re
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from urllib.parse import urlsplit

from bson import Binary, ObjectId
from flask import (abort, flash, g, jsonify, make_response, redirect,
                   render_template, request, session, url_for)
from PIL import Image
from pymongo.errors import PyMongoError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

MAX_POR_PRODUCTO = 10
MAX_PRODUCTOS = 40
METODO = "pbkdf2:sha256"

ESTADOS_PRODUCTO = ("Disponible", "Agotado")
ESTADOS_PEDIDO = ("Pendiente", "Pagado", "Enviado", "Entregado", "Cancelado")
METODOS_PAGO = ("Tarjeta (simulado)", "Transferencia", "Pago al recibir")
PROTEGIDOS = {"agregar", "editar", "eliminar"}   # CRUD original: solo admin
CATEGORIA_NUEVA = "__nueva__"                    # valor del selector "Crear nueva categoría"
MAX_IMAGEN = 5 * 1024 * 1024
ZONA = timezone(timedelta(hours=-5))             # Cancun: UTC-5 todo el ano


def dinero(centavos):
    try:
        return "${:,.2f}".format(Decimal(int(centavos)) / 100)
    except (TypeError, ValueError):
        return "—"


def fecha(valor):
    if not isinstance(valor, datetime):
        return ""
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(ZONA).strftime("%d/%m/%Y %H:%M")


def leer_precio(texto):
    """'1,299.50' -> 129950 centavos. None si no es un precio valido."""
    limpio = (texto or "").replace("$", "").replace(",", "").replace(" ", "")
    try:
        valor = Decimal(limpio)
    except InvalidOperation:
        return None
    if (not valor.is_finite() or valor <= 0 or valor > 1000000
            or valor.as_tuple().exponent < -2):
        return None
    return int(valor * 100)


def leer_producto(form):
    """Mismos limites que leer_formulario de app.py, mas precio y descripcion."""
    nombre = form.get("nombre", "").strip()
    categoria = form.get("categoria", "").strip()
    estado = form.get("estado", "").strip()
    descripcion = form.get("descripcion", "").strip()
    precio = leer_precio(form.get("precio", ""))
    error = None
    if not nombre or not categoria or not estado:
        error = "Completa nombre, categoría y estado."
    elif len(nombre) > 80 or len(categoria) > 20:
        error = "Máximo: nombre 80 y categoría 20 caracteres."
    elif estado not in ESTADOS_PRODUCTO:
        error = "Selecciona un estado válido."
    elif precio is None:
        error = "Escribe un precio válido, por ejemplo 1299.50."
    elif len(descripcion) > 300:
        error = "La descripción admite hasta 300 caracteres."
    datos = {"nombre": nombre, "categoria": categoria, "estado": estado,
             "precio_cent": precio, "descripcion": descripcion}
    return datos, error


def preparar_imagen(archivo):
    """Valida que sea una imagen real, la reduce y la devuelve en WEBP."""
    crudo = archivo.read(MAX_IMAGEN + 1)
    if len(crudo) > MAX_IMAGEN:
        return None, "La imagen pesa más de 5 MB."
    try:
        with Image.open(io.BytesIO(crudo)) as original:
            if original.format not in ("PNG", "JPEG", "WEBP", "GIF"):
                return None, "Usa una imagen PNG, JPG, WEBP o GIF."
            if original.width * original.height > 25_000_000:
                return None, "La imagen tiene demasiados píxeles."
            copia = original.convert("RGBA")
        copia.thumbnail((900, 900))
        salida = io.BytesIO()
        copia.save(salida, "WEBP", quality=82)
        return salida.getvalue(), None
    except Exception:
        return None, "No se pudo leer la imagen. Prueba con otro archivo."


def registrar_extras(app, base_datos):
    usuarios = base_datos["usuarios"]
    productos = base_datos["productos"]
    imagenes = base_datos["imagenes"]
    pedidos = base_datos["pedidos"]

    en_render = bool(os.environ.get("RENDER"))

    # La sesion necesita una clave secreta. En Render va en SECRET_KEY.
    clave_secreta = os.environ.get("SECRET_KEY")
    if not clave_secreta:
        if en_render:
            raise RuntimeError("Configura SECRET_KEY en Render.")
        clave_secreta = "solo-para-pruebas-locales"
    app.secret_key = clave_secreta
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=en_render,
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
    )
    if en_render:  # detras del proxy de Render: IP y https reales
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    # Codigo para crear administradores. En Render va en ADMIN_CODIGO;
    # sin esa variable la pagina /admin/registro no existe.
    admin_codigo = os.environ.get("ADMIN_CODIGO")
    if not admin_codigo and not en_render:
        admin_codigo = "admin-local"

    hash_falso = generate_password_hash("no-existe", method=METODO)
    app.jinja_env.filters["dinero"] = dinero
    app.jinja_env.filters["fecha"] = fecha
    app.jinja_env.filters["numero"] = lambda v: str(v)[-6:].upper()
    app.jinja_env.globals.update(
        ESTADOS_PEDIDO=ESTADOS_PEDIDO, ESTADOS_PRODUCTO=ESTADOS_PRODUCTO,
        METODOS_PAGO=METODOS_PAGO, MAX_POR_PRODUCTO=MAX_POR_PRODUCTO,
        CATEGORIA_NUEVA=CATEGORIA_NUEVA)

    # ------------------------- Utilidades -------------------------
    intentos = {}

    def bloqueado(clave, maximo, ventana=900):
        ahora = time.time()
        if len(intentos) > 5000:
            intentos.clear()
        recientes = [t for t in intentos.get(clave, []) if ahora - t < ventana]
        intentos[clave] = recientes
        return len(recientes) >= maximo

    def anotar_fallo(clave):
        intentos.setdefault(clave, []).append(time.time())

    def es_admin():
        if "es_admin" not in g:
            g.es_admin = False
            uid = session.get("uid")
            if uid and ObjectId.is_valid(uid):
                try:
                    cuenta = usuarios.find_one({"_id": ObjectId(uid)})
                    g.es_admin = bool(cuenta and cuenta.get("rol") == "admin")
                except PyMongoError:
                    pass
        return g.es_admin

    @app.context_processor
    def datos_comunes():
        carrito = session.get("carrito", {})
        try:  # categorías para la barra de navegación (buscador)
            categorias_nav = sorted(
                (c for c in productos.distinct("categoria") if isinstance(c, str)),
                key=str.lower)
        except PyMongoError:
            categorias_nav = []
        return {
            "usuario": session.get("nombre"),
            "es_admin": es_admin() if session.get("uid") else False,
            "carrito_total": sum(carrito.values()),
            "categorias_nav": categorias_nav,
        }

    def requiere_sesion(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            if not session.get("uid"):
                flash("Inicia sesión para continuar.", "warning")
                return redirect(url_for("iniciar_sesion"))
            return vista(*args, **kwargs)
        return envoltura

    def requiere_admin(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            if not session.get("uid"):
                flash("Inicia sesión como administrador.", "warning")
                return redirect(url_for("iniciar_sesion"))
            if not es_admin():
                abort(403, description="Solo el administrador puede hacer esto.")
            return vista(*args, **kwargs)
        return envoltura

    def abrir_sesion(usuario_id, nombre):
        session.clear()
        session["uid"] = str(usuario_id)
        session["nombre"] = nombre

    def volver_a(defecto):
        """Vuelve a la pagina anterior si es de este mismo sitio."""
        ref = request.referrer
        if ref:
            partes = urlsplit(ref)
            ruta = partes.path
            if (partes.netloc == request.host and ruta.startswith("/")
                    and not ruta.startswith("//")):
                return ruta + ("?" + partes.query if partes.query else "")
        return defecto

    def obtener_producto(id):
        if not ObjectId.is_valid(id):
            abort(404, description="La clave del producto no es válida.")
        producto = productos.find_one({"_id": ObjectId(id)})
        if producto is None:
            abort(404, description="Este producto ya no existe.")
        return producto

    def guardar_imagen(producto_id, datos):
        imagenes.delete_many({"_id": producto_id})
        imagenes.insert_one({"_id": producto_id, "tipo": "image/webp",
                             "datos": Binary(datos)})

    # --------- El CRUD original queda solo para administradores ---------
    @app.before_request
    def proteger_crud():
        if request.endpoint in PROTEGIDOS and not es_admin():
            if not session.get("uid"):
                flash("Inicia sesión como administrador.", "warning")
                return redirect(url_for("iniciar_sesion"))
            abort(403, description="Solo el administrador puede hacer esto.")

    @app.after_request
    def limpiar_imagen_huerfana(respuesta):
        """Si se elimina un producto (pagina o API), borra tambien su foto."""
        try:
            if respuesta.status_code in (204, 302) and request.method in (
                    "POST", "DELETE"):
                id = (request.view_args or {}).get("id")
                if (request.endpoint in ("eliminar", "api_producto")
                        and id and ObjectId.is_valid(id)
                        and productos.find_one({"_id": ObjectId(id)}) is None):
                    imagenes.delete_many({"_id": ObjectId(id)})
        except PyMongoError:
            pass
        return respuesta

    @app.errorhandler(403)
    @app.errorhandler(413)
    def error_extra(error):
        mensaje = error.description
        if error.code == 413:
            mensaje = "El archivo es demasiado grande. Máximo 5 MB."
        if request.path.startswith("/api/"):
            return jsonify({"error": mensaje}), error.code
        return render_template("error.html", mensaje=mensaje), error.code

    @app.route("/favicon.ico")
    def favicon():
        return app.send_static_file("img/favicon.ico")

    # ------------------------- Cuentas -------------------------
    def validar_cuenta(form):
        nombre = form.get("nombre", "").strip()
        correo = form.get("correo", "").strip().lower()
        clave = form.get("contrasena", "")
        repetir = form.get("repetir", "")
        error = None
        if not nombre or not correo or not clave:
            error = "Completa todos los campos."
        elif len(nombre) > 40 or len(correo) > 80:
            error = "Máximo: nombre 40 y correo 80 caracteres."
        elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", correo):
            error = "Escribe un correo válido."
        elif not 8 <= len(clave) <= 72:
            error = "La contraseña debe tener entre 8 y 72 caracteres."
        elif clave != repetir:
            error = "Las contraseñas no coinciden."
        elif usuarios.find_one({"correo": correo}):
            error = "Ese correo ya tiene una cuenta."
        return error, nombre, correo, clave

    def crear_usuario(nombre, correo, clave, rol):
        return usuarios.insert_one({
            "nombre": nombre, "correo": correo, "rol": rol,
            "clave": generate_password_hash(clave, method=METODO),
        }).inserted_id

    @app.route("/cuenta/nueva", methods=["GET", "POST"])
    def crear_cuenta():
        if request.method == "POST":
            error, nombre, correo, clave = validar_cuenta(request.form)
            if error:
                return render_template("crear_cuenta.html", error=error,
                                       nombre=nombre, correo=correo), 400
            abrir_sesion(crear_usuario(nombre, correo, clave, "cliente"), nombre)
            flash("Cuenta creada. ¡Bienvenido!", "success")
            return redirect(url_for("inicio"))
        return render_template("crear_cuenta.html", nombre="", correo="")

    @app.route("/admin/registro", methods=["GET", "POST"])
    def admin_registro():
        if not admin_codigo:
            abort(404, description="Esta página no está disponible.")
        clave_ip = "admin:" + (request.remote_addr or "?")
        if request.method == "POST":
            if bloqueado(clave_ip, 5):
                return render_template(
                    "admin_registro.html", nombre="", correo="",
                    error="Demasiados intentos. Espera unos minutos."), 429
            codigo = request.form.get("codigo", "")
            if not hmac.compare_digest(codigo.encode(), admin_codigo.encode()):
                anotar_fallo(clave_ip)
                error, nombre, correo = ("Código de administrador incorrecto.",
                                         request.form.get("nombre", ""),
                                         request.form.get("correo", ""))
                return render_template("admin_registro.html", error=error,
                                       nombre=nombre, correo=correo), 403
            error, nombre, correo, clave = validar_cuenta(request.form)
            if error:
                return render_template("admin_registro.html", error=error,
                                       nombre=nombre, correo=correo), 400
            abrir_sesion(crear_usuario(nombre, correo, clave, "admin"), nombre)
            flash("Cuenta de administrador creada.", "success")
            return redirect(url_for("admin_panel"))
        return render_template("admin_registro.html", nombre="", correo="")

    @app.route("/cuenta/entrar", methods=["GET", "POST"])
    def iniciar_sesion():
        if request.method == "POST":
            clave_ip = "login:" + (request.remote_addr or "?")
            if bloqueado(clave_ip, 10):
                return render_template(
                    "login.html", correo="",
                    error="Demasiados intentos. Espera unos minutos."), 429
            correo = request.form.get("correo", "").strip().lower()
            clave = request.form.get("contrasena", "")
            cuenta = None
            if correo and len(correo) <= 80:
                cuenta = usuarios.find_one({"correo": correo})
            hash_guardado = cuenta["clave"] if cuenta else hash_falso
            if check_password_hash(hash_guardado, clave) and cuenta:
                abrir_sesion(cuenta["_id"], cuenta["nombre"])
                flash("Bienvenido, " + cuenta["nombre"] + ".", "success")
                if cuenta.get("rol") == "admin":
                    return redirect(url_for("admin_panel"))
                return redirect(url_for("inicio"))
            anotar_fallo(clave_ip)
            return render_template(
                "login.html", correo=correo,
                error="Correo o contraseña incorrectos."), 401
        return render_template("login.html", correo="")

    @app.route("/cuenta/salir", methods=["POST"])
    def cerrar_sesion():
        session.clear()
        flash("Cerraste sesión.", "success")
        return redirect(url_for("inicio"))

    # ------------------------- Vistas del catalogo -------------------------
    @app.route("/producto/<id>")
    def producto_detalle(id):
        return render_template("producto.html", p=obtener_producto(id))

    @app.route("/producto/<id>/imagen")
    def producto_imagen(id):
        if not ObjectId.is_valid(id):
            abort(404, description="La clave del producto no es válida.")
        doc = imagenes.find_one({"_id": ObjectId(id)})
        if doc is None:
            abort(404, description="Este producto no tiene imagen.")
        r = make_response(bytes(doc["datos"]))
        r.headers["Content-Type"] = doc.get("tipo", "image/webp")
        r.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        r.headers["X-Content-Type-Options"] = "nosniff"
        return r

    # ------------------------- Panel de administrador -------------------------
    @app.route("/admin")
    @requiere_admin
    def admin_panel():
        lista = list(productos.find().sort("nombre", 1))
        pendientes = len(list(pedidos.find({"estado": "Pendiente"})))
        return render_template("admin.html", lista=lista, pendientes=pendientes)

    def categorias_existentes():
        """Categorías que ya usan los productos (sin repetir mayúsculas)."""
        try:
            vistas = {}
            for c in productos.distinct("categoria"):
                if isinstance(c, str) and c.strip():
                    vistas.setdefault(c.strip().lower(), c.strip())
            return sorted(vistas.values(), key=str.lower)
        except PyMongoError:
            return []

    def formulario_producto(modo, producto, destino):
        """Alta y edicion comparten la misma pantalla."""
        categorias = categorias_existentes()
        if request.method == "POST":
            form = request.form.to_dict()
            if form.get("categoria") == CATEGORIA_NUEVA:
                # "Crear nueva": usa lo escrito; si ya existe, reutiliza su escritura
                nueva = " ".join(form.get("categoria_nueva", "").split())
                form["categoria"] = {c.lower(): c for c in categorias}.get(
                    nueva.lower(), nueva)
            datos, error = leer_producto(form)
            imagen = None
            archivo = request.files.get("imagen")
            if not error and archivo and archivo.filename:
                imagen, error = preparar_imagen(archivo)
            if error:
                return render_template(
                    "admin_producto.html", modo=modo, p=producto or {},
                    f=request.form, error=error, categorias=categorias), 400
            quitar = request.form.get("quitar_imagen") == "1"
            if imagen or quitar:
                datos["imagen"] = bool(imagen)
                datos["img_v"] = int(time.time())
            if producto is None:
                datos.setdefault("imagen", False)
                datos.setdefault("img_v", int(time.time()))
                nuevo_id = productos.insert_one(datos).inserted_id
            else:
                nuevo_id = producto["_id"]
                productos.update_one({"_id": nuevo_id}, {"$set": datos})
            if imagen:
                guardar_imagen(nuevo_id, imagen)
            elif quitar:
                imagenes.delete_many({"_id": nuevo_id})
            flash("Producto guardado.", "success")
            return redirect(url_for("admin_panel"))
        return render_template("admin_producto.html", modo=modo,
                               p=producto or {}, f=None, error=None,
                               categorias=categorias)

    @app.route("/admin/producto/nuevo", methods=["GET", "POST"])
    @requiere_admin
    def admin_nuevo():
        return formulario_producto("nuevo", None, "admin_nuevo")

    @app.route("/admin/producto/<id>/editar", methods=["GET", "POST"])
    @requiere_admin
    def admin_editar(id):
        return formulario_producto("editar", obtener_producto(id), "admin_editar")

    @app.route("/admin/pedidos")
    @requiere_admin
    def admin_pedidos():
        lista = list(pedidos.find().sort("creado", -1).limit(200))
        return render_template("admin_pedidos.html", lista=lista)

    @app.route("/admin/pedidos/<id>/estado", methods=["POST"])
    @requiere_admin
    def admin_pedido_estado(id):
        estado = request.form.get("estado", "")
        if not ObjectId.is_valid(id) or estado not in ESTADOS_PEDIDO:
            abort(400, description="Pedido o estado no válido.")
        pedidos.update_one({"_id": ObjectId(id)}, {"$set": {"estado": estado}})
        flash("Estado del pedido actualizado.", "success")
        return redirect(url_for("admin_pedidos"))

    # ------------------------- Carrito -------------------------
    def armar_carrito():
        carrito = session.get("carrito", {})
        ids = [ObjectId(i) for i in carrito if ObjectId.is_valid(i)]
        filas = []
        for p in productos.find({"_id": {"$in": ids}}).sort("nombre", 1):
            clave = str(p["_id"])
            cantidad = carrito[clave]
            precio = p.get("precio_cent")
            ok = p.get("estado") == "Disponible" and isinstance(precio, int)
            filas.append({
                "id": clave, "p": p, "nombre": p["nombre"],
                "categoria": p["categoria"], "cantidad": cantidad,
                "precio": precio if ok else None, "ok": ok,
                "subtotal": precio * cantidad if ok else 0,
                "motivo": ("Agotado" if p.get("estado") != "Disponible"
                           else "Sin precio"),
            })
        vigentes = {f["id"] for f in filas}
        if set(carrito) != vigentes:  # quita productos que ya no existen
            session["carrito"] = {k: v for k, v in carrito.items()
                                  if k in vigentes}
        return filas, sum(f["subtotal"] for f in filas)

    @app.route("/carrito")
    @requiere_sesion
    def ver_carrito():
        filas, total_cent = armar_carrito()
        return render_template(
            "carrito.html", filas=filas, total_cent=total_cent,
            total=sum(f["cantidad"] for f in filas),
            hay_problemas=any(not f["ok"] for f in filas))

    @app.route("/carrito/agregar/<id>", methods=["POST"])
    @requiere_sesion
    def carrito_agregar(id):
        producto = obtener_producto(id)
        destino = volver_a(url_for("inicio") + "#lista")
        if producto.get("estado") != "Disponible":
            flash("Ese producto está agotado.", "warning")
            return redirect(destino)
        if not isinstance(producto.get("precio_cent"), int):
            flash("Ese producto todavía no tiene precio.", "warning")
            return redirect(destino)
        try:
            cantidad = int(request.form.get("cantidad", "1"))
        except ValueError:
            cantidad = 1
        cantidad = max(1, min(cantidad, MAX_POR_PRODUCTO))
        carrito = dict(session.get("carrito", {}))
        clave = str(producto["_id"])
        if clave not in carrito and len(carrito) >= MAX_PRODUCTOS:
            flash("Tu carrito ya tiene el máximo de productos.", "warning")
            return redirect(destino)
        carrito[clave] = min(carrito.get(clave, 0) + cantidad, MAX_POR_PRODUCTO)
        session["carrito"] = carrito
        flash("Agregaste «" + producto["nombre"] + "» al carrito.", "success")
        return redirect(destino)

    @app.route("/carrito/cambiar/<id>", methods=["POST"])
    @requiere_sesion
    def carrito_cambiar(id):
        carrito = dict(session.get("carrito", {}))
        accion = request.form.get("accion", "")
        if id in carrito and accion in ("mas", "menos", "quitar"):
            if accion == "mas":
                carrito[id] = min(carrito[id] + 1, MAX_POR_PRODUCTO)
            elif accion == "menos":
                carrito[id] -= 1
            else:
                carrito[id] = 0
            if carrito[id] <= 0:
                del carrito[id]
            session["carrito"] = carrito
        return redirect(url_for("ver_carrito"))

    @app.route("/carrito/vaciar", methods=["POST"])
    @requiere_sesion
    def carrito_vaciar():
        session["carrito"] = {}
        flash("Vaciaste el carrito.", "success")
        return redirect(url_for("ver_carrito"))

    # ------------------------- Pedidos -------------------------
    @app.route("/pedido/confirmar", methods=["GET", "POST"])
    @requiere_sesion
    def confirmar_pedido():
        filas, total_cent = armar_carrito()
        if not filas:
            flash("Tu carrito está vacío.", "warning")
            return redirect(url_for("ver_carrito"))
        if any(not f["ok"] for f in filas):
            flash("Quita del carrito los productos agotados o sin precio.",
                  "warning")
            return redirect(url_for("ver_carrito"))
        datos = {"nombre": session.get("nombre", ""), "telefono": "",
                 "direccion": "", "metodo": METODOS_PAGO[0]}
        error = None
        if request.method == "POST":
            for campo in datos:
                datos[campo] = request.form.get(campo, "").strip()
            if not datos["nombre"] or not datos["direccion"]:
                error = "Escribe tu nombre y la dirección de entrega."
            elif len(datos["nombre"]) > 60 or len(datos["direccion"]) > 160:
                error = "Máximo: nombre 60 y dirección 160 caracteres."
            elif not re.fullmatch(r"[0-9 +()-]{8,20}", datos["telefono"]):
                error = "Escribe un teléfono válido (solo números, 8 a 20)."
            elif datos["metodo"] not in METODOS_PAGO:
                error = "Selecciona un método de pago."
            if not error:
                pedido = pedidos.insert_one({
                    "usuario_id": session["uid"],
                    "usuario": session.get("nombre", ""),
                    "items": [{"id": f["id"], "nombre": f["nombre"],
                               "precio_cent": f["precio"],
                               "cantidad": f["cantidad"]} for f in filas],
                    "total_cent": total_cent,
                    "estado": "Pendiente",
                    "contacto": {"nombre": datos["nombre"],
                                 "telefono": datos["telefono"],
                                 "direccion": datos["direccion"]},
                    "metodo": datos["metodo"],
                    "creado": datetime.now(timezone.utc),
                })
                session["carrito"] = {}
                flash("Pedido #" + str(pedido.inserted_id)[-6:].upper()
                      + " registrado. Gracias por tu compra.", "success")
                return redirect(url_for("mis_pedidos"))
        return render_template("pedido.html", filas=filas,
                               total_cent=total_cent, d=datos, error=error), (
                                   400 if error else 200)

    @app.route("/mis-pedidos")
    @requiere_sesion
    def mis_pedidos():
        lista = list(pedidos.find({"usuario_id": session["uid"]})
                     .sort("creado", -1))
        return render_template("mis_pedidos.html", lista=lista)

    @app.route("/mis-pedidos/<id>/cancelar", methods=["POST"])
    @requiere_sesion
    def cancelar_pedido(id):
        if not ObjectId.is_valid(id):
            abort(404, description="Ese pedido no existe.")
        pedido = pedidos.find_one({"_id": ObjectId(id)})
        if pedido is None or pedido.get("usuario_id") != session["uid"]:
            abort(404, description="Ese pedido no existe.")
        if pedido.get("estado") != "Pendiente":
            flash("Solo se pueden cancelar pedidos pendientes.", "warning")
        else:
            pedidos.update_one({"_id": pedido["_id"]},
                               {"$set": {"estado": "Cancelado"}})
            flash("Pedido cancelado.", "success")
        return redirect(url_for("mis_pedidos"))
