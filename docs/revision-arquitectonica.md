# Ampliación del roadmap: robustez, seguridad y medición

Fecha: 2026-10-13. Esta ampliación concilia la lista de `docs/propuestas.md` con la revisión estática de `despachar.py`, `cola.py`, `mutacion.py`, los agentes y el README. Es un plan de trabajo, no evidencia de que las mejoras ya estén implementadas.

## Hallazgos concretos que originan el trabajo

1. **Referencia Git estable.** `despachar()` captura el SHA de la base para una corrida, pero `preparar_worktree()` reutiliza el worktree existente por proyecto/tema y devuelve la rama actual. Hace falta validar esa identidad y registrar la referencia exacta que se usó en cada evaluación.
2. **Worktree no equivale a sandbox de seguridad.** Las instrucciones del agente y la comprobación posterior de alcance no impiden por sí mismas lecturas o efectos fuera del directorio. `enlazar_entornos()` enlaza `.venv` y `node_modules` del repositorio original, que pueden ser mutables o contener acceso indirecto a recursos locales.
3. **Revisión obligatoria no cerrada como compuerta.** Cuando se solicita `revisor = true`, el estado principal se decide antes de la revisión; la salida de revisión se agrega después. Un error o un resultado malformado del revisor no cambia necesariamente `resultado`.
4. **Timeout del proceso exterior.** El trabajador tiene timeout dentro del despachador, pero `cola.runner_subproceso()` espera a `despachar.py` sin timeout propio. Un bloqueo fuera del proceso de OpenCode puede dejar la cola esperando.
5. **Detectores heurísticos.** La detección de secretos mediante regex y la lista de archivos de dependencias son filtros incompletos. Deben tener cobertura de regresión y documentación de límites; no se deben presentar como garantías.
6. **Interpretación de mutación.** La puntuación describe la proporción de mutantes seleccionados que los tests matan. No es una puntuación global de calidad. Deben mostrarse universo total, cantidad seleccionada, sobrevivientes y errores; las mutaciones equivalentes son una limitación conocida.

## S0 — Endurecimiento antes de autonomía

### S0.1 Base y worktree

- Guardar `base_sha`, `head_sha`, rama, ruta del worktree y referencia de destino al inicio y al cierre.
- Rechazar o poner en cuarentena un worktree existente si su rama o metadatos no coinciden con el encargo.
- Comparar alcance y diff contra el SHA fijado; comprobar por separado si la rama base avanzó.
- Antes de integración, calcular conflictos contra la punta actual de la rama destino. No hacer merge automáticamente.

**Pruebas:** base que avanza durante el encargo; worktree con rama inesperada; tema reutilizado con configuración distinta; rama destino que avanza después de la ejecución.

### S0.2 Modelo de amenaza y aislamiento efectivo

- Documentar qué puede leer, escribir y ejecutar cada rol, qué variables de entorno hereda y qué secretos podrían estar disponibles.
- Revisar los enlaces simbólicos a `.venv` y `node_modules`; preferir entornos separados o desechables cuando sea viable. Si se mantienen enlaces, explicitar el riesgo y restringir permisos.
- Investigar controles de sistema operativo disponibles en el entorno real (usuario sin privilegios, sandbox, namespaces o herramientas equivalentes) antes de afirmar que hay aislamiento fuerte.
- Mantener prohibido enviar secretos y datos de terceros a modelos gratuitos.

**Pruebas:** sandbox con archivos centinela fuera del worktree y variables ficticias; demostrar accesos efectivos, no solo evaluar el prompt. No ejecutar pruebas destructivas sobre datos reales.

### S0.3 Estado de revisión como compuerta

- Definir estados distintos para revisión válida, observaciones, error, timeout y salida malformada.
- Si el encargo requiere revisión, impedir que un fallo de revisión se confunda con aprobación. Mantener separado el resultado de tests del estado de aprobación global.
- Validar formato del veredicto y conteo de hallazgos; no confiar solo en que el modelo respetó el prompt.
- Verificar el worktree antes y después de la revisión y registrar cualquier mutación.

