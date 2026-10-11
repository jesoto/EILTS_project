# Publicar la app en Streamlit Cloud (solo para ti)

Resultado: una URL `https://TU-APP.streamlit.app` privada, que funciona aunque tu PC esté apagado, con tus libros, tu progreso y tus grabaciones guardados
en **tu** bucket de Google Cloud. Solo entran los correos que tú autorices.

```
Tu PC ──(scripts/sync_to_cloud.py)──▶ Bucket privado de Google Cloud Storage ◀──▶ Streamlit Cloud (app.py)
                                      derived/ · resources/ (audios) · recordings/ · db/ielts.db        │
                                                                              Login Google + ALLOWED_EMAILS · OpenAI (tu clave)
```

**Tiempo estimado:** 45-60 min la primera vez. Necesitas: cuenta de Google con tarjeta (la capa gratuita de Google Cloud basta, pero exige activar la facturación),
cuenta de GitHub, tu clave de OpenAI y los tests ya ingeridos y verificados en tu PC.

> Esto es para **uso personal**: tus copias de los libros viven en un bucket privado a tu nombre. No se comparten ni se publican, y nunca van a GitHub.

---

## 0. Antes de empezar (en tu PC)
```powershell
uv run python scripts/doctor.py     # todo en orden
uv run python scripts/ingest.py     # tests extraídos en data/derived/
# Abre la app → «Verificar claves» y verifica los tests que vayas a usar
uv run pytest                       # la suite pasa
```

## 1. Código en GitHub
```powershell
git push        # el repositorio no contiene libros, claves ni datos: lo garantizan tests/test_onboarding.py
```
Puede ser público o privado. Si es público, cualquiera puede clonarlo, pero necesitará **sus** libros y **su** clave.

## 2. Google Cloud: proyecto, facturación y presupuesto
1. <https://console.cloud.google.com> → selector de proyectos → **Proyecto nuevo** (p. ej. `ielts-trainer`).
2. **Facturación** → vincula una cuenta de facturación al proyecto.
3. **Facturación → Presupuestos y alertas → Crear presupuesto**: 1 USD con alertas al 50 %, 90 % y 100 %. *(Es tu seguro contra sorpresas.)*

## 3. Bucket privado
**Cloud Storage → Buckets → Crear**
- Nombre: único en el mundo (p. ej. `ielts-trainer-tunombre-2026`). Anótalo: es tu `GCS_BUCKET`.
- Ubicación: **Región** → `us-central1`, `us-east1` o `us-west1` (cuentan para la capa gratuita «Always Free»; compruébalo en la documentación vigente de precios).
- Clase: Standard.
- Control de acceso: **Uniforme**.
- Protección: marca **«Aplicar prevención de acceso público en este bucket»**. *(Así ni un error de configuración lo hace público.)*

## 4. Cuenta de servicio (la identidad de la app)
1. **IAM y administración → Cuentas de servicio → Crear**: nombre `ielts-app`. **No le des roles de proyecto.**
2. **Cloud Storage → tu bucket → Permisos → Otorgar acceso**: principal = el correo de la cuenta de servicio (`ielts-app@…iam.gserviceaccount.com`),
   rol **Administrador de objetos de Storage** (*Storage Object Admin*). Solo sobre ese bucket.
