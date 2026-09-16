"""Almacenamiento de archivos en BunnyCDN.

Dos piezas distintas de Bunny, que es fácil confundir:

  * **Storage Zone** — donde se suben los archivos. Se habla por HTTP contra
    ``{region}.storage.bunnycdn.com`` con la cabecera ``AccessKey``.
  * **Pull Zone** — el dominio público que sirve esos archivos
    (``algo.b-cdn.net``). Es el que va en el ``src`` de las etiquetas img.

Si no hay credenciales configuradas, el proyecto cae a almacenamiento local
(`MEDIA_ROOT`) para que se pueda trabajar en desarrollo sin tocar Bunny.
"""

import urllib.error
import urllib.request
from urllib.parse import quote

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, Storage
from django.utils.deconstruct import deconstructible

TIEMPO_LIMITE = 20  # segundos


class ErrorBunny(Exception):
    """Falló una operación contra la API de Bunny."""


@deconstructible
class BunnyStorage(Storage):
    def __init__(self, zona=None, clave=None, region=None, dominio=None):
        self.zona = zona or getattr(settings, "BUNNY_STORAGE_ZONE", "")
        self.clave = clave or getattr(settings, "BUNNY_STORAGE_KEY", "")
        self.region = region if region is not None else getattr(settings, "BUNNY_REGION", "")
        self.dominio = dominio or getattr(settings, "BUNNY_PULL_ZONE", "")
        if not (self.zona and self.clave and self.dominio):
            raise ImproperlyConfigured(
                "BunnyCDN necesita BUNNY_STORAGE_ZONE, BUNNY_STORAGE_KEY y "
                "BUNNY_PULL_ZONE."
            )

    # -- direcciones --------------------------------------------------------
    @property
    def _host(self) -> str:
        # La región por defecto (Falkenstein) va sin prefijo.
        return f"{self.region}.storage.bunnycdn.com" if self.region else "storage.bunnycdn.com"

    def _endpoint(self, nombre: str) -> str:
        return f"https://{self._host}/{self.zona}/{quote(nombre.lstrip('/'))}"

    def url(self, nombre):
        return f"https://{self.dominio}/{quote(nombre.lstrip('/'))}"

    # -- HTTP ---------------------------------------------------------------
    def _pedir(self, metodo, nombre, datos=None, tipo=None):
        pedido = urllib.request.Request(
            self._endpoint(nombre), data=datos, method=metodo
        )
        pedido.add_header("AccessKey", self.clave)
        pedido.add_header("Accept", "application/json")
        if tipo:
            pedido.add_header("Content-Type", tipo)
        return urllib.request.urlopen(pedido, timeout=TIEMPO_LIMITE)

    # -- API de Storage -----------------------------------------------------
    def _save(self, nombre, contenido):
        contenido.seek(0)
        datos = contenido.read()
        try:
            self._pedir("PUT", nombre, datos=datos, tipo="application/octet-stream")
        except urllib.error.HTTPError as error:
            raise ErrorBunny(
                f"Bunny rechazó la subida de {nombre}: {error.code} {error.reason}"
            ) from error
        except urllib.error.URLError as error:
            raise ErrorBunny(f"No se pudo contactar a Bunny: {error.reason}") from error
        return nombre

    def _open(self, nombre, modo="rb"):
        try:
            with self._pedir("GET", nombre) as respuesta:
                return ContentFile(respuesta.read(), name=nombre)
        except urllib.error.HTTPError as error:
            raise ErrorBunny(f"No se pudo leer {nombre}: {error.code}") from error

    def delete(self, nombre):
        try:
            self._pedir("DELETE", nombre)
        except urllib.error.HTTPError as error:
            if error.code != 404:  # borrar algo que ya no está no es un error
                raise ErrorBunny(f"No se pudo borrar {nombre}: {error.code}") from error
        except urllib.error.URLError:
            # Un archivo huérfano es mucho menos grave que romper el guardado.
            pass

    def exists(self, nombre):
        try:
            self._pedir("GET", nombre).close()
            return True
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return False
            raise ErrorBunny(f"No se pudo consultar {nombre}: {error.code}") from error
        except urllib.error.URLError:
            # Ante la duda decimos que no existe: los nombres llevan uuid, así
            # que una colisión real es prácticamente imposible.
            return False

    def size(self, nombre):
        with self._pedir("GET", nombre) as respuesta:
            return int(respuesta.headers.get("Content-Length") or 0)

    def get_accessed_time(self, nombre):
        raise NotImplementedError("Bunny Storage no expone fecha de acceso.")


def bunny_configurado() -> bool:
    return all(
        [
            getattr(settings, "BUNNY_STORAGE_ZONE", ""),
            getattr(settings, "BUNNY_STORAGE_KEY", ""),
            getattr(settings, "BUNNY_PULL_ZONE", ""),
        ]
    )


def almacenamiento_imagenes():
    """Storage de las fotos: Bunny si está configurado, local si no.

    Se pasa como callable a `ImageField(storage=...)`, así el fallback se
    decide en cada arranque y la migración no queda atada a un backend.
    """
    if bunny_configurado():
        return BunnyStorage()
    return FileSystemStorage()
