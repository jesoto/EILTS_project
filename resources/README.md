# Carpeta `resources/`: tus libros y audios

Esta carpeta **no se sube a GitHub** (todo su contenido está en `.gitignore`, salvo este archivo).
Cada persona debe poner aquí **sus propias copias** de los materiales. Esta aplicación no incluye ni distribuye ningún libro.

## Qué poner

| Contenido | Dónde | Para qué |
|---|---|---|
| PDF de un libro de tests (p. ej. *Cambridge IELTS 17 Academic*) con **texto seleccionable** | cualquier subcarpeta | Se extraen los tests, las claves y las transcripciones |
| Audios `.mp3` del libro | en la misma carpeta que su PDF (o dentro de una subcarpeta) | Listening, dictado y shadowing |
| Otros libros (vocabulario, gramática…) | donde quieras | Solo de consulta; la app no los lee |

Ejemplo de estructura (los nombres de carpeta pueden ser cualquiera):

```
resources/
  Cambridge IELTS 17/
    cambridge_ielts_17_academic.pdf
    Audios/
      T1 AUDIO 1.mp3
      T1 AUDIO 2.mp3
      ...
```

## Cómo se reconocen los libros
`data/books.yaml` dice qué libros sabe leer la app: el nombre (o patrón) del PDF y cómo se llaman los audios
(`T1 AUDIO 1.mp3` = test 1, parte 1). Si tus archivos tienen otro nombre, edita ese archivo.
Los PDF **escaneados** (sin texto seleccionable) no se pueden leer sin OCR.

## Después de copiar los archivos
```powershell
uv run python scripts/doctor.py          # ¿ve la app tus libros?
uv run python scripts/ingest.py          # extrae los tests a data/derived/ (también ignorado por git)
```
Luego abre la app → **Verificar claves** y compara cada clave con el PDF antes de practicar:
una clave mal leída arruina la evaluación.
