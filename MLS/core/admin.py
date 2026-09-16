from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.gis.admin import GISModelAdmin
from django.db.models import Q

from .forms import UsuarioChangeForm, UsuarioCreationForm
from .models import (
    Agencia,
    AgenciaEnlace,
    Asesor,
    AsesorAgencia,
    AsesorEnlace,
    Captacion,
    Ciudad,
    ComisionParticipacion,
    EstadoAsesor,
    HistorialPrecio,
    ImagenInmueble,
    Inmueble,
    Operacion,
    Pais,
    Propietario,
    TipoInmueble,
    Usuario,
)


def asesor_de(request):
    return getattr(request.user, "asesor", None)


def es_admin_mls(request) -> bool:
    return request.user.is_superuser or request.user.has_perm("core.gestionar_todo_inmueble")


# ---------------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------------
class AgenciaEnlaceInline(admin.TabularInline):
    model = AgenciaEnlace
    extra = 1


class AsesorEnlaceInline(admin.TabularInline):
    model = AsesorEnlace
    extra = 1


class AsesorAgenciaInline(admin.TabularInline):
    model = AsesorAgencia
    extra = 0
    autocomplete_fields = ["agencia"]


class ImagenInmuebleInline(admin.TabularInline):
    model = ImagenInmueble
    extra = 3


class HistorialPrecioInline(admin.TabularInline):
    """Solo lectura: lo escribe Inmueble.save() automáticamente."""

    model = HistorialPrecio
    extra = 0
    can_delete = False
    readonly_fields = [
        "precio_usd", "precio_secundario", "moneda_secundaria", "motivo",
        "registrado_por", "notas", "registrado_en",
    ]

    def has_add_permission(self, request, obj=None):
        return False


class ComisionParticipacionFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        total = 0
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            total += form.cleaned_data.get("porcentaje") or 0
        if total > 100:
            raise forms.ValidationError(
                f"El reparto suma {total}%, no puede superar el 100% de la comisión."
            )


class ComisionParticipacionInline(admin.TabularInline):
    model = ComisionParticipacion
    formset = ComisionParticipacionFormSet
    extra = 2
    autocomplete_fields = ["asesor", "agencia"]


# ---------------------------------------------------------------------------
# Acceso
# ---------------------------------------------------------------------------
@admin.register(Usuario)
class UsuarioAdmin(BaseUserAdmin):
    form = UsuarioChangeForm
    add_form = UsuarioCreationForm
    ordering = ["email"]
    list_display = ["email", "nombre", "apellido", "is_active", "is_staff"]
    list_filter = ["is_active", "is_staff", "is_superuser", "groups"]
    search_fields = ["email", "nombre", "apellido"]
    filter_horizontal = ["groups", "user_permissions"]
    fieldsets = [
        (None, {"fields": ["email", "password"]}),
        ("Datos", {"fields": ["nombre", "apellido"]}),
        ("Permisos", {
            "fields": ["is_active", "is_staff", "is_superuser", "groups",
                       "user_permissions"],
        }),
        ("Fechas", {"fields": ["last_login", "date_joined"]}),
    ]
    add_fieldsets = [
        (None, {
            "classes": ["wide"],
            "fields": ["email", "nombre", "apellido", "password1", "password2"],
        }),
    ]


# ---------------------------------------------------------------------------
# Catálogos
# ---------------------------------------------------------------------------
@admin.register(Pais)
class PaisAdmin(admin.ModelAdmin):
    list_display = ["nombre", "codigo_iso", "moneda_secundaria", "activo"]
    search_fields = ["nombre", "codigo_iso"]


@admin.register(Ciudad)
class CiudadAdmin(admin.ModelAdmin):
    list_display = ["nombre", "pais", "activo"]
    list_filter = ["pais", "activo"]
    search_fields = ["nombre"]


@admin.register(TipoInmueble)
class TipoInmuebleAdmin(admin.ModelAdmin):
    list_display = ["nombre", "slug", "activo"]
    search_fields = ["nombre"]


# ---------------------------------------------------------------------------
# Actores
# ---------------------------------------------------------------------------
@admin.register(Agencia)
class AgenciaAdmin(admin.ModelAdmin):
    list_display = ["nombre", "nit", "ciudad", "celular", "activa"]
    list_filter = ["activa", "pais"]
    search_fields = ["nombre", "nit", "correo"]
    inlines = [AgenciaEnlaceInline]


