# IELTS Trainer — Contexto del proyecto

App local en Streamlit que entrena al usuario para el **IELTS Academic del 29 de diciembre de 2026** siguiendo un plan fijo de 11 semanas. Cada día de la semana tiene un botón de práctica con la estrategia ya cargada; los ejercicios varían, la dificultad es progresiva y todo se evalúa con feedback de errores.

Usuario: hispanohablante nativo (Perú), nivel B1/B2 bajo. Debilidades: **gramática y Writing**. Meta: 6.5 overall (B2 alto); meta de estiramiento: 7.0 (C1). Toma clases con una profesora martes y jueves.

Idioma de la interfaz: español. Contenido de ejercicios: inglés. Feedback: explicación en español + corrección en inglés.

---

## Restricciones técnicas

- **Stack:** Python 3.11+, Streamlit, SQLite (vía SQLAlchemy o sqlite3), pydantic para esquemas.
- **LLM:** toda llamada pasa por una interfaz `LLMProvider` con `OpenAIProvider` (por defecto, clave en `.env`/secrets) y `OllamaProvider` (local, gratis); stub `AnthropicProvider` para el futuro. El modelo se configura en `config.toml` / `.env`, nunca hardcodeado.
- **Respuestas del LLM siempre en JSON validado con pydantic**, con reintento (máx. 2) si el JSON no valida. Temperatura baja (≤0.3) para evaluación, más alta (~0.8) para generar ejercicios.
- **Speech-to-text:** `faster-whisper` local, con timestamps por palabra.
- **PDFs:** PyMuPDF (`fitz`). Los PDFs tienen texto seleccionable (no requieren OCR).
- **`resources/` está en `.gitignore`.** Contiene libros y audios con copyright: solo se leen localmente, nunca se suben, nunca se copian textos completos a archivos versionados. Los índices derivados (JSON de tests, claves de respuesta) van en `data/derived/`, también ignorado por git.
- La app corre local por defecto (`streamlit run app.py`). Existe un modo `cloud` opcional (Streamlit Cloud + Google Cloud Storage privado + login de Google; ver `DEPLOY.md`). Quien clone el repo pone sus propios libros en `resources/` y su propia clave de OpenAI.
- Las bandas que estime el LLM se muestran siempre como **"banda estimada (aproximada)"**.

---

## Calendario y fases

- Inicio: **lunes 12 oct 2026**. Examen: **martes 29 dic 2026**. Semana N = `((fecha - 2026-10-12).days // 7) + 1`.
- Antes del 12 oct: modo **diagnóstico** (test completo para línea base).

| Fase | Semanas | Fechas | Modo |
|---|---|---|---|
| 1. Cimientos | 1–4 | 12 oct – 8 nov | Adquisición. Sin cronómetro. Writing guiado. Reading/Listening por tipo de pregunta |
| 2. Construcción | 5–8 | 9 nov – 6 dic | Writing cronometrado (20/40 min). Tests completos los sábados |
| 3. Simulacro | 9–11 | 7 dic – 27 dic | Resistencia. Simulacros completos. Repaso del error log. Semana 11 ligera |

- **Punto de control: domingo 22 nov** (simulacro completo). Overall ≥ 6.0 → mantener fecha. < 5.5 → sugerir mover examen. Entre 5.5 y 6.0 → sugerir consultarlo con la profesora.
- 24 y 25 dic: días libres. 28 dic: descanso (mostrar checklist de logística). 29 dic: examen.

**Principio clave (teoría de carga cognitiva):** nunca mezclar adquisición de estructuras nuevas con simulacros cronometrados en el mismo bloque. Bloques de máx. 45–50 min.

---

## Semana tipo (lo que carga cada botón)

Todos los días incluyen **15 min de Anki/SRS** (vocabulario + chunks).

