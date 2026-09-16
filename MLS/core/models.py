"""Modelos del MLS (Multiple Listing Service) inmobiliario.

Estructura:
    Acceso         -> Usuario
    Catálogos      -> Pais, Ciudad, TipoInmueble
    Actores        -> Agencia, Asesor, AsesorAgencia (historial), Propietario
    Publicaciones  -> Inmueble, HistorialPrecio, ImagenInmueble
    Negocio        -> Captacion, Operacion, ComisionParticipacion

Convenciones del proyecto:
  * Los inmuebles NUNCA se borran: `delete()` hace baja lógica (`activo=False`).
  * La geometría vive en `Inmueble.ubicacion` (PostGIS); lat/lon son propiedades.
  * `calle` es dato privado del MLS; el público solo ve zona/ciudad.
  * Nada se publica sin que un broker lo apruebe (ver `Inmueble.aprobar_publicacion`).
"""

import math
import pathlib
import random
import uuid

from django.conf import settings
from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.contrib.gis.db import models as gis_models
from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.dispatch import receiver
from django.utils import timezone
from django.utils.text import slugify

from .storage import almacenamiento_imagenes


# ---------------------------------------------------------------------------
# Bases reutilizables
# ---------------------------------------------------------------------------
class TimeStampedModel(models.Model):
    """Auditoría mínima: cuándo se creó y cuándo se tocó por última vez."""

    creado_en = models.DateTimeField(auto_now_add=True, db_index=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Acceso
# ---------------------------------------------------------------------------
class UsuarioManager(BaseUserManager):
    """Manager del usuario propio: la identidad es el correo."""

    use_in_migrations = True

    def get_by_natural_key(self, username):
        # Login case-insensitive: "Ana@x.com" y "ana@x.com" son la misma cuenta.
        return self.get(email__iexact=username)

    def _crear(self, email, password, **extra):
        if not email:
            raise ValueError("El correo electrónico es obligatorio.")
        usuario = self.model(email=self.normalize_email(email).lower(), **extra)
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._crear(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_active", True)
        if not extra.get("is_staff") or not extra.get("is_superuser"):
            raise ValueError("Un superusuario necesita is_staff e is_superuser en True.")
        return self._crear(email, password, **extra)


class Usuario(AbstractBaseUser, PermissionsMixin):
    """Cuenta de acceso al sistema. La identidad es el correo.

    `auth.User` no servía: su `username` solo admite letras, números y
    los signos . @ + - _ , así que
    correos perfectamente válidos como o'brien@x.com no pueden usarse como
    identidad, y su límite de 150 caracteres corta correos de hasta 254.
    """

    email = models.EmailField("correo electrónico", max_length=254, unique=True)
    nombre = models.CharField(max_length=150, blank=True)
    apellido = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField("activo", default=True)
    is_staff = models.BooleanField("acceso al admin", default=False)
    date_joined = models.DateTimeField("fecha de alta", default=timezone.now)

    objects = UsuarioManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        ordering = ["email"]
        constraints = [
            # `unique=True` distingue mayúsculas; esto hace la unicidad real.
            models.UniqueConstraint(Lower("email"), name="uq_usuario_email_ci"),
        ]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = self.email.lower()
        super().save(*args, **kwargs)

    def get_full_name(self):
        return f"{self.nombre} {self.apellido}".strip() or self.email

    def get_short_name(self):
        return self.nombre or self.email


class Plataforma(models.TextChoices):
    FACEBOOK = "facebook", "Facebook"
    INSTAGRAM = "instagram", "Instagram"
    TIKTOK = "tiktok", "TikTok"
    WHATSAPP = "whatsapp", "WhatsApp"
    LINKEDIN = "linkedin", "LinkedIn"
    YOUTUBE = "youtube", "YouTube"
    X = "x", "X (Twitter)"
    WEB = "web", "Sitio web"
    OTRO = "otro", "Otro"


class EnlaceSocial(TimeStampedModel):
    """Base abstracta para los links (red social, url) de asesores y agencias."""

    plataforma = models.CharField(max_length=20, choices=Plataforma.choices)
    url = models.URLField(max_length=300)
    etiqueta = models.CharField(max_length=80, blank=True)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        abstract = True
        ordering = ["orden", "plataforma"]

    def __str__(self):
        return f"{self.get_plataforma_display()}: {self.url}"


# ---------------------------------------------------------------------------
# Catálogos
# ---------------------------------------------------------------------------
class Pais(models.Model):
    nombre = models.CharField(max_length=80, unique=True)
    codigo_iso = models.CharField(
        "código ISO 3166-1 alfa-2", max_length=2, unique=True, help_text="BO, PE, MX…"
    )
    prefijo_telefonico = models.CharField(max_length=6, blank=True, help_text="+591")
    # Permite resolver el "precio secundario" sin hardcodear la moneda por país.
    moneda_secundaria = models.CharField(
        max_length=3, blank=True, help_text="Código ISO 4217: BOB, PEN, MXN…"
    )
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "país"
        verbose_name_plural = "países"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Ciudad(models.Model):
    pais = models.ForeignKey(Pais, on_delete=models.PROTECT, related_name="ciudades")
    nombre = models.CharField(max_length=120)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "ciudades"
        ordering = ["pais__nombre", "nombre"]
        constraints = [
            models.UniqueConstraint(fields=["pais", "nombre"], name="uq_ciudad_por_pais")
        ]

    def __str__(self):
        return f"{self.nombre}, {self.pais.codigo_iso}"


class TipoInmueble(models.Model):
    nombre = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=90, unique=True, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "tipo de inmueble"
        verbose_name_plural = "tipos de inmueble"
        ordering = ["nombre"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nombre)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre


# ---------------------------------------------------------------------------
# Agencias
# ---------------------------------------------------------------------------
class Agencia(TimeStampedModel):
    nombre = models.CharField(max_length=150, unique=True)
    nit = models.CharField("NIT / RUC / RFC", max_length=30, blank=True)
    pais = models.ForeignKey(
        Pais, on_delete=models.PROTECT, related_name="agencias", null=True, blank=True
    )
    ciudad = models.ForeignKey(
        Ciudad, on_delete=models.PROTECT, related_name="agencias", null=True, blank=True
    )
    celular = models.CharField(max_length=25, blank=True)
    correo = models.EmailField(blank=True)
    direccion = models.CharField(max_length=255, blank=True)
    descripcion = models.TextField(blank=True)
    logo_url = models.URLField(max_length=500, blank=True)
    activa = models.BooleanField(default=True, db_index=True)

    class Meta:
        verbose_name = "agencia"
        verbose_name_plural = "agencias"
        ordering = ["nombre"]
        constraints = [
            # NIT único solo cuando existe (varias agencias pueden no tenerlo cargado).
            models.UniqueConstraint(
                fields=["pais", "nit"],
                condition=~models.Q(nit=""),
                name="uq_agencia_nit_por_pais",
            )
        ]

    def __str__(self):
        return self.nombre

    @property
    def asesores_activos(self):
        return Asesor.objects.filter(
            membresias__agencia=self, membresias__fecha_fin__isnull=True, activo=True
        )


class AgenciaEnlace(EnlaceSocial):
    agencia = models.ForeignKey(Agencia, on_delete=models.CASCADE, related_name="enlaces")

    class Meta(EnlaceSocial.Meta):
        verbose_name = "enlace de agencia"
        verbose_name_plural = "enlaces de agencia"
        constraints = [
            models.UniqueConstraint(fields=["agencia", "url"], name="uq_enlace_agencia_url")
        ]


# ---------------------------------------------------------------------------
# Asesores
# ---------------------------------------------------------------------------
class EstadoAsesor(models.TextChoices):
    PENDIENTE = "pendiente", "Pendiente de aprobación"
    APROBADO = "aprobado", "Aprobado"
    RECHAZADO = "rechazado", "Rechazado"
    SUSPENDIDO = "suspendido", "Suspendido"


def generar_codigo_asesor() -> str:
    """Identidad propia del asesor dentro del MLS (no depende de una ley local)."""
    return f"MLS-A-{uuid.uuid4().hex[:8].upper()}"


class Asesor(TimeStampedModel):
    # Cuenta de acceso al sistema (opcional: un asesor puede existir sin login).
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asesor",
    )
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    ci = models.CharField("CI / documento de identidad", max_length=30)
    pais = models.ForeignKey(
        Pais, on_delete=models.PROTECT, related_name="asesores", null=True, blank=True
    )
    # Identificación propia del MLS: siempre existe, es la que se muestra públicamente.
    codigo_mls = models.CharField(
        max_length=20, unique=True, default=generar_codigo_asesor, editable=False
    )
    # Matrícula oficial, si el país tiene ley/registro de asesores inmobiliarios.
    registro_oficial = models.CharField(
        max_length=50, blank=True, help_text="Matrícula oficial donde exista la ley"
    )
    celular = models.CharField(max_length=25, blank=True)
    correo = models.EmailField(blank=True)
    foto_url = models.URLField(max_length=500, blank=True)
    fecha_ingreso = models.DateField(default=timezone.localdate)
    # `activo` = opera hoy dentro del MLS. `estado` = dónde está en el circuito
    # de alta. Son cosas distintas y una constraint impide que se contradigan.
    activo = models.BooleanField("activo dentro del MLS", default=True, db_index=True)
    estado = models.CharField(
        max_length=12,
        choices=EstadoAsesor.choices,
        default=EstadoAsesor.APROBADO,
        db_index=True,
        help_text="Las altas cargadas por un administrador nacen aprobadas",
    )
    aprobado_por = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="asesores_aprobados",
    )
    aprobado_en = models.DateTimeField(null=True, blank=True)

    agencias = models.ManyToManyField(
        Agencia, through="AsesorAgencia", related_name="asesores", blank=True
    )

    class Meta:
        verbose_name = "asesor"
        verbose_name_plural = "asesores"
        ordering = ["apellido", "nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["pais", "ci"],
                condition=~models.Q(ci=""),
                name="uq_asesor_ci_por_pais",
            ),
            # Nadie opera sin estar aprobado.
            models.CheckConstraint(
                condition=models.Q(activo=False)
                | models.Q(estado=EstadoAsesor.APROBADO),
                name="ck_asesor_activo_solo_si_aprobado",
            ),
        ]
        indexes = [models.Index(fields=["activo", "apellido"])]

    def __str__(self):
        return f"{self.nombre} {self.apellido} ({self.codigo_mls})"

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombre} {self.apellido}".strip()

    @property
    def membresia_actual(self):
        return self.membresias.filter(fecha_fin__isnull=True).select_related("agencia").first()

    @property
    def agencia_actual(self):
        membresia = self.membresia_actual
        return membresia.agencia if membresia else None

    @property
    def es_broker(self) -> bool:
        """Un broker administra toda la cartera de su agencia, no solo la propia."""
        membresia = self.membresia_actual
        return bool(membresia and membresia.es_broker)

    @property
    def esta_aprobado(self) -> bool:
        return self.estado == EstadoAsesor.APROBADO

    def aplicar_estado(self, estado, *, revisor=None):
        """Única puerta para cambiar el estado del asesor.

        Deriva desde acá `activo` y el `is_active` de la cuenta, para que las
        tres banderas no puedan contradecirse. Un PENDIENTE conserva
        `is_active=True`: puede entrar, pero el panel lo frena con un mensaje
        claro en vez de un "credenciales incorrectas" que no explica nada.
        """
        self.estado = estado
        self.activo = estado == EstadoAsesor.APROBADO
        if self.activo and self.aprobado_en is None:
            self.aprobado_por = revisor
            self.aprobado_en = timezone.now()
        self.save(
            update_fields=[
                "estado", "activo", "aprobado_por", "aprobado_en", "actualizado_en",
            ]
        )
        if self.usuario_id:
            puede_entrar = estado in {EstadoAsesor.PENDIENTE, EstadoAsesor.APROBADO}
            if self.usuario.is_active != puede_entrar:
                self.usuario.is_active = puede_entrar
                self.usuario.save(update_fields=["is_active"])


