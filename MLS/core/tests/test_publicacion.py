"""Bloque 3: circuito de aprobación (14 comprobaciones).

Derivación: por cada transición de la máquina de estados, un escenario de
camino habilitado y uno de camino no habilitado según el perfil.
"""

from decimal import Decimal

from django.urls import reverse

from core.models import EstadoPublicacion, ImagenInmueble, Inmueble

from .base import BaseMLS


def datos_alta(pais, ciudad, tipo, titulo="Casa nueva"):
    return {
        "titulo": titulo, "descripcion": "x", "tipo_transaccion": "venta",
        "tipo_inmueble": tipo.pk, "pais": pais.pk, "ciudad": ciudad.pk,
        "zona": "Urubó", "medios_banos": 0, "estacionamientos": 1,
        "radio_privacidad_m": 300, "precio_usd": "120000", "cuartos": 2, "banos": 1,
        "imagenes-TOTAL_FORMS": "3", "imagenes-INITIAL_FORMS": "0",
        "imagenes-MIN_NUM_FORMS": "0", "imagenes-MAX_NUM_FORMS": "1000",
        "imagenes-0-url": "https://ejemplo.com/1.jpg", "imagenes-0-orden": "0",
        "imagenes-0-es_portada": "on",
        "imagenes-1-url": "https://ejemplo.com/2.jpg", "imagenes-1-orden": "1",
        "imagenes-2-url": "", "imagenes-2-orden": "",
    }