| Día | Duración | Bloques |
|---|---|---|
| Lunes (remoto) | 1h30 | Writing Task 2 (40 min) + reescritura con checklist (20 min) + gramática del tema semanal (30 min) |
| Martes (oficina + clase) | 30 min | Listening (audio de práctica) + preparar ensayo del lunes para la profesora (export PDF/markdown con errores marcados) |
| Miércoles (oficina) | 45 min | Reading: 1 passage cronometrado (20 min) + análisis de errores (15 min) + shadowing (10 min) |
| Jueves (oficina + clase) | 30 min | Speaking Part 2: grabar monólogo de 2 min + feedback. Generar lista de dudas para la profesora |
| Viernes (remoto) | 1h15 | Writing Task 1 (20 min) + reescritura (15 min) + gramática/colocaciones del error log (30 min) |
| Sábado | 2h30 | Listening completo (30 min) + Reading completo (60 min) + corrección y error log (45 min) |
| Domingo | 1h | Auditoría semanal (20 min) + Speaking Part 1 y 3 (20 min) + SRS |

Variantes por fase:
- **Fase 1:** sábado = secciones sueltas por tipo de pregunta, no test completo. Writing sin cronómetro.
- **Fase 3:** sábado = simulacro completo de 2h45 (con Writing). Lunes = simulacro de Writing + Reading.

---

## Calendario semana a semana

| Sem | Fechas | Gramática | Writing | Reading / Listening | Vocab (tema) |
|---|---|---|---|---|---|
| 1 | 12–18 oct | Sujeto obligatorio + concordancia | T1: estructura y overview (line graph) | T/F/Not Given · Listening sec. 1 | Educación |
| 2 | 19–25 oct | Artículos | T2: opinión | Matching headings · Listening sec. 2 | Tecnología |
| 3 | 26 oct – 1 nov | Tiempos en T1 + preposiciones con datos | T1: bar chart y tabla | Completion · Listening sec. 3 | Medio ambiente |
| 4 | 2–8 nov | Relativas y concesivas | T2: discussion (both views) | Multiple choice / matching info · Listening sec. 4 | Salud |
| 5 | 9–15 nov | Condicionales | T1: pie chart y mixtos · inicia cronómetro | Primer Reading y Listening completos | Sociedad y ciudades |
| 6 | 16–22 nov | Voz pasiva | T1: process y map · T2: problema-solución | Simulacro 22 nov (checkpoint) | Trabajo y economía |
| 7 | 23–29 nov | Top 3 errores del error log | T2: ventajas-desventajas | Tests completos, foco en tipo más débil | Gobierno y crimen |
| 8 | 30 nov – 6 dic | Inversión, nominalización | T2: doble pregunta | Tests completos, Listening a 1.25x | Repaso colocaciones |
| 9 | 7–13 dic | Error log | 2 T1 + 2 T2 cronometrados | 2 simulacros completos | Repaso global |
| 10 | 14–20 dic | Error log | 2 T1 + 2 T2 cronometrados | 2 simulacros completos | Repaso global |
| 11 | 21–27 dic | Checklist | 1 simulacro Writing (lun 21) | 1 simulacro completo (mar 22) | Repaso ligero |

Guardar esta tabla como `data/curriculum.yaml` (versionado) y que toda la lógica lea de ahí.

---

## Módulos

### 1. Gramática
- Temas priorizados por penalización en GRA: (1) sujeto obligatorio / pro-drop (*It is clear that…*, nunca *Is clear that…*), (2) concordancia sujeto-verbo, (3) artículos, (4) tiempos en Task 1, (5) relativas y concesivas, (6) condicionales, (7) voz pasiva, (8) preposiciones con datos (*increase by*, *rise to*, *peak at*).
- Método por sesión: micro-teoría (≤10 min) → ejercicios → producción (párrafo con el tema).
- Tipos de ejercicio (rotar, no repetir el mismo formato dos veces seguidas): gap-fill, detección y corrección de errores, transformación de oraciones, ordenar palabras, escribir oraciones propias sobre temas IELTS.
- Distractores basados en **interferencia del español** (pro-drop, falsos amigos, artículos, preposiciones calcadas).
- Ejercicios cerrados se corrigen sin LLM (clave generada junto al ejercicio). Producción libre la corrige el LLM.