class AsesorEnlace(EnlaceSocial):
    asesor = models.ForeignKey(Asesor, on_delete=models.CASCADE, related_name="enlaces")

    class Meta(EnlaceSocial.Meta):
        verbose_name = "enlace de asesor"
        verbose_name_plural = "enlaces de asesor"
        constraints = [
            models.UniqueConstraint(fields=["asesor", "url"], name="uq_enlace_asesor_url")
        ]


class AsesorAgencia(TimeStampedModel):
    """Relación Asesor <-> Agencia e historial en una sola tabla.

    La membresía vigente es la que tiene `fecha_fin` en NULL; una restricción
    garantiza que exista a lo sumo una vigente por asesor.
    """

    asesor = models.ForeignKey(Asesor, on_delete=models.CASCADE, related_name="membresias")
    agencia = models.ForeignKey(Agencia, on_delete=models.PROTECT, related_name="membresias")
    fecha_inicio = models.DateField(default=timezone.localdate)
    fecha_fin = models.DateField(null=True, blank=True)
    cargo = models.CharField(max_length=80, blank=True, help_text="Asesor, broker, gerente…")
    es_broker = models.BooleanField(
        default=False, help_text="Puede gestionar toda la cartera de la agencia"
    )
    notas = models.TextField(blank=True)

    class Meta:
        verbose_name = "membresía asesor-agencia"
        verbose_name_plural = "historial asesor-agencia"
        ordering = ["-fecha_inicio"]
        constraints = [
            models.UniqueConstraint(
                fields=["asesor"],
                condition=models.Q(fecha_fin__isnull=True),
                name="uq_una_membresia_vigente_por_asesor",
            ),
            models.CheckConstraint(
                condition=models.Q(fecha_fin__isnull=True)
                | models.Q(fecha_fin__gte=models.F("fecha_inicio")),
                name="ck_membresia_fechas_coherentes",
            ),
        ]
        indexes = [models.Index(fields=["agencia", "fecha_fin"])]

    def __str__(self):
        fin = self.fecha_fin or "vigente"
        return f"{self.asesor_id} @ {self.agencia} ({self.fecha_inicio} → {fin})"

    @property
    def vigente(self) -> bool:
        return self.fecha_fin is None


