"""Bloque 1: acceso y ciclo de vida de la cuenta (11 comprobaciones).

Derivación: un escenario por cada estado del asesor y por cada decisión del
formulario de acceso.
"""

from django.urls import reverse

from core.models import Asesor, EstadoAsesor, Usuario

from .base import CLAVE, BaseMLS


class Autenticacion(BaseMLS):

    def test_01_el_formulario_pide_correo_no_usuario(self):
        html = self.client.get(reverse("core:login")).content.decode()
        self.assertIn("Correo electrónico", html)
        self.assertIn('maxlength="254"', html)

    def test_02_el_acceso_no_distingue_mayusculas(self):
        respuesta = self.client.post(reverse("core:login"), {
            "username": self.u_ana.email.upper(), "password": CLAVE})
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(respuesta["Location"], reverse("core:panel"))

    def test_03_admite_correos_con_apostrofo(self):
        """El caso que `auth.User` no podía representar."""
        respuesta = self.client.post(reverse("core:registro"), {
            "nombre": "Sean", "apellido": "O'Brien", "ci": "8877665",
            "pais": self.bolivia.pk, "celular": "+59170000000",
            "correo": "o'brien@ejemplo.com",
            "password1": "MLSlatam2026!", "password2": "MLSlatam2026!"})
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(Usuario.objects.filter(email="o'brien@ejemplo.com").exists())

    def test_04_la_solicitud_nace_pendiente_y_sin_acceso_al_admin(self):
        self.client.post(reverse("core:registro"), {
            "nombre": "Nadia", "apellido": "Ruiz", "ci": "6655443",
            "pais": self.bolivia.pk, "correo": "nadia@ejemplo.com",
            "password1": "MLSlatam2026!", "password2": "MLSlatam2026!"})
        asesor = Asesor.objects.get(ci="6655443")
        self.assertEqual(asesor.estado, EstadoAsesor.PENDIENTE)
        self.assertFalse(asesor.activo)
        self.assertTrue(asesor.usuario.is_active)   # entra, pero el panel lo frena
        self.assertFalse(asesor.usuario.is_staff)

    def _pendiente(self):
        self.client.post(reverse("core:registro"), {
            "nombre": "Nadia", "apellido": "Ruiz", "ci": "6655443",
            "pais": self.bolivia.pk, "correo": "nadia@ejemplo.com",
            "password1": "MLSlatam2026!", "password2": "MLSlatam2026!"})
        asesor = Asesor.objects.get(ci="6655443")
        cliente = self.client_class()
        cliente.login(username="nadia@ejemplo.com", password="MLSlatam2026!")
        return asesor, cliente

    def test_05_el_pendiente_entra_pero_el_panel_lo_frena(self):
        _, cliente = self._pendiente()
        respuesta = cliente.get(reverse("core:panel"))
        self.assertEqual(respuesta.status_code, 403)
        self.assertIn("siendo revisada", respuesta.content.decode())

    def test_06_el_pendiente_no_puede_cargar_inmuebles(self):
        _, cliente = self._pendiente()
        self.assertEqual(cliente.get(reverse("core:inmueble_nuevo")).status_code, 403)

    def test_07_tras_la_aprobacion_el_panel_queda_accesible(self):
        asesor, cliente = self._pendiente()
        asesor.aplicar_estado(EstadoAsesor.APROBADO)
        self.assertEqual(cliente.get(reverse("core:panel")).status_code, 200)

    def test_08_la_suspension_mata_la_sesion_abierta(self):
        """La propiedad que se habría perdido con el diseño de autenticación
        descartado: suspender debe expulsar en la petición siguiente."""
        cliente = self.entrar(self.u_ana)
        self.assertEqual(cliente.get(reverse("core:panel")).status_code, 200)
        self.ana.aplicar_estado(EstadoAsesor.SUSPENDIDO)
        respuesta = cliente.get(reverse("core:panel"))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse("core:login"), respuesta["Location"])

    def test_09_el_cierre_de_sesion_por_get_se_rechaza(self):
        cliente = self.entrar(self.u_ana)
        self.assertEqual(cliente.get(reverse("core:logout")).status_code, 405)

    def test_10_el_cierre_de_sesion_por_post_redirige_al_portal(self):
        cliente = self.entrar(self.u_ana)
        respuesta = cliente.post(reverse("core:logout"))
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(respuesta["Location"], reverse("core:landing"))
        self.assertEqual(cliente.get(reverse("core:panel")).status_code, 302)

    def test_11_las_paginas_privadas_exigen_sesion(self):
        for nombre in ("core:panel", "core:aprobaciones", "core:inmueble_nuevo"):
            respuesta = self.client.get(reverse(nombre))
            self.assertEqual(respuesta.status_code, 302)
            self.assertIn(reverse("core:login"), respuesta["Location"])
