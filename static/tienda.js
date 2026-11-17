// Zultek: pantalla de carga con gif, filtro de la barra de navegación,
// animaciones de aparición e imágenes de respaldo.
(function () {
  var cargando = document.getElementById('cargando');
  var texto = document.getElementById('cargando-texto');
  var reducir = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function mostrar(mensaje) {
    if (!cargando) return;
    texto.textContent = mensaje || 'Cargando…';
    cargando.hidden = false;
  }
  // Al volver con el botón "atrás" el navegador puede restaurar la página con el gif visible
  window.addEventListener('pageshow', function () { if (cargando) cargando.hidden = true; });

  // Al enviar un formulario (si no fue cancelado con un confirm)
  document.addEventListener('submit', function (e) {
    if (e.defaultPrevented) return;
    var f = e.target;
    if (!(f instanceof HTMLFormElement) || f.id === 'filtro') return;
    var sube = f.enctype === 'multipart/form-data' &&
               f.querySelector('input[type=file]') &&
               f.querySelector('input[type=file]').files.length > 0;
    mostrar(sube ? 'Subiendo imagen…' : 'Cargando…');
  });

  // Al navegar a otra página del sitio
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[href]');
    if (!a || e.defaultPrevented || e.button !== 0) return;
    if (e.ctrlKey || e.metaKey || e.shiftKey || a.target === '_blank') return;
    var url = new URL(a.href, location.href);
    if (url.origin !== location.origin) return;
    if (url.pathname === location.pathname && url.search === location.search) return; // solo ancla
    if (a.hasAttribute('data-bs-toggle')) return;
    mostrar('Cargando…');
  });

  // Imagen que no carga: se muestra el ícono de Zultek
  document.querySelectorAll('img[data-fallback]').forEach(function (img) {
    img.addEventListener('error', function () {
      img.classList.add('sin-foto');
      img.src = img.dataset.fallback;
      img.removeAttribute('data-fallback');
    });
  });

  // ---------- Aparición al desplazarse ----------
  var apariciones = document.querySelectorAll('.aparecer');
  if ('IntersectionObserver' in window && !reducir) {
    var obs = new IntersectionObserver(function (entradas) {
      entradas.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add('visto'); obs.unobserve(en.target); }
      });
    }, { threshold: 0.08, rootMargin: '0px 0px -30px 0px' });
    apariciones.forEach(function (el) { obs.observe(el); });
  } else {
    apariciones.forEach(function (el) { el.classList.add('visto'); });
  }

  
  // ---------- Filtro de pedidos por estado (administrador) ----------
  var tabs = document.querySelectorAll('[data-estado-filtro]');
  if (tabs.length) {
    var pedidos = document.querySelectorAll('[data-estado-pedido]');
    var sinPedidos = document.getElementById('sin-pedidos');
    tabs.forEach(function (b) {
      b.addEventListener('click', function () {
        tabs.forEach(function (x) { x.classList.toggle('activo', x === b); });
        var e = b.dataset.estadoFiltro, n = 0;
        pedidos.forEach(function (p) {
          var ok = !e || p.dataset.estadoPedido === e;
          p.hidden = !ok; if (ok) n++;
        });
        if (sinPedidos) sinPedidos.hidden = n !== 0;
      });
    });
  }

  // ---------- Cantidad (+ / −) en el detalle del producto ----------
  document.querySelectorAll('[data-stepper]').forEach(function (s) {
    var inp = s.querySelector('input');
    s.querySelectorAll('button[data-paso]').forEach(function (b) {
      b.addEventListener('click', function () {
        var min = parseInt(inp.min, 10) || 1, max = parseInt(inp.max, 10) || 99;
        var v = (parseInt(inp.value, 10) || min) + parseInt(b.dataset.paso, 10);
        inp.value = Math.max(min, Math.min(max, v));
      });
    });
  });

  // ---------- Mostrar / ocultar contraseña ----------
  document.querySelectorAll('[data-ver-clave]').forEach(function (b) {
    b.addEventListener('click', function () {
      var c = document.getElementById(b.dataset.verClave);
      if (!c) return;
      var oculto = c.type === 'password';
      c.type = oculto ? 'text' : 'password';
      b.classList.toggle('activo', oculto);
    });
  });

  // ---------- Medidor de seguridad de la contraseña ----------
  document.querySelectorAll('[data-medidor]').forEach(function (c) {
    var med = document.getElementById(c.dataset.medidor);
    c.addEventListener('input', function () {
      var v = c.value, n = 0;
      if (v.length >= 8) n++;
      if (/[a-z]/.test(v) && /[A-Z]/.test(v)) n++;
      if (/\d/.test(v)) n++;
      if (/[^A-Za-z0-9]/.test(v) || v.length >= 14) n++;
      med.dataset.nivel = v ? n : 0;
    });
  });

  // ---------- Formulario de producto: vista previa en vivo ----------
  var formProd = document.getElementById('form-producto');
  if (formProd) {
    var $ = function (id) { return document.getElementById(id); };
    var nombre = $('nombre'), cat = $('categoria'), catNueva = $('categoria_nueva'), est = $('estado'), precio = $('precio');
    var desc = $('descripcion'), img = $('imagen');
    function dinero(txt) {
      var n = parseFloat(String(txt).replace(/[$,\s]/g, ''));
      if (isNaN(n) || n <= 0) return '$0.00';
      return '$' + n.toLocaleString('es-MX', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    function pintar() {
      $('vp-nombre').textContent = nombre.value.trim() || 'Nombre del producto';
      var nueva = cat.value === '__nueva__';
      if (catNueva) {                       // "Crear nueva categoría": muestra/oculta el campo
        catNueva.hidden = !nueva;
        catNueva.required = nueva;
      }
      var nombreCat = nueva ? (catNueva ? catNueva.value.trim() : '') : cat.options[cat.selectedIndex].text;
      $('vp-categoria').textContent = (cat.value && nombreCat) ? nombreCat : 'Categoría';
      $('vp-precio').textContent = dinero(precio.value);
      var e = est.value || 'Disponible';
      $('vp-estado').textContent = e;
      $('vp-estado').dataset.estado = e;
      if (desc && $('cuenta-desc')) {
        var n = desc.value.length;
        $('cuenta-desc').textContent = n + '/300';
        $('cuenta-desc').classList.toggle('casi', n > 260);
      }
    }
    [nombre, cat, catNueva, est, precio, desc].forEach(function (el) {
      if (el) { el.addEventListener('input', pintar); el.addEventListener('change', pintar); }
    });
    pintar();
    cat.addEventListener('change', function () {
      if (cat.value === '__nueva__' && catNueva) catNueva.focus();
    });

    function verArchivo(f) {
      if (!f) return;
      $('nombre-archivo').textContent = f.name;
      if (!/^image\//.test(f.type)) return;
      var lector = new FileReader();
      lector.onload = function () {
        var v = $('vp-img'); v.src = lector.result; v.classList.remove('sin-foto');
      };
      lector.readAsDataURL(f);
    }
    if (img) img.addEventListener('change', function () { verArchivo(img.files[0]); });
    var zona = $('zona-subida');
    if (zona && img) {
      ['dragenter', 'dragover'].forEach(function (ev) {
        zona.addEventListener(ev, function () { zona.classList.add('arrastrando'); });
      });
      ['dragleave', 'drop'].forEach(function (ev) {
        zona.addEventListener(ev, function () { zona.classList.remove('arrastrando'); });
      });
      // Al soltar el archivo, el propio input lo recibe (está encima de la zona)
    }
  }

  // Contador de la reserva. Solo INFORMA: el servidor vuelve a revisar la
  // hora al confirmar. Parte de los segundos que calculó el servidor, así no
  // depende de que el reloj del dispositivo esté bien.
  var cuentas = document.querySelectorAll('[data-cuenta]');
  if (cuentas.length) {
    var fin = Date.now() + (parseInt(cuentas[0].getAttribute('data-cuenta'), 10) || 0) * 1000;
    var pintar = function () {
      var faltan = Math.max(0, fin - Date.now());
      var m = String(Math.floor(faltan / 60000)).padStart(2, '0');
      var s = String(Math.floor((faltan % 60000) / 1000)).padStart(2, '0');
      for (var i = 0; i < cuentas.length; i++) cuentas[i].textContent = m + ':' + s;
      return faltan;
    };
    pintar();
        if ((parseInt(cuentas[0].getAttribute('data-cuenta'), 10) || 0) > 5) {
      try { sessionStorage.removeItem('reserva_recargada'); } catch (e) {}
    }
        var reloj = setInterval(function () {
      if (pintar() === 0) {
        clearInterval(reloj);
        var yaRecargo = false;
        try { yaRecargo = sessionStorage.getItem('reserva_recargada') === '1'; } catch (e) {}
        if (!yaRecargo) {
          try { sessionStorage.setItem('reserva_recargada', '1'); } catch (e) {}
          window.location.assign(window.location.pathname); // el servidor libera y recalcula
        } else {
          for (var i = 0; i < cuentas.length; i++) cuentas[i].textContent = 'terminó';
        }
      }
    }, 1000);
  }

  // Pequeño rebote del contador del carrito después de agregar un producto
  var cuenta = document.querySelector('.navbar .conteo');
  if (cuenta && document.querySelector('.alerta-flash.alert-success')) cuenta.classList.add('rebota');
})();
