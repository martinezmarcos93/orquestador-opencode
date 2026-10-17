---
name: director-opencode
description: Claude como DIRECTOR de trabajadores OpenCode. Redactar encargos con bloque de configuración, lanzar el despachador en segundo plano, leer el veredicto y decidir (integrar, dar una orden nueva o tomarlo). Usar cuando Marcos pida delegar, orquestar, "que opencode haga X", "mandá a los trabajadores" o revisar lo que devolvió OpenCode. Complementa a delegacion-opencode.
---

# Director de OpenCode

Vos dirigís; los trabajadores obedecen. **Nunca controlás una terminal en vivo**: te comunicás por archivos.
Reglas de calibre y de obediencia: `delegacion-opencode` y `_metodologias/claude-code/calibre-y-delegacion.md` (A y B-sensible no se delegan).

## Trabajadores (agentes de OpenCode, `~/.config/opencode/agents/`)
- `tester`: solo escribe tests; no puede editar fuera de `tests/`/`test/`.
- `implementador`: una tarea acotada dentro de los archivos permitidos del encargo.
- `higiene`: limpieza sin cambiar comportamiento; usá `exige_baseline_verde = true` y una base con tests verdes.
- `revisor`: solo lectura. Se activa con `revisor = true` en el encargo; deja `revision.md` con severidad individual (`[ALTA]`, `[MEDIA]` o `[BAJA]`) y evidencia. Tomalo como una señal para investigar, no como veredicto: verificá cada hallazgo ALTA en el diff.

## Ciclo
1. **Elegí** proyecto (nivel C o D), trabajador y una tarea chica (los modelos gratuitos se pierden con contexto largo). Si no es git en ext4, se prepara primero un sandbox.
2. **Redactá** `_encargos/<proyecto>/NNN-tema.md` (vault de proyectos) con la plantilla `plantilla-encargo.md`, empezando por el bloque de configuración:
   ```
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
   +++
   ```
   El oráculo corre dentro del worktree, antes y después. Por defecto, el despachador **no** enlaza `.venv` ni `node_modules` del repositorio original; `permitir_entornos_compartidos = true` habilita esos enlaces de forma explícita y reduce el aislamiento. Usá rutas **relativas**. Si el encargo menciona la ruta del repo original, el despachador la reescribe por la del worktree cuando corresponde. **Un worktree no es un sandbox de seguridad**: no garantiza por sí solo que el proceso no pueda leer archivos externos, heredar variables sensibles o acceder a la red. No delegues secretos ni datos de terceros a modelos gratuitos; las tareas sensibles requieren controles de sistema operativo verificados.
3. **Lanzá** en segundo plano: `python3 ~/src/orquestador-opencode/despachar.py <encargo>` con `run_in_background`. Al terminar te reactivás solo: no hagas polling. `--dry-run` prepara el worktree sin gastar cuota.
4. **Leé en orden de costo:** JSON de `resultado` → `runs/<proyecto>-<id>/ronda-N/estado.json` → `REPORTE.md` → `git diff --stat` → diff completo. No confíes en el "listo": corré el oráculo vos.
5. **Decidí** según `resultado`:
   - `pasa`: revisá el diff y proponele a Marcos integrar. El merge a main es suyo. **Si son tests, hacé prueba de mutación** (ver abajo) antes de dar por buena la calidad.
   - `falla_oraculo`, `sin_cambios`, `trabajo_sin_commitear` (a veces es menor: documentos sueltos; commitealos vos): orden nueva (mismo `id`, misma `tema`, reutiliza el worktree) con el **feedback concreto** en el cuerpo del encargo. Cada `id` admite 2 rondas.
   - `fuera_de_alcance`, `dependencia_nueva`, `posible_secreto`: no leas el diff; descartá la rama o devolvela con la regla violada.
   - `timeout`, `error_opencode`: mirá `opencode.err`; probablemente cuota o proxy (`systemctl --user status litellm-opencode`).
   - `tope_rondas`: lo tomás vos.
6. **Bitácora:** anotá qué se delegó, qué se integró y qué se rechazó, con el motivo.

## Opciones del despachador
- `--validar`: valida el TOML, los tipos, los patrones de alcance, el repo, la referencia base y los agentes requeridos. No crea worktree, no ejecuta el oráculo y no lanza OpenCode; si `exige_baseline_verde = true`, informa que el baseline se comprobará al despachar. La CLI aplica automáticamente el mismo preflight antes de despachar o revisar. Los encargos de `higiene` requieren `exige_baseline_verde = true`.
- Varios encargos: `cola.py E1.md E2.md --max 2` (tope 3). Encargos del mismo repo con `permitidos` que se superponen o el mismo `tema` se serializan solos.
- `--reevaluar`: repite oráculo, alcance, mutación y revisor sobre el trabajo ya hecho, sin lanzar OpenCode ni consumir ronda. Usalo después de commitear a mano algo menor (bitácoras sueltas) o de arreglar un detalle.
- `[mutacion]` en el encargo: `archivos`, `funciones` (opcional), `umbral` (0.8). Bajo el umbral → `tests_debiles` con la lista de sobrevivientes en `estado.json`.
- `--visor` (o `ORQUESTADOR_VISOR=1`): un panel por corrida en una pestaña `orquestador` de Herdr, solo si Claude corre dentro de Herdr. Nunca roba el foco ni toca paneles ajenos; cerrá la pestaña al terminar si no la querés.

## Reglas
- Paralelismo máximo 2-3 trabajadores (comparten cuota gratuita). Un worktree por tema.
- Una tanda = un tema. Las tareas ambiguas las resolvés vos antes de delegar.
- Nada con secretos ni datos de terceros sale a modelos gratuitos.

## Prueba de mutación manual (para encargos de tests)
Copiá el código a un directorio temporal, cambiá una condición o constante (`<` por `<=`, un umbral, un peso, el orden) y corré los tests: tienen que fallar.
Aplicá la mutación en la función correcta (reemplazar "la primera coincidencia" puede caer en otra función). Los que sobreviven revelan bordes que el trabajador "probó" con casos que no distinguen.
No te fíes de los "bugs encontrados" del trabajador: contá vos la regla de negocio y contrastá con el código antes de aceptar un reporte de bug.