# ---------------------------------------------------------------------------
# Propietarios
# ---------------------------------------------------------------------------
class TipoPersona(models.TextChoices):
    NATURAL = "natural", "Persona natural"
    JURIDICA = "juridica", "Persona jurídica"


class Propietario(TimeStampedModel):
    """Dueño del inmueble. Dato sensible: solo visible para quien lo captó.

    Sus datos de contacto no se exponen en el listado público del MLS.
    """

    tipo_persona = models.CharField(
        max_length=10, choices=TipoPersona.choices, default=TipoPersona.NATURAL
    )
    nombre = models.CharField(max_length=100, help_text="Nombre o razón social")
    apellido = models.CharField(max_length=100, blank=True)
    documento = models.CharField(
        "CI / NIT / RUC", max_length=30, blank=True
    )
    pais = models.ForeignKey(
        Pais, on_delete=models.PROTECT, related_name="propietarios", null=True, blank=True
    )
    celular = models.CharField(max_length=25, blank=True)
    celular_alterno = models.CharField(max_length=25, blank=True)
    correo = models.EmailField(blank=True)
    direccion = models.CharField(max_length=255, blank=True)
    notas = models.TextField(blank=True)
    # Quién cargó al propietario: define quién puede verlo.
    registrado_por = models.ForeignKey(
        Asesor, on_delete=models.PROTECT, related_name="propietarios_registrados",
        null=True, blank=True,
    )
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "propietario"
        verbose_name_plural = "propietarios"
        ordering = ["nombre", "apellido"]
        constraints = [
            models.UniqueConstraint(
                fields=["pais", "documento"],
                condition=~models.Q(documento=""),
                name="uq_propietario_documento_por_pais",
            )
        ]
        indexes = [models.Index(fields=["nombre", "apellido"])]

    def __str__(self):
        return self.nombre_completo

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombre} {self.apellido}".strip()


# ---------------------------------------------------------------------------
# Inmuebles
# ---------------------------------------------------------------------------
class TipoTransaccion(models.TextChoices):
    VENTA = "venta", "Venta"
    ALQUILER = "alquiler", "Alquiler"
    ANTICRETICO = "anticretico", "Anticrético"
    VENTA_ALQUILER = "venta_alquiler", "Venta o alquiler"
    PREVENTA = "preventa", "Preventa"
    TRASPASO = "traspaso", "Traspaso"


class EstadoConservacion(models.IntegerChoices):
    A_ESTRENAR = 5, "A estrenar"
    EXCELENTE = 4, "Excelente"
    BUENO = 3, "Bueno"
    REGULAR = 2, "Regular"
    A_REFACCIONAR = 1, "A refaccionar"


class UsoSuelo(models.TextChoices):
    RESIDENCIAL = "residencial", "Residencial"
    COMERCIAL = "comercial", "Comercial"
    MIXTO = "mixto", "Mixto"
    INDUSTRIAL = "industrial", "Industrial"
    AGRICOLA = "agricola", "Agrícola"
    TURISTICO = "turistico", "Turístico"
    OTRO = "otro", "Otro"


class EstadoPublicacion(models.TextChoices):
    BORRADOR = "borrador", "Borrador"
    EN_REVISION = "en_revision", "En revisión"
    PUBLICADO = "publicado", "Publicado"
    RESERVADO = "reservado", "Reservado"
    CERRADO = "cerrado", "Vendido / alquilado"
    PAUSADO = "pausado", "Pausado"


def generar_codigo_inmueble() -> str:
    return f"MLS-P-{uuid.uuid4().hex[:8].upper()}"


