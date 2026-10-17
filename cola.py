#!/usr/bin/env python3
"""Cola de encargos con paralelismo limitado (2-3) para no agotar la cuota gratuita compartida.

Dos encargos del mismo repo que podrían tocar los mismos archivos (o que comparten tema/worktree)
nunca corren a la vez: "una sola cabeza por archivo". Si hay fallos de infraestructura seguidos
(cuota, proxy caído) la cola deja de lanzar y lo informa.

Uso: cola.py ENCARGO.md [ENCARGO.md ...] [--max 2]
"""
import argparse
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import despachar

logger = logging.getLogger("cola")

MAX_PERMITIDO = 3
FALLOS_DE_INFRAESTRUCTURA = {"timeout", "timeout_despachador", "error_opencode", "error_despachador", "error_cola", "presupuesto_no_verificable", "error_codex"}


def _prefijo(patron: str) -> str:
    """Parte fija del patrón antes del primer comodín."""
    return patron.split("*", 1)[0]


def se_pisan(a: dict, b: dict) -> bool:
    """True si dos encargos no deben correr a la vez (misma cabeza sobre los mismos archivos)."""
    try:
        repo_a = str(Path(a["repo"]).expanduser().resolve())
        repo_b = str(Path(b["repo"]).expanduser().resolve())
    except (OSError, RuntimeError):
        # Ante rutas no resolubles, serializar es más seguro que asumir independencia.
        repo_a, repo_b = a["repo"], b["repo"]
    if repo_a != repo_b:
        return False
    if a["tema"] == b["tema"]:
        return True
    return any(_prefijo(x).startswith(_prefijo(y)) or _prefijo(y).startswith(_prefijo(x))
               for x in a["permitidos"] for y in b["permitidos"])


def _clave(enc: dict) -> tuple[str, str]:
    return enc["cfg"]["proyecto"], enc["cfg"]["id"]


def planificar(encargos: list[dict], runner, max_paralelo: int = 2, corte_fallos: int = 2) -> list[dict]:
    """Ejecuta encargos respetando conflictos y dependencias de una sola rama predecesora."""
    max_paralelo = max(1, min(max_paralelo, MAX_PERMITIDO))
    pendientes, corriendo, resultados = list(encargos), {}, []
    completados = {}
    seguidos, detenida = 0, False
    with ThreadPoolExecutor(max_workers=max_paralelo) as ex:
        while pendientes or corriendo:
            if not detenida:
                for enc in list(pendientes):
                    if len(corriendo) >= max_paralelo:
                        break
                    depende_de = enc["cfg"].get("depende_de", [])
                    base_dependencia = None
                    if depende_de:
                        clave_dep = (enc["cfg"]["proyecto"], depende_de[0])
                        if clave_dep not in completados:
                            continue
                        estado_dep = completados[clave_dep]
                        aprobado = (
                            estado_dep.get("resultado") in ("pasa", "tests_preparados")
                            and estado_dep.get("aprobacion", "no_requerida") in ("no_requerida", "aprobado")
                        )
                        if not aprobado:
                            estado = {"id": enc["cfg"]["id"], "proyecto": enc["cfg"]["proyecto"],
                                      "resultado": "dependencia_fallida",
                                      "motivo": f"la dependencia {depende_de[0]} no fue aprobada"}
                            pendientes.remove(enc)
                            resultados.append(estado)
                            completados[_clave(enc)] = estado
                            continue
                        base_dependencia = estado_dep.get("rama")
                        if not base_dependencia:
                            estado = {"id": enc["cfg"]["id"], "proyecto": enc["cfg"]["proyecto"],
                                      "resultado": "dependencia_sin_rama",
                                      "motivo": f"la dependencia {depende_de[0]} no informó una rama de trabajo"}
                            pendientes.remove(enc)
                            resultados.append(estado)
                            completados[_clave(enc)] = estado
                            continue
                    if any(se_pisan(enc["cfg"], c["cfg"]) for c in corriendo.values()):
                        continue
                    pendientes.remove(enc)
                    enc_ejecucion = dict(enc)
                    if base_dependencia:
                        enc_ejecucion["base_dependencia"] = base_dependencia
                    corriendo[ex.submit(runner, enc_ejecucion)] = enc
            elif pendientes:
                for enc in pendientes:
                    estado = {"id": enc["cfg"]["id"], "proyecto": enc["cfg"]["proyecto"],
                              "resultado": "no_lanzado",
                              "motivo": f"cola detenida tras {seguidos} fallos de infraestructura seguidos"}
                    resultados.append(estado)
                    completados[_clave(enc)] = estado
                pendientes.clear()

            if not corriendo:
                if pendientes:
                    for enc in pendientes:
                        estado = {"id": enc["cfg"]["id"], "proyecto": enc["cfg"]["proyecto"],
                                  "resultado": "dependencia_no_resuelta",
                                  "motivo": "no se pudo resolver la dependencia; revisar IDs, ciclo o resultado previo"}
                        resultados.append(estado)
                        completados[_clave(enc)] = estado
                    pendientes.clear()
                break

            hechos, _ = wait(corriendo, return_when=FIRST_COMPLETED)
            for f in hechos:
                enc = corriendo.pop(f)
                try:
                    estado = f.result()
                except Exception as e:
                    logger.error("falló el runner de %s: %s", enc["ruta"], e, exc_info=True)
                    estado = {"id": enc["cfg"]["id"], "proyecto": enc["cfg"]["proyecto"],
                              "resultado": "error_cola", "error": str(e)}
                estado.setdefault("id", enc["cfg"]["id"])
                estado.setdefault("proyecto", enc["cfg"]["proyecto"])
                estado.setdefault("depende_de", enc["cfg"].get("depende_de", []))
                resultados.append(estado)
                completados[_clave(enc)] = estado
                seguidos = seguidos + 1 if estado.get("resultado") in FALLOS_DE_INFRAESTRUCTURA else 0
                detenida = detenida or seguidos >= corte_fallos
    return resultados

