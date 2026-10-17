# Propuestas de implementación

Ideas rescatadas de proyectos similares, convertidas en cambios concretos para este orquestador. Solo ideas: no se copia código ni se instala nada de terceros (varios no tienen licencia, uno es GPL-3.0, y los skills/agentes importados corren con `bash` permitido en modo desatendido).

Estado al 2026-10-17: el último CI run #370 aprobó 158 tests en los incrementos de inmutables, integración, ledger/uso, schema v1, cadena test-first y presupuesto. Se agregó además un backend optativo para Codex CLI sin prompts, con sandbox workspace-write; su aceptación en el equipo anfitrión sigue pendiente.

## Fuentes revisadas

Se leyeron tres archivos por la API de GitHub (solo lectura):

| Archivo | Qué contiene | Qué nos sirve |
|---|---|---|
| `dirigent-skills/skills/verify-done/SKILL.md` (MIT) | Prompt de 1,8 KB: "no declares terminado sin evidencia fresca" | Nada nuevo. Nuestro oráculo ejecutable ya es la versión mecánica. Su señal de alarma "el test pasó a la primera, ¿prueba algo?" es justo lo que mide la mutación |
| `director-cli/director/cost.py` | Ledger JSONL append-only: rol, modelo, tokens, costo, nodo, timestamp; agrupa por rol y modelo | El patrón del registro de uso (propuesta 1) |
| `singular-lite/schemas/state-packet.v0.schema.json` (GPL-3.0) | Paquete de estado por tarea: refs git, archivos propios y cambiados, comandos con código de salida y log, tests por fase, evidencias, bloqueos, próxima acción | Los campos que le faltan a nuestro `estado.json` (propuesta 2). Se reimplementa con nombres propios, sin copiar el archivo |

## Resumen y orden sugerido

| # | Propuesta | Esfuerzo | Impacto | Depende de |
|---|---|---|---|---|
| 0 | `verificar.sh`: chequeo de mantenimiento en un comando | Muy bajo | Alto | nada |
| 1 | Historial y registro de uso (tokens, duración, veredicto) | Bajo | Alto | nada |
| 2 | `estado.json` v1 con `siguiente_accion` y evidencias | Bajo | Alto | 1 |
| 3 | Archivos `inmutables` en el encargo | Muy bajo | Alto | nada |
| 4 | Validador de encargos (`--validar`) | Bajo | Medio | nada |
| 5 | Encadenar encargos (`depende_de`) y ciclo tests → implementar | Medio | Alto | 3 |
| 6 | Presupuesto de tokens con corte en vivo | Medio | Alto | 1 |
| 7 | Vista previa de integración (¿choca con main?) | Muy bajo | Medio | nada |
| 8 | Cola nocturna con systemd | Medio | Medio | 1, 6 |
| 9 | Cooldown de modelos en LiteLLM | Bajo | Medio | verificar primero |

Lo que **no** conviene: daemon con manifiestos YAML y SQLite (contra "simplicidad técnica intencionada"; el repo de referencia está archivado), ejecución nocturna en GitHub Actions (el CI de repos privados está bloqueado por facturación y el código saldría a máquinas de terceros), un agente que mergee (el merge es decisión humana), gateways de modelos de terceros (tus prompts pasarían por intermediarios) e importar colecciones de skills o agentes (cadena de suministro).

---

## 0. `verificar.sh`: el mantenimiento como script, no como skill

**Problema.** Sin CI, nadie corre los tests salvo que se acuerde. Los bugs de esta etapa (`strip()` que comía una letra, stdout vacío de `herdr pane run`) pasaron los tests y aparecieron con trabajo real.

**Implementación.** Un `verificar.sh` en la raíz que corre, en orden y cortando en el primer fallo:
1. `python3 -m unittest discover -s tests` (unos 5 s).
2. Un `--dry-run` del encargo de ejemplo contra un repo temporal (comprueba worktree, enlaces y mensaje, sin gastar cuota).
3. Chequeos de entorno: `opencode` en el PATH, agentes instalados iguales a los del repo (`diff agents/ ~/.config/opencode/agents/`), proxy LiteLLM respondiendo.
4. Opcional `--vivo`: un encargo mínimo real contra un sandbox (cuesta cuota; se corre antes de cambios grandes).

Un hook `pre-push` opcional ejecuta solo el paso 1.

**Aceptación.** Un cambio que rompa el mensaje a OpenCode, o un agente desactualizado, hace fallar `verificar.sh` sin tocar cuota.

