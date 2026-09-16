"""Bloque 5: capa de almacenamiento intercambiable (4 comprobaciones).

Verifica que la interfaz se resuelve por configuración y que el backend del
proveedor externo construye correctamente las dos direcciones que maneja: la
de escritura contra la zona de almacenamiento y la pública de la zona de
distribución. No se contacta el servicio real.
"""

import io

from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from PIL import Image

from core.storage import BunnyStorage, almacenamiento_imagenes, bunny_configurado

from .base import BaseMLS


def imagen_falsa(nombre="foto.jpg"):
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (180, 120, 90)).save(buf, format="JPEG")
    return SimpleUploadedFile(nombre, buf.getvalue(), content_type="image/jpeg")


class Almacenamiento(SimpleTestCase):

    def test_53_sin_credenciales_cae_al_almacenamiento_local(self):
        with override_settings(BUNNY_STORAGE_ZONE="", BUNNY_STORAGE_KEY="",
                               BUNNY_PULL_ZONE=""):
            self.assertFalse(bunny_configurado())
            self.assertIsInstance(almacenamiento_imagenes(), FileSystemStorage)

    def test_54_con_credenciales_usa_el_proveedor_externo(self):
        with override_settings(BUNNY_STORAGE_ZONE="mls-fotos",
                               BUNNY_STORAGE_KEY="clave", BUNNY_REGION="",
                               BUNNY_PULL_ZONE="mls.b-cdn.net"):
            self.assertTrue(bunny_configurado())
            self.assertIsInstance(almacenamiento_imagenes(), BunnyStorage)

    def test_55_las_direcciones_distinguen_escritura_de_lectura(self):
        """La zona de almacenamiento recibe la escritura; la de distribución
        es la que se publica. Confundirlas es el error habitual."""
        b = BunnyStorage(zona="mls-fotos", clave="clave", region="",
                         dominio="mls.b-cdn.net")
        self.assertEqual(b._endpoint("inmuebles/abc/f1.jpg"),
                         "https://storage.bunnycdn.com/mls-fotos/inmuebles/abc/f1.jpg")
        self.assertEqual(b.url("inmuebles/abc/f1.jpg"),
                         "https://mls.b-cdn.net/inmuebles/abc/f1.jpg")
        # La región cambia el servidor de escritura, no el de distribución.
        br = BunnyStorage(zona="mls-fotos", clave="clave", region="br",
                          dominio="mls.b-cdn.net")
        self.assertTrue(br._endpoint("a/b.jpg").startswith(
            "https://br.storage.bunnycdn.com/"))
        # Los espacios se escapan en la dirección pública.
        self.assertIn("%20", b.url("inmuebles/abc/foto con espacio.jpg"))

    def test_56_sin_configuracion_completa_el_backend_no_se_construye(self):
        with self.assertRaises(ImproperlyConfigured):
            BunnyStorage(zona="mls-fotos", clave="", dominio="")


class ImagenesDelInmueble(BaseMLS):

    def test_57_la_foto_subida_se_nombra_con_identificadores_opacos(self):
        from core.models import ImagenInmueble
        imagen = ImagenInmueble.objects.create(
            inmueble=self.inmueble, archivo=imagen_falsa("mi-casa-frente.jpg"))
        self.assertTrue(imagen.en_cdn)
        self.assertNotIn("mi-casa-frente", imagen.archivo.name)
        self.assertIn(str(self.inmueble.pk), imagen.archivo.name)
        self.assertEqual(imagen.src, imagen.archivo.url)
        # Borrar la fila borra el archivo: sin esto quedarían huérfanos.
        almacen, nombre = imagen.archivo.storage, imagen.archivo.name
        self.assertTrue(almacen.exists(nombre))
        imagen.delete()
        self.assertFalse(almacen.exists(nombre))
