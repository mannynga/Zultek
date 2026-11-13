"""Zultek: reserva temporal (apartado) de existencias y codigo QR.

Elemento que se reserva: UNIDADES de un producto (modelo "Cantidad").
Cada producto guarda en MongoDB el campo "existencias" = unidades LIBRES.

Como se evita la doble reserva
------------------------------
Apartar descuenta las unidades con UNA sola operacion atomica de MongoDB:

    find_one_and_update({_id, estado: "Disponible", existencias >= N},
                        {$inc: {existencias: -N}})

Si dos personas piden la ultima unidad al mismo tiempo, MongoDB ejecuta
una operacion despues de la otra: la primera la recibe y la segunda ve
existencias = 0 y es rechazada. No se lee primero y se escribe despues.

Ciclo de vida de una reserva (coleccion "reservas")
---------------------------------------------------
    temporal --confirmar--> confirmada   (las unidades quedan apartadas)
    temporal --cancelar---> cancelada    (las unidades regresan)
    temporal --vence------> vencida      (las unidades regresan)

Cada cambio de estado es otra operacion atomica con filtro
estado == "temporal"; solo una (confirmar, cancelar o vencer) puede ganar,
asi las unidades nunca se devuelven dos veces.

Vencimiento
-----------
"expira_en" se guarda en MongoDB. El contador de la pantalla solo ayuda a
verlo: quien decide es el servidor. Antes de mostrar o reservar se liberan
las reservas vencidas, asi cerrar la pestana no deja nada bloqueado.
"""
import io
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

import segno
from bson import ObjectId
from flask import (abort, flash, jsonify, make_response, redirect,
                   render_template, request, session, url_for)
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

MAX_APARTADO = 10             # unidades por reserva
EXISTENCIAS_INICIALES = 10    # a productos viejos sin el campo "existencias"
FOLIO_VALIDO = re.compile(r"[A-Z0-9-]{4,16}")

ETIQUETAS = {
    "temporal": "Apartado",
    "confirmada": "Confirmada",
    "cancelada": "Cancelada",
    "vencida": "Vencida",
}

# Paginas que antes de mostrarse liberan las reservas que ya vencieron
ENDPOINTS_CON_LIMPIEZA = {
    "inicio", "producto_detalle", "reservar", "ver_reserva", "mi_reserva",
    "cancelar_reserva", "confirmar_reserva", "api_reserva",
}


def minutos_reserva():
    """Duracion de la reserva: 5 minutos (RESERVA_MINUTOS puede bajarla a 3)."""
    try:
        minutos = int(os.environ.get("RESERVA_MINUTOS", "5"))
    except ValueError:
        minutos = 5
    return max(3, min(5, minutos))


def ahora():
    return datetime.now(timezone.utc)


def como_utc(valor):
    """MongoDB devuelve fechas sin zona; siempre son UTC."""
    if valor.tzinfo is None:
        return valor.replace(tzinfo=timezone.utc)
    return valor


