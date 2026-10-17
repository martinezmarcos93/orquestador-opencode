#!/usr/bin/env python3
"""Prueba de mutación mínima para Python (solo librería estándar).

Cambia UNA condición/operador/constante por vez en una copia temporal del worktree y corre el oráculo:
si los tests siguen verdes, el mutante "sobrevivió" y los tests no miran ese detalle.
Los tests verdes no bastan: la mutación mide si de verdad verifican algo.

Uso: mutacion.py DIR --archivo f.py [--funcion nombre ...] --cmd "pytest -q" [--max 80]
"""
import argparse
import ast
import json
import logging
import os
import random
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger("mutacion")

CMP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt,
       ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Is: ast.IsNot, ast.IsNot: ast.Is}
BIN = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult}
BOOL = {ast.And: ast.Or, ast.Or: ast.And}
SIMBOLO = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Eq: "==", ast.NotEq: "!=",
           ast.Is: "is", ast.IsNot: "is not", ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
           ast.And: "and", ast.Or: "or"}


@dataclass
class Sitio:
    indice: int
    linea: int
    tipo: str
    de: str
    a: str


def _es_texto(nodo: ast.AST) -> bool:
    return isinstance(nodo, ast.JoinedStr) or (isinstance(nodo, ast.Constant) and isinstance(nodo.value, str))


class _Mutador(ast.NodeTransformer):
    """Con objetivo=None solo enumera los sitios; con objetivo=n aplica la mutación n-ésima.
    El recorrido es idéntico en ambos modos, así los índices coinciden."""

    def __init__(self, funciones: set[str] | None, objetivo: int | None):
        self.funciones, self.objetivo = funciones, objetivo
        self.pila: list[str] = []
        self.sitios: list[Sitio] = []
        self.aplicado = False

    def _activo(self) -> bool:
        return not self.funciones or any(f in self.funciones for f in self.pila)

    def _sitio(self, nodo: ast.AST, tipo: str, de: str, a: str) -> bool:
        """Registra el sitio y devuelve True si hay que mutarlo ahora."""
        s = Sitio(len(self.sitios), nodo.lineno, tipo, de, a)
        self.sitios.append(s)
        if self.objetivo == s.indice:
            self.aplicado = True
            return True
        return False

    def _funcion(self, nodo):
        self.pila.append(nodo.name)
        self.generic_visit(nodo)
        self.pila.pop()
        return nodo

    visit_FunctionDef = visit_AsyncFunctionDef = _funcion

    def visit_If(self, nodo: ast.If):
        t = nodo.test
        if isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == "__name__":
            return nodo
        return self.generic_visit(nodo)

    def visit_Compare(self, nodo: ast.Compare):
        self.generic_visit(nodo)
        if self._activo():
            for i, op in enumerate(nodo.ops):
                if type(op) in CMP and self._sitio(nodo, "comparacion", SIMBOLO[type(op)], SIMBOLO[CMP[type(op)]]):
                    nodo.ops[i] = CMP[type(op)]()
        return nodo

    def visit_BinOp(self, nodo: ast.BinOp):
        self.generic_visit(nodo)
        if self._activo() and type(nodo.op) in BIN and not (_es_texto(nodo.left) or _es_texto(nodo.right)):
            if self._sitio(nodo, "aritmetica", SIMBOLO[type(nodo.op)], SIMBOLO[BIN[type(nodo.op)]]):
                nodo.op = BIN[type(nodo.op)]()
        return nodo

    def visit_BoolOp(self, nodo: ast.BoolOp):
        self.generic_visit(nodo)
        if self._activo() and self._sitio(nodo, "logica", SIMBOLO[type(nodo.op)], SIMBOLO[BOOL[type(nodo.op)]]):
            nodo.op = BOOL[type(nodo.op)]()
        return nodo

    def visit_UnaryOp(self, nodo: ast.UnaryOp):
        self.generic_visit(nodo)
        if self._activo() and isinstance(nodo.op, ast.Not) and self._sitio(nodo, "negacion", "not x", "x"):
            return nodo.operand
        return nodo

    def visit_Constant(self, nodo: ast.Constant):
        v = nodo.value
        if self._activo() and isinstance(v, (int, float)) and not isinstance(v, bool):
            nuevo = v + 1 if isinstance(v, int) else (v * 1.1 if v else 1.0)
            if self._sitio(nodo, "constante", repr(v), repr(nuevo)):
                return ast.copy_location(ast.Constant(nuevo), nodo)
        return nodo


def sitios(fuente: str, funciones: set[str] | None = None) -> list[Sitio]:
    m = _Mutador(funciones, None)
    m.visit(ast.parse(fuente))
    return m.sitios


def aplicar(fuente: str, indice: int, funciones: set[str] | None = None) -> str:
    arbol = ast.parse(fuente)
    m = _Mutador(funciones, indice)
    arbol = m.visit(arbol)
    if not m.aplicado:
        raise IndexError(f"no existe el sitio {indice}")
    return ast.unparse(ast.fix_missing_locations(arbol))


def _correr(comandos: list[str], cwd: Path, timeout: int | float, gracia_s: float = 2) -> bool:
    """True si TODOS los comandos pasan; al timeout termina el grupo y sus descendientes."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    for cmd in comandos:
        proc = subprocess.Popen(
            cmd, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, start_new_session=True,
        )
        try:
            proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.communicate(timeout=gracia_s)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.communicate()
            return False
        if proc.returncode != 0:
            return False
    return True


def evaluar(wt: Path, archivos: list[str], comandos: list[str], funciones: list[str] | None = None,
            maximo: int = 80, semilla: int = 0, timeout: int = 60) -> dict:
    """Muta una copia de `wt` (el worktree original no se toca) y devuelve el resumen."""
    fset = set(funciones) if funciones else None
    with tempfile.TemporaryDirectory(prefix="mutacion-") as tmp:
        copia = Path(tmp) / "w"
        shutil.copytree(wt, copia, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "runs"))
        if not _correr(comandos, copia, timeout * 3):
            return {"error": "el oráculo no pasa sobre la copia sin mutar", "total": 0}
        originales = {a: (copia / a).read_text(encoding="utf-8") for a in archivos}
        candidatos = [(a, s) for a in archivos for s in sitios(originales[a], fset)]
        universo = len(candidatos)
        if universo > maximo:
            candidatos = sorted(random.Random(semilla).sample(candidatos, maximo), key=lambda c: (c[0], c[1].indice))
        vivos = []
        for archivo, sitio in candidatos:
            try:
                (copia / archivo).write_text(aplicar(originales[archivo], sitio.indice, fset), encoding="utf-8")
                if _correr(comandos, copia, timeout):
                    vivos.append({"archivo": archivo, **{k: v for k, v in asdict(sitio).items() if k != "indice"}})
            finally:
                (copia / archivo).write_text(originales[archivo], encoding="utf-8")
    total = len(candidatos)
    return {"total": total, "universo": universo, "muertos": total - len(vivos),
            "puntaje": round((total - len(vivos)) / total, 3) if total else None, "sobrevivientes": vivos}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dir", type=Path)
    ap.add_argument("--archivo", action="append", required=True)
    ap.add_argument("--funcion", action="append")
    ap.add_argument("--cmd", action="append", required=True)
    ap.add_argument("--max", type=int, default=80)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    print(json.dumps(evaluar(a.dir.resolve(), a.archivo, a.cmd, a.funcion, a.max), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
