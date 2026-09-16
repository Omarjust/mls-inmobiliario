"""Formularios del panel y del circuito de acceso."""

from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    BaseUserCreationForm,
    UserChangeForm,
)
from django.contrib.auth.password_validation import validate_password
from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.db import transaction
from django.forms import inlineformset_factory

from .models import (
    Agencia,
    Asesor,
    AsesorAgencia,
    EstadoAsesor,
    ImagenInmueble,
    Inmueble,
    Pais,
    Usuario,
)


class LoginForm(AuthenticationForm):
    """Login por correo.

    A un usuario rechazado o suspendido se le deja el mensaje genérico de
    credenciales inválidas: decirle "tu cuenta está deshabilitada" confirmaría
    que ese correo existe en el sistema, y no le sirve de nada a quien sí es
    el dueño de la cuenta.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        campo = self.fields["username"]
        campo.label = "Correo electrónico"
        # AuthenticationForm.__init__ pisa el max_length con el del USERNAME_FIELD.
        campo.max_length = 254
        campo.widget = forms.EmailInput(
            attrs={
                "autofocus": True,
                "autocomplete": "email",
                "placeholder": "vos@agencia.com",
                "maxlength": 254,
            }
        )
        self.fields["password"].widget = forms.PasswordInput(
            attrs={"autocomplete": "current-password", "placeholder": "••••••••"}
        )
        self.fields["password"].label = "Contraseña"


class RegistroAsesorForm(forms.Form):
    """Solicitud de ingreso al MLS. Queda pendiente de aprobación."""

    nombre = forms.CharField(max_length=100)
    apellido = forms.CharField(max_length=100)
    ci = forms.CharField(max_length=30, label="CI / documento de identidad")
    pais = forms.ModelChoiceField(
        queryset=Pais.objects.filter(activo=True), label="País"
    )
    celular = forms.CharField(max_length=25, required=False)
    correo = forms.EmailField(max_length=254, label="Correo electrónico")
    agencia = forms.ModelChoiceField(
        queryset=Agencia.objects.filter(activa=True),
        required=False,
        label="Agencia",
        help_text="Si todavía no tenés agencia podés dejarlo vacío, pero vas a "
        "necesitar una para publicar.",
    )
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Repetir contraseña", widget=forms.PasswordInput)

    def clean_correo(self):
        return self.cleaned_data["correo"].strip().lower()

    def clean_ci(self):
        ci = self.cleaned_data["ci"].strip()
        pais = self.data.get("pais")
        if ci and pais and Asesor.objects.filter(ci=ci, pais_id=pais).exists():
            raise ValidationError(
                "Ya hay un asesor registrado con ese documento. Si sos vos, "
                "escribinos a contacto@housematchmls.com."
            )
        return ci

    def clean(self):
        datos = super().clean()
        p1, p2 = datos.get("password1"), datos.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Las contraseñas no coinciden.")
        elif p1:
            usuario = Usuario(
                email=datos.get("correo", ""),
                nombre=datos.get("nombre", ""),
                apellido=datos.get("apellido", ""),
            )
            try:
                validate_password(p1, usuario)
            except ValidationError as error:
                self.add_error("password1", error)
        return datos

    @transaction.atomic
    def save(self):
        """Crea la solicitud. Devuelve None si el correo ya estaba tomado.

        No se avisa en pantalla que el correo existe: sería un oráculo para
        enumerar las cuentas del MLS. La vista muestra siempre la misma
        pantalla de confirmación.
        """
        datos = self.cleaned_data
        correo = datos["correo"]
        if Usuario.objects.filter(email__iexact=correo).exists():
            return None

        usuario = Usuario.objects.create_user(
            email=correo,
            password=datos["password1"],
            nombre=datos["nombre"],
            apellido=datos["apellido"],
            is_active=True,   # puede entrar; el panel lo frena hasta la aprobación
            is_staff=False,   # los asesores no pisan el admin de Django
        )
        asesor = Asesor.objects.create(
            usuario=usuario,
            nombre=datos["nombre"],
            apellido=datos["apellido"],
            ci=datos["ci"],
            pais=datos["pais"],
            celular=datos.get("celular", ""),
            correo=correo,
            estado=EstadoAsesor.PENDIENTE,
            activo=False,
        )
        if datos.get("agencia"):
            AsesorAgencia.objects.create(asesor=asesor, agencia=datos["agencia"])
        return asesor


class InmuebleForm(forms.ModelForm):
    """Alta y edición de un inmueble desde el panel.

    La ubicación se carga como latitud/longitud sueltas y se arma el `Point`
    en `save()`: un mapa interactivo necesita JS externo y queda para después.
    """

    latitud = forms.DecimalField(
        max_digits=9, decimal_places=6, required=False,
        help_text="Privado: no se muestra exacto al público",
    )
    longitud = forms.DecimalField(max_digits=9, decimal_places=6, required=False)

    SECCIONES = [
        ("Lo esencial", ["titulo", "tipo_transaccion", "tipo_inmueble", "descripcion"]),
        ("Ubicación pública", ["pais", "ciudad", "zona", "referencia_publica"]),
        ("Ubicación privada", [
            "calle", "numero_puerta", "latitud", "longitud",
            "mostrar_direccion_exacta", "radio_privacidad_m",
        ]),
        ("Distribución", [
            "cuartos", "banos", "medios_banos", "estacionamientos",
            "niveles_construidos", "tipo_piso", "piscina", "estado_conservacion",
            "uso_suelo", "cocina",
        ]),
        ("Superficies (m²)", [
            "area_construida", "area_terreno", "metros_frente", "metros_fondo",
            "m2_cocina", "m2_almacen", "m2_jardin",
        ]),
        ("Precio", [
            "precio_usd", "precio_secundario", "moneda_secundaria",
            "precio_secundario_fijo",
        ]),
        ("Compartir en el MLS", ["comparte_comision", "comision_compartida_pct"]),
    ]

    class Meta:
        model = Inmueble
        fields = [
            "titulo", "descripcion", "tipo_transaccion", "tipo_inmueble",
            "pais", "ciudad", "zona", "referencia_publica",
            "calle", "numero_puerta", "mostrar_direccion_exacta", "radio_privacidad_m",
            "cuartos", "banos", "medios_banos", "cocina", "estacionamientos",
            "niveles_construidos", "tipo_piso", "piscina", "estado_conservacion",
            "uso_suelo",
            "metros_frente", "metros_fondo", "area_construida", "area_terreno",
            "m2_cocina", "m2_almacen", "m2_jardin",
            "precio_usd", "precio_secundario", "moneda_secundaria",
            "precio_secundario_fijo",
            "comparte_comision", "comision_compartida_pct",
        ]
        widgets = {
            "descripcion": forms.Textarea(attrs={"rows": 5}),
            "cocina": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.ubicacion:
            self.fields["latitud"].initial = self.instance.latitud
            self.fields["longitud"].initial = self.instance.longitud

    def clean(self):
        datos = super().clean()
        ciudad, pais = datos.get("ciudad"), datos.get("pais")
        if ciudad and pais and ciudad.pais_id != pais.pk:
            self.add_error("ciudad", "La ciudad no pertenece al país seleccionado.")
        lat, lon = datos.get("latitud"), datos.get("longitud")
        if (lat is None) != (lon is None):
            self.add_error("longitud", "Cargá latitud y longitud, o ninguna de las dos.")
        return datos

    def save(self, commit=True):
        inmueble = super().save(commit=False)
        lat, lon = self.cleaned_data.get("latitud"), self.cleaned_data.get("longitud")
        if lat is not None and lon is not None:
            inmueble.ubicacion = Point(float(lon), float(lat), srid=4326)
        if commit:
            inmueble.save()
        return inmueble


class ImagenInmuebleForm(forms.ModelForm):
    """Una fila de la galería: un archivo subido al CDN o una URL externa.

    `orden` tiene default en el modelo, así que Django le pone `initial=0` y
    una fila que el usuario dejó en blanco cuenta como "modificada": sin esto,
    dejar un renglón vacío devolvía "este campo es obligatorio".
    """

    class Meta:
        model = ImagenInmueble
        fields = ["archivo", "url", "descripcion", "orden", "es_portada"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["orden"].required = False
        self.fields["archivo"].widget.attrs["accept"] = "image/*"
        self.fields["url"].widget.attrs["placeholder"] = "https://…"
        self.fields["url"].label = "…o pegá una URL"

    def _fila_vacia(self) -> bool:
        """¿El usuario no tocó esta fila?

        `orden` queda afuera a propósito: tiene default en el modelo, así que
        se renderiza con valor 0 y estaría presente aunque nadie la toque. Los
        demás campos sí cuentan, para que escribir una descripción sin subir
        foto avise en vez de descartarse en silencio.
        """
        if self.instance.pk:
            return False
        if self.files.get(self.add_prefix("archivo")):
            return False
        for campo in ("url", "descripcion"):
            if (self.data.get(self.add_prefix(campo)) or "").strip():
                return False
        return not self.data.get(self.add_prefix("es_portada"))

    def has_changed(self):
        # Una fila sin archivo ni URL se ignora por completo.
        if self._fila_vacia():
            return False
        return super().has_changed()

    def clean_orden(self):
        return self.cleaned_data.get("orden") or 0



ImagenInmuebleFormSet = inlineformset_factory(
    Inmueble,
    ImagenInmueble,
    form=ImagenInmuebleForm,
    extra=3,
    can_delete=True,
)


class RechazoForm(forms.Form):
    """El broker devuelve el aviso con una explicación.

    El motivo es obligatorio: rechazar sin decir por qué es la forma más
    rápida de que los asesores dejen de usar el sistema.
    """

    motivo = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}),
        label="¿Qué hay que corregir?",
        max_length=1000,
    )


# ---------------------------------------------------------------------------
# Formularios del admin para el usuario propio
# ---------------------------------------------------------------------------
class UsuarioCreationForm(BaseUserCreationForm):
    class Meta(BaseUserCreationForm.Meta):
        model = Usuario
        fields = ("email", "nombre", "apellido")


class UsuarioChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = Usuario
        fields = "__all__"