@admin.register(Asesor)
class AsesorAdmin(admin.ModelAdmin):
    list_display = [
        "nombre_completo", "codigo_mls", "estado", "ci", "celular",
        "agencia_actual", "fecha_ingreso", "activo",
    ]
    list_filter = ["estado", "activo", "pais", "fecha_ingreso"]
    search_fields = ["nombre", "apellido", "ci", "codigo_mls", "correo"]
    readonly_fields = ["codigo_mls", "aprobado_por", "aprobado_en"]
    inlines = [AsesorEnlaceInline, AsesorAgenciaInline]
    actions = ["aprobar", "rechazar", "suspender"]

    # -- blindaje -----------------------------------------------------------
    # Los asesores no entran al admin (is_staff=False), pero si alguna vez se
    # revierte esa decisión, sin esto podrían editar la ficha de cualquier otro.
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if es_admin_mls(request):
            return qs
        asesor = asesor_de(request)
        return qs.filter(pk=asesor.pk) if asesor else qs.none()

    def has_change_permission(self, request, obj=None):
        if obj is None or es_admin_mls(request):
            return super().has_change_permission(request, obj)
        asesor = asesor_de(request)
        return bool(asesor and obj.pk == asesor.pk)

    def get_readonly_fields(self, request, obj=None):
        campos = list(super().get_readonly_fields(request, obj))
        if not es_admin_mls(request):
            # Nadie se auto-aprueba ni se auto-activa.
            campos += ["estado", "activo"]
        return campos

    # -- acciones -----------------------------------------------------------
    def _cambiar(self, request, queryset, estado, verbo):
        revisor = asesor_de(request)
        for asesor in queryset:
            asesor.aplicar_estado(estado, revisor=revisor)
        self.message_user(request, f"{queryset.count()} asesor(es) {verbo}.")

    @admin.action(description="Aprobar el ingreso al MLS")
    def aprobar(self, request, queryset):
        self._cambiar(request, queryset, EstadoAsesor.APROBADO, "aprobado(s)")

    @admin.action(description="Rechazar la solicitud")
    def rechazar(self, request, queryset):
        self._cambiar(request, queryset, EstadoAsesor.RECHAZADO, "rechazado(s)")

    @admin.action(description="Suspender")
    def suspender(self, request, queryset):
        self._cambiar(request, queryset, EstadoAsesor.SUSPENDIDO, "suspendido(s)")


@admin.register(AsesorAgencia)
class AsesorAgenciaAdmin(admin.ModelAdmin):
    list_display = ["asesor", "agencia", "fecha_inicio", "fecha_fin", "es_broker", "vigente"]
    list_filter = ["agencia", "es_broker"]
    autocomplete_fields = ["asesor", "agencia"]

    # `es_broker` decide quién aprueba publicaciones y quién ve la cartera de
    # toda la agencia: es el campo que jamás puede quedar auto-editable.
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if es_admin_mls(request):
            return qs
        asesor = asesor_de(request)
        return qs.filter(asesor=asesor) if asesor else qs.none()

    def has_add_permission(self, request):
        return es_admin_mls(request)

    def has_change_permission(self, request, obj=None):
        return es_admin_mls(request)

    def has_delete_permission(self, request, obj=None):
        return es_admin_mls(request)


@admin.register(Propietario)
class PropietarioAdmin(admin.ModelAdmin):
    """Datos sensibles: cada asesor ve solo los propietarios que registró."""

    list_display = ["nombre_completo", "tipo_persona", "documento", "celular", "activo"]
    list_filter = ["tipo_persona", "pais", "activo"]
    search_fields = ["nombre", "apellido", "documento", "celular", "correo"]
    autocomplete_fields = ["registrado_por"]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if es_admin_mls(request):
            return qs
        asesor = asesor_de(request)
        return qs.filter(registrado_por=asesor) if asesor else qs.none()

    def save_model(self, request, obj, form, change):
        if not change and not obj.registrado_por_id:
            obj.registrado_por = asesor_de(request)
        super().save_model(request, obj, form, change)