class InmuebleQuerySet(models.QuerySet):
    def activos(self):
        return self.filter(activo=True)

    def publicados(self):
        return self.filter(activo=True, estado_publicacion=EstadoPublicacion.PUBLICADO)

    def visibles_para(self, usuario):
        """Inmuebles que el usuario puede *editar*. Ver, ve todo el MLS."""
        if usuario is None or usuario.is_anonymous:
            return self.none()
        if usuario.is_superuser or usuario.has_perm("core.gestionar_todo_inmueble"):
            return self
        asesor = getattr(usuario, "asesor", None)
        # Mismo criterio que `Inmueble.puede_editar`: un asesor dado de baja no
        # edita nada, así que tampoco debe verlo listado como suyo.
        if asesor is None or not asesor.activo:
            return self.none()
        agencia = asesor.agencia_actual if asesor.es_broker else None
        if agencia is not None:
            return self.filter(
                models.Q(captador=asesor) | models.Q(agencia_captadora=agencia)
            )
        return self.filter(captador=asesor)

    def por_aprobar(self, usuario):
        """Cola de revisión: lo que la agencia del broker mandó a publicar."""
        if usuario is None or usuario.is_anonymous:
            return self.none()
        pendientes = self.filter(
            activo=True, estado_publicacion=EstadoPublicacion.EN_REVISION
        )
        if usuario.is_superuser or usuario.has_perm("core.gestionar_todo_inmueble"):
            return pendientes
        asesor = getattr(usuario, "asesor", None)
        if asesor is None or not asesor.activo or not asesor.es_broker:
            return self.none()
        agencia = asesor.agencia_actual
        return pendientes.filter(agencia_captadora=agencia) if agencia else self.none()


