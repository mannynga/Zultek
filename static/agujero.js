// Zultek · Agujero negro con humo: nubes suaves que se desvanecen y luces
// que recorren el anillo. Se dibuja en un <canvas> DENTRO de .banner-fondo,
// así acompaña a la imagen cuando ésta se desplaza. Sin librerías, GIF ni video.
// Se pausa si la pestaña está oculta o el banner no se ve, y no corre si la
// persona pidió "reducir movimiento" (queda la imagen y el resplandor CSS).
(function () {
  'use strict';
  var caja = document.querySelector('.banner-fondo');
  if (!caja) return;
  var reducir = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reducir) return;

  // La imagen de fondo mide 736x414, con background-size: cover y posición
  // "center 42%" (ver estilos.css). Medidas del anillo, en píxeles de la imagen:
  var IMG_W = 736, IMG_H = 414, POS_Y = 0.42;
  var HOYO_X = 355, HOYO_Y = 235;        // centro del agujero
  var RX = 142;                          // semiancho del anillo
  var RY_ARCO = 103, RY_DISCO = 21;      // alto del arco (arriba) y del disco (abajo)
  var INCLINA = 0.14;                    // el anillo baja hacia la derecha (rad)
  var cosI = Math.cos(INCLINA), senI = Math.sin(INCLINA);

  var lienzo = document.createElement('canvas');
  lienzo.setAttribute('aria-hidden', 'true');
  lienzo.style.cssText =
    'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;';
  caja.appendChild(lienzo);
  var ctx = lienzo.getContext('2d');
  if (!ctx) return;

  var cx = 0, cy = 0, esc = 1;
  var K = 0.4;   // resolución del lienzo: el humo es difuso, basta una fracción
  function medir() {
    var w = caja.clientWidth, h = caja.clientHeight;
    if (!w || !h) return;
    lienzo.width = Math.max(1, Math.round(w * K));
    lienzo.height = Math.max(1, Math.round(h * K));
    esc = Math.max(w / IMG_W, h / IMG_H);
    cx = (w - IMG_W * esc) / 2 + HOYO_X * esc;
    cy = (h - IMG_H * esc) * POS_Y + HOYO_Y * esc;
    // El resplandor CSS (agujero.css) usa estas variables para seguir al agujero
    caja.style.setProperty('--hx', cx + 'px');
    caja.style.setProperty('--hy', cy + 'px');
    caja.style.setProperty('--gl', (RX * esc * 2.7) + 'px');
  }

  // ---- Sprites: manchas suaves, sin bordes (por eso no se ven choques) ----
  function mancha(rgb) {
    var c = document.createElement('canvas');
    c.width = c.height = 128;
    var g = c.getContext('2d');
    var d = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    d.addColorStop(0, 'rgba(' + rgb + ',1)');
    d.addColorStop(0.3, 'rgba(' + rgb + ',.55)');
    d.addColorStop(0.65, 'rgba(' + rgb + ',.14)');
    d.addColorStop(1, 'rgba(' + rgb + ',0)');
    g.fillStyle = d;
    g.fillRect(0, 0, 128, 128);
    return c;
  }
  var TONOS = [mancha('170,80,255'), mancha('255,110,215'), mancha('235,190,255')];

  // ---- Luces que recorren el anillo e iluminan el humo a su paso ----
  var luces = [
    { a: 0.6, v: 0.34, k: 0.0 },
    { a: 2.7, v: 0.21, k: 2.1 },
    { a: 4.5, v: 0.46, k: 4.2 }
  ];
  function iluminacion(a) {
    var suma = 0;
    for (var i = 0; i < luces.length; i++) {
      var d = Math.atan2(Math.sin(a - luces[i].a), Math.cos(a - luces[i].a));
      suma += luces[i].i * Math.exp(-(d * d) / 0.5);
    }
    return suma;
  }

  // ---- Humo: cada nube nace, viaja por la órbita, se expande y se desvanece ----
  var movil = window.innerWidth < 700;
  var N = movil ? 40 : 72;
  var activas = N;               // calidad adaptable: baja sola si el equipo va lento
  var acumulado = 0, cuentas = 0;
  var humo = [];
  function reiniciar(p, inicial) {
    var nube = Math.random() < 0.45;          // nube del disco (abajo) o borde del anillo
    p.nube = nube;
    p.rr0 = nube ? 1.12 + Math.random() * 0.75 : 0.97 + Math.random() * 0.14;
    p.rr = p.rr0;
    p.a = nube ? 0.2 + Math.random() * (Math.PI - 0.9) : Math.random() * Math.PI * 2;
    p.v = (nube ? 0.10 : 0.17) / Math.pow(p.rr, 1.5) * (0.7 + Math.random() * 0.6);
    p.dur = 5 + Math.random() * 5;
    p.t = inicial ? Math.random() * p.dur : 0;
    p.tam = (nube ? 34 : 26) + Math.random() * 30;   // radio, en px de la imagen
    p.est = nube ? 1.6 : 2.4;                       // estiramiento a lo largo del giro
    p.j = nube ? 8 + Math.random() * 55 : (Math.random() - 0.5) * 12;
    p.sem = Math.random() * 6.283;
    var r = Math.random();
    p.tono = nube ? (r < 0.6 ? 0 : 1) : (r < 0.45 ? 0 : r < 0.85 ? 1 : 2);
  }
  for (var i = 0; i < N; i++) { var p = {}; reiniciar(p, true); humo.push(p); }

  // Forma de la órbita vista desde la cámara: arriba un arco alto (la parte
  // trasera del disco curvada por la gravedad) y abajo un disco plano y ancho.
  function posicion(p, a, tiempo) {
    var s = Math.sin(a), c = Math.cos(a);
    var alto = s < 0 ? RY_ARCO : RY_DISCO;
    var turb = (p.t / p.dur) * 10;           // el humo se agita más al envejecer
    var x = RX * esc * p.rr * c + Math.sin(tiempo * 0.7 + p.sem) * turb * esc;
    var y = alto * esc * p.rr * s + (p.j + Math.cos(tiempo * 0.5 + p.sem * 2) * turb) * esc;
    return [cx + x * cosI - y * senI, cy + x * senI + y * cosI, s];
  }

  var activo = true, visible = true, ultimo = 0, reloj = 0;
  function cuadro(ahora) {
    if (!activo || !visible) { ultimo = 0; return; }
    var dt = ultimo ? Math.min((ahora - ultimo) / 1000, 0.05) : 0.016;
    ultimo = ahora; reloj += dt;

    for (var l = 0; l < luces.length; l++) {
      luces[l].a += luces[l].v * dt;
      luces[l].i = 0.6 + 0.4 * Math.sin(reloj * 0.8 + luces[l].k);   // pulsan
    }

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, lienzo.width, lienzo.height);
    ctx.globalCompositeOperation = 'lighter';

    // Si el promedio de los últimos cuadros es lento (< ~30 fps), usa menos humo
    acumulado += dt; cuentas++;
    if (cuentas >= 40) {
      if (acumulado / cuentas > 0.034 && activas > 20) activas = Math.max(20, activas - 14);
      acumulado = 0; cuentas = 0;
    }

    for (var i = 0; i < activas; i++) {
      var p = humo[i];
      p.t += dt; p.a += p.v * dt;
      if (p.t >= p.dur) { reiniciar(p, false); continue; }
      var fase = p.t / p.dur;
      p.rr = p.rr0 * (1 + (p.nube ? 0.1 : 0.3) * fase);          // el humo del borde se desprende hacia afuera
      var vida = Math.pow(Math.sin(Math.PI * fase), 1.3);        // aparece y se desvanece
      var q = posicion(p, p.a, reloj);
      var o = posicion(p, p.a + 0.04, reloj);
      var ang = Math.atan2(o[1] - q[1], o[0] - q[0]);
      var dop = 0.55 + 0.45 * (Math.cos(p.a) + 1) / 2;           // algo más de brillo a la derecha
      var luz = iluminacion(p.a);
      var base = p.nube ? 0.13 : 0.22;
      ctx.globalAlpha = Math.min(0.6, base * vida * dop * (1 + 1.5 * luz));
      var rad = p.tam * esc * (0.75 + 0.7 * fase);                // se expande
      var c = Math.cos(ang), s = Math.sin(ang);
      ctx.setTransform(c * K, s * K, -s * K, c * K, q[0] * K, q[1] * K);
      ctx.drawImage(TONOS[p.tono], -rad * p.est, -rad, rad * 2 * p.est, rad * 2);
    }

    // Núcleos de las luces: halos suaves que viajan por el borde del anillo
    ctx.setTransform(K, 0, 0, K, 0, 0);
    for (var k = 0; k < luces.length; k++) {
      var lp = posicion({ rr: 1, j: 0, t: 0, dur: 1, sem: 0 }, luces[k].a, reloj);
      var dopL = 0.5 + 0.5 * (Math.cos(luces[k].a) + 1) / 2;
      ctx.globalAlpha = 0.14 * luces[k].i * dopL;
      var R1 = 52 * esc;
      ctx.drawImage(TONOS[2], lp[0] - R1, lp[1] - R1, R1 * 2, R1 * 2);
      ctx.globalAlpha = 0.07 * luces[k].i * dopL;
      var R2 = 90 * esc;
      ctx.drawImage(TONOS[1], lp[0] - R2, lp[1] - R2, R2 * 2, R2 * 2);
    }
    ctx.globalAlpha = 1;
    requestAnimationFrame(cuadro);
  }
  function arrancar() {
    if (activo && visible && !ultimo) requestAnimationFrame(cuadro);
  }

  medir();
  if (window.ResizeObserver) new ResizeObserver(medir).observe(caja);
  else window.addEventListener('resize', medir);
  document.addEventListener('visibilitychange', function () {
    activo = !document.hidden; arrancar();
  });
  if (window.IntersectionObserver) {
    new IntersectionObserver(function (e) {
      visible = e[0].isIntersecting; arrancar();
    }).observe(caja.parentElement || caja);
  }
  arrancar();
})();
