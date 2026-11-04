"""Tienda Zultek: cuentas, administrador, precios, carrito y pedidos.

Este archivo solo AGREGA rutas. No modifica el CRUD de la pagina
(/agregar, /editar, /eliminar) ni la API (/api/productos...):
- Las rutas /agregar, /editar y /eliminar siguen existiendo, pero ahora
  solo las puede usar un administrador (ver proteger_crud).
- El panel de administrador (/admin) agrega y edita productos con su
  precio, descripcion e imagen escribiendo en la misma coleccion
  "productos". Otras colecciones: usuarios, imagenes, pedidos.
- El carrito es una RESERVA TEMPORAL guardada en Atlas (coleccion "reservas");
  el pedido guarda los precios del momento y descuenta las existencias.
- No hay cobro real: el pago es simulado y NO se piden datos de tarjeta.
"""
import hmac
import io
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from urllib.parse import urlsplit

from bson import Binary, ObjectId
from flask import (abort, flash, g, jsonify, make_response, redirect,
                   render_template, request, session, url_for)
from PIL import Image
from pymongo import ReturnDocument
from pymongo.errors import PyMongoError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

MAX_POR_PRODUCTO = 10
MAX_PRODUCTOS = 40
MAX_EXISTENCIAS = 9999
# Minutos que dura una reserva. En Render se puede cambiar con RESERVA_MINUTOS
# (por ejemplo 1 para probar el vencimiento sin esperar 5 minutos).
DURACION_RESERVA_MINUTOS = max(1, min(int(os.environ.get("RESERVA_MINUTOS", "5")), 60))
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


def ahora_utc():
    return datetime.now(timezone.utc)


