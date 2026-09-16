"""Mundo mínimo compartido por los cuatro bloques de pruebas."""

from decimal import Decimal

from django.contrib.gis.geos import Point
from django.test import TestCase

from core.models import (
    Agencia,
    Asesor,
    AsesorAgencia,
    Ciudad,
    EstadoPublicacion,
    Inmueble,
    Pais,
    Propietario,
    TipoInmueble,
    Usuario,
)

CLAVE = "Prueba-MLS-2026"


class BaseMLS(TestCase):
    """Dos agencias, tres asesores y un inmueble publicado.

    Ana es broker de Meridiano; Diego, asesor de la misma agencia; Beto, asesor
    de otra. Esa configuración es la que permite distinguir el aislamiento
    entre agencias del aislamiento entre asesores.
    """

    @classmethod
    def setUpTestData(cls):
        cls.bolivia = Pais.objects.create(
            nombre="Bolivia", codigo_iso="BO", prefijo_telefonico="+591",
            moneda_secundaria="BOB",
        )
        cls.peru = Pais.objects.create(
            nombre="Perú", codigo_iso="PE", moneda_secundaria="PEN",
        )
        cls.santa_cruz = Ciudad.objects.create(pais=cls.bolivia, nombre="Santa Cruz")
        cls.lima = Ciudad.objects.create(pais=cls.peru, nombre="Lima")
        cls.casa = TipoInmueble.objects.create(nombre="Casa")

        cls.meridiano = Agencia.objects.create(
            nombre="Meridiano Propiedades", nit="1023456789", pais=cls.bolivia,
        )
        cls.altiplano = Agencia.objects.create(
            nombre="Altiplano Inmobiliaria", nit="3011223344", pais=cls.bolivia,
        )

        cls.ana, cls.u_ana = cls._crear_asesor(
            "Ana", "Rojas", "7654321", cls.meridiano, broker=True)
        cls.diego, cls.u_diego = cls._crear_asesor(
            "Diego", "Salazar", "9900112", cls.meridiano)
        cls.beto, cls.u_beto = cls._crear_asesor(
            "Beto", "Lima", "1122334", cls.altiplano)
        # Asesor aprobado pero sin agencia: no puede publicar.
        cls.sin_agencia, cls.u_sin_agencia = cls._crear_asesor(
            "Sara", "Vega", "5544332", None)

        cls.propietario = Propietario.objects.create(
            nombre="Carlos", apellido="Vaca", documento="9988776",
            pais=cls.bolivia, registrado_por=cls.diego,
        )
        cls.inmueble = cls.crear_inmueble(cls.diego, "Casa de Diego")

    @classmethod
    def _crear_asesor(cls, nombre, apellido, ci, agencia, broker=False):
        usuario = Usuario.objects.create_user(
            email=f"{nombre.lower()}.{apellido.lower()}@latammls.com",
            password=CLAVE, nombre=nombre, apellido=apellido,
        )
        asesor = Asesor.objects.create(
            usuario=usuario, nombre=nombre, apellido=apellido, ci=ci,
            pais=cls.bolivia, correo=usuario.email,
        )
        if agencia is not None:
            AsesorAgencia.objects.create(
                asesor=asesor, agencia=agencia, es_broker=broker)
        return asesor, usuario

    @classmethod
    def crear_inmueble(cls, captador, titulo, precio="150000", publicado=False):
        inmueble = Inmueble.objects.create(
            titulo=titulo, tipo_transaccion="venta", tipo_inmueble=cls.casa,
            captador=captador, pais=cls.bolivia, ciudad=cls.santa_cruz,
            zona="Equipetrol", calle="Av. San Martín 123",
            cuartos=3, banos=2, area_construida=Decimal("240"),
            precio_usd=Decimal(precio),
            ubicacion=Point(-63.1821, -17.7667, srid=4326),
        )
        if publicado:
            inmueble.aprobar_publicacion(captador)
        return inmueble

    def entrar(self, usuario):
        """Devuelve un cliente con sesión iniciada para ese usuario."""
        from django.test import Client
        cliente = Client()
        ok = cliente.login(username=usuario.email, password=CLAVE)
        self.assertTrue(ok, f"no se pudo iniciar sesión como {usuario.email}")
        return cliente