class Inmueble(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    codigo = models.CharField(
        max_length=20, unique=True, default=generar_codigo_inmueble, editable=False,
        help_text="Código corto para compartir con clientes",
    )
    titulo = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, blank=True)
    descripcion = models.TextField(blank=True)

    # --- Clasificación -----------------------------------------------------
    tipo_transaccion = models.CharField(max_length=20, choices=TipoTransaccion.choices)
    tipo_inmueble = models.ForeignKey(
        TipoInmueble, on_delete=models.PROTECT, related_name="inmuebles"
    )
    estado_publicacion = models.CharField(
        max_length=15, choices=EstadoPublicacion.choices, default=EstadoPublicacion.BORRADOR,
        db_index=True,
    )
    # Baja lógica: los inmuebles nunca se borran (histórico de mercado).
    activo = models.BooleanField(default=True, db_index=True)

    # --- Responsables ------------------------------------------------------
    captador = models.ForeignKey(
        Asesor, on_delete=models.PROTECT, related_name="inmuebles_captados"
    )
    # Agencia "congelada" al momento de la captación: si el asesor cambia de
    # agencia, la publicación conserva a quién pertenecía la captación.
    agencia_captadora = models.ForeignKey(
        Agencia, on_delete=models.PROTECT, related_name="inmuebles_captados",
        null=True, blank=True,
    )

    # --- Ubicación pública -------------------------------------------------
    pais = models.ForeignKey(Pais, on_delete=models.PROTECT, related_name="inmuebles")
    ciudad = models.ForeignKey(Ciudad, on_delete=models.PROTECT, related_name="inmuebles")
    zona = models.CharField(max_length=120, blank=True, help_text="PÚBLICO: barrio o zona")
    referencia_publica = models.CharField(
        max_length=200, blank=True,
        help_text="PÚBLICO: referencia difusa, ej. 'a 2 cuadras del 4to anillo'",
    )

    # --- Ubicación privada (solo asesores autorizados) ---------------------
    calle = models.CharField(
        max_length=200, blank=True, help_text="PRIVADO: dirección exacta"
    )
    numero_puerta = models.CharField(max_length=20, blank=True, help_text="PRIVADO")
    ubicacion = gis_models.PointField(
        "ubicación exacta", geography=True, srid=4326, null=True, blank=True,
        help_text="PRIVADO: punto exacto (lon, lat)",
    )
    mostrar_direccion_exacta = models.BooleanField(
        default=False, help_text="Si está activo, el público ve calle y punto exacto"
    )
    radio_privacidad_m = models.PositiveSmallIntegerField(
        default=300, help_text="Radio en metros para difuminar el punto público"
    )

    # --- Distribución ------------------------------------------------------
    cuartos = models.PositiveSmallIntegerField(null=True, blank=True)
    banos = models.PositiveSmallIntegerField("baños", null=True, blank=True)
    medios_banos = models.PositiveSmallIntegerField("medios baños", default=0)
    cocina = models.TextField(blank=True, help_text="Descripción de la cocina")
    estacionamientos = models.PositiveSmallIntegerField(default=0)
    niveles_construidos = models.PositiveSmallIntegerField(null=True, blank=True)
    tipo_piso = models.CharField(max_length=120, blank=True)
    piscina = models.BooleanField(default=False)
    estado_conservacion = models.PositiveSmallIntegerField(
        choices=EstadoConservacion.choices, null=True, blank=True
    )
    uso_suelo = models.CharField(max_length=20, choices=UsoSuelo.choices, blank=True)

    # --- Superficies (m²) ---------------------------------------------------
    metros_frente = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    metros_fondo = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    area_construida = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    area_terreno = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    m2_cocina = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    m2_almacen = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    m2_jardin = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # --- Precios ------------------------------------------------------------
    precio_usd = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    precio_secundario = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True,
        help_text="Precio en la moneda local del país",
    )
    moneda_secundaria = models.CharField(
        max_length=3, blank=True, help_text="Se completa desde el país si se deja vacío"
    )
    precio_secundario_fijo = models.BooleanField(
        default=False,
        help_text="El precio local es fijo y no se recalcula desde el USD",
    )

    # --- Compartición MLS ---------------------------------------------------
    comparte_comision = models.BooleanField(
        default=True, help_text="¿Se comparte con otros asesores del MLS?"
    )
    comision_compartida_pct = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="% del total que recibe el asesor colocador",
    )
    publicado_en = models.DateTimeField(null=True, blank=True)

    # --- Circuito de aprobación ---------------------------------------------
    enviado_a_revision_en = models.DateTimeField(null=True, blank=True)
    revisado_por = models.ForeignKey(
        Asesor, on_delete=models.PROTECT, related_name="publicaciones_revisadas",
        null=True, blank=True,
        help_text="Broker o administrador que aprobó la publicación",
    )
    revisado_en = models.DateTimeField(null=True, blank=True)
    motivo_rechazo = models.TextField(
        blank=True, help_text="Lo que el broker le devuelve al asesor"
    )

    objects = InmuebleQuerySet.as_manager()

    class Meta:
        verbose_name = "inmueble"
        verbose_name_plural = "inmuebles"
        ordering = ["-creado_en"]
        indexes = [
            models.Index(fields=["estado_publicacion", "tipo_transaccion"]),
            models.Index(fields=["ciudad", "tipo_inmueble"]),
            models.Index(fields=["precio_usd"]),
            models.Index(fields=["activo", "estado_publicacion"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(precio_usd__isnull=True) | models.Q(precio_usd__gte=0),
                name="ck_inmueble_precio_no_negativo",
            ),
            # Nada llega al portal sin que conste quién lo aprobó.
            models.CheckConstraint(
                condition=~models.Q(estado_publicacion=EstadoPublicacion.PUBLICADO)
                | models.Q(revisado_por__isnull=False),
                name="ck_publicado_requiere_revisor",
            ),
        ]
        permissions = [
            ("gestionar_todo_inmueble", "Puede editar cualquier inmueble del MLS"),
            ("ver_direccion_exacta", "Puede ver la dirección exacta y el propietario"),
        ]

    def __str__(self):
        return f"[{self.codigo}] {self.titulo}"

    # -- seguimiento de cambios de precio -----------------------------------
    @classmethod
    def from_db(cls, db, field_names, values):
        instancia = super().from_db(db, field_names, values)
        instancia._precio_previo = (
            instancia.__dict__.get("precio_usd"),
            instancia.__dict__.get("precio_secundario"),
        )
        instancia._titulo_previo = instancia.__dict__.get("titulo")
        return instancia

    def refresh_from_db(self, *args, **kwargs):
        """Recargar también reinicia las referencias de cambio.

        `refresh_from_db()` copia los campos de una instancia nueva pero no sus
        atributos auxiliares: sin esto, `_precio_previo` quedaba con el valor de
        la primera lectura y el seguimiento de cambios se desfasaba.
        """
        super().refresh_from_db(*args, **kwargs)
        self._precio_previo = (self.precio_usd, self.precio_secundario)
        self._titulo_previo = self.titulo

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.titulo)[:200]
        if not self.moneda_secundaria and self.pais_id:
            self.moneda_secundaria = self.pais.moneda_secundaria
        if not self.agencia_captadora_id and self.captador_id:
            self.agencia_captadora = self.captador.agencia_actual
        if self.estado_publicacion == EstadoPublicacion.PUBLICADO and not self.publicado_en:
            self.publicado_en = timezone.now()

        es_nuevo = self._state.adding
        previo = getattr(self, "_precio_previo", (None, None))

        # Un aviso publicado vuelve a la cola si le tocan el precio o el título:
        # son los dos datos con los que el comprador decide. Cambiar la
        # descripción o sumar fotos no lo baja del portal.
        # Solo se evalúa en guardados completos; los `update_fields` puntuales
        # (sincronización desde Operacion, baja lógica) no deben disparar esto.
        if (
            not es_nuevo
            and kwargs.get("update_fields") is None
            and self.estado_publicacion == EstadoPublicacion.PUBLICADO
            and (
                previo[0] != self.precio_usd
                or getattr(self, "_titulo_previo", self.titulo) != self.titulo
            )
        ):
            self.estado_publicacion = EstadoPublicacion.EN_REVISION
            self.enviado_a_revision_en = timezone.now()
            self.revisado_por = None
            self.revisado_en = None

        super().save(*args, **kwargs)
        self._titulo_previo = self.titulo

        actual = (self.precio_usd, self.precio_secundario)
        if es_nuevo or previo != actual:
            HistorialPrecio.objects.create(
                inmueble=self,
                precio_usd=self.precio_usd,
                precio_secundario=self.precio_secundario,
                moneda_secundaria=self.moneda_secundaria,
                motivo=(
                    HistorialPrecio.Motivo.PUBLICACION_INICIAL
                    if es_nuevo
                    else HistorialPrecio.Motivo.AJUSTE
                ),
            )
            self._precio_previo = actual

    def delete(self, *args, hard=False, **kwargs):
        """Baja lógica. El histórico de mercado no se borra.

        Usar `delete(hard=True)` solo en scripts de mantenimiento.
        """
        if hard:
            return super().delete(*args, **kwargs)
        self.activo = False
        self.estado_publicacion = EstadoPublicacion.PAUSADO
        self.save(update_fields=["activo", "estado_publicacion", "actualizado_en"])
        return (0, {})

    def clean(self):
        if self.ciudad_id and self.pais_id and self.ciudad.pais_id != self.pais_id:
            raise ValidationError({"ciudad": "La ciudad no pertenece al país seleccionado."})

    # -- coordenadas --------------------------------------------------------
    @property
    def latitud(self):
        return self.ubicacion.y if self.ubicacion else None

    @property
    def longitud(self):
        return self.ubicacion.x if self.ubicacion else None

    def set_coordenadas(self, latitud, longitud):
        self.ubicacion = Point(float(longitud), float(latitud), srid=4326)

    def ubicacion_publica(self):
        """Punto desplazado dentro del radio de privacidad.

        Determinista por inmueble: el desplazamiento no cambia entre visitas,
        así el pin no "salta" en el mapa.
        """
        if not self.ubicacion:
            return None
        if self.mostrar_direccion_exacta:
            return self.ubicacion
        rnd = random.Random(str(self.pk))
        angulo = rnd.uniform(0, 2 * math.pi)
        # sqrt() para distribuir uniformemente en el área, no concentrar al centro.
        distancia = self.radio_privacidad_m * math.sqrt(rnd.uniform(0.35, 1.0))
        lat, lon = self.ubicacion.y, self.ubicacion.x
        d_lat = (distancia * math.cos(angulo)) / 111_320
        d_lon = (distancia * math.sin(angulo)) / (
            111_320 * max(math.cos(math.radians(lat)), 0.01)
        )
        return Point(lon + d_lon, lat + d_lat, srid=4326)

    # -- dirección ----------------------------------------------------------
    @property
    def direccion_publica(self) -> str:
        partes = [p for p in [self.zona, self.ciudad.nombre, self.pais.nombre] if p]
        return ", ".join(partes)

    @property
    def direccion_privada(self) -> str:
        partes = [p for p in [self.calle, self.numero_puerta, self.zona] if p]
        return " ".join(partes)

    def direccion_para(self, usuario) -> str:
        if self.mostrar_direccion_exacta or self.puede_ver_datos_sensibles(usuario):
            return self.direccion_privada or self.direccion_publica
        return self.direccion_publica

    # -- permisos -----------------------------------------------------------
    def _asesor_de(self, usuario):
        if usuario is None or usuario.is_anonymous:
            return None
        return getattr(usuario, "asesor", None)

    def puede_editar(self, usuario) -> bool:
        """Un asesor solo edita sus propias captaciones."""
        if usuario is None or usuario.is_anonymous:
            return False
        if usuario.is_superuser or usuario.has_perm("core.gestionar_todo_inmueble"):
            return True
        asesor = self._asesor_de(usuario)
        if asesor is None or not asesor.activo:
            return False
        if self.captador_id == asesor.pk:
            return True
        # El broker gestiona la cartera de su propia agencia.
        return bool(
            asesor.es_broker
            and self.agencia_captadora_id
            and asesor.agencia_actual
            and asesor.agencia_actual.pk == self.agencia_captadora_id
        )

    # -- circuito de aprobación ---------------------------------------------
    def puede_enviar_a_revision(self, usuario) -> bool:
        """Mandar a publicar exige pertenecer a una agencia que lo avale."""
        if self.estado_publicacion not in {
            EstadoPublicacion.BORRADOR,
            EstadoPublicacion.EN_REVISION,
        }:
            return False
        if not self.puede_editar(usuario):
            return False
        return self.captador.agencia_actual is not None

    def puede_aprobar_publicacion(self, usuario) -> bool:
        """Solo el broker de la agencia captadora, o un administrador del MLS.

        El broker puede aprobar sus propias captaciones: es la autoridad de su
        agencia y queda registrado en `revisado_por`, así que la
        responsabilidad sigue siendo rastreable.
        """
        if usuario is None or usuario.is_anonymous:
            return False
        if usuario.is_superuser or usuario.has_perm("core.gestionar_todo_inmueble"):
            return True
        asesor = self._asesor_de(usuario)
        if asesor is None or not asesor.activo or not asesor.es_broker:
            return False
        agencia = asesor.agencia_actual
        return bool(agencia and self.agencia_captadora_id == agencia.pk)

    def enviar_a_revision(self):
        self.estado_publicacion = EstadoPublicacion.EN_REVISION
        self.enviado_a_revision_en = timezone.now()
        self.motivo_rechazo = ""
        self.save(
            update_fields=[
                "estado_publicacion", "enviado_a_revision_en", "motivo_rechazo",
                "actualizado_en",
            ]
        )

    def aprobar_publicacion(self, revisor):
        self.estado_publicacion = EstadoPublicacion.PUBLICADO
        self.revisado_por = revisor
        self.revisado_en = timezone.now()
        self.motivo_rechazo = ""
        if not self.publicado_en:
            self.publicado_en = timezone.now()
        self.save(
            update_fields=[
                "estado_publicacion", "revisado_por", "revisado_en",
                "motivo_rechazo", "publicado_en", "actualizado_en",
            ]
        )

    def rechazar_publicacion(self, revisor, motivo):
        self.estado_publicacion = EstadoPublicacion.BORRADOR
        self.revisado_por = revisor
        self.revisado_en = timezone.now()
        self.motivo_rechazo = motivo
        self.save(
            update_fields=[
                "estado_publicacion", "revisado_por", "revisado_en",
                "motivo_rechazo", "actualizado_en",
            ]
        )

    def puede_ver_datos_sensibles(self, usuario) -> bool:
        """Dirección exacta y datos del propietario."""
        if usuario is not None and not usuario.is_anonymous:
            if usuario.has_perm("core.ver_direccion_exacta"):
                return True
        return self.puede_editar(usuario)

    # -- relaciones ---------------------------------------------------------
    @property
    def captacion_vigente(self):
        return self.captaciones.filter(estado=Captacion.Estado.VIGENTE).first()

    @property
    def propietarios(self):
        captacion = self.captacion_vigente
        return captacion.propietarios.all() if captacion else Propietario.objects.none()

    @property
    def portada(self):
        return self.imagenes.first()


