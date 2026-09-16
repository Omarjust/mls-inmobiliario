from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Min, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import (
    CreateView,
    FormView,
    ListView,
    TemplateView,
    UpdateView,
    View,
)

from .forms import (
    ImagenInmuebleFormSet,
    InmuebleForm,
    LoginForm,
    RechazoForm,
    RegistroAsesorForm,
)
from .models import (
    Agencia,
    Asesor,
    Captacion,
    Ciudad,
    ComisionParticipacion,
    EstadoPublicacion,
    Inmueble,
    TipoInmueble,
    TipoTransaccion,
)

# Rangos de precio ofrecidos en el buscador del hero.
RANGOS_PRECIO = [
    ("", "Cualquier precio"),
    ("0-50000", "Hasta $50.000"),
    ("50000-100000", "$50.000 – $100.000"),
    ("100000-200000", "$100.000 – $200.000"),
    ("200000-400000", "$200.000 – $400.000"),
    ("400000-", "Más de $400.000"),
]


def q_publicado():
    """Filtro reutilizable para anotaciones: inmuebles activos y publicados."""
    return Q(inmuebles__activo=True, inmuebles__estado_publicacion=EstadoPublicacion.PUBLICADO)


class BuscadorMixin:
    """Opciones del formulario de búsqueda, compartidas por la landing y los resultados."""

    def opciones_buscador(self):
        return {
            "operaciones": TipoTransaccion.choices,
            "tipos": TipoInmueble.objects.filter(activo=True),
            "ciudades": Ciudad.objects.filter(activo=True).select_related("pais"),
            "rangos_precio": RANGOS_PRECIO,
        }


class LandingView(BuscadorMixin, TemplateView):
    template_name = "core/landing.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        publicados = Inmueble.objects.publicados()

        contexto.update(self.opciones_buscador())
        contexto["destacados"] = (
            publicados.select_related("tipo_inmueble", "ciudad", "agencia_captadora")
            .prefetch_related("imagenes")
            .order_by("-publicado_en")[:6]
        )
        contexto["metricas"] = {
            "inmuebles": publicados.count(),
            "asesores": Asesor.objects.filter(activo=True).count(),
            "agencias": Agencia.objects.filter(activa=True).count(),
            "ciudades": publicados.values("ciudad").distinct().count(),
        }
        contexto["tipos_destacados"] = (
            TipoInmueble.objects.filter(activo=True)
            .annotate(
                total=Count("inmuebles", filter=q_publicado())
            )
            .filter(total__gt=0)
            .order_by("-total")[:6]
        )
        contexto["ciudades_destacadas"] = (
            Ciudad.objects.annotate(
                total=Count("inmuebles", filter=q_publicado()),
                desde=Min("inmuebles__precio_usd", filter=q_publicado()),
            )
            .filter(total__gt=0)
            .select_related("pais")
            .order_by("-total")[:4]
        )
        return contexto


class BuscarView(BuscadorMixin, ListView):
    template_name = "core/buscar.html"
    context_object_name = "inmuebles"
    paginate_by = 12

    def get_queryset(self):
        qs = (
            Inmueble.objects.publicados()
            .select_related("tipo_inmueble", "ciudad", "pais", "agencia_captadora")
            .prefetch_related("imagenes")
        )
        params = self.request.GET

        if operacion := params.get("operacion"):
            qs = qs.filter(tipo_transaccion=operacion)
        if tipo := params.get("tipo"):
            qs = qs.filter(tipo_inmueble__slug=tipo)
        if ciudad := params.get("ciudad"):
            qs = qs.filter(ciudad_id=ciudad)
        if texto := params.get("q"):
            qs = qs.filter(titulo__icontains=texto)
        if precio := params.get("precio"):
            desde, _, hasta = precio.partition("-")
            if desde:
                qs = qs.filter(precio_usd__gte=desde)
            if hasta:
                qs = qs.filter(precio_usd__lte=hasta)

        orden = params.get("orden")
        ordenes = {
            "precio_asc": "precio_usd",
            "precio_desc": "-precio_usd",
            "recientes": "-publicado_en",
        }
        return qs.order_by(ordenes.get(orden, "-publicado_en"))

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto.update(self.opciones_buscador())
        contexto["filtros"] = self.request.GET
        # Querystring sin `page`, para que la paginación conserve los filtros.
        params = self.request.GET.copy()
        params.pop("page", None)
        contexto["querystring"] = params.urlencode()
        return contexto