def segundos_restantes(vence):
    """Segundos que faltan para vence_en (solo informa; el servidor decide)."""
    if not isinstance(vence, datetime):
        return 0
    if vence.tzinfo is None:
        vence = vence.replace(tzinfo=timezone.utc)
    return max(0, int((vence - ahora_utc()).total_seconds()))


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
    try:
        existencias = int(form.get("existencias", "").strip())
    except ValueError:
        existencias = None
    error = None
    if not nombre or not categoria or not estado:
        error = "Completa nombre, categoría y estado."
    elif len(nombre) > 80 or len(categoria) > 20:
        error = "Máximo: nombre 80 y categoría 20 caracteres."
    elif estado not in ESTADOS_PRODUCTO:
        error = "Selecciona un estado válido."
    elif precio is None:
        error = "Escribe un precio válido, por ejemplo 1299.50."
    elif existencias is None or not 0 <= existencias <= MAX_EXISTENCIAS:
        error = "Las existencias deben ser un número entero entre 0 y 9999."
    elif len(descripcion) > 300:
        error = "La descripción admite hasta 300 caracteres."
    datos = {"nombre": nombre, "categoria": categoria, "estado": estado,
             "precio_cent": precio, "descripcion": descripcion,
             "existencias": existencias if existencias is not None else 0}
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
    reservas = base_datos["reservas"]
    cliente = base_datos.client

    try:
        reservas.create_index([("reserva_id", 1), ("producto_id", 1)],
                              unique=True, name="reserva_producto_unico")
        reservas.create_index("vence_en", name="vence_en")
        # Productos anteriores: valores iniciales. Es seguro repetirlo porque
        # solo toca documentos que todavia no tienen el campo.
        # El 10 es solo para pruebas: despues el administrador pone la existencia real.
        productos.update_many({"existencias": {"$exists": False}},
                              {"$set": {"existencias": 10}})
        productos.update_many({"reservadas": {"$exists": False}},
                              {"$set": {"reservadas": 0}})
    except PyMongoError as error:
        app.logger.warning("No se pudo preparar la reserva en Atlas: %s", error)

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
        try:  # unidades apartadas (activas) en Atlas para este visitante
            activas = (reservas_activas(session.get("reserva_id"))
                       if session.get("uid") else [])
        except PyMongoError:
            activas = []
        try:  # categorías para la barra de navegación (buscador)
            categorias_nav = sorted(
                (c for c in productos.distinct("categoria") if isinstance(c, str)),
                key=str.lower)
        except PyMongoError:
            categorias_nav = []
        return {
            "usuario": session.get("nombre"),
            "es_admin": es_admin() if session.get("uid") else False,
            "carrito_total": sum(int(i["cantidad"]) for i in activas),
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
        try:  # lo apartado vuelve a estar disponible para los demas
            cancelar_todo(session.get("reserva_id"))
        except PyMongoError:
            pass
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
                datos["reservadas"] = 0
                nuevo_id = productos.insert_one(datos).inserted_id
            else:
                nuevo_id = producto["_id"]
                # No se pueden dejar menos existencias que las unidades apartadas.
                resultado = productos.update_one(
                    {"_id": nuevo_id,
                     "$expr": {"$lte": [{"$ifNull": ["$reservadas", 0]},
                                        datos["existencias"]]}},
                    {"$set": datos})
                if resultado.matched_count == 0:
                    return render_template(
                        "admin_producto.html", modo=modo, p=producto or {},
                        f=request.form, categorias=categorias, error=(
                            "Hay más unidades apartadas por clientes que las "
                            "existencias que escribiste. Sube la cantidad o "
                            "espera a que venzan las reservas.")), 400
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
        actual = pedidos.find_one({"_id": ObjectId(id)})
        if actual is None:
            abort(404, description="Ese pedido no existe.")
        if estado == "Cancelado":
            # Cancelar devuelve las unidades a las existencias.
            en_transaccion(lambda ms: cancelar_y_devolver(actual["_id"], ms))
        elif actual.get("estado") == "Cancelado":
            flash("Un pedido cancelado no se puede reactivar: ya se devolvieron "
                  "sus existencias.", "warning")
            return redirect(url_for("admin_pedidos"))
        else:
            pedidos.update_one({"_id": actual["_id"]}, {"$set": {"estado": estado}})
        flash("Estado del pedido actualizado.", "success")
        return redirect(url_for("admin_pedidos"))

    # ------------------------- Reserva temporal -------------------------
    # La reserva vive en Atlas. El contador de la pagina solo informa: quien
    # decide si una unidad esta libre es la operacion atomica de MongoDB.
    class PedidoRechazado(Exception):
        pass

    def obtener_reserva_id():
        if not session.get("reserva_id"):
            session["reserva_id"] = uuid.uuid4().hex
        return session["reserva_id"]

    def en_transaccion(operacion):
        """Ejecuta operacion(ms) en una transaccion de Atlas (con reintentos)."""
        with cliente.start_session() as ms:
            return ms.with_transaction(operacion)

    def disponibles_de(p):
        return max(0, int(p.get("existencias", 0) or 0)
                   - int(p.get("reservadas", 0) or 0))

    def reservas_activas(reserva_id):
        if not reserva_id:
            return []
        return list(reservas.find({"reserva_id": reserva_id, "estado": "activa",
                                   "vence_en": {"$gt": ahora_utc()}}))

    def reservar(oid, reserva_id, cantidad):
        """Aparta unidades SOLO si siguen libres. -> (codigo, unidades)."""
        def operacion(ms):
            ahora = ahora_utc()
            vence = ahora + timedelta(minutes=DURACION_RESERVA_MINUTOS)
            actual = reservas.find_one(
                {"reserva_id": reserva_id, "producto_id": oid,
                 "estado": "activa"}, session=ms)
            ya = int(actual["cantidad"]) if actual else 0
            permitido = min(cantidad, MAX_POR_PRODUCTO - ya)
            if permitido <= 0:
                return "limite", 0
            # Revisar y apartar en UN solo movimiento: aqui se evita vender
            # dos veces la ultima unidad.
            producto = productos.find_one_and_update(
                {"_id": oid, "estado": "Disponible",
                 "precio_cent": {"$type": "number"},
                 "$expr": {"$gte": [
                     {"$subtract": [{"$ifNull": ["$existencias", 0]},
                                    {"$ifNull": ["$reservadas", 0]}]},
                     permitido]}},
                {"$inc": {"reservadas": permitido}},
                return_document=ReturnDocument.AFTER, session=ms)
            if producto is None:
                return "sin_disponibilidad", 0
            reservas.update_one(
                {"reserva_id": reserva_id, "producto_id": oid},
                {"$inc": {"cantidad": permitido},
                 "$set": {"estado": "activa", "vence_en": vence},
                 "$setOnInsert": {"creada_en": ahora}},
                upsert=True, session=ms)
            return "ok", permitido
        return en_transaccion(operacion)

    def devolver(oid, reserva_id, cantidad=None):
        """Libera unidades apartadas (todas si cantidad es None)."""
        def operacion(ms):
            reserva = reservas.find_one(
                {"reserva_id": reserva_id, "producto_id": oid,
                 "estado": "activa"}, session=ms)
            if reserva is None:
                return 0
            total = int(reserva["cantidad"])
            n = total if cantidad is None else min(cantidad, total)
            if n >= total:
                reservas.delete_one({"_id": reserva["_id"]}, session=ms)
            else:
                reservas.update_one({"_id": reserva["_id"]},
                                    {"$inc": {"cantidad": -n}}, session=ms)
            productos.update_one({"_id": oid}, {"$inc": {"reservadas": -n}},
                                 session=ms)
            return n
        return en_transaccion(operacion)

    def cancelar_todo(reserva_id):
        if not reserva_id:
            return
        for r in list(reservas.find({"reserva_id": reserva_id,
                                     "estado": "activa"})):
            devolver(r["producto_id"], reserva_id)

    def liberar_vencidas():
        """Devuelve a disponibilidad las reservas cuyo vence_en ya paso."""
        vencidas = list(reservas.find({"estado": "activa",
                                       "vence_en": {"$lte": ahora_utc()}}))
        for candidata in vencidas:
            def operacion(ms, candidata=candidata):
                eliminada = reservas.find_one_and_delete(
                    {"_id": candidata["_id"], "estado": "activa"}, session=ms)
                if eliminada:  # solo una vez, aunque dos peticiones coincidan
                    productos.update_one(
                        {"_id": eliminada["producto_id"]},
                        {"$inc": {"reservadas": -int(eliminada["cantidad"])}},
                        session=ms)
            en_transaccion(operacion)

    ENDPOINTS_CON_RESERVA = {
        "inicio", "producto_detalle", "ver_carrito", "carrito_agregar",
        "carrito_cambiar", "carrito_vaciar", "confirmar_pedido", "admin_panel"}

    @app.before_request
    def liberar_antes_de_responder():
        if request.endpoint in ENDPOINTS_CON_RESERVA:
            liberar_vencidas()

    def cancelar_y_devolver(pedido_id, ms, solo_pendiente=False, usuario_id=None):
        """Marca el pedido como Cancelado y devuelve sus unidades a existencias."""
        filtro = {"_id": pedido_id, "estado": {"$ne": "Cancelado"}}
        if solo_pendiente:
            filtro["estado"] = "Pendiente"
        if usuario_id is not None:
            filtro["usuario_id"] = usuario_id
        pedido = pedidos.find_one_and_update(
            filtro, {"$set": {"estado": "Cancelado"}}, session=ms)
        if pedido and pedido.get("stock_descontado"):
            for item in pedido.get("items", []):
                if ObjectId.is_valid(item.get("id")):
                    productos.update_one(
                        {"_id": ObjectId(item["id"])},
                        {"$inc": {"existencias": int(item["cantidad"])}},
                        session=ms)
        return bool(pedido)

    # ------------------------- Carrito (lee las reservas de Atlas) -------------------------
    def armar_carrito():
        activas = reservas_activas(session.get("reserva_id"))
        ids = [i["producto_id"] for i in activas]
        por_id = {p["_id"]: p for p in productos.find({"_id": {"$in": ids}})}
        filas = []
        for item in activas:
            p = por_id.get(item["producto_id"])
            if p is None:  # el producto se elimino: la reserva queda huerfana
                reservas.delete_one({"_id": item["_id"]})
                continue
            cantidad = int(item["cantidad"])
            precio = p.get("precio_cent")
            # Una unidad ya apartada sigue siendo de este carrito aunque el
            # producto aparezca sin disponibilidad para los demas.
            ok = isinstance(precio, int)
            filas.append({
                "id": str(p["_id"]), "p": p, "nombre": p["nombre"],
                "categoria": p["categoria"], "cantidad": cantidad,
                "precio": precio if ok else None, "ok": ok,
                "subtotal": precio * cantidad if ok else 0,
                "motivo": "Sin precio", "vence_en": item["vence_en"],
            })
        filas.sort(key=lambda f: f["nombre"].lower())
        vence = min((f["vence_en"] for f in filas), default=None)
        return filas, sum(f["subtotal"] for f in filas), vence

    @app.route("/carrito")
    @requiere_sesion
    def ver_carrito():
        filas, total_cent, vence = armar_carrito()
        return render_template(
            "carrito.html", filas=filas, total_cent=total_cent,
            total=sum(f["cantidad"] for f in filas),
            hay_problemas=any(not f["ok"] for f in filas),
            vence_en=vence, restante=segundos_restantes(vence),
            minutos_reserva=DURACION_RESERVA_MINUTOS)

    def avisar_sin_disponibilidad(producto_id, nombre):
        actual = productos.find_one({"_id": producto_id}) or {}
        quedan = disponibles_de(actual)
        if actual.get("estado") != "Disponible":
            flash("«" + nombre + "» ya no está disponible.", "warning")
        elif quedan > 0:
            flash("Solo quedan " + str(quedan) + " unidad(es) de «" + nombre
                  + "» disponibles ahora mismo.", "warning")
        else:
            flash("«" + nombre + "» ya no tiene unidades disponibles: otra "
                  "persona las acaba de apartar. Puede liberarse si no "
                  "confirma a tiempo.", "warning")

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
        reserva_id = obtener_reserva_id()
        activas = reservas_activas(reserva_id)
        if (producto["_id"] not in {i["producto_id"] for i in activas}
                and len(activas) >= MAX_PRODUCTOS):
            flash("Tu carrito ya tiene el máximo de productos.", "warning")
            return redirect(destino)
        codigo, apartadas = reservar(producto["_id"], reserva_id, cantidad)
        if codigo == "ok":
            flash("Apartaste " + str(apartadas) + " × «" + producto["nombre"]
                  + "» durante " + str(DURACION_RESERVA_MINUTOS)
                  + " minutos. Confirma tu pedido antes de que termine.",
                  "success")
        elif codigo == "limite":
            flash("Ya tienes el máximo de unidades de ese producto.", "warning")
        else:
            avisar_sin_disponibilidad(producto["_id"], producto["nombre"])
        return redirect(destino)

    @app.route("/carrito/cambiar/<id>", methods=["POST"])
    @requiere_sesion
    def carrito_cambiar(id):
        if not ObjectId.is_valid(id):
            abort(404, description="La clave del producto no es válida.")
        oid = ObjectId(id)
        reserva_id = session.get("reserva_id")
        accion = request.form.get("accion", "")
        if reserva_id and accion in ("mas", "menos", "quitar"):
            if accion == "mas":
                codigo, _ = reservar(oid, reserva_id, 1)
                if codigo == "limite":
                    flash("Ya tienes el máximo de unidades de ese producto.",
                          "warning")
                elif codigo != "ok":
                    avisar_sin_disponibilidad(oid, "este producto")
            elif accion == "menos":
                devolver(oid, reserva_id, 1)
            else:
                devolver(oid, reserva_id)
                flash("Reserva cancelada: el producto quedó libre.", "success")
        return redirect(url_for("ver_carrito"))

    @app.route("/carrito/vaciar", methods=["POST"])
    @requiere_sesion
    def carrito_vaciar():
        cancelar_todo(session.get("reserva_id"))
        flash("Vaciaste el carrito. Los productos quedaron libres.", "success")
        return redirect(url_for("ver_carrito"))

    # ------------------------- Pedidos -------------------------
    def crear_pedido(reserva_id, datos):
        """Confirma TODO o nada: revisa reservas, descuenta, crea pedido, cierra."""
        def operacion(ms):
            ahora = ahora_utc()
            items = list(reservas.find(
                {"reserva_id": reserva_id, "estado": "activa",
                 "vence_en": {"$gt": ahora}}, session=ms))
            if not items:
                raise PedidoRechazado(
                    "Tu reserva venció. Vuelve a agregar los productos.")
            lineas, total = [], 0
            for item in items:
                n = int(item["cantidad"])
                p = productos.find_one_and_update(
                    {"_id": item["producto_id"],
                     "precio_cent": {"$type": "number"},
                     "existencias": {"$gte": n}, "reservadas": {"$gte": n}},
                    {"$inc": {"existencias": -n, "reservadas": -n}},
                    session=ms)
                if p is None:
                    raise PedidoRechazado(
                        "No fue posible confirmar: un producto cambió o ya no existe.")
                lineas.append({"id": str(p["_id"]), "nombre": p["nombre"],
                               "precio_cent": p["precio_cent"], "cantidad": n})
                total += p["precio_cent"] * n
            cerradas = reservas.delete_many(
                {"_id": {"$in": [i["_id"] for i in items]},
                 "estado": "activa"}, session=ms)
            if cerradas.deleted_count != len(items):
                raise PedidoRechazado("Tu reserva cambió. Revisa tu carrito.")
            return pedidos.insert_one({
                "usuario_id": session["uid"],
                "usuario": session.get("nombre", ""),
                "items": lineas,
                "total_cent": total,
                "estado": "Pendiente",
                "contacto": {"nombre": datos["nombre"],
                             "telefono": datos["telefono"],
                             "direccion": datos["direccion"]},
                "metodo": datos["metodo"],
                "stock_descontado": True,
                "creado": ahora,
            }, session=ms).inserted_id
        return en_transaccion(operacion)

    @app.route("/pedido/confirmar", methods=["GET", "POST"])
    @requiere_sesion
    def confirmar_pedido():
        filas, total_cent, vence = armar_carrito()
        if not filas:
            flash("Tu carrito está vacío o tu reserva venció.", "warning")
            return redirect(url_for("ver_carrito"))
        if any(not f["ok"] for f in filas):
            flash("Quita del carrito los productos sin precio.", "warning")
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
                try:
                    pedido_id = crear_pedido(session.get("reserva_id"), datos)
                except PedidoRechazado as rechazo:
                    flash(str(rechazo), "warning")
                    return redirect(url_for("ver_carrito"))
                session.pop("reserva_id", None)
                flash("Pedido #" + str(pedido_id)[-6:].upper()
                      + " registrado. Gracias por tu compra.", "success")
                return redirect(url_for("mis_pedidos"))
        return render_template("pedido.html", filas=filas,
                               total_cent=total_cent, d=datos, error=error,
                               vence_en=vence,
                               restante=segundos_restantes(vence)), (
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
            en_transaccion(lambda ms: cancelar_y_devolver(
                pedido["_id"], ms, solo_pendiente=True,
                usuario_id=session["uid"]))
            flash("Pedido cancelado.", "success")
        return redirect(url_for("mis_pedidos"))