class HistorialPrecio(models.Model):
    """Cada cambio de precio queda registrado. Se escribe solo desde Inmueble.save()."""

    class Motivo(models.TextChoices):
        PUBLICACION_INICIAL = "inicial", "Publicación inicial"
        AJUSTE = "ajuste", "Ajuste de precio"
        REVALORIZACION = "revalorizacion", "Revalorización"
        CIERRE = "cierre", "Precio de cierre"

    inmueble = models.ForeignKey(
        Inmueble, on_delete=models.CASCADE, related_name="historial_precios"
    )
    precio_usd = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    precio_secundario = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True
    )
    moneda_secundaria = models.CharField(max_length=3, blank=True)
    motivo = models.CharField(max_length=20, choices=Motivo.choices, default=Motivo.AJUSTE)
    registrado_por = models.ForeignKey(
        Asesor, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="cambios_de_precio",
    )
    notas = models.CharField(max_length=200, blank=True)
    registrado_en = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "historial de precio"
        verbose_name_plural = "historial de precios"
        ordering = ["-registrado_en"]
        indexes = [models.Index(fields=["inmueble", "-registrado_en"])]

    def __str__(self):
        return f"{self.inmueble_id}: {self.precio_usd} USD ({self.registrado_en:%Y-%m-%d})"


def ruta_imagen_inmueble(instancia, nombre_original):
    """Ruta dentro del Storage Zone: inmuebles/<uuid>/<aleatorio>.<ext>.

    El nombre lleva uuid para que dos fotos con el mismo nombre de archivo no
    se pisen y para no filtrar el nombre original que puso el asesor.
    """
    extension = pathlib.Path(nombre_original).suffix.lower() or ".jpg"
    return f"inmuebles/{instancia.inmueble_id}/{uuid.uuid4().hex}{extension}"