**Pruebas:** JSONL vacío, texto sin secciones requeridas, timeout, hallazgo alto, respuesta APTO sin formato válido y cambios inesperados del revisor.

### S0.4 Recuperación de procesos y cola

- Añadir timeout al subproceso despachador en la cola, con terminación controlada y captura de stdout/stderr.
- Registrar estado de inicio, fin y motivo de interrupción; garantizar que una corrida interrumpida pueda identificarse sin duplicar trabajo automáticamente.
- Tratar salida vacía o JSON inválido como error explícito, conservando diagnóstico.
- Revisar que los patrones de `permitidos` se comparen de forma consistente; los prefijos de comodines de `se_pisan()` son una aproximación conservadora, no un analizador general de patrones.

**Pruebas:** runner bloqueado, proceso terminado, stdout vacío, JSON inválido, interrupción entre estados y patrones anidados/solapados.

### S0.5 Alcance, secretos y dependencias

- Cubrir archivos de bloqueo y manifiestos de dependencias de los ecosistemas que realmente se usen.
- Tratar detección de secretos por regex como una capa inicial; agregar casos sintéticos para formatos frecuentes y cambios por renombre/borrado.
- Registrar qué comprobaciones se ejecutaron y cuáles no están disponibles.

**Pruebas:** secretos ficticios en formatos variados, falso positivo, dependencia añadida en manifiesto alternativo y archivo renombrado. No usar credenciales reales.

## S1 — Observabilidad y calidad de medición

### S1.1 Mutación interpretable

- Reportar siempre `universo`, `total` seleccionado, `muertos`, `sobrevivientes` y error de oráculo si corresponde.
- Explicar que el puntaje solo mide el conjunto de mutaciones ensayado; no equipararlo con cobertura ni calidad general.
- Considerar clasificación manual o heurística de mutantes posiblemente equivalentes, sin descontarlos automáticamente sin evidencia.
- Garantizar límites temporales de cada comando de oráculo y restauración del archivo en cada salida.

**Pruebas:** universo vacío, muestreo truncado reproducible, oráculo inicial roto, timeout y restauración después de fallo.

### S1.2 Comparación de agentes/modelos

- Aprovechar `uso.py` e `historial.py` para agrupar por agente, modelo confirmado, clase de tarea, veredicto, rondas, duración, tokens y defectos detectados.
- Marcar modelo desconocido cuando la fuente no lo informe. No inferirlo por nombre del agente o configuración supuesta.
- Mostrar tamaño de muestra y advertir sobre la dificultad desigual de las tareas y otros factores de confusión.

**Criterio:** reporte reproducible con datos faltantes explícitos y sumas consistentes con `estado.json`.

## Orden conciliado

1. S0.1 base/worktree y S0.3 revisión: reducen errores de atribución y aprobaciones ambiguas.
2. P0 `verificar.sh` y P4 validador: hacen repetibles los chequeos antes de consumir cuota.
3. S0.2 aislamiento y S0.5 detectores: antes de cualquier ejecución desatendida o con información sensible.
4. P3 inmutables y P2 estado estructurado: formalizan contratos y evidencias.
5. P1 historial junto con S1.1 medición de mutación.
6. S0.4 timeout/recuperación y P7 vista previa de integración.
7. P5 dependencias, P6 presupuesto de tokens y P9 cooldown de LiteLLM.
8. S1.2 medición comparativa y finalmente P8 cola nocturna con systemd.

Este orden no obliga a implementar varios cambios en un mismo commit: se mantiene un incremento por vez, con pruebas y actualización del roadmap en cada paso.

## Disciplina de evidencia

Cada ítem debe informar cuatro estados por separado: código implementado, tests automatizados ejecutados, prueba en vivo ejecutada y validación pendiente en el equipo local. La inspección remota del código no prueba comportamiento en el PC de Marcos. `main` permanece intacta hasta autorización expresa; durante este ciclo se usa una sola rama temporal y no se fusiona automáticamente.


