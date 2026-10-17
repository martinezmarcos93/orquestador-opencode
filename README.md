# Orquestador OpenCode — Claude dirige, los trabajadores obedecen

Sistema de orquestación en el que Claude Code actúa como **director** y modelos gratuitos de OpenCode como **trabajadores**. Claude escribe un encargo acotado, el despachador lo ejecuta en un worktree de trabajo (no es un sandbox de seguridad por sí mismo), verifica el resultado con un oráculo y Claude revisa y decide: integrar, dar una orden nueva con feedback o tomarlo él.

> **Principio fundamental:** Claude no controla terminales, coordina trabajo. La comunicación es por archivos y el veredicto sale de un oráculo ejecutable, no del "listo" de quien trabajó.

---

## Instalación rápida

**Requisitos:** Python 3.11+, `git`, [`opencode`](https://opencode.ai) con un proveedor configurado (en este caso un proxy LiteLLM local con fallback entre modelos gratuitos) y Claude Code.

```bash
git clone https://github.com/martinezmarcos93/orquestador-opencode.git
cd orquestador-opencode
./instalar.sh          # copia los agentes a ~/.config/opencode/agents y la skill a ~/.claude/skills
bash verificar.sh       # compilación, ayuda CLI y suite unitaria; no llama modelos ni requiere red
bash verificar.sh --installed  # además detecta agentes/skill instalados ausentes o desactualizados
python3 -m unittest discover -s tests
python3 despachar.py ENCARGO.md --validar  # valida sin crear worktree ni ejecutar el oráculo/modelo
```

No tiene dependencias externas: solo la librería estándar.

---

## Cómo usar

### Flujo básico

1. **Elegí** un proyecto de bajo calibre (git, en disco ext4) y una tarea chica con oráculo verificable.
2. **Redactá** el encargo en `_encargos/<proyecto>/NNN-tema.md`, empezando por el bloque de configuración:

   ```toml
   +++
   id = "001"
   proyecto = "mercado-sandbox"
   repo = "/home/usuario/src/mercado-sandbox"
   agente = "tester"
   tema = "tests-nucleo"
   base = "main"
   permitidos = ["tests/**"]
   oraculo = [".venv/bin/python -m pytest -q"]
   timeout_min = 20
   # Opcional: Codex CLI con revisión automática de permisos y sandbox workspace-write
   # motor = "codex"
   # Opcional: presupuesto máximo de tokens de entrada, vigilado durante la ejecución
   # presupuesto_tokens = 400000
   # Solo si el oráculo necesita usar el entorno del repo original (reduce aislamiento):
   # permitir_entornos_compartidos = true
   revisor = true                 # opcional: revisión de solo lectura tras un "pasa"
   exige_baseline_verde = false   # true para higiene: sin baseline verde no se lanza nada

   [mutacion]                     # opcional: prueba de mutación (Python)
   archivos = ["market_analyzer.py"]
   funciones = ["calcular_signal"]  # opcional: limita las funciones a mutar
   umbral = 0.8
   +++
   ```

   En un encargo de `implementador` que deba preservar los tests, agregá `inmutables = ["tests/**"]` y mantené el código de producción dentro de `permitidos`; el patrón protegido bloquea cualquier cambio en esas rutas, incluso archivos nuevos.

   Para una cadena test-first, el encargo `tester` usa `espera_rojo = true` y `espera_rojo_contiene = ["nombre_del_test", "AssertionError"]`, con `permitidos = ["tests/**"]`. El implementador declara `depende_de = ["001"]`, `inmutables = ["tests/**"]` y `permitidos = ["src/**"]`. Pasá ambos encargos a `cola.py` en el mismo lote. Por ahora cada encargo admite una sola dependencia y el tester debe tener baseline verde antes de añadir los tests.

3. **Despachá** (desde Claude, con `run_in_background`; se reactiva solo al terminar):

   ```bash
   python3 despachar.py ENCARGO.md                  # un encargo
   python3 cola.py E1.md E2.md E3.md --max 2        # varios en paralelo (máx. 3), sin pisarse
   python3 despachar.py ENCARGO.md --validar        # valida configuración, repo, base, agentes y oráculo
   python3 despachar.py ENCARGO.md --dry-run        # prepara el worktree sin lanzar oráculo/modelo
   python3 despachar.py ENCARGO.md --reevaluar      # repite oráculo, alcance, mutación y revisor sin lanzar OpenCode
   python3 despachar.py ENCARGO.md --revisar-solo   # solo el revisor, sobre el worktree existente
   python3 despachar.py ENCARGO.md --visor          # un panel por corrida en Herdr (si corrés dentro de Herdr)
   python3 historial.py --por agente              # resume resultados y tokens conocidos desde el ledger
   ```

La CLI valida automáticamente repo, referencia base, tipos de configuración y agentes instalados antes de despachar o revisar. `--validar` no crea worktree ni ejecuta oráculos o modelos. Los oráculos tienen un timeout por comando y, al agotarse, se termina su grupo de procesos. Un worktree reutilizado con cambios sin commitear se bloquea para evitar mezclar trabajo anterior.
Cada corrida añade un registro compacto a `runs/historial.jsonl`. El uso se extrae de eventos `step-finish` presentes en JSONL; si faltan datos, se muestran como desconocidos y no como cero. El ledger no guarda prompts ni diffs.
El backend predeterminado es OpenCode. Con `motor = "codex"`, el despachador ejecuta `codex exec --approve-for-me --json -`, con `sandbox_workspace_write.writable_roots=[]` y `network_access=false`: Codex aplica su revisión automática de solicitudes dentro de `workspace-write` y no abre prompts interactivos al usuario. Esto no delega cada aprobación a Claude; Claude revisa la entrega final, y las operaciones fuera del sandbox deben fallar cerradas. No controla sesiones abiertas manualmente en Codex Desktop/IDE. `presupuesto_tokens` aún no es compatible con el stream JSONL de Codex y se rechaza en preflight.
   ```

4. **Leé el veredicto** en `runs/<proyecto>-<id>/ronda-N/estado.json`, revisá el diff y decidí. Si el resultado es `pasa`, la vista previa `integracion_previa` informa si la combinación con la base actual parece limpia o tiene conflictos; es solo lectura y no hace merge.

### Veredictos

| `resultado` | Qué significa | Qué hace el director |
|---|---|---|
| `pasa` | Oráculo verde, dentro de alcance (y mutación sobre el umbral, si se pidió) | Revisa el diff y propone integrar (el merge es humano) |
| `tests_debiles` | Oráculo verde, pero la prueba de mutación quedó bajo el umbral | Nueva ronda: pasarle los mutantes sobrevivientes |
| `error_mutacion` / `mutacion_sin_candidatos` | La evaluación de mutación falló o no encontró sitios para mutar | Corregir la evaluación/configuración; no se aprueba por puntaje ausente |
| `baseline_rojo` | El encargo exige baseline verde y no lo hay | Arreglar el baseline antes de delegar |
| `falla_oraculo` | Los tests no pasan | Nueva ronda con feedback concreto |
| `sin_cambios` / `trabajo_sin_commitear` | No hizo nada, o dejó cambios sueltos | Nueva ronda o los commitea |
| `fuera_de_alcance` | Tocó archivos no permitidos | Descarta o devuelve sin leer el diff |
| `viola_inmutables` | Modificó, borró o renombró una ruta protegida | Rechaza la entrega; omite oráculo/mutación para evitar efectos secundarios |
| `tests_preparados` | Tester añadió tests que fallan con los marcadores esperados | Resultado intermedio: ejecutar el implementador dependiente |
| `tests_no_fallan` / `tests_rojos_sin_evidencia` | Los tests no fallan o el fallo no coincide con la evidencia declarada | Corregir el encargo tester antes de implementar |
| `dependencia_fallida` / `dependencia_no_resuelta` | Un predecesor no fue aprobado o no se pudo resolver | No lanzar el dependiente; revisar la cadena |
| `dependencia_nueva` / `posible_secreto` | Cambió dependencias o metió algo sensible | Descarta |
| `presupuesto_agotado` | Alcanzó `presupuesto_tokens` | Conserva la entrega parcial y evalúa si corresponde ampliar el límite |
| `presupuesto_no_verificable` | El stream no permite medir tokens de entrada | Se detiene por seguridad; verifica el formato JSONL y la versión de OpenCode |
| `error_codex` | Codex CLI falló o una operación fue bloqueada por workspace-write | Revisar `opencode.err`; no se habilitan permisos más amplios automáticamente |
| `timeout` / `error_opencode` | Cuota, proxy o modelo colgado | Revisa `opencode.err` |
| `worktree_reutilizado_sucio` | El worktree conserva cambios sin commitear de una corrida anterior | Preserva o limpia explícitamente esos cambios antes de reintentar |
| `tope_rondas` | Ya hubo 2 rondas del mismo encargo | Lo toma Claude |

---

## Arquitectura

```
Claude (director)                       despachar.py                      OpenCode (trabajador)
 │ escribe _encargos/<proy>/NNN.md ───▶ │ git worktree + rama opencode/…
 │                                      │ entornos compartidos solo con opt-in
 │                                      │ opencode run --agent <trabajador> ─▶ trabaja y commitea
 │                                      │ ◀──────── REPORTE.md + commits ─────┘
 │                                      │ oráculo antes/después · alcance · deps · secretos
 │ ◀──────────── estado.json ───────────┘
 ├─ pasa ────────▶ revisa diff, prueba de mutación, propone integrar
 ├─ ajustes ─────▶ nuevo encargo con feedback (máx. 2 rondas)
 └─ tope ────────▶ lo termina Claude
```

### Trabajadores

Cada trabajador es un agente de OpenCode (`agents/*.md`) con su propio prompt y permisos de edición:

| Agente | Función | Puede editar |
|---|---|---|
| `tester` | Escribe solo tests | `tests/**`, `REPORTE.md`, `docs/opencode/**` |
| `implementador` | Una tarea acotada de código | Archivos permitidos del encargo |
| `higiene` | Limpieza sin cambiar comportamiento (imports, código muerto, logging); exige baseline verde | Archivos permitidos del encargo |
| `revisor` | Revisa el diff de la rama y reporta hallazgos `[ALTA/MEDIA/BAJA]` con evidencia | Nada (solo lectura; el despachador verifica que no tocó el worktree) |

---

## Estructura del repositorio

```
orquestador-opencode/
├── README.md
├── despachar.py                 # despachador: un encargo → un veredicto
├── cola.py                      # varios encargos en paralelo (2-3), sin pisarse
├── mutacion.py                  # prueba de mutación para Python (AST, sin dependencias)
├── uso.py                       # suma tokens reportados por eventos JSONL de OpenCode
├── historial.py                 # ledger append-only y resumen por agente/resultado/proyecto
├── visor.py / ver.py            # panel opcional en Herdr y su formateador en vivo
├── instalar.sh                  # instala agentes y skill
├── agents/                      # trabajadores de OpenCode
├── skills/director-opencode/    # skill de Claude: el ciclo del director
├── tests/                       # unittest del despachador
├── schemas/estado.v1.schema.json # contrato mínimo versionado de estado.json
└── runs/                        # logs y estado.json por corrida (ignorado por git)
```

---

## Lecciones de la primera práctica

Probado el 2026-10-13 con un sandbox de análisis de mercado y el agente `tester`:

1. **OpenCode desatendido rechaza leer fuera del worktree** y se detiene en silencio (`external_directory ... auto-rejecting`). Por eso el encargo va incrustado en el mensaje y la ruta del repo original se reescribe.
2. **Un worktree no trae `.venv` ni `node_modules`** (están en `.gitignore`): por defecto no se enlazan, para no exponer al trabajador un entorno modificable compartido con el repo original. El opt-in `permitir_entornos_compartidos = true` restaura los symlinks y debe usarse solo cuando el riesgo esté aceptado.
3. **`git status` colapsa carpetas nuevas** a `docs/`: se usa `-uall` para no dar falsos positivos de alcance.
4. **No fiarse del "listo" ni de los "bugs encontrados".** El modelo gratuito afirmó asserts que contradecían su propia aritmética y los llamó bugs del código.
5. **Prueba de mutación como compuerta de calidad:** tests verdes no bastan. Dos bordes de RSI sobrevivieron a la mutación hasta que el director los corrigió.

---

6. **Los tests del propio orquestador necesitan casos de regresión reales.** Dos bugs míos pasaron los tests y aparecieron con trabajo real: `git()` hacía `strip()` y `' M archivo'` perdía la primera letra (`arket_analyzer.py` → falso `fuera_de_alcance`), y `herdr pane run` responde rc 0 con stdout vacío, lo que reventaba el parser del visor.
7. **El revisor se calibró, no se asumió:** sobre una rama con defectos sembrados (cambio silencioso de producción, secreto, test sin asserts, assert contradictorio) detectó 4 de 4 con evidencia y 0 falsos positivos; sobre la rama buena respondió APTO. Omitió un import sin usar (baja).
8. **Paralelismo real:** dos trabajadores a la vez tardaron 258 s en vez de ~440 s en serie. El candado por proyecto evita que dos `git worktree add` choquen, y el planificador serializa encargos que podrían tocar los mismos archivos.
9. **Un trabajador contaminó la suite** reemplazando `sys.modules["rich"]` por un `MagicMock` a nivel de módulo; el oráculo (la suite completa) lo detectó y la ronda 2, con feedback concreto, lo corrigió.
10. **Límite de la mutación:** con pocas funciones el universo es chico (4 mutantes en `guardar_reporte`) y el puntaje es grueso; sirve para encontrar bordes concretos, no como porcentaje de calidad.

---

## Qué sigue

El plan por fases, con criterio de aceptación para cada ítem, está en [`ROADMAP.md`](ROADMAP.md). El diseño y el origen de cada idea (rescatadas de proyectos similares) están en [`docs/propuestas.md`](docs/propuestas.md).

---

## Calibre y límites

Solo se delega trabajo de bajo calibre: sin secretos, sin dinero ni datos de terceros. Los modelos gratuitos pueden usar los prompts para entrenar. El trabajador nunca hace push a `main` ni merge, y el despachador verifica que `main` quedó intacto.