def todos_aprobados(resultados: list[dict]) -> bool:
    """Solo cierra con éxito si cada etapa pasa o es un tests_preparados consumido."""
    dependencias_consumidas = set()
    for resultado in resultados:
        deps = resultado.get("depende_de", [])
        if isinstance(deps, list):
            dependencias_consumidas.update((resultado.get("proyecto"), dep) for dep in deps)

    for resultado in resultados:
        estado = resultado.get("resultado")
        aprobado = resultado.get("aprobacion", "no_requerida") in ("no_requerida", "aprobado")
        if estado == "pasa" and aprobado:
            continue
        if (estado == "tests_preparados" and aprobado
                and (resultado.get("proyecto"), resultado.get("id")) in dependencias_consumidas):
            continue
        return False
    return True

def comunicar_con_timeout(proc, timeout_s: int, gracia_s: float = 5) -> tuple[str, str, bool]:
    """Espera un proceso y, al vencer, termina su grupo completo; devuelve stdout, stderr y timeout."""
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
        return stdout, stderr, False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = proc.communicate(timeout=gracia_s)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate()
        return stdout, stderr, True


def _texto_con_base(texto: str, base: str) -> str:
    """Cambia solo la referencia base del bloque TOML sin modificar el encargo original."""
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    coincidencia = re.match(r"\A(\s*\+\+\+\n)(.*?)\n\+\+\+(.*)\Z", texto, re.S)
    if not coincidencia:
        raise ValueError("no se puede aplicar la dependencia: falta el bloque de configuración +++")
    apertura, configuracion, resto = coincidencia.groups()
    linea_base = re.compile(r"(?m)^\s*base\s*=.*$")
    nueva_base = f"base = {json.dumps(base)}"
    if linea_base.search(configuracion):
        configuracion = linea_base.sub(nueva_base, configuracion, count=1)
    else:
        configuracion = configuracion.rstrip() + "\n" + nueva_base
    return apertura + configuracion + "\n+++" + resto