# ---------------------------------------------------------------------------
# Inmuebles
# ---------------------------------------------------------------------------
@admin.register(Inmueble)
class InmuebleAdmin(GISModelAdmin):
    list_display = [
        "codigo", "titulo", "tipo_inmueble", "tipo_transaccion", "ciudad",
        "precio_usd", "estado_publicacion", "captador", "activo",
    ]
    list_filter = [
        "activo", "estado_publicacion", "tipo_transaccion", "tipo_inmueble",
        "pais", "ciudad", "piscina",
    ]
    search_fields = ["codigo", "titulo", "zona", "calle", "descripcion"]
    autocomplete_fields = ["captador", "agencia_captadora", "ciudad", "pais"]
    readonly_fields = [
        "id", "codigo", "creado_en", "actualizado_en",
        "enviado_a_revision_en", "revisado_por", "revisado_en",
    ]
    inlines = [ImagenInmuebleInline, HistorialPrecioInline]
    date_hierarchy = "creado_en"
    fieldsets = [
        (None, {"fields": ["id", "codigo", "titulo", "slug", "descripcion", "activo"]}),
        ("Clasificación", {
            "fields": ["tipo_transaccion", "tipo_inmueble", "estado_publicacion",
                       "publicado_en"],
        }),
        ("Responsables", {"fields": ["captador", "agencia_captadora"]}),
        ("Ubicación pública", {
            "fields": ["pais", "ciudad", "zona", "referencia_publica"],
        }),
        ("Ubicación privada", {
            "classes": ["collapse"],
            "description": "Solo visible para quien captó el inmueble y administradores.",
            "fields": ["calle", "numero_puerta", "ubicacion",
                       "mostrar_direccion_exacta", "radio_privacidad_m"],
        }),
        ("Distribución", {
            "fields": ["cuartos", "banos", "medios_banos", "cocina", "estacionamientos",
                       "niveles_construidos", "tipo_piso", "piscina",
                       "estado_conservacion", "uso_suelo"],
        }),
        ("Superficies (m²)", {
            "fields": ["metros_frente", "metros_fondo", "area_construida", "area_terreno",
                       "m2_cocina", "m2_almacen", "m2_jardin"],
        }),
        ("Precios", {
            "fields": ["precio_usd", "precio_secundario", "moneda_secundaria",
                       "precio_secundario_fijo"],
        }),
        ("MLS", {"fields": ["comparte_comision", "comision_compartida_pct"]}),
        ("Revisión", {
            "description": "Nada llega a publicado sin que conste quién lo aprobó.",
            "fields": ["enviado_a_revision_en", "revisado_por", "revisado_en",
                       "motivo_rechazo"],
        }),
        ("Auditoría", {"classes": ["collapse"], "fields": ["creado_en", "actualizado_en"]}),
    ]

    # -- reglas de acceso ---------------------------------------------------
    def get_queryset(self, request):
        """Ver: todo el MLS. Editar: lo controla has_change_permission."""
        return super().get_queryset(request).select_related(
            "tipo_inmueble", "ciudad", "captador", "agencia_captadora"
        )

    def get_search_fields(self, request):
        campos = list(self.search_fields)
        if not request.user.has_perm("core.ver_direccion_exacta"):
            # Sin este permiso no se busca por dirección exacta ajena: el admin
            # no consulta `ver_direccion_exacta` por su cuenta.
            campos = [c for c in campos if c != "calle"]
        return campos

    def has_change_permission(self, request, obj=None):
        if obj is None:
            return super().has_change_permission(request)
        return super().has_change_permission(request, obj) and obj.puede_editar(request.user)

    def has_delete_permission(self, request, obj=None):
        # Los inmuebles no se borran: se dan de baja con `activo`.
        return False

    def get_readonly_fields(self, request, obj=None):
        campos = list(super().get_readonly_fields(request, obj))
        if obj is not None and not obj.puede_ver_datos_sensibles(request.user):
            campos += ["calle", "numero_puerta", "ubicacion"]
        return campos

    def save_model(self, request, obj, form, change):
        if not change and not obj.captador_id:
            obj.captador = asesor_de(request)
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instancias = formset.save(commit=False)
        for instancia in instancias:
            if isinstance(instancia, HistorialPrecio) and not instancia.registrado_por_id:
                instancia.registrado_por = asesor_de(request)
            instancia.save()
        formset.save_m2m()
        for obj in formset.deleted_objects:
            obj.delete()

    @admin.action(description="Dar de baja (baja lógica)")
    def dar_de_baja(self, request, queryset):
        for inmueble in queryset:
            if inmueble.puede_editar(request.user):
                inmueble.delete()  # baja lógica

    @admin.action(description="Reactivar")
    def reactivar(self, request, queryset):
        for inmueble in queryset:
            if inmueble.puede_editar(request.user):
                inmueble.activo = True
                inmueble.save(update_fields=["activo", "actualizado_en"])

    @admin.action(description="Aprobar y publicar")
    def aprobar_publicacion(self, request, queryset):
        revisor = asesor_de(request)
        aprobados = 0
        for inmueble in queryset:
            if inmueble.puede_aprobar_publicacion(request.user):
                inmueble.aprobar_publicacion(revisor)
                aprobados += 1
        self.message_user(request, f"{aprobados} inmueble(s) publicado(s).")

    @admin.action(description="Devolver a borrador")
    def devolver_a_borrador(self, request, queryset):
        revisor = asesor_de(request)
        for inmueble in queryset:
            if inmueble.puede_aprobar_publicacion(request.user):
                inmueble.rechazar_publicacion(revisor, "Devuelto por el administrador.")
        self.message_user(request, "Listo.")

    actions = ["aprobar_publicacion", "devolver_a_borrador", "dar_de_baja", "reactivar"]


