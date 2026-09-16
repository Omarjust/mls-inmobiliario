from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    # --- público -----------------------------------------------------------
    path("", views.LandingView.as_view(), name="landing"),
    path("buscar/", views.BuscarView.as_view(), name="buscar"),

    # --- acceso ------------------------------------------------------------
    # Sin include("django.contrib.auth.urls"): arrastra las cinco vistas de
    # recuperación de contraseña, que todavía no hacemos.
    path("ingresar/", views.LoginAsesorView.as_view(), name="login"),
    path("salir/", LogoutView.as_view(), name="logout"),
    path("sumarme/", views.RegistroView.as_view(), name="registro"),
    path("sumarme/enviado/", views.RegistroEnviadoView.as_view(), name="registro_enviado"),

    # --- panel -------------------------------------------------------------
    path("panel/", views.PanelView.as_view(), name="panel"),
    path("panel/aprobaciones/", views.AprobacionesView.as_view(), name="aprobaciones"),
    path("panel/inmueble/nuevo/", views.InmuebleCreateView.as_view(), name="inmueble_nuevo"),
    path(
        "panel/inmueble/<uuid:pk>/editar/",
        views.InmuebleUpdateView.as_view(),
        name="inmueble_editar",
    ),
    path(
        "panel/inmueble/<uuid:pk>/enviar-revision/",
        views.InmuebleEnviarRevisionView.as_view(),
        name="inmueble_enviar_revision",
    ),
    path(
        "panel/inmueble/<uuid:pk>/aprobar/",
        views.InmuebleAprobarView.as_view(),
        name="inmueble_aprobar",
    ),
    path(
        "panel/inmueble/<uuid:pk>/rechazar/",
        views.InmuebleRechazarView.as_view(),
        name="inmueble_rechazar",
    ),
    path(
        "panel/inmueble/<uuid:pk>/baja/",
        views.InmuebleBajaView.as_view(),
        name="inmueble_baja",
    ),
]