### 2. Writing
- Task 1: estructura fija de 4 párrafos — Introducción (paráfrasis) → Overview (2 tendencias, **sin cifras**) → Cuerpo 1 → Cuerpo 2. Banco de frases de tendencias.
  - Gráficos: preferir los de los libros en `resources/` (extraer imagen + enunciado). Como alternativa, generar gráficos con matplotlib a partir de datos sintéticos (line, bar, pie, table, mixto; process/map solo desde libros).
- Task 2: 4 tipos — opinión, discussion, problema-solución, ventajas-desventajas (+ doble pregunta en fase 2). Párrafo de cuerpo = idea → explicación → ejemplo → vínculo con la pregunta.
- Editor con contador de palabras (T1 ≥150, T2 ≥250; sugerir 170/270) y cronómetro según fase.
- **Evaluación** (LLM → JSON): banda estimada por criterio (TA/TR, CC, LR, GRA) con justificación breve basada en los descriptores oficiales; lista de errores `{fragmento, corrección, categoría, explicación_es}`; 3 oraciones a reescribir; versión mejorada de un párrafo.
- **Checklist automática** previa al LLM (reglas + LLM ligero): sujeto explícito en cada cláusula, concordancia, artículos, falsos amigos (*actually, realize, eventually, sensible, assist, sympathetic*), ≥2 oraciones complejas por párrafo, conectores variados (penalizar abuso de *but/so/about*), overview sin cifras (T1), posición clara (T2), conteo de palabras.
- Paso obligatorio de **reescritura**: el usuario corrige las 3 peores oraciones y se vuelven a evaluar.
- Exportar ensayo + feedback a markdown/PDF para llevar a la profesora el martes.

### 3. Reading
- Fuente: tests de los libros Cambridge en `resources/`. Ingesta semi-automática (ver "Ingesta de recursos").
- Fase 1: un tipo de pregunta por semana según el calendario. Fase 2+: passages/tests completos.
- Límite de 20 min por passage; aviso a los 90 s en una misma pregunta.
- Corrección con clave. Por cada error, pedir al usuario la causa (sinónimo no reconocido, Not Given vs False, tiempo, vocabulario) y registrar.
- Conversión de raw score a banda (Academic): 30–32→7.0, 27–29→6.5, 23–26→6.0, 33–34→7.5, 35–36→8.0.

### 4. Listening
- Audios de los libros en `resources/` mapeados a sus tests y claves.
- Reproductor con control de velocidad (1.0x / 1.25x; 1.25x por defecto en semana 8).
- **La ortografía cuenta**: respuesta mal escrita = incorrecta. Normalizar solo mayúsculas/espacios.
- Ejercicio extra semanal de **dictado** (bottom-up): 1 min de audio para transcribir palabra por palabra; comparar contra la transcripción del libro y marcar formas débiles/coarticulación omitidas.
- Conversión: 30–31→7.0, 26–29→6.5, 23–25→6.0, 32–34→7.5, 35–36→8.0.

### 5. Speaking
- Grabación con `st.audio_input` → faster-whisper.
- Part 2: tarjeta de tema + 1 min de preparación (temporizador) + 2 min de habla. Part 1 y 3: preguntas por tema de la semana; estructura respuesta → razón → ejemplo.
- Métricas sin LLM: palabras/minuto, pausas > 1.5 s (desde timestamps), muletillas (*um, eh, like, you know*), repetición léxica, diversidad léxica.
- Feedback LLM sobre la transcripción: Fluency & Coherence, Lexical Resource, GRA (banda aproximada); pronunciación solo como observación aproximada.
- Shadowing: reproducir un fragmento, grabar al usuario, comparar transcripciones.