@admin.register(HistorialPrecio)
class HistorialPrecioAdmin(admin.ModelAdmin):
    list_display = [
        "inmueble", "precio_usd", "precio_secundario", "moneda_secundaria",
        "motivo", "registrado_en",
    ]
    list_filter = ["motivo", "moneda_secundaria"]
    search_fields = ["inmueble__codigo", "inmueble__titulo"]
    date_hierarchy = "registrado_en"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# ---------------------------------------------------------------------------
# Negocio
# ---------------------------------------------------------------------------
@admin.register(Captacion)
class CaptacionAdmin(admin.ModelAdmin):
    list_display = [
        "inmueble", "tipo", "asesor", "agencia", "fecha_inicio", "fecha_fin",
        "comision_pactada_pct", "estado",
    ]
    list_filter = ["tipo", "estado", "agencia"]
    search_fields = ["inmueble__codigo", "inmueble__titulo", "propietarios__nombre"]
    autocomplete_fields = ["inmueble", "asesor", "agencia"]
    filter_horizontal = ["propietarios"]

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("inmueble", "asesor", "agencia")
        if es_admin_mls(request):
            return qs
        asesor = asesor_de(request)
        return qs.filter(asesor=asesor) if asesor else qs.none()

    def save_model(self, request, obj, form, change):
        if not change and not obj.asesor_id:
            obj.asesor = asesor_de(request)
        super().save_model(request, obj, form, change)


@admin.register(Operacion)
class OperacionAdmin(admin.ModelAdmin):
    list_display = [
        "inmueble", "tipo_transaccion", "estado", "comprador_nombre",
        "precio_cierre_usd", "comision_total_usd", "fecha_cierre",
    ]
    list_filter = ["estado", "tipo_transaccion", "fecha_cierre"]
    search_fields = ["inmueble__codigo", "inmueble__titulo", "comprador_nombre"]
    autocomplete_fields = ["inmueble", "captacion"]
    readonly_fields = ["id", "creado_en", "actualizado_en"]
    inlines = [ComisionParticipacionInline]
    date_hierarchy = "fecha_cierre"

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("inmueble")
        if es_admin_mls(request):
            return qs
        asesor = asesor_de(request)
        if asesor is None:
            return qs.none()
        # Ve las operaciones donde participa: captó, colocó o cobra comisión.
        return qs.filter(
            Q(inmueble__captador=asesor) | Q(participaciones__asesor=asesor)
        ).distinct()


@admin.register(ComisionParticipacion)
class ComisionParticipacionAdmin(admin.ModelAdmin):
    list_display = ["operacion", "rol", "asesor", "agencia", "porcentaje",
                    "monto_usd", "pagada", "fecha_pago"]
    list_filter = ["rol", "pagada", "agencia"]
    search_fields = ["asesor__nombre", "asesor__apellido", "operacion__inmueble__codigo"]
    autocomplete_fields = ["operacion", "asesor", "agencia"]