def runner_subproceso(enc: dict) -> dict:
    """Corre despachar.py con timeout exterior; una dependencia usa un encargo temporal con base heredada."""
    ruta_encargo = Path(enc["ruta"])
    temporal = None
    if enc.get("base_dependencia"):
        despachar.RUNS.mkdir(parents=True, exist_ok=True)
        carpeta_temporal = despachar.RUNS / ".cola-encargos"
        carpeta_temporal.mkdir(parents=True, exist_ok=True)
        temporal = carpeta_temporal / (
            f"{enc['cfg']['proyecto']}-{enc['cfg']['id']}-{time.time_ns()}.md"
        )
        temporal.write_text(
            _texto_con_base(ruta_encargo.read_text(encoding="utf-8"), enc["base_dependencia"]),
            encoding="utf-8",
        )
        ruta_encargo = temporal
    try:
        cmd = [sys.executable, "-B", str(Path(despachar.__file__)), str(ruta_encargo)]
        timeout_s = enc["cfg"].get("timeout_cola_min", enc["cfg"].get("timeout_min", 20) + 30) * 60
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                start_new_session=True)
        stdout, stderr, agotado = comunicar_con_timeout(proc, timeout_s)
        if agotado:
            return {"id": enc["cfg"]["id"], "proyecto": enc["cfg"]["proyecto"],
                    "resultado": "timeout_despachador", "timeout_s": timeout_s,
                    "error": "el despachador excedió el timeout exterior",
                    "diagnostico": (stderr or stdout or "")[-400:]}
        try:
            estado = json.loads(stdout)
        except json.JSONDecodeError:
            return {"id": enc["cfg"]["id"], "proyecto": enc["cfg"]["proyecto"],
                    "resultado": "error_despachador", "codigo_salida": proc.returncode,
                    "error": (stderr or stdout or "salida vacía")[-400:]}
        if proc.returncode != 0:
            estado.setdefault("codigo_salida_despachador", proc.returncode)
        return estado
    finally:
        if temporal is not None:
            temporal.unlink(missing_ok=True)

def cargar(rutas: list[Path]) -> list[dict]:
    encargos, vistos = [], set()
    for ruta in rutas:
        cfg = despachar.parsear_encargo(ruta.read_text(encoding="utf-8"))
        clave = (cfg["proyecto"], cfg["id"])
        if clave in vistos:
            raise ValueError(f"encargo duplicado: {clave}")
        if len(cfg.get("depende_de", [])) > 1:
            raise ValueError("por ahora cada encargo puede depender de una sola rama predecesora")
        vistos.add(clave)
        encargos.append({"ruta": ruta.resolve(), "cfg": cfg})

    por_clave = {_clave(enc): enc for enc in encargos}
    for enc in encargos:
        for dep_id in enc["cfg"].get("depende_de", []):
            dep = por_clave.get((enc["cfg"]["proyecto"], dep_id))
            if dep is None:
                raise ValueError(
                    f"la dependencia {dep_id!r} de {enc['cfg']['id']!r} no está en esta cola/proyecto"
                )
            repo_dep = Path(dep["cfg"]["repo"]).expanduser().resolve()
            repo_enc = Path(enc["cfg"]["repo"]).expanduser().resolve()
            if repo_dep != repo_enc:
                raise ValueError("una dependencia debe usar el mismo repositorio que su encargo dependiente")

    visitados, en_pila = set(), set()
    def visitar(clave):
        if clave in en_pila:
            raise ValueError(f"ciclo de dependencias detectado en {clave}")
        if clave in visitados:
            return
        en_pila.add(clave)
        enc = por_clave[clave]
        for dep_id in enc["cfg"].get("depende_de", []):
            visitar((enc["cfg"]["proyecto"], dep_id))
        en_pila.remove(clave)
        visitados.add(clave)
    for clave in por_clave:
        visitar(clave)
    return encargos


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("encargos", nargs="+", type=Path)
    ap.add_argument("--visor", action="store_true", help="un panel por corrida en Herdr (si corre dentro de Herdr)")
    ap.add_argument("--max", type=int, default=2, help=f"trabajadores en paralelo (1-{MAX_PERMITIDO})")
    args = ap.parse_args()
    if not 1 <= args.max <= MAX_PERMITIDO:
        ap.error(f"--max debe estar entre 1 y {MAX_PERMITIDO}")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    if args.visor:
        os.environ["ORQUESTADOR_VISOR"] = "1"
    t0 = time.time()
    try:
        resultados = planificar(cargar(args.encargos), runner_subproceso, args.max)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"resultado": "cola_invalida", "error": str(exc)}, ensure_ascii=False))
        return 1
    resumen = {
        "duracion_s": round(time.time() - t0),
        "max_paralelo": args.max,
        "resultados": [
            {"proyecto": r.get("proyecto"), "id": r.get("id"), "resultado": r.get("resultado"),
             "aprobacion": r.get("aprobacion"), "rama": r.get("rama"), "commits": r.get("commits")}
            | ({k: r[k] for k in ("revision", "mutacion", "errores", "error", "motivo", "diagnostico",
                                   "timeout_s", "codigo_salida", "codigo_salida_despachador")
                if k in r})
            for r in resultados
        ],
    }
    despachar.RUNS.mkdir(exist_ok=True)
    (despachar.RUNS / f"cola-{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1_000_000_000:09d}.json").write_text(
        json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(resumen, indent=2, ensure_ascii=False))
    return 0 if todos_aprobados(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
