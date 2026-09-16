"""Crea el grupo de administradores del MLS con sus permisos.

    python manage.py seed_grupos

Los asesores NO necesitan grupo: no entran al admin de Django y todo su
acceso pasa por /panel/, filtrado fila por fila con `Inmueble.puede_editar()`,
`visibles_para()` y `puede_aprobar_publicacion()` — la capa que los permisos
de Django, que son por tabla, no cubren.
"""

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

# Modelos de catálogo que el administrador del MLS gestiona por completo.
CATALOGOS = ["pais", "ciudad", "tipoinmueble", "agencia", "asesor", "asesoragencia"]

PERMISOS_PROPIOS = ["gestionar_todo_inmueble", "ver_direccion_exacta"]


class Command(BaseCommand):
    help = "Crea el grupo 'Administrador MLS' y le asigna sus permisos."

    def handle(self, *args, **opciones):
        grupo, creado = Group.objects.get_or_create(name="Administrador MLS")

        permisos = list(
            Permission.objects.filter(
                content_type__app_label="core", codename__in=PERMISOS_PROPIOS
            )
        )
        for modelo in CATALOGOS:
            permisos += Permission.objects.filter(
                content_type__app_label="core", content_type__model=modelo
            )
        # Inventario completo, sin borrar (los inmuebles son baja lógica).
        permisos += Permission.objects.filter(
            content_type__app_label="core",
            content_type__model__in=[
                "inmueble", "imageninmueble", "captacion", "propietario",
                "operacion", "comisionparticipacion", "historialprecio",
            ],
        ).exclude(codename__startswith="delete_")

        grupo.permissions.set(permisos)
        estado = "creado" if creado else "actualizado"
        self.stdout.write(
            self.style.SUCCESS(
                f"Grupo 'Administrador MLS' {estado} con {len(set(permisos))} permisos."
            )
        )