class ImagenInmueble(models.Model):
    """Una foto del inmueble.

    Puede venir de dos lados: subida al CDN (`archivo`, que es el camino
    normal) o pegada como URL de un servicio externo (`url`). `src` resuelve
    cuál usar, y es lo que deben mirar las plantillas.
    """

    inmueble = models.ForeignKey(Inmueble, on_delete=models.CASCADE, related_name="imagenes")
    archivo = models.ImageField(
        "imagen",
        upload_to=ruta_imagen_inmueble,
        storage=almacenamiento_imagenes,
        blank=True,
        null=True,
    )
    url = models.URLField(
        max_length=500, blank=True,
        help_text="Solo si la foto ya está alojada en otro lado",
    )
    descripcion = models.CharField(max_length=150, blank=True)
    orden = models.PositiveSmallIntegerField(default=0)
    es_portada = models.BooleanField(default=False)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "imagen de inmueble"
        verbose_name_plural = "imágenes de inmueble"
        ordering = ["-es_portada", "orden", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["inmueble", "url"],
                condition=~models.Q(url=""),
                name="uq_imagen_inmueble_url",
            ),
            models.UniqueConstraint(
                fields=["inmueble"],
                condition=models.Q(es_portada=True),
                name="uq_una_portada_por_inmueble",
            ),
            # Una foto es un archivo subido o una URL externa, pero algo tiene
            # que ser: una fila sin ninguna de las dos no es nada.
            models.CheckConstraint(
                condition=~models.Q(archivo="") & models.Q(archivo__isnull=False)
                | ~models.Q(url=""),
                name="ck_imagen_tiene_origen",
                violation_error_message="Subí una imagen o pegá una URL.",
            ),
        ]

    def __str__(self):
        return f"{self.inmueble_id} · {self.src}"

    @property
    def src(self) -> str:
        """La dirección pública de la foto. Es lo que va en el `img src`."""
        if self.archivo:
            return self.archivo.url
        return self.url

    @property
    def en_cdn(self) -> bool:
        return bool(self.archivo)


@receiver(models.signals.post_delete, sender=ImagenInmueble)
def _borrar_archivo_de_imagen(sender, instance, **kwargs):
    """Borrar la fila borra el archivo del CDN.

    Django no lo hace solo desde la 1.3. Sin esto, cada foto que un asesor
    saca de la galería queda ocupando espacio en Bunny para siempre.
    """
    if instance.archivo:
        instance.archivo.delete(save=False)


# ---------------------------------------------------------------------------
# Captación (contrato con el propietario)
# ---------------------------------------------------------------------------
class Captacion(TimeStampedModel):
    """Contrato entre el propietario y el asesor/agencia que capta el inmueble.

    Define el tipo de autorización, su vigencia y la comisión pactada.
    Solo puede haber una captación VIGENTE por inmueble.
    """

    class Tipo(models.TextChoices):
        EXCLUSIVA = "exclusiva", "Exclusiva"
        CO_EXCLUSIVA = "co_exclusiva", "Co-exclusiva"
        ABIERTA = "abierta", "Abierta / simple"
        OPCION = "opcion", "Opción de compra"
        VERBAL = "verbal", "Autorización verbal"

    class Estado(models.TextChoices):
        VIGENTE = "vigente", "Vigente"
        VENCIDA = "vencida", "Vencida"
        RESCINDIDA = "rescindida", "Rescindida"
        CUMPLIDA = "cumplida", "Cumplida (se cerró la operación)"

    inmueble = models.ForeignKey(
        Inmueble, on_delete=models.PROTECT, related_name="captaciones"
    )
    propietarios = models.ManyToManyField(
        Propietario, related_name="captaciones",
        help_text="Firmantes; puede haber copropietarios",
    )
    asesor = models.ForeignKey(
        Asesor, on_delete=models.PROTECT, related_name="captaciones"
    )
    agencia = models.ForeignKey(
        Agencia, on_delete=models.PROTECT, related_name="captaciones",
        null=True, blank=True, help_text="Se completa desde el asesor si se deja vacío",
    )

    tipo = models.CharField(max_length=15, choices=Tipo.choices, default=Tipo.ABIERTA)
    estado = models.CharField(
        max_length=12, choices=Estado.choices, default=Estado.VIGENTE, db_index=True
    )
    fecha_inicio = models.DateField(default=timezone.localdate)
    fecha_fin = models.DateField(
        null=True, blank=True, help_text="Vencimiento de la autorización"
    )

    comision_pactada_pct = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="% sobre el precio de cierre",
    )
    comision_minima_usd = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    precio_autorizado_usd = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        help_text="Precio que el propietario autorizó a publicar",
    )
    precio_minimo_usd = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        help_text="PRIVADO: piso de negociación aceptado por el propietario",
    )
    documento_url = models.URLField(
        max_length=500, blank=True, help_text="Contrato firmado escaneado"
    )
    notas = models.TextField(blank=True)

    class Meta:
        verbose_name = "captación"
        verbose_name_plural = "captaciones"
        ordering = ["-fecha_inicio"]
        constraints = [
            models.UniqueConstraint(
                fields=["inmueble"],
                condition=models.Q(estado="vigente"),
                name="uq_una_captacion_vigente_por_inmueble",
            ),
            models.CheckConstraint(
                condition=models.Q(fecha_fin__isnull=True)
                | models.Q(fecha_fin__gte=models.F("fecha_inicio")),
                name="ck_captacion_fechas_coherentes",
            ),
        ]
        indexes = [models.Index(fields=["asesor", "estado"])]

    def __str__(self):
        return f"{self.get_tipo_display()} · {self.inmueble_id} ({self.get_estado_display()})"

    def save(self, *args, **kwargs):
        if not self.agencia_id and self.asesor_id:
            self.agencia = self.asesor.agencia_actual
        super().save(*args, **kwargs)

    @property
    def es_exclusiva(self) -> bool:
        return self.tipo in {self.Tipo.EXCLUSIVA, self.Tipo.CO_EXCLUSIVA}

    @property
    def vencida(self) -> bool:
        return bool(self.fecha_fin and self.fecha_fin < timezone.localdate())