def registrar_reservas(app, base_datos):
    productos = base_datos["productos"]
    reservas = base_datos["reservas"]
    estado_arranque = {"listo": False}

    # ------------------------- Preparacion -------------------------
    def preparar():
        """Una vez por proceso: indices y existencias de productos viejos."""
        if estado_arranque["listo"]:
            return
        reservas.create_index("folio", unique=True)
        reservas.create_index([("estado", 1), ("expira_en", 1)])
        reservas.create_index("visitante_id")
        # Productos creados antes de esta mejora no tienen "existencias"
        productos.update_many(
            {"existencias": {"$exists": False}, "estado": "Disponible"},
            {"$set": {"existencias": EXISTENCIAS_INICIALES}})
        productos.update_many(
            {"existencias": {"$exists": False}},
            {"$set": {"existencias": 0}})
        estado_arranque["listo"] = True

    def asegurar_existencias(producto):
        """Producto creado despues del arranque (p. ej. por /agregar)."""
        if "existencias" not in producto:
            inicial = (EXISTENCIAS_INICIALES
                       if producto.get("estado") == "Disponible" else 0)
            productos.update_one(
                {"_id": producto["_id"], "existencias": {"$exists": False}},
                {"$set": {"existencias": inicial}})

    # ------------------------- Liberacion de unidades -------------------------
    def devolver_unidades(reserva):
        productos.update_one({"_id": reserva["recurso_id"]},
                             {"$inc": {"existencias": reserva["cantidad"]}})

    def liberar_vencidas():
        """Marca como vencidas las reservas cuyo tiempo termino y devuelve
        sus unidades. Cada reserva se reclama de forma atomica."""
        preparar()
        for _ in range(200):
            momento = ahora()
            reserva = reservas.find_one_and_update(
                {"estado": "temporal", "expira_en": {"$lte": momento}},
                {"$set": {"estado": "vencida", "cerrada_en": momento}})
            if reserva is None:
                break
            devolver_unidades(reserva)

    def cancelar(reserva):
        """True si esta llamada fue la que cancelo (y devolvio unidades)."""
        momento = ahora()
        cerrada = reservas.find_one_and_update(
            {"_id": reserva["_id"], "estado": "temporal"},
            {"$set": {"estado": "cancelada", "cerrada_en": momento}})
        if cerrada is None:
            return False
        devolver_unidades(cerrada)
        return True

    def confirmar(reserva):
        """True si se confirmo a tiempo. Una reserva vencida no se confirma."""
        momento = ahora()
        confirmada = reservas.find_one_and_update(
            {"_id": reserva["_id"], "estado": "temporal",
             "expira_en": {"$gt": momento}},
            {"$set": {"estado": "confirmada", "confirmada_en": momento}})
        return confirmada is not None

    # ------------------------- Utilidades -------------------------
    def visitante_id():
        """Identifica a quien reserva (sesion), tenga o no cuenta."""
        visitante = session.get("visitante")
        if not (isinstance(visitante, str) and len(visitante) == 32):
            visitante = secrets.token_hex(16)
            session["visitante"] = visitante
        return visitante

    def reserva_activa(visitante):
        return reservas.find_one({"visitante_id": visitante,
                                  "estado": "temporal",
                                  "expira_en": {"$gt": ahora()}})

    def buscar_reserva(folio):
        folio = (folio or "").strip().upper()
        if not FOLIO_VALIDO.fullmatch(folio):
            abort(404, description="El folio no tiene un formato válido. "
                                   "Revisa el comprobante o el código QR.")
        reserva = reservas.find_one({"folio": folio})
        if reserva is None:
            abort(404, description="No existe una reserva con el folio «"
                                   + folio + "».")
        return reserva

    def segundos_restantes(reserva):
        if reserva.get("estado") != "temporal":
            return 0
        resto = como_utc(reserva["expira_en"]) - ahora()
        return max(0, int(resto.total_seconds()))

    def unidades_apartadas(producto_id):
        """Unidades de un producto apartadas ahora por reservas temporales."""
        vigentes = reservas.find(
            {"recurso_id": producto_id, "estado": "temporal",
             "expira_en": {"$gt": ahora()}})
        return sum(r["cantidad"] for r in vigentes)

    def base_publica():
        """Direccion publica del sitio. Para el QR nunca debe ser localhost
        en la entrega final: en Render se usa su URL publica."""
        for variable in ("APP_BASE_URL", "RENDER_EXTERNAL_URL"):
            valor = os.environ.get(variable, "").strip().rstrip("/")
            if valor.startswith(("http://", "https://")):
                return valor
        return request.url_root.rstrip("/")

    def enlace_publico(endpoint, **valores):
        return base_publica() + url_for(endpoint, **valores)

    def imagen_qr(direccion, nombre_archivo):
        salida = io.BytesIO()
        segno.make(direccion, error="m", micro=False).save(
            salida, kind="png", scale=8, border=3)
        respuesta = make_response(salida.getvalue())
        respuesta.headers["Content-Type"] = "image/png"
        respuesta.headers["Cache-Control"] = "no-store"
        if request.args.get("descargar") == "1":
            respuesta.headers["Content-Disposition"] = (
                'attachment; filename="' + nombre_archivo + '"')
        return respuesta

    def nuevo_folio():
        return "ZK-" + secrets.token_hex(3).upper()

    def propia_o_403(reserva):
        if reserva.get("visitante_id") != session.get("visitante"):
            abort(403, description="Solo quien hizo la reserva puede "
                                   "confirmarla o cancelarla.")

    # ------------------------- Plantillas -------------------------
    app.jinja_env.globals.update(
        apartadas=unidades_apartadas, enlace_publico=enlace_publico,
        ETIQUETAS_RESERVA=ETIQUETAS)

    @app.context_processor
    def datos_reserva():
        return {"reserva_folio": session.get("reserva_folio"),
                "MINUTOS_RESERVA": minutos_reserva()}

    @app.before_request
    def limpiar_vencidas():
        if request.endpoint in ENDPOINTS_CON_LIMPIEZA:
            liberar_vencidas()

    # ------------------------- Reservar -------------------------
    @app.route("/producto/<id>/apartar", methods=["POST"])
    def reservar(id):
        if not ObjectId.is_valid(id):
            abort(404, description="La clave del producto no es válida.")
        producto_id = ObjectId(id)
        producto = productos.find_one({"_id": producto_id})
        if producto is None:
            abort(404, description="Este producto ya no existe.")
        ficha = url_for("producto_detalle", id=id)

        visitante = visitante_id()
        activa = reserva_activa(visitante)
        if activa:
            flash("Ya tienes una reserva activa (folio " + activa["folio"]
                  + "). Confírmala o cancélala antes de apartar otro "
                  "producto.", "warning")
            return redirect(url_for("ver_reserva", folio=activa["folio"]))

        try:
            cantidad = int(request.form.get("cantidad", "1"))
        except ValueError:
            cantidad = 0
        if not 1 <= cantidad <= MAX_APARTADO:
            flash("Elige una cantidad entre 1 y " + str(MAX_APARTADO) + ".",
                  "warning")
            return redirect(ficha)

        asegurar_existencias(producto)
        # Paso atomico: descuenta solo si todavia alcanzan las unidades.
        tomado = productos.find_one_and_update(
            {"_id": producto_id, "estado": "Disponible",
             "existencias": {"$gte": cantidad}},
            {"$inc": {"existencias": -cantidad}},
            return_document=ReturnDocument.AFTER)
        if tomado is None:
            actual = productos.find_one({"_id": producto_id})
            if actual is None:
                abort(404, description="Este producto ya no existe.")
            libres = actual.get("existencias", 0)
            if actual.get("estado") != "Disponible":
                mensaje = "Este producto está agotado."
            elif libres <= 0:
                mensaje = ("Por ahora todas las unidades están apartadas por "
                           "otros clientes. Intenta de nuevo en unos minutos.")
            else:
                mensaje = ("Solo hay " + str(libres) + " unidad"
                           + ("" if libres == 1 else "es")
                           + " disponible" + ("" if libres == 1 else "s")
                           + " en este momento.")
            flash(mensaje, "warning")
            return redirect(ficha)

        minutos = minutos_reserva()
        inicio = ahora()
        precio = producto.get("precio_cent")
        documento = {
            "recurso_id": producto_id,
            "producto_nombre": producto.get("nombre", ""),
            "visitante_id": visitante,
            "cantidad": cantidad,
            "precio_cent": precio if isinstance(precio, int) else None,
            "total_cent": (precio * cantidad
                           if isinstance(precio, int) else None),
            "estado": "temporal",
            "minutos": minutos,
            "creada_en": inicio,
            "expira_en": inicio + timedelta(minutes=minutos),
        }
        guardada = False
        for _ in range(6):
            documento["folio"] = nuevo_folio()
            try:
                reservas.insert_one(documento)
                guardada = True
                break
            except DuplicateKeyError:
                documento.pop("_id", None)   # folio repetido: otro intento
            except Exception:
                productos.update_one({"_id": producto_id},
                                     {"$inc": {"existencias": cantidad}})
                raise
        if not guardada:
            productos.update_one({"_id": producto_id},
                                 {"$inc": {"existencias": cantidad}})
            flash("No se pudo crear la reserva. Intenta de nuevo.", "danger")
            return redirect(ficha)

        session["reserva_folio"] = documento["folio"]
        flash("Apartaste " + str(cantidad) + " × «"
              + producto.get("nombre", "") + "» por " + str(minutos)
              + " minutos. Confirma antes de que termine el tiempo.",
              "success")
        return redirect(url_for("ver_reserva", folio=documento["folio"]))

    # ------------------------- Ver, cancelar, confirmar -------------------------
    @app.route("/reserva/<folio>")
    def ver_reserva(folio):
        reserva = buscar_reserva(folio)
        producto = productos.find_one({"_id": reserva["recurso_id"]})
        return render_template(
            "reserva.html", r=reserva, producto=producto,
            es_dueno=reserva.get("visitante_id") == session.get("visitante"),
            segundos=segundos_restantes(reserva))

    @app.route("/mi-reserva")
    def mi_reserva():
        folio = session.get("reserva_folio")
        if not folio:
            flash("Todavía no has apartado ningún producto.", "warning")
            return redirect(url_for("inicio"))
        return redirect(url_for("ver_reserva", folio=folio))

    @app.route("/reserva/<folio>/cancelar", methods=["POST"])
    def cancelar_reserva(folio):
        reserva = buscar_reserva(folio)
        propia_o_403(reserva)
        if cancelar(reserva):
            flash("Reserva cancelada. Las unidades volvieron a estar "
                  "disponibles.", "success")
        else:
            flash(mensaje_final(reservas.find_one({"_id": reserva["_id"]})),
                  "warning")
        return redirect(url_for("ver_reserva", folio=reserva["folio"]))

    @app.route("/reserva/<folio>/confirmar", methods=["POST"])
    def confirmar_reserva(folio):
        reserva = buscar_reserva(folio)
        propia_o_403(reserva)
        if confirmar(reserva):
            flash("¡Reserva confirmada! Tus unidades quedaron apartadas.",
                  "success")
        else:
            flash(mensaje_final(reservas.find_one({"_id": reserva["_id"]})),
                  "warning")
        return redirect(url_for("ver_reserva", folio=reserva["folio"]))

    def mensaje_final(reserva):
        estado = (reserva or {}).get("estado")
        if estado == "vencida":
            return ("El tiempo de la reserva terminó y las unidades ya "
                    "fueron liberadas.")
        if estado == "cancelada":
            return "Esta reserva ya estaba cancelada."
        if estado == "confirmada":
            return "Esta reserva ya estaba confirmada."
        return "No se pudo completar la acción. Intenta de nuevo."

    @app.route("/api/reservas/<folio>")
    def api_reserva(folio):
        """Estado actual de la reserva (lo consulta el contador)."""
        reserva = buscar_reserva(folio)
        respuesta = jsonify({
            "folio": reserva["folio"],
            "estado": reserva["estado"],
            "segundos_restantes": segundos_restantes(reserva),
            "expira_en": como_utc(reserva["expira_en"]).isoformat(),
        })
        respuesta.headers["Cache-Control"] = "no-store"
        return respuesta

    # ------------------------- Codigos QR -------------------------
    @app.route("/reserva/<folio>/qr.png")
    def qr_reserva(folio):
        reserva = buscar_reserva(folio)
        direccion = enlace_publico("ver_reserva", folio=reserva["folio"])
        return imagen_qr(direccion, "qr-" + reserva["folio"] + ".png")

    @app.route("/producto/<id>/qr.png")
    def qr_producto(id):
        if not ObjectId.is_valid(id):
            abort(404, description="La clave del producto no es válida.")
        if productos.find_one({"_id": ObjectId(id)}, {"_id": 1}) is None:
            abort(404, description="Este producto ya no existe.")
        direccion = enlace_publico("producto_detalle", id=id)
        return imagen_qr(direccion, "qr-producto-" + id[-6:] + ".png")
