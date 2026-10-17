#!/usr/bin/env bash
# Verificación local sin llamadas a modelos ni acceso de red.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

modo="basic"
case "${1:-}" in
  "") ;;
  --installed) modo="installed" ;;
  --tools) modo="tools" ;;
  -h|--help)
    printf 'Uso: bash verificar.sh [--installed|--tools]\n'
    printf '  (sin opción)  sintaxis Python/shell, ayuda CLI y suite unitaria; sin red ni modelos\n'
    printf '  --installed  además compara agentes/skill instalados con el repositorio\n'
    printf '  --tools      además comprueba que git y opencode estén disponibles en PATH\n'
    exit 0
    ;;
  *) printf 'Opción desconocida: %s\n' "$1" >&2; exit 2 ;;
esac

command -v python3 >/dev/null || { echo "ERROR: falta python3" >&2; exit 1; }
python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit(f"ERROR: se requiere Python >= 3.11; actual: {sys.version.split()[0]}")
print(f"Python {sys.version.split()[0]}: OK")
PY

echo "== Compilación Python =="
python3 -m py_compile despachar.py cola.py mutacion.py uso.py historial.py ver.py visor.py tests/*.py

echo "== Ayuda CLI (no lanza modelos) =="
python3 -B despachar.py --help >/dev/null
python3 -B cola.py --help >/dev/null
python3 -B historial.py --help >/dev/null

echo "== Sintaxis shell =="
for script in instalar.sh verificar.sh; do bash -n "$script"; done

echo "== Suite unitaria =="
python3 -m unittest discover -s tests -v

if [[ "$modo" == "installed" ]]; then
  echo "== Comparación de agentes/skill instalados =="
  for fuente in agents/*.md; do
    destino="$HOME/.config/opencode/agents/${fuente##*/}"
    if [[ ! -f "$destino" ]]; then
      echo "ERROR: falta agente instalado: $destino" >&2
      exit 1
    fi
    if ! cmp -s "$fuente" "$destino"; then
      echo "ERROR: agente desactualizado: $destino (ejecutá bash instalar.sh)" >&2
      exit 1
    fi
  done
  skill="skills/director-opencode/SKILL.md"
  destino="$HOME/.claude/skills/director-opencode/SKILL.md"
  if [[ ! -f "$destino" ]] || ! cmp -s "$skill" "$destino"; then
    echo "ERROR: skill ausente o desactualizada: $destino (ejecutá bash instalar.sh)" >&2
    exit 1
  fi
fi

if [[ "$modo" == "tools" ]]; then
  command -v git >/dev/null || { echo "ERROR: falta git" >&2; exit 1; }
  command -v opencode >/dev/null || { echo "ERROR: falta opencode" >&2; exit 1; }
  echo "git y opencode disponibles. No se llamó al modelo ni se comprobó proveedor/proxy."
fi

echo "Verificación completada."