### 6. Vocabulario (SRS)
- Algoritmo SM-2 propio en SQLite.
- Tarjeta = palabra + familia (sustantivo/verbo/adjetivo/adverbio) + 2 colocaciones + oración del usuario. Nunca palabra suelta.
- AWL sublistas 1–5 en fase 1, 6–10 en fase 2. Tema semanal según calendario. Incluir falsos amigos.
- Colocaciones C1 de referencia: *conduct research*, *draw a conclusion*, *pose a threat*, *mitigate the effects*, *widen the income gap*, *place strain on*, etc.
- Los errores léxicos del error log generan tarjetas automáticamente.

### 7. Error log y auditoría
- Todo error detectado en cualquier módulo se guarda: `fecha, módulo, fragmento, corrección, categoría, explicación, conteo`.
- Categorías normalizadas (enum): `subject_omission, sv_agreement, articles, verb_tense, prepositions, false_friend, collocation, word_form, spelling, punctuation, cohesion, task_response, other`.
- **Top 3 categorías** de la semana → refuerzan la gramática de la semana siguiente (semanas 7, 9, 10 dependen de esto).
- **Auditoría del domingo** (página guiada): ¿qué medí? (scores de la semana), ¿dónde perdí puntos? (top 3), ¿por qué?, ¿qué cambio? (un objetivo concreto), ¿cómo me sentí? (energía/ansiedad 1–5; si es bajo dos semanas seguidas, sugerir reducir carga).

---

## Dificultad progresiva

- Nivel por habilidad (`grammar, writing, reading, listening, speaking, vocab`) en escala 1–10, guardado en la DB.
- Se ajusta con el rendimiento móvil de las últimas 5 sesiones: >80% acierto → +1; <50% → −1.
- La fase impone mínimos: cronómetro, longitud de textos, tests completos vs. sueltos.
- El generador recibe `{tema, nivel, fase, errores_frecuentes}` para que los ejercicios ataquen las debilidades reales.
- Evitar repetir ejercicios: guardar hash/semilla de los generados.

---

## Ingesta de recursos (`resources/`)

1. Script `scripts/ingest.py`: recorre `resources/`, inventaría PDFs y audios.
2. Extrae con PyMuPDF por test: passages de Reading, preguntas, prompts de Writing (+ imágenes de gráficos), tarjetas de Speaking, claves de respuesta y transcripciones de Listening.
3. Usa heurísticas (encabezados como "Test 1", "READING PASSAGE 1", "Answer Keys") + LLM local para estructurar a JSON en `data/derived/<libro>/<test>.json`.
4. **Paso de verificación humana**: página de Streamlit para revisar/corregir claves extraídas antes de usarlas. Una clave mal parseada arruina la evaluación.
5. Mapear audios a test/sección por nombre de archivo; si es ambiguo, pedir confirmación en la UI.

---

## UI

- **Inicio:** semana actual, fase, días restantes al examen, 7 botones (Lun–Dom) con el de hoy resaltado y estado (pendiente/hecho). Se puede practicar cualquier día, no solo hoy.
- **Sesión:** bloques en secuencia con temporizador por bloque, botón "siguiente bloque", resumen al final.
- **Progreso:** bandas estimadas por sección en el tiempo, raw scores de Reading/Listening, top errores, racha de días.
- **Error log:** tabla filtrable + export.
- **Profesora:** export del martes (ensayo + feedback) y del jueves (dudas + grabación/transcripción).

---

## Convenciones

- Estructura sugerida: `app.py`, `pages/`, `ielts/` (core: `calendar.py`, `curriculum.py`, `llm/`, `modules/`, `srs.py`, `scoring.py`, `db.py`), `scripts/`, `data/`, `tests/`.
- Prompts del LLM en archivos (`ielts/llm/prompts/*.md`), no inline.
- Tests con pytest para: cálculo de semana/fase, conversión de bandas (incluido redondeo del overall: .25 → .5, .75 → siguiente entero), SM-2, normalización de respuestas, validación de JSON.
- Commits pequeños por hito.
