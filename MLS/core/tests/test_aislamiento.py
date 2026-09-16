"""Bloque 2: aislamiento entre asesores y agencias (6 comprobaciones).

Derivación: un escenario por cada combinación de sujeto (asesor propio, asesor
de otra agencia, broker de la agencia) y objeto (inmueble propio, ajeno).
"""

from django.urls import reverse

from core.models import AsesorAgencia, Inmueble, Propietario

from .base import BaseMLS


class Aislamiento(BaseMLS):

    def test_12_editar_un_inmueble_ajeno_devuelve_404(self):
        """404 y no 403: una respuesta de acceso denegado confirmaría que existe."""
        cliente = self.entrar(self.u_beto)
        url = reverse("core:inmueble_editar", args=[self.inmueble.pk])
        self.assertEqual(cliente.get(url).status_code, 404)

    def test_13_un_asesor_de_otra_agencia_no_puede_aprobar(self):
        self.inmueble.enviar_a_revision()
        cliente = self.entrar(self.u_beto)
        url = reverse("core:inmueble_aprobar", args=[self.inmueble.pk])
        self.assertEqual(cliente.post(url).status_code, 404)
        self.inmueble.refresh_from_db()
        self.assertEqual(self.inmueble.estado_publicacion, "en_revision")

    def test_14_la_cola_del_broker_solo_trae_su_agencia(self):
        self.inmueble.enviar_a_revision()
        self.assertIn(self.inmueble, Inmueble.objects.por_aprobar(self.u_ana))
        ajeno = self.crear_inmueble(self.beto, "Casa de Beto")
        ajeno.enviar_a_revision()
        self.assertNotIn(ajeno, Inmueble.objects.por_aprobar(self.u_ana))

    def test_15_el_broker_ve_la_cartera_de_su_agencia(self):
        visibles = Inmueble.objects.visibles_para(self.u_ana)
        self.assertIn(self.inmueble, visibles)          # captado por Diego
        propio_beto = self.crear_inmueble(self.beto, "Otra de Beto")
        self.assertNotIn(propio_beto, visibles)

    def test_16_el_asesor_solo_ve_sus_captaciones(self):
        visibles = Inmueble.objects.visibles_para(self.u_diego)
        self.assertEqual(list(visibles), [self.inmueble])
        self.assertEqual(Inmueble.objects.visibles_para(self.u_beto).count(), 0)

    def test_17_los_propietarios_ajenos_no_son_visibles(self):
        """El propietario lo registró Diego; Beto no debe alcanzarlo."""
        from core.admin import PropietarioAdmin
        from django.contrib.admin.sites import AdminSite

        class Peticion:
            user = self.u_beto

        admin = PropietarioAdmin(Propietario, AdminSite())
        self.assertNotIn(self.propietario, admin.get_queryset(Peticion()))