class Publicacion(BaseMLS):

    def setUp(self):
        self.cliente = self.entrar(self.u_diego)
        self.broker = self.entrar(self.u_ana)

    # -- alta ---------------------------------------------------------------
    def test_18_el_alta_deja_borrador_con_captador_y_agencia(self):
        self.cliente.post(reverse("core:inmueble_nuevo"),
                          datos_alta(self.bolivia, self.santa_cruz, self.casa))
        inmueble = Inmueble.objects.get(titulo="Casa nueva")
        self.assertEqual(inmueble.estado_publicacion, EstadoPublicacion.BORRADOR)
        self.assertEqual(inmueble.captador, self.diego)
        self.assertEqual(inmueble.agencia_captadora, self.meridiano)
        self.assertEqual(inmueble.imagenes.count(), 2)
        self.assertEqual(inmueble.imagenes.filter(es_portada=True).count(), 1)

    def test_19_el_alta_registra_el_precio_inicial(self):
        self.cliente.post(reverse("core:inmueble_nuevo"),
                          datos_alta(self.bolivia, self.santa_cruz, self.casa))
        inmueble = Inmueble.objects.get(titulo="Casa nueva")
        self.assertEqual(inmueble.historial_precios.count(), 1)
        self.assertEqual(inmueble.historial_precios.first().motivo, "inicial")

    def test_20_un_borrador_no_aparece_en_el_portal(self):
        self.assertNotIn(self.inmueble.titulo,
                         self.client.get(reverse("core:buscar")).content.decode())

    # -- envío a revisión ---------------------------------------------------
    def test_21_el_asesor_no_puede_aprobar_su_propia_publicacion(self):
        self.inmueble.enviar_a_revision()
        url = reverse("core:inmueble_aprobar", args=[self.inmueble.pk])
        self.assertEqual(self.cliente.post(url).status_code, 404)
        self.inmueble.refresh_from_db()
        self.assertEqual(self.inmueble.estado_publicacion, EstadoPublicacion.EN_REVISION)

    def test_22_enviar_a_revision_registra_la_fecha(self):
        url = reverse("core:inmueble_enviar_revision", args=[self.inmueble.pk])
        self.assertEqual(self.cliente.post(url).status_code, 302)
        self.inmueble.refresh_from_db()
        self.assertEqual(self.inmueble.estado_publicacion, EstadoPublicacion.EN_REVISION)
        self.assertIsNotNone(self.inmueble.enviado_a_revision_en)

    def test_23_en_revision_sigue_fuera_del_portal(self):
        self.inmueble.enviar_a_revision()
        self.assertNotIn(self.inmueble.titulo,
                         self.client.get(reverse("core:buscar")).content.decode())

    # -- rechazo ------------------------------------------------------------
    def test_24_el_broker_rechaza_con_motivo_y_el_asesor_lo_ve(self):
        self.inmueble.enviar_a_revision()
        url = reverse("core:inmueble_rechazar", args=[self.inmueble.pk])
        self.broker.post(url, {"motivo": "Falta el plano."})
        self.inmueble.refresh_from_db()
        self.assertEqual(self.inmueble.estado_publicacion, EstadoPublicacion.BORRADOR)
        self.assertEqual(self.inmueble.motivo_rechazo, "Falta el plano.")
        html = self.cliente.get(
            reverse("core:inmueble_editar", args=[self.inmueble.pk])).content.decode()
        self.assertIn("Falta el plano.", html)

    def test_25_el_rechazo_exige_motivo(self):
        self.inmueble.enviar_a_revision()
        url = reverse("core:inmueble_rechazar", args=[self.inmueble.pk])
        self.broker.post(url, {"motivo": ""})
        self.inmueble.refresh_from_db()
        self.assertEqual(self.inmueble.estado_publicacion, EstadoPublicacion.EN_REVISION)

    # -- aprobación ---------------------------------------------------------
    def test_26_la_aprobacion_publica_y_registra_al_revisor(self):
        self.inmueble.enviar_a_revision()
        url = reverse("core:inmueble_aprobar", args=[self.inmueble.pk])
        self.assertEqual(self.broker.post(url).status_code, 302)
        self.inmueble.refresh_from_db()
        self.assertEqual(self.inmueble.estado_publicacion, EstadoPublicacion.PUBLICADO)
        self.assertEqual(self.inmueble.revisado_por, self.ana)
        self.assertEqual(self.inmueble.motivo_rechazo, "")

    def test_27_recien_aprobado_aparece_en_el_portal(self):
        self.inmueble.enviar_a_revision()
        self.broker.post(reverse("core:inmueble_aprobar", args=[self.inmueble.pk]))
        self.assertIn(self.inmueble.titulo,
                      self.client.get(reverse("core:buscar")).content.decode())

    def test_28_el_broker_aprueba_su_propia_captacion(self):
        propio = self.crear_inmueble(self.ana, "Casa de Ana")
        self.assertTrue(propio.puede_enviar_a_revision(self.u_ana))
        self.assertTrue(propio.puede_aprobar_publicacion(self.u_ana))
        propio.enviar_a_revision()
        self.broker.post(reverse("core:inmueble_aprobar", args=[propio.pk]))
        propio.refresh_from_db()
        self.assertEqual(propio.estado_publicacion, EstadoPublicacion.PUBLICADO)
        self.assertEqual(propio.revisado_por, self.ana)

    def test_29_sin_agencia_no_se_puede_enviar_a_revision(self):
        huerfano = self.crear_inmueble(self.sin_agencia, "Casa sin agencia")
        self.assertIsNone(self.sin_agencia.agencia_actual)
        self.assertFalse(huerfano.puede_enviar_a_revision(self.u_sin_agencia))

    # -- edición de un publicado --------------------------------------------
    def test_30_editar_la_descripcion_no_despublica(self):
        self.inmueble.aprobar_publicacion(self.ana)
        self.inmueble.refresh_from_db()
        self.inmueble.descripcion = "Descripción corregida."
        self.inmueble.save()
        self.inmueble.refresh_from_db()
        self.assertEqual(self.inmueble.estado_publicacion, EstadoPublicacion.PUBLICADO)

    def test_31_editar_el_precio_devuelve_a_revision(self):
        self.inmueble.aprobar_publicacion(self.ana)
        self.inmueble.refresh_from_db()
        self.inmueble.precio_usd = Decimal("139000")
        self.inmueble.save()
        self.inmueble.refresh_from_db()
        self.assertEqual(self.inmueble.estado_publicacion, EstadoPublicacion.EN_REVISION)
        self.assertIsNone(self.inmueble.revisado_por)
        self.assertEqual(self.inmueble.historial_precios.count(), 2)
        self.assertNotIn(self.inmueble.titulo,
                         self.client.get(reverse("core:buscar")).content.decode())