## Bitácora de implementación

### S0.1 — Base Git y reutilización del worktree

Estado: **implementación parcial; aceptación funcional pendiente**.

Cambios en esta rama:

- La corrida conserva la referencia de destino (`base_ref`) y el SHA exacto capturado al inicio (`base_sha`); los worktrees nuevos se crean desde ese SHA, no desde una segunda resolución de la rama que podría haber avanzado.
- El estado registra el HEAD inicial y final del worktree, el SHA de la rama destino al cierre y si esa referencia se movió durante la corrida.
- El diff y el conteo de commits siguen comparándose con el SHA inicial, no con una resolución posterior de la rama.
- Al reutilizar un worktree, se comprueba que la ruta Git corresponda a la ruta esperada, que la rama tenga el patrón `opencode/*-<tema>` y que pertenezca al mismo repositorio Git común.
- Si la base capturada al inicio no es ancestro del HEAD del worktree, el despachador termina esa corrida con `worktree_base_divergente` sin lanzar OpenCode. No hace rebase ni modifica el worktree automáticamente.
- Se añadieron pruebas para worktree nuevo, avance de la base antes de crearlo y durante el trabajo, comparación contra el SHA inicial y rama inesperada. También se garantiza el registro de snapshots en salidas tempranas.

Validación pendiente:

- GitHub Actions run #60 ejecutó `bash verificar.sh`: 97 tests aprobados. Incluye un `--dry-run` CLI en un repositorio Git temporal, sin ejecutar OpenCode ni el oráculo.
- Los tests CLI validan `estado.json` de `--dry-run`, y una salida temprana `baseline_rojo` valida snapshots sin lanzar OpenCode. Falta inspeccionar un `estado.json` de una corrida real con trabajador ejecutado.

No se ejecutó OpenCode ni se hicieron pruebas en vivo. No se modificó ni se fusionó `main`.

### S0.3 — Compuerta de aprobación de la revisión

Estado: **implementación parcial; aceptación funcional pendiente**.

Cambios en esta rama:

- Se valida que el revisor emita exactamente `APTO` o `CON_OBSERVACIONES`, incluya ambas secciones y respete el formato de hallazgos con evidencia.
- Una salida vacía, formato inválido, timeout, código de salida no cero o modificación del worktree no puede producir aprobación.
- Un veredicto `APTO` con hallazgos ALTA/MEDIA se trata como inconsistente; `CON_OBSERVACIONES` bloquea la aprobación global.
- El estado `resultado` conserva el resultado técnico de tests/oráculo y `aprobacion` registra por separado el resultado de la revisión.
- La CLI y la cola devuelven código no exitoso si una revisión requerida no termina en `aprobado`; la cola incluye `aprobacion` en su resumen.
- Se añadieron pruebas unitarias para formato válido, observaciones, salida malformada, timeout/error y propagación del bloqueo a la cola.

Validación pendiente:

- GitHub Actions run #60 aprobó 97 tests. Las pruebas del proceso de revisión usan OpenCode simulado y cubren timeout, código no cero, salida vacía y mutación del worktree.
- Prueba pendiente con OpenCode real: comprobar el formato que produce la versión instalada y un veredicto con hallazgo ALTA.
- Confirmar que el formato real que produce el agente `revisor` satisface el validador; ajustar el contrato si la evidencia real lo requiere, sin debilitar el gate por conveniencia.

No se ejecutó OpenCode ni se hicieron pruebas en vivo. No se modificó ni se fusionó `main`.

### S0.4 — Timeout exterior de la cola

Estado: **implementación parcial; aceptación aún no demostrada**.

Cambios en esta rama:

- El encargo acepta `timeout_cola_min`, entero que debe superar `timeout_min`; por defecto es `timeout_min + 30` para dejar margen a oráculos y revisión.
- La cola usa `Popen.communicate(timeout=...)` y crea una sesión/grupo de procesos independiente. Ante timeout, envía SIGTERM al grupo y escala a SIGKILL si no termina en cinco segundos.
- El resultado `timeout_despachador` es explícito y cuenta para el corte por fallos consecutivos de infraestructura.
- Si el subproceso termina con código distinto de cero pero imprime JSON válido, la cola conserva el estado y agrega el código de salida; si el JSON es inválido o está vacío, devuelve `error_despachador`.
- Se añadieron tests con un proceso simulado para los caminos SIGTERM y SIGKILL.

Validación pendiente:

- GitHub Actions run #60 aprobó 97 tests, incluidos los tests simulados y un caso Linux real con un descendiente que ignora SIGTERM; la implementación escaló a SIGKILL y el descendiente no escribió su marcador.
- GitHub Actions run #60 ejecutó también el runner real contra un despachador bloqueado en el oráculo: devolvió `timeout_despachador`, no inició OpenCode y la prueba terminó correctamente.
- Pendiente ejecutar `cola.py` completo para comprobar el resumen de cola y la política de corte ante fallos consecutivos en esa misma situación.

No se ejecutaron procesos reales de OpenCode ni pruebas en vivo. No se modificó ni se fusionó `main`.

### S0.5 — Detectores heurísticos de secretos y dependencias

Estado: **implementación parcial; aceptación aún no demostrada**.

Cambios en esta rama:

- El filtro de secretos reconoce asignaciones de claves/tokens con o sin comillas, claves JSON, encabezados de claves privadas y algunos prefijos comunes de proveedores (por ejemplo, GitHub, AWS y Slack).
- La detección de dependencias incluye nombres de manifiestos y lockfiles de varios ecosistemas y patrones `requirements-*` / `constraints-*` en formatos `.txt` y `.in`.
- Se añadieron pruebas sintéticas de detección y de archivos que no deberían clasificarse como dependencias.

Limitaciones y validación pendiente:

- GitHub Actions run #60 aprobó los tests sintéticos de detección; todavía falta revisar falsos positivos/negativos con cambios reales representativos.
- El filtro no sustituye un escáner de secretos dedicado ni cubre todas las convenciones de cada ecosistema; un resultado negativo no demuestra que un cambio esté libre de credenciales.
- La lista de manifiestos es deliberadamente explícita y debe ampliarse con evidencia de los repositorios reales que el orquestador gestione.

No se ejecutó OpenCode ni se hicieron pruebas en vivo. No se modificó ni se fusionó `main`.

## P0 — Verificación local y CI

Estado: **implementación parcial; primera ejecución automatizada completada**.

Cambios en esta rama:

- Se creó `verificar.sh`: modo básico comprueba Python 3.11+, compila los módulos, valida sintaxis shell, invoca las ayudas CLI y ejecuta la suite unitaria. No invoca modelos ni requiere red.
- `--installed` compara los agentes y la skill instalados con sus fuentes del repositorio; `--tools` comprueba disponibilidad de `git` y `opencode` sin llamar al proveedor.
- Se agregó un workflow de GitHub Actions para ejecutar el modo básico en pushes a esta rama y en PR hacia `main`.
- El README documenta los comandos.

Validación completada: GitHub Actions run #60 terminó correctamente; `bash verificar.sh` reportó 97 tests aprobados. La prueba automatizada de CLI `--dry-run` verificó que OpenCode no se invoca.

Pendiente: prueba en vivo de OpenCode y del proveedor LiteLLM, inspección del estado de una corrida con trabajador real, y `--dry-run` en el equipo anfitrión. La verificación de CI no reemplaza esas pruebas de integración.

No se fusionó `main`.

### S0.2 — Reducción de exposición por entornos compartidos

Estado: **mitigación parcial; no equivale a sandbox**.

Cambios en esta rama:

