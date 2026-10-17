"""Registro append-only y resumen de corridas del orquestador."""
import argparse
import fcntl
import json
import os
from pathlib import Path

CAMPOS_USO = ("entrada", "salida", "razonamiento", "cache_lectura", "cache_escritura")


def _uso_para_registro(valor):
    if not isinstance(valor, dict):
        valor = {}
    return {
        "disponible": valor.get("disponible") if isinstance(valor.get("disponible"), bool) else None,
        "completo": valor.get("completo") if isinstance(valor.get("completo"), bool) else None,
        **{
            campo: valor.get(campo) if isinstance(valor.get(campo), int) and not isinstance(valor.get(campo), bool)
            else None
            for campo in CAMPOS_USO
        },
    }


def registro_desde_estado(estado: dict) -> dict:
    """Crea un registro compacto; no incluye prompts, diffs ni contenido de archivos."""
    mutacion = estado.get("mutacion") if isinstance(estado.get("mutacion"), dict) else {}
    revision = estado.get("revision") if isinstance(estado.get("revision"), dict) else {}
    return {
        "timestamp": estado.get("fin_utc"),
        "proyecto": estado.get("proyecto"),
        "id": estado.get("id"),
        "ronda": estado.get("ronda"),
        "agente": estado.get("agente"),
        "motor": estado.get("motor", "opencode"),
        "resultado": estado.get("resultado", "desconocido"),
        "duracion_s": estado.get("duracion_s") if isinstance(estado.get("duracion_s"), (int, float)) else None,
        "uso": _uso_para_registro(estado.get("uso")),
        "uso_revision": _uso_para_registro(estado.get("uso_revision")),
        "puntaje_mutacion": mutacion.get("puntaje"),
        "hallazgos_altos": revision.get("altas") if isinstance(revision.get("altas"), int) else None,
        "integracion_previa": (
            estado.get("integracion_previa", {}).get("estado")
            if isinstance(estado.get("integracion_previa"), dict) else None
        ),
        "presupuesto_tokens": estado.get("presupuesto_tokens"),
        "tokens_entrada_observados": estado.get("tokens_entrada_observados"),
        "tokens_entrada_parcial": estado.get("tokens_entrada_parcial"),
        "presupuesto_agotado": estado.get("presupuesto_agotado"),
        "presupuesto_no_verificable": estado.get("presupuesto_no_verificable"),
        "estado_json": estado.get("estado_json"),
    }


def registrar_estado(estado: dict, ruta: str | Path) -> dict:
    """Anexa una línea JSON bajo bloqueo exclusivo y fuerza su persistencia en disco."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    registro = registro_desde_estado(estado)
    linea = json.dumps(registro, ensure_ascii=False, separators=(",", ":")) + "\n"
    with ruta.open("a", encoding="utf-8") as archivo:
        fcntl.flock(archivo.fileno(), fcntl.LOCK_EX)
        try:
            archivo.write(linea)
            archivo.flush()
            os.fsync(archivo.fileno())
        finally:
            fcntl.flock(archivo.fileno(), fcntl.LOCK_UN)
    return registro


def leer_historial(ruta: str | Path) -> tuple[list[dict], int]:
    """Lee registros válidos; devuelve por separado cuántas líneas se descartaron."""
    registros = []
    invalidas = 0
    try:
        archivo = Path(ruta).open("r", encoding="utf-8")
    except FileNotFoundError:
        return registros, invalidas
    with archivo:
        for linea in archivo:
            if not linea.strip():
                continue
            try:
                valor = json.loads(linea)
            except json.JSONDecodeError:
                invalidas += 1
                continue
            if not isinstance(valor, dict):
                invalidas += 1
                continue
            registros.append(valor)
    return registros, invalidas


def agrupar(registros: list[dict], por: str = "agente") -> list[dict]:
    """Agrupa corridas sin tratar campos ausentes como cero."""
    if por not in ("agente", "resultado", "proyecto"):
        raise ValueError("por debe ser agente, resultado o proyecto")
    grupos = {}
    for registro in registros:
        clave = registro.get(por) or "desconocido"
        grupo = grupos.setdefault(clave, {
            por: clave, "corridas": 0, "pasa": 0, "duracion_s": 0, "corridas_con_duracion": 0,
            "uso": {campo: {"total": 0, "corridas_con_dato": 0} for campo in CAMPOS_USO},
        })
        grupo["corridas"] += 1
        if registro.get("resultado") == "pasa":
            grupo["pasa"] += 1
        duracion = registro.get("duracion_s")
        if isinstance(duracion, (int, float)) and not isinstance(duracion, bool):
            grupo["duracion_s"] += duracion
            grupo["corridas_con_duracion"] += 1
        uso = registro.get("uso") if isinstance(registro.get("uso"), dict) else {}
        for campo in CAMPOS_USO:
            valor = uso.get(campo)
            if isinstance(valor, int) and not isinstance(valor, bool) and valor >= 0:
                grupo["uso"][campo]["total"] += valor
                grupo["uso"][campo]["corridas_con_dato"] += 1

    salida = []
    for grupo in grupos.values():
        for campo, agregado in grupo["uso"].items():
            if agregado["corridas_con_dato"] == 0:
                agregado["total"] = None
            agregado["completo"] = agregado["corridas_con_dato"] == grupo["corridas"]
        salida.append(grupo)
    return sorted(salida, key=lambda g: str(g[por]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archivo", type=Path, default=Path(__file__).resolve().parent / "runs" / "historial.jsonl")
    parser.add_argument("--por", choices=("agente", "resultado", "proyecto"), default="agente")
    parser.add_argument("--json", action="store_true", help="imprime el resumen como JSON")
    args = parser.parse_args()

    registros, invalidas = leer_historial(args.archivo)
    resumen = agrupar(registros, args.por)
    if args.json:
        print(json.dumps({"registros": len(registros), "lineas_invalidas": invalidas, "grupos": resumen},
                         indent=2, ensure_ascii=False))
        return 0
    if not registros:
        print(f"No hay registros en {args.archivo}")
        return 0
    print(f"Corridas: {len(registros)} · líneas inválidas ignoradas: {invalidas} · agrupado por {args.por}")
    for grupo in resumen:
        def formato_uso(campo):
            agregado = grupo["uso"][campo]
            if agregado["total"] is None:
                return f"{campo}=desconocido"
            return f"{campo}={agregado['total']} ({agregado['corridas_con_dato']}/{grupo['corridas']} corridas con dato)"
        tokens_txt = f"{formato_uso('entrada')}, {formato_uso('salida')}"
        print(f"{grupo[args.por]}: {grupo['corridas']} corridas, {grupo['pasa']} pasa, "
              f"duración={grupo['duracion_s']}s ({grupo['corridas_con_duracion']} conocidas), {tokens_txt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
