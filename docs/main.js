(function () {
  "use strict";

  // Cada pantalla trae su propia URL y el pie que explica qué está probando.
  var VISTAS = {
    portada: {
      url: "latammls.com",
      alt: "Portada de LatamMLS: buscador de inmuebles sobre una fotografía, con las métricas del inventario debajo.",
      pie: "La portada abre con el buscador y las métricas salen de la base, no son adorno: 12 propiedades publicadas, 4 asesores, 3 agencias."
    },
    buscador: {
      url: "latammls.com/buscar/?operacion=venta",
      alt: "Resultados de búsqueda con filtros por operación, tipo, ciudad y precio.",
      pie: "El buscador filtra de verdad: operación, tipo, ciudad y rango de precio, con orden y paginación que conservan los filtros."
    },
    panel: {
      url: "latammls.com/panel/",
      alt: "Panel del asesor con sus métricas, captaciones por vencer y su inventario.",
      pie: "El panel muestra solo lo del asesor. Pedir por dirección directa un inmueble ajeno devuelve 404, no 403: un 403 confirmaría que existe."
    },
    aprobaciones: {
      url: "latammls.com/panel/aprobaciones/",
      alt: "Cola de revisión del broker, con un aviso pendiente y los botones de aprobar o devolver.",
      pie: "La cola del broker. Nada de esto está en el portal todavía; al aprobar queda registrado quién lo hizo, y devolver exige escribir el motivo."
    },
    carga: {
      url: "latammls.com/panel/inmueble/nuevo/",
      alt: "Formulario de carga de inmueble, con las secciones de ubicación pública y privada separadas.",
      pie: "El formulario separa la ubicación pública de la privada. La calle y el punto exacto son dato reservado de quien captó."
    },
    acceso: {
      url: "latammls.com/ingresar/",
      alt: "Pantalla de acceso con el campo de correo electrónico.",
      pie: "La identidad es el correo, no un nombre de usuario: el modelo de Django no admite direcciones con apóstrofo, frecuentes en apellidos de la región."
    }
  };

  var pestanas = Array.prototype.slice.call(document.querySelectorAll(".pestana"));
  var captura = document.getElementById("captura");
  var ventana = document.getElementById("ventana");
  var url = document.getElementById("url");
  var pie = document.getElementById("pie");

  // Precarga: cambiar de pestaña no debe mostrar un hueco blanco.
  Object.keys(VISTAS).forEach(function (k) {
    var i = new Image();
    i.src = "assets/" + k + ".jpg";
  });

  function mostrar(clave) {
    var v = VISTAS[clave];
    if (!v) return;
    captura.src = "assets/" + clave + ".jpg";
    captura.alt = v.alt;
    url.textContent = v.url;
    pie.textContent = v.pie;
    ventana.scrollTop = 0;
    pestanas.forEach(function (b) {
      var activa = b.dataset.vista === clave;
      b.classList.toggle("activa", activa);
      b.setAttribute("aria-selected", activa ? "true" : "false");
    });
  }

  pestanas.forEach(function (b, i) {
    b.addEventListener("click", function () { mostrar(b.dataset.vista); });
    // Flechas entre pestañas, como espera un lector de pantalla en un tablist.
    b.addEventListener("keydown", function (e) {
      var d = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1
            : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
      if (!d) return;
      e.preventDefault();
      var n = pestanas[(i + d + pestanas.length) % pestanas.length];
      n.focus();
      mostrar(n.dataset.vista);
    });
  });

  // Copiar los comandos de instalación
  var copiar = document.getElementById("copiar");
  if (copiar && navigator.clipboard) {
    copiar.addEventListener("click", function () {
      navigator.clipboard.writeText(copiar.dataset.copia).then(function () {
        copiar.textContent = "Copiado";
        copiar.classList.add("hecho");
        setTimeout(function () {
          copiar.textContent = "Copiar";
          copiar.classList.remove("hecho");
        }, 1800);
      });
    });
  } else if (copiar) {
    copiar.hidden = true;
  }
})();