# ===========================================================================
# Acceso
# ===========================================================================
def _dentro_del_limite(request, clave, limite=8, ventana=300):
    """Throttle por IP. Django no trae rate limiting y sin esto el login es
    fuerza bruta libre y el registro un generador de filas basura.

    Usa el cache por defecto (en memoria): sirve en desarrollo y en un solo
    proceso. En producción con varios workers hay que apuntarlo a Redis.
    """
    ip = request.META.get("REMOTE_ADDR", "desconocida")
    llave = f"throttle:{clave}:{ip}"
    intentos = cache.get(llave, 0)
    if intentos >= limite:
        return False
    cache.set(llave, intentos + 1, ventana)
    return True


class LoginAsesorView(LoginView):
    template_name = "core/auth/ingresar.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        if not _dentro_del_limite(request, "login"):
            messages.error(
                request, "Demasiados intentos. Esperá unos minutos y volvé a probar."
            )
            return redirect("core:login")
        return super().post(request, *args, **kwargs)


class RegistroView(FormView):
    template_name = "core/auth/sumarme.html"
    form_class = RegistroAsesorForm
    success_url = reverse_lazy("core:registro_enviado")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("core:panel")
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if not _dentro_del_limite(request, "registro", limite=5, ventana=900):
            messages.error(request, "Demasiadas solicitudes. Probá de nuevo más tarde.")
            return redirect("core:registro")
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        # Devuelve None si el correo ya existía: no lo decimos en pantalla.
        form.save()
        return super().form_valid(form)


class RegistroEnviadoView(TemplateView):
    template_name = "core/auth/enviado.html"


