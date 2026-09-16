# MLS — Multiple Listing Service inmobiliario

Django 6.1 + PostgreSQL 17 + PostGIS 3.6.

**[Ver la app →](https://omarjust.github.io/mls-inmobiliario/)** · capturas de la aplicación corriendo, sin maqueta.

## Puesta en marcha

```bash
brew services start postgresql@17          # si no está corriendo
cd MLS
../venv/bin/python manage.py migrate
../venv/bin/python manage.py createsuperuser
../venv/bin/python manage.py runserver
```

Admin en http://127.0.0.1:8000/admin/

## Base de datos

Se conecta por defecto a `mls_db` con el rol `mls_user`. Para cambiarlo,
exportar `MLS_DB_NAME`, `MLS_DB_USER`, `MLS_DB_PASSWORD`, `MLS_DB_HOST`, `MLS_DB_PORT`.

Crear la base desde cero:

```bash
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"
createuser -s mls_user           # o CREATE ROLE ... LOGIN PASSWORD ...
createdb -O mls_user mls_db
psql -d mls_db -c "CREATE EXTENSION postgis;"
```

## Tipos de usuario

| Perfil | ¿Login? | Cómo se distingue |
|---|---|---|
| Visitante | No | Anónimo. Nunca ve calle exacta, punto real ni propietario. |
| Asesor | Sí | `usuario.asesor` existe. Edita solo sus captaciones. |
| Broker | Sí | `AsesorAgencia.es_broker=True`. Aprueba lo de su agencia. |
| Administrador MLS | Sí | `is_staff` + permiso `gestionar_todo_inmueble`. |
| Superusuario | Sí | Perfil técnico. |

El propietario **no** es usuario: es un dato que carga y ve el asesor que captó.

## Acceso

La identidad es el correo (`core.Usuario`, con `USERNAME_FIELD = "email"`), no un
nombre de usuario: `auth.User` no admite correos como `o'brien@x.com`.

| Ruta | Qué es |
|---|---|
| `/ingresar/` | Login |
| `/sumarme/` | Solicitud de ingreso (queda pendiente de aprobación) |
| `/panel/` | Panel del asesor |
| `/panel/aprobaciones/` | Cola de revisión del broker |

Tras `seed_demo`, para entrar como broker: **ana.rojas@housematchmls.com / demo12345**
(los otros asesores usan la misma contraseña).

## Circuito de publicación

```
BORRADOR --enviar a revisión--> EN REVISIÓN --aprueba el broker--> PUBLICADO
   ^                                 |                                 |
   +--------- rechaza con motivo ----+                                 |
   +------------------- editar precio o título ------------------------+
```

Nada aparece en el portal hasta que un broker lo aprueba. El broker se auto-aprueba;
un asesor sin agencia no puede publicar.

## Reglas de negocio implementadas

| Regla | Dónde |
|---|---|
| Un asesor solo edita sus captaciones (el broker, las de su agencia) | `Inmueble.puede_editar()` + `InmuebleAdmin.has_change_permission` |
| Los inmuebles no se borran, se dan de baja | `Inmueble.delete()` (baja lógica) |
| Una sola membresía asesor-agencia vigente | constraint `uq_una_membresia_vigente_por_asesor` |
| Una sola captación vigente por inmueble | constraint `uq_una_captacion_vigente_por_inmueble` |
| Cada cambio de precio queda registrado | `Inmueble.save()` → `HistorialPrecio` |
| El reparto de comisiones no supera el 100% | `ComisionParticipacionFormSet.clean()` |
| La calle y el punto exacto son privados | `Inmueble.direccion_para()` / `ubicacion_publica()` |
| Al cerrar una operación, el inmueble pasa a "cerrado" | `Operacion._sincronizar_inmueble()` |
| Nada se publica sin que conste quién lo aprobó | constraint `ck_publicado_requiere_revisor` |
| Un asesor no opera si no está aprobado | constraint `ck_asesor_activo_solo_si_aprobado` |
| Suspender a alguien mata su sesión en el siguiente request | `Usuario.is_active` + `ModelBackend.get_user` |
| Los asesores no entran al admin de Django | `is_staff=False`; trabajan en `/panel/` |

## Imágenes — BunnyCDN

Las fotos se suben a una **Storage Zone** y se sirven por la **Pull Zone**. Cuatro
variables de entorno, ninguna en el código:

```bash
export BUNNY_STORAGE_ZONE=mls-fotos          # nombre de la Storage Zone
export BUNNY_STORAGE_KEY=...                 # su password/AccessKey
export BUNNY_PULL_ZONE=mls-fotos.b-cdn.net   # dominio público, sin https://
export BUNNY_REGION=br                       # vacío = Falkenstein; 'ny','la','sg','br'…
```

**Sin esas variables el proyecto guarda en `MEDIA_ROOT` y funciona igual**, así que
no hace falta tocar Bunny para desarrollar. El backend está en `core/storage.py`.

Cada foto puede venir de dos lados y `ImagenInmueble.src` resuelve cuál usar:

| Campo | Cuándo |
|---|---|
| `archivo` | Subida desde el panel. Va al CDN. Es el camino normal. |
| `url` | La foto ya está alojada en otro lado. |

Los archivos se guardan como `inmuebles/<uuid del inmueble>/<uuid>.<ext>`: no se
pisan entre sí y no filtran el nombre original. Borrar la fila borra el archivo
del CDN (`post_delete`).

## Comandos

```bash
python manage.py seed_grupos   # grupo "Administrador MLS" con sus permisos
python manage.py seed_demo --reset
```

## Pendientes

- Recuperación de contraseña (hoy la resetea un admin desde `/admin/`).
- Ficha pública del inmueble (`/inmueble/<codigo>/`): hoy las tarjetas del
  buscador no llevan a ninguna parte.
- Miniaturas y marca de agua sobre las fotos del CDN.
- Probar la subida contra Bunny de verdad: está verificada solo con el
  almacenamiento local.
- Mapa interactivo en el formulario: la ubicación se carga como lat/lon sueltas.
- Notificar por correo al asesor cuando le aprueban o rechazan (`MAILERS` ya
  apunta a consola, falta engancharlo).
- El throttle de login usa el cache en memoria: en producción, apuntarlo a Redis.
- `SECRET_KEY` por entorno, `DEBUG=False` y cookies seguras antes de producción.
- API REST (Django REST Framework).
- Leads / solicitudes de clientes.