- Los worktrees nuevos ya no reciben enlaces simbólicos a `.venv` o `node_modules` por defecto.
- El encargo debe declarar explícitamente `permitir_entornos_compartidos = true` para restaurar el comportamiento anterior; el estado registra la opción. Se valida el tipo booleano al parsear el encargo.
- Se añadieron pruebas para el comportamiento seguro por defecto y para el opt-in explícito.
- El README aclara que un worktree es un espacio de trabajo Git, no una frontera de seguridad.

Riesgos todavía abiertos:

- El proceso de OpenCode hereda el entorno del despachador y no está confinado a nivel de sistema operativo. El acceso a home, archivos externos, credenciales en configuración y red sigue dependiendo del comportamiento/permisos de OpenCode y del sistema anfitrión.
- No se impuso bubblewrap/container porque los mounts y credenciales requeridos por la instalación real de OpenCode/LiteLLM no se conocen ni se pueden probar desde este entorno. Activar una sandbox supuesta sin validar esas dependencias podría dejar el sistema inutilizable o dar una falsa sensación de aislamiento.

Validación pendiente:

- Ejecutar en la máquina anfitriona un encargo de prueba con permisos controlados y comprobar rutas/variables accesibles.
- Diseñar e integrar sandbox de SO con allowlist explícita de mounts/variables, y probar que el agente no puede leer ni modificar el repo original, el home ni credenciales ajenas al proxy.
- Los tests de opt-in por defecto y symlink explícito pasan en GitHub Actions run #60.

No se afirma aislamiento fuerte.

## Barrido transversal adicional — 2026-10-14

Cambios implementados en la rama de hardening; la CI de esta tanda debe confirmar los tests antes de considerar el incremento verificado.

- OpenCode, el revisor, los comandos de oráculo y la ejecución de oráculos durante mutación se ejecutan con timeout y terminación de grupos/descendientes. Al agotarse el plazo se envía SIGTERM y se escala a SIGKILL si quedan procesos descendientes; el oráculo principal deja evidencia en `oraculo.log`. Esto reduce el riesgo de dejar procesos huérfanos tanto desde CLI directa como desde cola.
- El preflight comprueba el ejecutable inicial de cada comando cuando puede determinarse con seguridad; si el comando usa builtins o sintaxis compleja de shell, deja una advertencia explícita en lugar de afirmar que lo verificó.
- Se normalizan finales de línea CRLF al leer el encargo.
- Si se reutiliza un worktree con archivos sin commitear, se devuelve `worktree_reutilizado_sucio` y no se ejecuta el oráculo ni OpenCode sobre ese estado ambiguo.
- La cola compara rutas de repositorio normalizadas para evitar paralelismo accidental entre dos rutas que apuntan al mismo repo; errores del runner cuentan como fallos de infraestructura. `--max` queda limitado explícitamente a 1–3, el resumen retiene diagnósticos y el nombre de archivo incorpora fracción de segundo para reducir colisiones.
- `estado.json` incorpora versión, timestamps UTC y `siguiente_accion`. Se añadió un esquema JSON y un validador del contrato mínimo con biblioteca estándar.
- La compuerta de mutación ya bloquea resultados cuando la evaluación falla o no encuentra candidatos; las excepciones se registran en `mutacion.json` y no se interpreta un puntaje ausente como aprobación.

Límites que permanecen abiertos:

- No se implementó un sandbox de SO ni se demostró aislamiento fuerte.
- Los timeouts del oráculo no prueban el comportamiento de OpenCode/LiteLLM real ni sustituyen la inspección de JSONL y estado de una corrida auténtica.
- La verificación de comandos de shell es necesariamente parcial; el usuario debe tratar los comandos del encargo como código ejecutable de confianza.
- La validación actual del estado cubre el contrato mínimo y no reemplaza una implementación completa de JSON Schema.
- No se ejecutó la integración real en el equipo anfitrión. La aceptación de esos puntos queda para Claude/Marcos.
