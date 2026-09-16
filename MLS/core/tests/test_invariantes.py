"""Bloque 4: rechazo efectivo de las 21 restricciones del motor.

Derivación: una comprobación por restricción declarada, construida sobre los
valores límite de su predicado. Cada intento corre en su propia transacción
para que el fallo de uno no invalide los siguientes.

Estas comprobaciones no recorren la aplicación: escriben directo contra la base
para demostrar que la garantía no depende del código que la invoca.
"""

from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction

from core.models import (
    Agencia,
    AgenciaEnlace,
    Asesor,
    AsesorAgencia,
    AsesorEnlace,
    Captacion,
    Ciudad,
    ComisionParticipacion,
    EstadoAsesor,
    EstadoPublicacion,
    ImagenInmueble,
    Inmueble,
    Operacion,
    Propietario,
    Usuario,
)

from .base import BaseMLS


class Invariantes(BaseMLS):
    """Cada prueba intenta escribir un estado que el motor debe rechazar."""

    def _rechaza(self, fn):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                fn()

    # -- unicidad -----------------------------------------------------------
    def test_32_uq_usuario_email_ci(self):
        """La escritura por lotes no pasa por save(), que normaliza a minúsculas:
        es la vía que solo la restricción del motor protege."""
        self._rechaza(lambda: Usuario.objects.bulk_create(
            [Usuario(email=self.u_ana.email.upper(), password="x")]))

    def test_33_uq_asesor_ci_por_pais(self):
        self._rechaza(lambda: Asesor.objects.create(
            nombre="Otra", apellido="Persona", ci=self.ana.ci, pais=self.bolivia))

    def test_34_uq_agencia_nit_por_pais(self):
        self._rechaza(lambda: Agencia.objects.create(
            nombre="Otra SRL", nit=self.meridiano.nit, pais=self.bolivia))

    def test_35_uq_propietario_documento_por_pais(self):
        self._rechaza(lambda: Propietario.objects.create(
            nombre="Otro", documento=self.propietario.documento, pais=self.bolivia))

    def test_36_uq_ciudad_por_pais(self):
        self._rechaza(lambda: Ciudad.objects.create(
            pais=self.bolivia, nombre=self.santa_cruz.nombre))

    def test_37_uq_una_membresia_vigente_por_asesor(self):
        self._rechaza(lambda: AsesorAgencia.objects.create(
            asesor=self.ana, agencia=self.altiplano))

    def test_38_uq_una_captacion_vigente_por_inmueble(self):
        Captacion.objects.create(inmueble=self.inmueble, asesor=self.diego)
        self._rechaza(lambda: Captacion.objects.create(
            inmueble=self.inmueble, asesor=self.diego))

    def test_39_uq_una_portada_por_inmueble(self):
        ImagenInmueble.objects.create(
            inmueble=self.inmueble, url="https://ejemplo.com/a.jpg", es_portada=True)
        self._rechaza(lambda: ImagenInmueble.objects.create(
            inmueble=self.inmueble, url="https://ejemplo.com/b.jpg", es_portada=True))

    def test_40_uq_imagen_inmueble_url(self):
        ImagenInmueble.objects.create(
            inmueble=self.inmueble, url="https://ejemplo.com/c.jpg")
        self._rechaza(lambda: ImagenInmueble.objects.create(
            inmueble=self.inmueble, url="https://ejemplo.com/c.jpg"))

    def test_41_uq_enlace_asesor_url(self):
        AsesorEnlace.objects.create(
            asesor=self.ana, plataforma="web", url="https://ana.com")
        self._rechaza(lambda: AsesorEnlace.objects.create(
            asesor=self.ana, plataforma="web", url="https://ana.com"))

    def test_42_uq_enlace_agencia_url(self):
        AgenciaEnlace.objects.create(
            agencia=self.meridiano, plataforma="web", url="https://meridiano.com")
        self._rechaza(lambda: AgenciaEnlace.objects.create(
            agencia=self.meridiano, plataforma="web", url="https://meridiano.com"))

    def test_43_uq_participacion_por_rol_y_asesor(self):
        operacion = Operacion.objects.create(
            inmueble=self.inmueble, tipo_transaccion="venta",
            comprador_nombre="Diana", precio_cierre_usd=Decimal("100000"),
            comision_total_usd=Decimal("5000"))
        ComisionParticipacion.objects.create(
            operacion=operacion, rol="captador", asesor=self.diego,
            porcentaje=Decimal("50"))
        self._rechaza(lambda: ComisionParticipacion.objects.create(
            operacion=operacion, rol="captador", asesor=self.diego,
            porcentaje=Decimal("50")))

    # -- verificación -------------------------------------------------------
    def test_44_ck_asesor_activo_solo_si_aprobado(self):
        self._rechaza(lambda: Asesor.objects.create(
            nombre="X", apellido="Y", ci="1010101", pais=self.bolivia,
            activo=True, estado=EstadoAsesor.PENDIENTE))

    def test_45_ck_membresia_fechas_coherentes(self):
        self._rechaza(lambda: AsesorAgencia.objects.create(
            asesor=self.sin_agencia, agencia=self.meridiano,
            fecha_inicio=date(2025, 6, 1), fecha_fin=date(2025, 1, 1)))

    def test_46_ck_captacion_fechas_coherentes(self):
        self._rechaza(lambda: Captacion.objects.create(
            inmueble=self.inmueble, asesor=self.diego,
            estado=Captacion.Estado.VENCIDA,
            fecha_inicio=date(2025, 6, 1), fecha_fin=date(2025, 1, 1)))

    def test_47_ck_publicado_requiere_revisor(self):
        self._rechaza(lambda: Inmueble.objects.create(
            titulo="Sin revisor", tipo_transaccion="venta", tipo_inmueble=self.casa,
            captador=self.diego, pais=self.bolivia, ciudad=self.santa_cruz,
            estado_publicacion=EstadoPublicacion.PUBLICADO, revisado_por=None))

    def test_48_ck_inmueble_precio_no_negativo(self):
        self._rechaza(lambda: Inmueble.objects.create(
            titulo="Precio negativo", tipo_transaccion="venta",
            tipo_inmueble=self.casa, captador=self.diego, pais=self.bolivia,
            ciudad=self.santa_cruz, precio_usd=Decimal("-1")))

    def test_49_ck_operacion_precio_no_negativo(self):
        self._rechaza(lambda: Operacion.objects.create(
            inmueble=self.inmueble, tipo_transaccion="venta",
            comprador_nombre="N", precio_cierre_usd=Decimal("-5")))

    def test_50_ck_operacion_cerrada_con_fecha(self):
        self._rechaza(lambda: Operacion.objects.create(
            inmueble=self.inmueble, tipo_transaccion="venta",
            comprador_nombre="N", precio_cierre_usd=Decimal("1000"),
            estado=Operacion.Estado.CERRADA, fecha_cierre=None))

    def test_51_ck_participacion_tiene_beneficiario(self):
        operacion = Operacion.objects.create(
            inmueble=self.inmueble, tipo_transaccion="venta",
            comprador_nombre="N", precio_cierre_usd=Decimal("1000"))
        self._rechaza(lambda: ComisionParticipacion.objects.create(
            operacion=operacion, rol="mls", asesor=None, agencia=None,
            porcentaje=Decimal("10")))

    def test_52_ck_imagen_tiene_origen(self):
        self._rechaza(lambda: ImagenInmueble.objects.create(
            inmueble=self.inmueble, url="", archivo=None))
