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

  // ---------- Contadores animados (resumen del panel) ----------
  document.querySelectorAll('[data-contar]').forEach(function (el) {
    var meta = parseInt(el.dataset.contar, 10);
    if (isNaN(meta) || reducir || meta === 0) return;
    var inicio = null, dur = 900;
    el.textContent = '0';
    function paso(t) {
      if (inicio === null) inicio = t;
      var p = Math.min((t - inicio) / dur, 1);
      el.textContent = Math.round(meta * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(paso);
    }
    requestAnimationFrame(paso);
  });

  // ---------- Buscador de la barra: búsqueda, categoría, solo disponibles ----------
  var form = document.getElementById('filtro');
  var buscar = document.getElementById('buscar');
  var categoria = document.getElementById('categoria-filtro');
  var solo = document.getElementById('solo-disponibles');
  var items = document.querySelectorAll('[data-filtrable]');
  var vacio = document.getElementById('sin-resultados');
  var conteo = document.getElementById('conteo-resultados') || document.getElementById('conteo-admin');
  var esConteoAdmin = conteo && conteo.id === 'conteo-admin';

  function filtrar() {
    var q = buscar.value.trim().toLowerCase();
    var visibles = 0;
    items.forEach(function (t) {
      var ok = (!q || t.dataset.texto.indexOf(q) !== -1) &&
               (!categoria.value || t.dataset.categoria === categoria.value) &&
               (!solo || !solo.checked || t.dataset.disponible === '1');
      t.hidden = !ok;
      if (ok) visibles++;
    });
    if (vacio) vacio.hidden = visibles !== 0 || items.length === 0;
    if (conteo) {
      conteo.textContent = esConteoAdmin ? visibles :
        visibles + ' producto' + (visibles === 1 ? '' : 's') +
        (visibles !== items.length ? ' de ' + items.length : '');
    }
  }

  if (form && buscar && categoria) {
    // Si llegas desde otra página, la búsqueda viene en la dirección (?q=…&cat=…)
    var params = new URLSearchParams(location.search);
    if (params.get('q')) buscar.value = params.get('q');
    if (params.get('cat')) {
      var existe = Array.prototype.some.call(categoria.options, function (o) { return o.value === params.get('cat'); });
      if (existe) categoria.value = params.get('cat');
    }

    if (items.length) {                      // la página tiene lista que filtrar
      buscar.addEventListener('input', filtrar);
      categoria.addEventListener('change', filtrar);
      if (solo) solo.addEventListener('change', filtrar);
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        filtrar();
        var lista = document.getElementById('lista');
        if (lista) lista.scrollIntoView({ behavior: reducir ? 'auto' : 'smooth' });
      });
      var limpiar = document.getElementById('limpiar-filtros');
      if (limpiar) limpiar.addEventListener('click', function () {
        buscar.value = ''; categoria.value = ''; if (solo) solo.checked = false; filtrar(); buscar.focus();
      });
      if (buscar.value || categoria.value) {
        filtrar();
        var l = document.getElementById('lista');
        if (l && location.pathname === '/') setTimeout(function () { l.scrollIntoView(); }, 60);
      }
    }
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
    var nombre = $('nombre'), cat = $('categoria'), est = $('estado'), precio = $('precio');
    var desc = $('descripcion'), img = $('imagen');
    function dinero(txt) {
      var n = parseFloat(String(txt).replace(/[$,\s]/g, ''));
      if (isNaN(n) || n <= 0) return '$0.00';
      return '$' + n.toLocaleString('es-MX', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    function pintar() {
      $('vp-nombre').textContent = nombre.value.trim() || 'Nombre del producto';
      $('vp-categoria').textContent = cat.value.trim() || 'Categoría';
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
    [nombre, cat, est, precio, desc].forEach(function (el) {
      if (el) { el.addEventListener('input', pintar); el.addEventListener('change', pintar); }
    });
    pintar();

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

  // Pequeño rebote del contador del carrito después de agregar un producto
  var cuenta = document.querySelector('.navbar .conteo');
  if (cuenta && document.querySelector('.alerta-flash.alert-success')) cuenta.classList.add('rebota');
})();