# ---------------------------------------------------------------------------
# Operaciones (cierres) y comisiones
# ---------------------------------------------------------------------------
class Operacion(TimeStampedModel):
    """Cierre de negocio sobre un inmueble: venta, alquiler o anticrético."""

    class Estado(models.TextChoices):
        EN_PROCESO = "en_proceso", "En proceso"
        RESERVADA = "reservada", "Reservada / con anticipo"
        CERRADA = "cerrada", "Cerrada"
        CAIDA = "caida", "Caída"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    inmueble = models.ForeignKey(
        Inmueble, on_delete=models.PROTECT, related_name="operaciones"
    )
    captacion = models.ForeignKey(
        Captacion, on_delete=models.PROTECT, related_name="operaciones",
        null=True, blank=True,
    )
    tipo_transaccion = models.CharField(max_length=20, choices=TipoTransaccion.choices)
    estado = models.CharField(
        max_length=12, choices=Estado.choices, default=Estado.EN_PROCESO, db_index=True
    )

    # Contraparte. Sin modelo de leads por ahora: datos mínimos del comprador.
    comprador_nombre = models.CharField("nombre del comprador/inquilino", max_length=150)
    comprador_documento = models.CharField(max_length=30, blank=True)
    comprador_celular = models.CharField(max_length=25, blank=True)
    comprador_correo = models.EmailField(blank=True)

    fecha_reserva = models.DateField(null=True, blank=True)
    fecha_cierre = models.DateField(null=True, blank=True)

    precio_cierre_usd = models.DecimalField(max_digits=14, decimal_places=2)
    precio_cierre_secundario = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True
    )
    moneda_secundaria = models.CharField(max_length=3, blank=True)

    comision_total_pct = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    comision_total_usd = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Se calcula desde el % si se deja vacío",
    )
    notas = models.TextField(blank=True)

    class Meta:
        verbose_name = "operación"
        verbose_name_plural = "operaciones"
        ordering = ["-fecha_cierre", "-creado_en"]
        indexes = [
            models.Index(fields=["estado", "fecha_cierre"]),
            models.Index(fields=["inmueble", "estado"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(precio_cierre_usd__gte=0),
                name="ck_operacion_precio_no_negativo",
            ),
            # Una operación cerrada necesita fecha de cierre.
            models.CheckConstraint(
                condition=~models.Q(estado="cerrada") | models.Q(fecha_cierre__isnull=False),
                name="ck_operacion_cerrada_con_fecha",
            ),
        ]

    def __str__(self):
        return f"{self.get_tipo_transaccion_display()} {self.inmueble_id} · {self.get_estado_display()}"

    def save(self, *args, **kwargs):
        if not self.moneda_secundaria and self.inmueble_id:
            self.moneda_secundaria = self.inmueble.moneda_secundaria
        if self.comision_total_usd is None and self.comision_total_pct is not None:
            self.comision_total_usd = (
                self.precio_cierre_usd * self.comision_total_pct / 100
            ).quantize(self.precio_cierre_usd)
        super().save(*args, **kwargs)
        self._sincronizar_inmueble()

    def _sincronizar_inmueble(self):
        """El estado del inmueble sigue al de su operación."""
        inmueble = self.inmueble
        nuevo = {
            self.Estado.RESERVADA: EstadoPublicacion.RESERVADO,
            self.Estado.CERRADA: EstadoPublicacion.CERRADO,
        }.get(self.estado)
        if nuevo and inmueble.estado_publicacion != nuevo:
            inmueble.estado_publicacion = nuevo
            inmueble.save(update_fields=["estado_publicacion", "actualizado_en"])
        if self.estado == self.Estado.CERRADA and self.captacion_id:
            Captacion.objects.filter(pk=self.captacion_id).update(
                estado=Captacion.Estado.CUMPLIDA
            )

    # -- reparto ------------------------------------------------------------
    @property
    def porcentaje_repartido(self):
        total = self.participaciones.aggregate(t=models.Sum("porcentaje"))["t"]
        return total or 0

    @property
    def comision_repartida_usd(self):
        total = self.participaciones.aggregate(t=models.Sum("monto_usd"))["t"]
        return total or 0

    def validar_reparto(self):
        """El reparto no puede superar el 100% de la comisión."""
        if self.porcentaje_repartido > 100:
            raise ValidationError(
                f"El reparto suma {self.porcentaje_repartido}%, no puede superar 100%."
            )


class ComisionParticipacion(TimeStampedModel):
    """Cuánto le toca a cada participante de la comisión de una operación."""

    class Rol(models.TextChoices):
        CAPTADOR = "captador", "Asesor captador"
        COLOCADOR = "colocador", "Asesor colocador"
        REFERIDOR = "referidor", "Referidor"
        AGENCIA_CAPTADORA = "agencia_captadora", "Agencia captadora"
        AGENCIA_COLOCADORA = "agencia_colocadora", "Agencia colocadora"
        MLS = "mls", "MLS"

    operacion = models.ForeignKey(
        Operacion, on_delete=models.CASCADE, related_name="participaciones"
    )
    rol = models.CharField(max_length=20, choices=Rol.choices)
    asesor = models.ForeignKey(
        Asesor, on_delete=models.PROTECT, related_name="comisiones",
        null=True, blank=True,
    )
    agencia = models.ForeignKey(
        Agencia, on_delete=models.PROTECT, related_name="comisiones",
        null=True, blank=True,
    )
    porcentaje = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="% sobre la comisión total de la operación",
    )
    monto_usd = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Se calcula desde el % si se deja vacío",
    )
    pagada = models.BooleanField(default=False, db_index=True)
    fecha_pago = models.DateField(null=True, blank=True)
    notas = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "participación en comisión"
        verbose_name_plural = "participaciones en comisiones"
        ordering = ["rol"]
        constraints = [
            models.UniqueConstraint(
                fields=["operacion", "rol", "asesor"],
                name="uq_participacion_por_rol_y_asesor",
            ),
            models.CheckConstraint(
                condition=models.Q(asesor__isnull=False) | models.Q(agencia__isnull=False),
                name="ck_participacion_tiene_beneficiario",
            ),
        ]
        indexes = [models.Index(fields=["pagada", "fecha_pago"])]

    def __str__(self):
        quien = self.asesor or self.agencia
        return f"{self.get_rol_display()} · {quien} · {self.porcentaje}%"

    def save(self, *args, **kwargs):
        if not self.agencia_id and self.asesor_id:
            self.agencia = self.asesor.agencia_actual
        if self.monto_usd is None and self.operacion.comision_total_usd is not None:
            self.monto_usd = (
                self.operacion.comision_total_usd * self.porcentaje / 100
            ).quantize(self.operacion.comision_total_usd)
        super().save(*args, **kwargs)

    def clean(self):
        if self.asesor_id is None and self.agencia_id is None:
            raise ValidationError("La participación debe tener un asesor o una agencia.")