## 1. Historial y registro de uso

**Origen.** `cost.py`: ledger append-only que sobrevive entre corridas.

**Dato verificado.** El stream `--format json` de OpenCode trae tokens por paso (`step-finish.tokens`). Una corrida real: 18 pasos, 155.214 tokens de entrada y 2.986 de salida. La entrada crece a cada paso porque se reenvía el contexto: es el costo que importa.

**Implementación inicial en `docs/roadmap-hardening` (CI run #370: 158 tests aprobados).**
- `uso.py` implementa `resumir_stream(lineas)` y `resumir_archivo(ruta)`, suma tokens por evento `step-finish` y no convierte campos/archivos ausentes en cero.
- El despachador añade resúmenes del stream de OpenCode y del revisor al estado cuando están disponibles.
- `historial.py` mantiene `runs/historial.jsonl` append-only con bloqueo exclusivo y `fsync`; registra resultado, duración, tokens conocidos, puntaje de mutación, hallazgos altos y referencia al estado, sin guardar prompts ni diffs.
- `historial.py --por agente|resultado|proyecto` agrupa registros y muestra cuántas corridas aportan datos para cada métrica.
- `verificar.sh` incluye los módulos y la ayuda CLI en la comprobación básica.

**Aceptación.** CI verde con fixtures sintéticas; después, una cola real de tres encargos debe cuadrar con sus `estado.json`. Campos ausentes se mantienen como desconocidos.

**Pendiente de verificar.** Si los eventos indican qué modelo respondió. Si no, el nombre real lo sabe LiteLLM (ver propuesta 9).

## 2. estado.json v1

**Origen.** El state packet: referencias Git, archivos propios y cambiados, comandos con código de salida y log, tests por fase, evidencias y próxima acción.

**Qué existe.** schema_version = 1, timestamps con zona horaria, siguiente_accion, referencia al propio estado.json, snapshots de HEAD/base, veredicto, alcance, mutación, revisión, vista previa de integración y uso disponible. El ledger también registra un resumen compacto de cada invocación.

**Qué sigue faltando.** No se registran todavía todos los comandos/tests como eventos estructurados con sus logs y referencias de evidencia normalizadas. Tampoco se ha validado una corrida real de OpenCode con el estado producido.

**Implementación actual.** schemas/estado.v1.schema.json describe los campos principales de Git, resultados, uso, mutación, revisión e integración. validar_estado_v1 valida el estado contra las propiedades declaradas: tipos, const, enum, rangos, longitud, patrones, fechas con zona horaria, campos requeridos y arrays/objetos anidados. Rechaza booleanos en campos enteros. Se permiten propiedades adicionales por compatibilidad. Es un validador del subconjunto utilizado por el esquema, no un motor JSON Schema completo.

**Validación.** GitHub Actions run #298 aprobó 141 tests, incluidos casos de restricciones anidadas, tipos y compatibilidad hacia delante.

**Aceptación pendiente.** Cubrir retornos tempranos y cada veredicto con estados persistidos; validar un estado.json producido por una corrida real; decidir si la complejidad justifica adoptar una implementación completa de JSON Schema.


## 3. Archivos `inmutables`

**Problema.** "No aflojar asserts" y "no tocar los tests" hoy son una instrucción en el prompt, que un modelo gratuito puede ignorar.

**Implementación.** Un campo opcional `inmutables = ["tests/**"]` en el encargo. El despachador compara rutas modificadas contra la base y bloquea con `viola_inmutables`; se usa `git diff --no-renames` para detectar ambos extremos de un movimiento. Los patrones se validan como rutas relativas sin traversal. Implementado y cubierto en CI run #264: tests sintéticos verifican modificación por patrones, borrado, renombre, traversal y bloqueo del veredicto. Pendiente probar el ciclo completo con un worker real.

**Aceptación.** Un `implementador` que modifica un test existente queda rechazado sin leer el diff.

## 4. Validador de encargos

**Problema.** Los tres primeros intentos de la práctica fallaron por errores del encargo (ruta fuera del worktree, `.venv` inexistente), no del modelo.

**Implementación inicial en la rama de hardening.** `python3 despachar.py ENCARGO.md --validar` comprueba manualmente y la CLI aplica el mismo preflight automáticamente antes de despachar/revisar. Comprueba:
- Tipos y presencia de campos, lista de patrones permitidos relativos sin traversal, lista de comandos de oráculo no vacía, detección de rutas absolutas externas al repo en el cuerpo y ejecutable inicial cuando puede inferirse. Los comandos complejos de shell generan advertencia.
- Rutas de mutación relativas, umbral de mutación entre 0 y 1 y máximo positivo de mutantes.
- Existencia del repositorio Git, resolución de la referencia base y agente instalado en `~/.config/opencode/agents/`.
- Límite total de 30.000 caracteres.
- No crea worktrees, no ejecuta comandos del oráculo y no lanza OpenCode. Si `exige_baseline_verde = true`, informa que la comprobación ocurre durante el despacho.

**Pendiente para completar P4.** Probar encargos históricos representativos y validar con la instalación real; el preflight no puede demostrar la ejecutabilidad de cada etapa dentro de un pipeline o expansión compleja de shell.

**Aceptación.** Cada error de la práctica tiene un test que el validador atrapa; ningún encargo inválido lanza OpenCode.

## 5. Encadenar encargos y ciclo tests → implementar

**Origen.** El planner/ejecutor de director-cli: tests de aceptación primero, luego implementación.

**Idea.** El tester escribe tests que fallan por la razón esperada; esos tests son el oráculo del implementador, que no puede modificarlos.

**Implementación inicial en docs/roadmap-hardening (CI run #370: 158 tests aprobados).**
- Campo depende_de = ["001"]: cola.py valida que la dependencia esté en el lote y en el mismo proyecto/repositorio, rechaza ciclos y limita cada tarea a una sola rama predecesora. Espera a que el predecesor esté aprobado y crea una copia temporal del encargo B con base apuntando a la rama A; no modifica el archivo original.
- El encargo B puede declarar inmutables = ["tests/**"] y permitidos = ["src/**"].
- En A, espera_rojo = true exige agente tester, alcance de tests y espera_rojo_contiene con marcadores literales. El oráculo antes debe pasar; el oráculo después debe fallar y contener todos los marcadores. Si cumple, el resultado intermedio es tests_preparados. Si los tests pasan o el fallo no tiene la evidencia declarada, la etapa no se acepta.
- cola.py reconoce tests_preparados como resultado intermedio y continúa con la tarea dependiente.

**Aceptación pendiente.** Ejemplo real en sandbox: tester crea tests de una función nueva, implementador los satisface, el oráculo final pasa y los tests permanecen inmutables. Dependencias múltiples todavía no están soportadas.


## 6. Presupuesto de tokens con corte en vivo

**Hueco real.** El timeout por duración no limita el consumo de tokens; una tarea puede agotar la cuota antes de llegar al timeout.

**Implementación inicial en docs/roadmap-hardening (CI run #370: 158 tests aprobados).**
- Campo opcional presupuesto_tokens, entero positivo, mide tokens de entrada.
- Cuando está configurado, el despachador lee stdout JSONL en vivo, persiste cada línea y suma input en eventos step-finish.
- Al alcanzar el límite, termina el grupo de procesos, conserva el stream parcial y emite presupuesto_agotado.
- Si faltan eventos/campos para verificar el consumo, detiene el worker y emite presupuesto_no_verificable; no trata datos ausentes como cero.
- El estado distingue tokens_entrada_observados de tokens_entrada_parcial y guarda el presupuesto configurado. El historial incluye presupuesto y resultado.
- El timeout por duración sigue vigente; si no se configura presupuesto, se conserva el camino de ejecución previo.

**Aceptación pendiente.** El CI run #370 aprobó 158 tests sin ResourceWarning/fugas, incluidos corte sintético, stream incompleto y timeout. Falta verificar que el formato de eventos de la versión instalada de OpenCode/LiteLLM expone los tokens esperados y probar el límite en una corrida real.


## 7. Vista previa de integración

**Origen.** Disciplina de "merge-conflict safety" de `dirigent-skills`, sin el agente que mergea.

**Implementación.** Al terminar con `pasa`, `git merge-tree --write-tree <base_sha_actual> <head_sha_trabajo>` (solo lectura) registra `integracion_previa` con estado `limpia`, `conflictos` o `error`, hashes de entrada y diagnóstico. Si detecta conflictos, `siguiente_accion` pide resolverlos antes de integrar. El merge sigue siendo humano; la vista previa no modifica refs ni worktrees. Implementado y cubierto en CI run #264: tests sintéticos verifican integración limpia, conflicto reproducible y que HEAD/worktree de destino no cambian. Pendiente probar el flujo completo con una entrega real.

## 8. Cola nocturna con systemd

**Tu modelo.** "OpenCode corre desatendido hasta agotar su cuota y Claude revisa después en lote."

**Implementación.** `cola.py --carpeta _encargos/<proyecto>/pendientes --hasta-cuota` mueve cada encargo a `en-curso/` y después a `listos/` o `fallidos/`, y se detiene sola con la regla de corte por fallos de infraestructura que ya existe. Un servicio de usuario con timer (systemd, como pide tu convención) la dispara de noche. Al despertar, Claude lee `historial.jsonl` y `siguiente_accion` de cada encargo y revisa en lote.

**Depende de** 1 y 6, para no gastar la cuota de golpe y saber qué pasó.

## 8. Codex CLI sin prompts interactivos

**Problema.** Los workers Codex pueden detenerse repetidamente esperando aprobación para leer/editar archivos dentro de su worktree. Las aprobaciones manuales vuelven al humano un operador de cada llamada.

**Implementación inicial en docs/roadmap-hardening.** La configuración optativa motor = "codex" ejecuta:

codex exec --approve-for-me --json -

El despachador pasa las instrucciones del rol local por stdin, aplica timeout y captura JSONL/stderr. Configura sandbox_workspace_write.writable_roots=[] y network_access=false. Codex realiza su propia revisión automática de solicitudes dentro de workspace-write; no es Claude quien aprueba cada solicitud. Si una operación queda fuera del sandbox, debe fallar cerrada. El backend predeterminado sigue siendo OpenCode.

**Límites explícitos.**
- Esta política solo aplica a las corridas de Codex lanzadas por el despachador; no controla una sesión abierta manualmente en Codex Desktop/IDE.
- No convierte a Claude en aprobador directo de cada solicitud: el no-prompt se resuelve mediante la revisión automática de Codex y el sandbox. Un futuro mecanismo de excepciones realmente dirigido por Claude tendría que usar una API de autorización explícita y una política auditable.
- El parser y presupuesto de tokens de OpenCode no se aplican a Codex; la combinación se rechaza en preflight hasta validar el stream de uso de Codex.
- No se ha confirmado en el equipo anfitrión que las operaciones Git necesarias para un worktree funcionen bajo la sandbox de Codex.

**Aceptación pendiente.** Con Codex CLI instalado, ejecutar una tarea de prueba en worktree, confirmar que puede editar y ejecutar tests sin prompts, verificar que no escribe fuera del worktree y comprobar que una operación bloqueada no provoca un prompt ni deja procesos huérfanos.


## 9. Cooldown de modelos fallidos

**Problema.** Un modelo gratuito que da timeouts o respuestas vacías sigue entrando en la cadena.

**Antes de agregar un gateway nuevo, verificar si LiteLLM ya lo resuelve.** Suele traer configuración de reintentos, fallos permitidos y enfriamiento por modelo (`router_settings`); hay que confirmar los nombres exactos en la versión instalada y probarlo con un modelo caído a propósito. Si alcanza, es solo configuración y no suma ninguna dependencia ni intermediario.

---

## ¿Hace falta una flota de skills para mantener esto funcionando?

**No.** Lo que mantiene el proyecto en pie son el código y los tests (158 aprobados en CI run #370), y las instrucciones de cada trabajador (`agents/*.md`). Los bugs reales de esta etapa los encontraron el oráculo y el uso real, no la falta de un skill.

Un skill es un documento que el modelo carga en su contexto. Cada uno que se suma cuesta contexto y es otro texto que puede ser ambiguo, quedar desactualizado o (si viene de terceros) llevar instrucciones ajenas con acceso a una shell.

Lo mínimo útil:

| Pieza | Para qué | Dónde |
|---|---|---|
| `director-opencode` | El ciclo del director (ya existe) | Claude |
| `delegacion-opencode` | Reglas de obediencia del trabajador (ya existe) | OpenCode |
| `verificar.sh` (propuesta 0) | Mantenimiento: comprobar que todo sigue andando | Script |
| `agents/*.md` | Una definición por rol | OpenCode |

Regla práctica: si algo se puede comprobar con un comando que devuelve éxito o error, va en un script con tests, no en un skill. Un skill se justifica solo para criterio humano (cuándo delegar, cómo escribir el feedback), y eso ya lo cubre `director-opencode`.
