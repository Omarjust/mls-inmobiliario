"""Carga datos de demostración para ver la landing con contenido real.

    python manage.py seed_demo          # agrega lo que falte
    python manage.py seed_demo --reset  # borra antes lo cargado por este comando
"""

import random
from decimal import Decimal

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import (
    Agencia,
    Asesor,
    AsesorAgencia,
    Captacion,
    Ciudad,
    EstadoConservacion,
    EstadoPublicacion,
    HistorialPrecio,
    ImagenInmueble,
    Inmueble,
    Operacion,
    Pais,
    Propietario,
    TipoInmueble,
    TipoTransaccion,
    Usuario,
)

PAISES = [
    ("Bolivia", "BO", "+591", "BOB"),
    ("Perú", "PE", "+51", "PEN"),
]

CIUDADES = {
    "BO": [
        ("Santa Cruz de la Sierra", -17.7833, -63.1821),
        ("La Paz", -16.4897, -68.1193),
        ("Cochabamba", -17.3895, -66.1568),
    ],
    "PE": [("Lima", -12.0464, -77.0428)],
}

TIPOS = ["Casa", "Departamento", "Terreno", "Oficina", "Local comercial", "Galpón"]

AGENCIAS = [
    ("Meridiano Propiedades", "1023456789"),
    ("Casa Norte Bienes Raíces", "2098765432"),
    ("Altiplano Inmobiliaria", "3011223344"),
]

ASESORES = [
    ("Ana", "Rojas", "7654321"),
    ("Beto", "Lima", "1122334"),
    ("Carla", "Peredo", "5566778"),
    ("Diego", "Salazar", "9900112"),
]

INMUEBLES = [
    ("Casa de 3 dormitorios con jardín en Equipetrol", "Casa", "venta", "Equipetrol",
     189000, 3, 2, 2, 240, 360, True),
    ("Departamento premium frente al parque", "Departamento", "venta", "Urubó",
     142000, 2, 2, 1, 118, None, False),
    ("Terreno de 800 m² sobre avenida principal", "Terreno", "venta", "Radial 26",
     96000, None, None, 0, None, 800, False),
    ("Oficina corporativa en torre A", "Oficina", "alquiler", "Centro empresarial",
     1450, None, 2, 2, 165, None, False),
    ("Casa familiar en condominio cerrado", "Casa", "venta", "Las Palmas",
     275000, 4, 3, 3, 310, 500, True),
    ("Departamento de 1 dormitorio amoblado", "Departamento", "alquiler", "Sopocachi",
     620, 1, 1, 1, 62, None, False),
    ("Local comercial a pie de calle", "Local comercial", "alquiler", "Miraflores",
     2100, None, 1, 0, 95, None, False),
    ("Casa colonial restaurada en el casco viejo", "Casa", "venta", "Casco Viejo",
     320000, 5, 4, 2, 380, 420, False),
    ("Departamento con vista a la cordillera", "Departamento", "anticretico", "Calacoto",
     45000, 3, 2, 1, 135, None, False),
    ("Galpón industrial con oficinas", "Galpón", "venta", "Parque Industrial",
     410000, None, 2, 6, 1200, 2000, False),
    ("Departamento en preventa · entrega 2027", "Departamento", "preventa", "San Isidro",
     168000, 2, 2, 1, 96, None, True),
    ("Casa de campo con piscina", "Casa", "venta", "Zona Norte",
     345000, 4, 4, 4, 420, 1500, True),
]

CLAVE_DEMO = "demo12345"

DESCRIPCION = (
    "Excelente propiedad en una de las zonas de mayor plusvalía de la ciudad. "
    "Ambientes amplios y luminosos, terminaciones de primera calidad y acceso "
    "inmediato a colegios, supermercados y vías principales. Ideal tanto para "
    "vivienda como para inversión. Coordiná tu visita con el asesor a cargo."
)