3. Cuenta de servicio → **Claves → Agregar clave → Crear clave nueva → JSON**. Se descarga un `.json`.
   Guárdalo **fuera de la carpeta del proyecto** (p. ej. en `C:\Users\TU-USUARIO\secretos\`). Quien tenga ese archivo puede leer y borrar tu bucket.

## 5. Login con Google (OAuth)
1. **APIs y servicios → Pantalla de consentimiento de OAuth** → tipo **Externo** → nombre de la app y tu correo.
   En **Usuarios de prueba** añade tu correo. Puedes dejarla en estado *Testing*: solo tú entras.
2. **APIs y servicios → Credenciales → Crear credenciales → ID de cliente de OAuth → Aplicación web**.
   **URIs de redirección autorizados** (los dos):
   - `https://TU-APP.streamlit.app/oauth2callback`  *(elige el nombre de TU-APP ahora; lo usarás en el paso 7)*
   - `http://localhost:8501/oauth2callback`  *(para probar en tu PC)*
3. Copia el **ID de cliente** y el **secreto**.

## 6. Subir tus datos al bucket
Desde tu PC, con la clave JSON del paso 4:
```powershell
# 1) simulación: muestra qué se subiría, sin subir nada
uv run python scripts/sync_to_cloud.py --bucket TU_BUCKET --credentials "C:\ruta\clave.json" --dry-run
# 2) subida real (pide confirmación)
uv run python scripts/sync_to_cloud.py --bucket TU_BUCKET --credentials "C:\ruta\clave.json"
```
Sube: tests extraídos y sus imágenes (`derived/`), **solo los audios que usan tus tests** (no tus PDF), tu progreso (`db/ielts.db`, solo si aún no existe en la nube)
y, con `--recordings`, tus grabaciones. Es incremental: puedes repetirlo cuando ingieras o verifiques más tests.
`--force-db` sobrescribe la base de la nube con la local (úsalo con cuidado).
`--skip-db` no toca la base (recomendado si tu base local solo tiene datos de prueba).

**¿Ya subiste tus libros al bucket por otro camino** (p. ej. arrastrando la carpeta desde la consola)? No hace falta subirlos otra vez:
indica la carpeta donde están con `--resources-prefix Resources_IELTS` y añade `GCS_RESOURCES_PREFIX = "Resources_IELTS/"` a los Secrets.
Las rutas de los audios son las mismas que en tu carpeta `resources/`, así que se reconocen sin cambios.

## 7. Streamlit Community Cloud
1. <https://share.streamlit.io> → inicia sesión con GitHub → **Create app** → tu repositorio, rama `main`, archivo `app.py`.
2. En **App URL** pon el subdominio que elegiste en el paso 5.
3. **Advanced settings → Python version: 3.12** y pega en **Secrets** el contenido de [.streamlit/secrets.toml.example](.streamlit/secrets.toml.example) con tus valores:
   - `OPENAI_API_KEY`, `ALLOWED_EMAILS` (tu correo), `GCS_BUCKET`, `IELTS_TZ`, `IELTS_EXAM_DATE` si no es el 29-dic-2026.
   - `[auth]`: `redirect_uri` = la URL exacta del paso 5, `client_id`, `client_secret`, y una `cookie_secret` larga y aleatoria.
   - `[gcp_service_account]`: los campos del `.json` del paso 4 (`private_key` conserva los `\n`).
4. **Deploy**. La primera vez tarda unos minutos en instalar dependencias.
5. *(Doble barrera, opcional)* **Settings → Sharing → Only specific people can view this app** y añade tu correo.

## 8. Comprobar que todo funciona
1. Abre tu URL → **Entrar con Google**. Con otra cuenta debe decir «no tiene acceso».
2. Página **Configuración** → **Probar conexiones**: OpenAI responde, el bucket es accesible y **privado**.
3. **Verificar claves** muestra tus tests; **Reading/Listening** reproducen audio (URLs firmadas de 1 h).
4. Haz un ejercicio, pulsa **Rebootear app** en Streamlit y comprueba en **Progreso** que tus datos siguen ahí.

*(Prueba previa en tu PC, opcional: copia `.streamlit/secrets.toml.example` a `.streamlit/secrets.toml` con tus valores y ejecuta `uv run streamlit run app.py`;
el login de Google funcionará con la URI `http://localhost:8501/oauth2callback`.)*

---

## Mantenimiento
| Tarea | Cómo |
|---|---|
| Copias de seguridad | Automáticas: `db/backups/ielts-AAAA-MM-DD.db` en el bucket (una por día, últimas 14). |
| Restaurar una copia | Cloud Storage → copia `db/backups/ielts-…db` sobre `db/ielts.db` y reinicia la app. |
| Si ves «Conflicto» en Configuración | Dos instancias escribieron a la vez. Elige conservar lo de la sesión o recargar la nube. Evita tener la app abierta en dos sitios. |
| Rotar la clave de OpenAI | Crea otra, cámbiala en los Secrets y revoca la antigua. |
| Rotar la clave del bucket | Cuenta de servicio → crea una clave JSON nueva, actualiza `[gcp_service_account]`, borra la antigua. |
| Ver el gasto | Página **Progreso → Modelo de lenguaje** (estimado) y tu panel de OpenAI (real). Hay un tope diario configurable (`max_calls_per_day`). |
| Cambiar la fecha de examen | `IELTS_EXAM_DATE` en los Secrets. |
| Añadir un libro | En tu PC: copia el PDF, `ingest.py`, verifica, y `sync_to_cloud.py`. |
| Borrarlo todo | Elimina la app en Streamlit, el bucket y el proyecto de Google Cloud. |

## Si algo falla
| Síntoma | Causa probable |
|---|---|
| «Falta configurar `ALLOWED_EMAILS`» | No está en los Secrets (la app falla cerrada a propósito). |
| Google dice `redirect_uri_mismatch` | El `redirect_uri` de los Secrets no coincide exactamente con el del paso 5. |
| «La cuenta … no tiene acceso» | Tu correo no está en `ALLOWED_EMAILS` o no está verificado. |
| Configuración → «No se pudo acceder al bucket» | `GCS_BUCKET` mal escrito, o la cuenta de servicio no tiene el rol sobre el bucket. |
| El audio no suena | La URL firmada caducó (recarga la página) o la clave de la cuenta de servicio es inválida. |
| La transcripción falla | Sin crédito en OpenAI o clave inválida; el mensaje lo indica. |
| La app va lenta tras un rato sin usarla | Streamlit Cloud la suspende por inactividad; el primer arranque descarga la base. |

## Límites a tener en cuenta
- Streamlit Community Cloud tiene memoria limitada: por eso la transcripción usa la API de OpenAI (~0,006 USD por minuto) y no Whisper local.
- Una sola persona y una sola pestaña a la vez (la última escritura gana; el conflicto se avisa, no se fusiona).
- Las bandas siguen siendo **estimaciones aproximadas**.
