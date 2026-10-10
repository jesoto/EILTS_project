# IELTS Trainer

App local (Streamlit) para preparar el IELTS Academic del 29 dic 2026 con un plan de 11 semanas.
La metodología y el calendario están en [CLAUDE.md](CLAUDE.md) y [data/curriculum.yaml](data/curriculum.yaml).

## Requisitos
- [uv](https://docs.astral.sh/uv/) (instala Python 3.12 y las dependencias).
- [Ollama](https://ollama.com) con un modelo para evaluar: `ollama pull gemma3:12b` (el modelo se cambia en [config.toml](config.toml)).
- Carpeta `resources/` con tus libros y audios (se lee en local; está en `.gitignore`).

## Uso
```powershell
uv sync                                  # primera vez
uv run python scripts/ingest.py          # extrae tests de Cambridge 17 a data/derived/ (ignorado por git)
uv run streamlit run app.py              # abre la app
uv run pytest                            # tests
```

1. **Verifica las claves** en la página «Verificar claves» antes de practicar Reading/Listening.
2. Cada día usa su botón en la pantalla de inicio. Los bloques van en secuencia con temporizador.
3. Los domingos haz la auditoría; el martes y el jueves exporta lo que llevas a clase (bloques «Preparar ensayo» y «Dudas»).

## Variables de entorno útiles
| Variable | Efecto |
|---|---|
| `IELTS_TODAY=2026-10-14` | Simula otra fecha (para probar el plan) |
| `IELTS_DB=ruta.db` | Usa otra base de datos |
| `IELTS_DERIVED=carpeta` | Usa otra carpeta de tests ingeridos |
| `IELTS_LLM_MODEL`, `IELTS_OLLAMA_HOST`, `IELTS_STT_MODEL` | Sobrescriben `config.toml` |

## Notas
- Las bandas que muestra la app son **estimaciones aproximadas** de un modelo local: úsalas para ver tendencias.
- Whisper (`small`, CPU) descarga ~500 MB la primera vez que transcribes.
- Los PDFs escaneados (p. ej. Cambridge 16) necesitan OCR y todavía no se ingieren.