# ===========================================================================
# Panel del asesor
# ===========================================================================
class PanelMixin(LoginRequiredMixin):
    """Exige sesión iniciada y un asesor aprobado detrás de la cuenta."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        self.asesor = getattr(request.user, "asesor", None)
        if self.asesor is None or not self.asesor.esta_aprobado:
            return render(
                request,
                "core/panel/pendiente.html",
                {"asesor": self.asesor},
                status=403,
            )
        return super().dispatch(request, *args, **kwargs)


class PanelView(PanelMixin, TemplateView):
    template_name = "core/panel/index.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        usuario = self.request.user
        mios = (
            Inmueble.objects.visibles_para(usuario)
            .filter(activo=True)
            .select_related("tipo_inmueble", "ciudad", "captador")
            .prefetch_related("imagenes")
        )
        hoy = timezone.localdate()

        contexto["asesor"] = self.asesor
        contexto["inmuebles"] = mios.order_by("-actualizado_en")[:24]
        contexto["por_aprobar"] = (
            Inmueble.objects.por_aprobar(usuario)
            .select_related("captador", "tipo_inmueble", "ciudad")
            .order_by("enviado_a_revision_en")
        )
        contexto["metricas"] = {
            "publicados": mios.filter(
                estado_publicacion=EstadoPublicacion.PUBLICADO
            ).count(),
            "en_revision": mios.filter(
                estado_publicacion=EstadoPublicacion.EN_REVISION
            ).count(),
            "borradores": mios.filter(
                estado_publicacion=EstadoPublicacion.BORRADOR
            ).count(),
            "comisiones": ComisionParticipacion.objects.filter(
                asesor=self.asesor, pagada=False
            ).aggregate(total=Sum("monto_usd"))["total"]
            or 0,
        }
        contexto["captaciones_por_vencer"] = (
            Captacion.objects.filter(
                asesor=self.asesor,
                estado=Captacion.Estado.VIGENTE,
                fecha_fin__isnull=False,
                fecha_fin__lte=hoy + timedelta(days=30),
            )
            .select_related("inmueble")
            .order_by("fecha_fin")
        )
        contexto["puede_publicar"] = self.asesor.agencia_actual is not None
        return contexto


class AprobacionesView(PanelMixin, TemplateView):
    """Cola de revisión del broker."""

    template_name = "core/panel/aprobaciones.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["asesor"] = self.asesor
        contexto["pendientes"] = (
            Inmueble.objects.por_aprobar(self.request.user)
            .select_related("captador", "tipo_inmueble", "ciudad", "agencia_captadora")
            .prefetch_related("imagenes")
            .order_by("enviado_a_revision_en")
        )
        contexto["form_rechazo"] = RechazoForm()
        return contexto


class InmuebleFormMixin(PanelMixin):
    model = Inmueble
    form_class = InmuebleForm
    template_name = "core/panel/inmueble_form.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        if self.request.POST:
            contexto["imagenes"] = ImagenInmuebleFormSet(
                self.request.POST, self.request.FILES, instance=self.object
            )
        else:
            contexto["imagenes"] = ImagenInmuebleFormSet(instance=self.object)
        return contexto

    def form_valid(self, form):
        imagenes = ImagenInmuebleFormSet(
            self.request.POST, self.request.FILES, instance=form.instance
        )
        # Validar ANTES de tocar la base: si no, un formset inválido deja el
        # inmueble creado y devuelve el formulario con error, que es peor que
        # no haber guardado nada.
        if not imagenes.is_valid():
            return self.form_invalid(form)

        with transaction.atomic():
            if not form.instance.captador_id:
                form.instance.captador = self.asesor
            self.object = form.save()
            imagenes.instance = self.object
            imagenes.save()
        messages.success(self.request, "Inmueble guardado.")
        return redirect("core:inmueble_editar", pk=self.object.pk)


class InmuebleCreateView(InmuebleFormMixin, CreateView):
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        self.object = None
        return kwargs


class InmuebleUpdateView(InmuebleFormMixin, UpdateView):
    def get_queryset(self):
        # 404 y no 403: no confirmamos que el inmueble ajeno exista.
        return Inmueble.objects.visibles_para(self.request.user)


class AccionInmuebleView(PanelMixin, View):
    """Base de las transiciones de publicación. Siempre por POST."""

    permiso = None

    def get_inmueble(self):
        inmueble = get_object_or_404(
            Inmueble.objects.visibles_para(self.request.user), pk=self.kwargs["pk"]
        )
        return inmueble

    def post(self, request, *args, **kwargs):
        inmueble = self.get_inmueble()
        if not getattr(inmueble, self.permiso)(request.user):
            raise PermissionDenied("No podés hacer eso sobre este inmueble.")
        return self.ejecutar(inmueble)

    def ejecutar(self, inmueble):
        raise NotImplementedError


class InmuebleEnviarRevisionView(AccionInmuebleView):
    permiso = "puede_enviar_a_revision"

    def ejecutar(self, inmueble):
        inmueble.enviar_a_revision()
        messages.success(
            self.request,
            f"«{inmueble.titulo}» quedó en revisión. Te avisamos cuando "
            f"{inmueble.agencia_captadora} lo apruebe.",
        )
        return redirect("core:panel")


class InmuebleAprobarView(AccionInmuebleView):
    permiso = "puede_aprobar_publicacion"

    def get_inmueble(self):
        # El broker aprueba lo de su agencia, que ya está en `visibles_para`.
        return get_object_or_404(
            Inmueble.objects.por_aprobar(self.request.user), pk=self.kwargs["pk"]
        )

    def ejecutar(self, inmueble):
        inmueble.aprobar_publicacion(self.asesor)
        messages.success(self.request, f"«{inmueble.titulo}» ya está publicado.")
        return redirect("core:aprobaciones")


class InmuebleRechazarView(InmuebleAprobarView):
    def ejecutar(self, inmueble):
        form = RechazoForm(self.request.POST)
        if not form.is_valid():
            messages.error(self.request, "Escribí qué hay que corregir.")
            return redirect("core:aprobaciones")
        inmueble.rechazar_publicacion(self.asesor, form.cleaned_data["motivo"])
        messages.success(self.request, f"«{inmueble.titulo}» volvió al asesor.")
        return redirect("core:aprobaciones")


class InmuebleBajaView(AccionInmuebleView):
    permiso = "puede_editar"

    def ejecutar(self, inmueble):
        inmueble.delete()  # baja lógica: el histórico de mercado no se borra
        messages.success(self.request, f"«{inmueble.titulo}» se dio de baja.")
        return redirect("core:panel")