class Command(BaseCommand):
    help = "Carga inmuebles, asesores y agencias de demostración."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true", help="Borra los datos de demo antes de cargar."
        )

    @transaction.atomic
    def handle(self, *args, **opciones):
        rnd = random.Random(7)

        if opciones["reset"]:
            # Orden inverso a las dependencias PROTECT.
            Operacion.objects.all().delete()
            Captacion.objects.all().delete()
            ImagenInmueble.objects.all().delete()
            HistorialPrecio.objects.all().delete()
            # QuerySet.delete() borra de verdad; la baja lógica es solo del modelo.
            Inmueble.objects.all().delete()
            Propietario.objects.all().delete()
            AsesorAgencia.objects.all().delete()
            correos = list(
                Asesor.objects.exclude(usuario=None).values_list("usuario__email", flat=True)
            )
            Asesor.objects.all().delete()
            Usuario.objects.filter(email__in=correos).delete()
            Agencia.objects.all().delete()
            self.stdout.write("Datos de demo eliminados.")

        # --- catálogos -----------------------------------------------------
        paises = {}
        for nombre, iso, prefijo, moneda in PAISES:
            paises[iso], _ = Pais.objects.get_or_create(
                codigo_iso=iso,
                defaults={
                    "nombre": nombre,
                    "prefijo_telefonico": prefijo,
                    "moneda_secundaria": moneda,
                },
            )

        ciudades = []
        for iso, listado in CIUDADES.items():
            for nombre, lat, lon in listado:
                ciudad, _ = Ciudad.objects.get_or_create(pais=paises[iso], nombre=nombre)
                ciudades.append((ciudad, lat, lon))

        tipos = {
            nombre: TipoInmueble.objects.get_or_create(nombre=nombre)[0] for nombre in TIPOS
        }

        # --- agencias y asesores -------------------------------------------
        bo = paises["BO"]
        agencias = []
        for nombre, nit in AGENCIAS:
            agencia, _ = Agencia.objects.get_or_create(
                nombre=nombre,
                defaults={
                    "nit": nit,
                    "pais": bo,
                    "ciudad": ciudades[0][0],
                    "celular": f"+591 7{rnd.randint(1000000, 9999999)}",
                    "correo": f"contacto@{nombre.split()[0].lower()}.com",
                    "direccion": "Av. San Martín, Equipetrol",
                    "descripcion": "Agencia asociada a la red LatamMLS.",
                },
            )
            agencias.append(agencia)

        asesores = []
        for indice, (nombre, apellido, ci) in enumerate(ASESORES):
            correo = f"{nombre.lower()}.{apellido.lower()}@latammls.com"
            asesor = Asesor.objects.filter(ci=ci, pais=bo).first()
            if asesor is None:
                usuario, _ = Usuario.objects.get_or_create(
                    email=correo,
                    defaults={"nombre": nombre, "apellido": apellido},
                )
                # Contraseña conocida, solo para probar el panel en desarrollo.
                usuario.set_password(CLAVE_DEMO)
                usuario.save()
                asesor = Asesor.objects.create(
                    usuario=usuario,
                    nombre=nombre,
                    apellido=apellido,
                    ci=ci,
                    pais=bo,
                    celular=f"+591 7{rnd.randint(1000000, 9999999)}",
                    correo=correo,
                )
                AsesorAgencia.objects.create(
                    asesor=asesor,
                    agencia=agencias[indice % len(agencias)],
                    es_broker=(indice == 0),
                    cargo="Broker" if indice == 0 else "Asesor",
                )
            asesores.append(asesor)

        # --- inmuebles ------------------------------------------------------
        broker = next((a for a in asesores if a.es_broker), asesores[0])
        creados = 0
        for indice, datos in enumerate(INMUEBLES):
            (titulo, tipo, operacion, zona, precio, cuartos, banos,
             garajes, construida, terreno, piscina) = datos

            if Inmueble.objects.filter(titulo=titulo).exists():
                continue

            ciudad, lat, lon = ciudades[indice % len(ciudades)]
            captador = asesores[indice % len(asesores)]

            inmueble = Inmueble.objects.create(
                titulo=titulo,
                descripcion=DESCRIPCION,
                tipo_transaccion=operacion,
                tipo_inmueble=tipos[tipo],
                estado_publicacion=EstadoPublicacion.BORRADOR,
                captador=captador,
                pais=ciudad.pais,
                ciudad=ciudad,
                zona=zona,
                calle=f"Calle {rnd.randint(1, 40)} N° {rnd.randint(100, 900)}",
                referencia_publica="A pocas cuadras de la avenida principal",
                ubicacion=Point(
                    lon + rnd.uniform(-0.04, 0.04),
                    lat + rnd.uniform(-0.04, 0.04),
                    srid=4326,
                ),
                cuartos=cuartos,
                banos=banos,
                medios_banos=rnd.choice([0, 1]),
                estacionamientos=garajes,
                niveles_construidos=rnd.choice([1, 2, 2, 3]),
                tipo_piso=rnd.choice(["Porcelanato", "Cerámica", "Madera", "Micro cemento"]),
                piscina=piscina,
                estado_conservacion=rnd.choice(
                    [EstadoConservacion.A_ESTRENAR, EstadoConservacion.EXCELENTE,
                     EstadoConservacion.BUENO]
                ),
                cocina="Cocina independiente con muebles bajo y sobre mesada.",
                area_construida=construida,
                area_terreno=terreno,
                precio_usd=Decimal(precio),
                precio_secundario=Decimal(precio) * Decimal("6.96"),
                comparte_comision=True,
                comision_compartida_pct=Decimal("50.00"),
            )

            for posicion in range(rnd.randint(3, 5)):
                ImagenInmueble.objects.create(
                    inmueble=inmueble,
                    url=f"https://picsum.photos/seed/mls-{indice}-{posicion}/1200/900",
                    orden=posicion,
                    es_portada=(posicion == 0),
                    descripcion="Fotografía de referencia",
                )

            propietario = Propietario.objects.create(
                nombre=rnd.choice(["Carlos", "Marcela", "Javier", "Lucía", "Rodrigo"]),
                apellido=rnd.choice(["Vaca", "Áñez", "Quispe", "Montero", "Aguirre"]),
                documento=str(rnd.randint(1000000, 9999999)),
                pais=ciudad.pais,
                celular=f"+591 7{rnd.randint(1000000, 9999999)}",
                registrado_por=captador,
            )
            captacion = Captacion.objects.create(
                inmueble=inmueble,
                asesor=captador,
                tipo=rnd.choice([Captacion.Tipo.EXCLUSIVA, Captacion.Tipo.ABIERTA]),
                comision_pactada_pct=Decimal("5.00"),
                precio_autorizado_usd=Decimal(precio),
            )
            captacion.propietarios.add(propietario)

            # Los dos últimos quedan esperando al broker, para poder ver la
            # cola de aprobación con datos; el resto nace ya aprobado.
            if indice >= len(INMUEBLES) - 2:
                inmueble.enviar_a_revision()
            else:
                inmueble.aprobar_publicacion(broker)
            creados += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Listo: {creados} inmuebles nuevos · "
                f"{Agencia.objects.count()} agencias · {Asesor.objects.count()} asesores.\n"
                f"Entrá como broker: {asesores[0].usuario.email} / {CLAVE_DEMO}"
            )
        )
