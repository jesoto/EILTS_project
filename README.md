# IELTS Trainer

App en Streamlit que te entrena para el **IELTS Academic** con un plan fijo de 11 semanas: cada día tiene su botón de práctica con la
estrategia cargada; los ejercicios varían, la dificultad es progresiva y todo se evalúa con feedback de errores que alimenta tu error log.
Interfaz en español, ejercicios en inglés. La metodología completa está en [CLAUDE.md](CLAUDE.md) y el calendario en [data/curriculum.yaml](data/curriculum.yaml).

> Las bandas que muestra la app son **estimaciones aproximadas** de un modelo de lenguaje: úsalas para ver tendencias, no como veredicto.
> Proyecto independiente: no está afiliado a IELTS, British Council, IDP ni Cambridge.

## Qué incluye
Gramática y Writing con evaluación por criterios · Speaking con transcripción y métricas de fluidez · Reading y Listening con tus libros
(corrección con clave, causa de cada error, dictado) · Vocabulario con repetición espaciada (SM-2) · error log · auditoría semanal ·
punto de control · exports en Markdown/PDF para tu profesora.

## Empezar (en tu equipo)
Necesitas [uv](https://docs.astral.sh/uv/) y una **clave de la API de OpenAI**. Los libros los pones tú: **este repo no incluye ninguno**.

```powershell
git clone <este-repo> ; cd EILTS_project
uv sync --extra local-stt                  # --extra local-stt solo si quieres Whisper local (si no, usa la API de OpenAI)
copy .env.example .env                     # y pon tu OPENAI_API_KEY dentro
uv run python scripts/doctor.py            # ¿qué falta?
uv run streamlit run app.py
```

1. **Tus libros:** copia el PDF (con texto seleccionable) y sus audios a `resources/`. Instrucciones y estructura en [resources/README.md](resources/README.md).
2. **Ingesta:** `uv run python scripts/ingest.py` extrae los tests a `data/derived/` (ignorado por git). Los libros que se reconocen están en [data/books.yaml](data/books.yaml).
3. **Verifica las claves** en la página «Verificar claves» antes de practicar Reading/Listening: una clave mal leída arruina la evaluación.
4. **Tu fecha de examen:** `exam_date` en [config.toml](config.toml) (o `IELTS_EXAM_DATE`). El plan empieza el lunes 11 semanas antes de la semana del examen.

La página **Configuración** de la app (y `scripts/doctor.py`) te dice qué falta: clave, modelo, libros, almacenamiento, acceso.

## Modelo de lenguaje
Se elige en [config.toml](config.toml) (`provider`):
- **`openai`** (por defecto): usa tu `OPENAI_API_KEY`. Modelo `gpt-4.1-mini`, ~0,002 USD por evaluación de Writing; el gasto estimado sale en Progreso. Puedes poner un tope diario (`max_calls_per_day`).
- **`ollama`** (local, gratis): `ollama pull gemma3:12b`. Más lento y con explicaciones menos fiables.

Con OpenAI se envían a su API tus textos (ensayos, transcripciones, ejercicios). Reading y Listening no usan LLM.

## Publicarla en Streamlit Cloud (solo para ti)
Mismo código en modo `cloud`: base de datos sincronizada con **Google Cloud Storage**, tus libros y audios en un **bucket privado**,
transcripción con la API de OpenAI y **login de Google con lista de correos**. Pasos en [DEPLOY.md](DEPLOY.md).

## Variables de entorno útiles
| Variable | Efecto |
|---|---|
| `OPENAI_API_KEY` | Tu clave (en `.env` o en los secrets de Streamlit) |
| `IELTS_MODE=local\|cloud` | Modo de ejecución |
| `IELTS_TZ=America/Lima` | Zona horaria (el servidor de Streamlit Cloud está en UTC) |
| `IELTS_EXAM_DATE=2026-12-29` | Fecha de examen; recalcula todo el plan |
| `IELTS_TODAY=2026-10-14` | Simula otra fecha (para probar el plan) |
| `IELTS_LLM_PROVIDER`, `IELTS_OPENAI_MODEL`, `IELTS_LLM_MODEL`, `IELTS_OLLAMA_HOST` | Sobrescriben `config.toml` |
| `IELTS_STT_PROVIDER=auto\|local\|openai`, `IELTS_STT_MODEL` | Transcripción |
| `IELTS_DB`, `IELTS_DERIVED`, `IELTS_RESOURCES`, `IELTS_RECORDINGS` | Rutas alternativas (modo local) |
| `ALLOWED_EMAILS`, `GCS_BUCKET`, `IELTS_REQUIRE_LOGIN=1` | Acceso y almacenamiento (modo cloud) |

## Desarrollo
```powershell
uv run pytest        # toda la suite (no necesita red ni claves)
```
Estructura: `app.py` y `pages/` (pantallas) · `ielts/` (núcleo: calendario, currículo, scoring, SRS, LLM, ingesta, almacenamiento, sincronización de la base de datos) ·
`data/` (currículo, temas de gramática, contenido de Speaking…) · `scripts/` (ingesta, diagnóstico, subida a la nube) · `tests/`.

## Notas
- Whisper local (`small`, CPU) descarga ~500 MB la primera vez que transcribes.
- Los PDFs escaneados (p. ej. Cambridge 16) necesitan OCR y todavía no se ingieren.
