"""Extracción conservadora de uso desde eventos JSONL de OpenCode.

No estima tokens ni inventa valores: los campos ausentes se conservan como None y
el resumen marca si el stream está incompleto.
"""
import json
from pathlib import Path
from typing import Iterable

CAMPOS = ("entrada", "salida", "razonamiento", "cache_lectura", "cache_escritura")


def _numero(valor):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    if valor < 0 or int(valor) != valor:
        return None
    return int(valor)


def _tokens_del_evento(evento: dict):
    parte = evento.get("part")
    if not isinstance(parte, dict):
        parte = {}
    tokens = parte.get("tokens")
    if not isinstance(tokens, dict):
        tokens = evento.get("tokens")
    return parte, tokens if isinstance(tokens, dict) else None


def _normalizar_tokens(tokens: dict) -> dict:
    cache = tokens.get("cache")
    if not isinstance(cache, dict):
        cache = {}
    return {
        "entrada": _numero(tokens.get("input", tokens.get("input_tokens"))),
        "salida": _numero(tokens.get("output", tokens.get("output_tokens"))),
        "razonamiento": _numero(tokens.get("reasoning", tokens.get("reasoning_tokens"))),
        "cache_lectura": _numero(cache.get("read", tokens.get("cache_read"))),
        "cache_escritura": _numero(cache.get("write", tokens.get("cache_write"))),
    }


def resumir_stream(lineas: Iterable[str]) -> dict:
    """Resume eventos step-finish; ignora otros eventos y cuenta líneas JSON inválidas."""
    pasos = 0
    eventos_con_tokens = 0
    lineas_invalidas = 0
    totales = {campo: 0 for campo in CAMPOS}
    vistos = {campo: 0 for campo in CAMPOS}
    razon_final = None

    for linea in lineas:
        if not linea.strip():
            continue
        try:
            evento = json.loads(linea)
        except (json.JSONDecodeError, TypeError):
            lineas_invalidas += 1
            continue
        if not isinstance(evento, dict):
            continue
        parte, tokens = _tokens_del_evento(evento)
        tipo = evento.get("type", parte.get("type"))
        if tipo != "step-finish" and parte.get("type") != "step-finish":
            continue
        pasos += 1
        razon = parte.get("reason", evento.get("reason"))
        if isinstance(razon, str) and razon:
            razon_final = razon
        if tokens is None:
            continue
        eventos_con_tokens += 1
        for campo, valor in _normalizar_tokens(tokens).items():
            if valor is not None:
                totales[campo] += valor
                vistos[campo] += 1

    disponible = eventos_con_tokens > 0
    resumen = {
        "disponible": disponible,
        "completo": bool(pasos) and eventos_con_tokens == pasos and all(
            vistos[campo] == eventos_con_tokens for campo in CAMPOS
        ),
        "pasos": pasos,
        "eventos_con_tokens": eventos_con_tokens,
        "lineas_invalidas": lineas_invalidas,
        "razon_final": razon_final,
    }
    for campo in CAMPOS:
        # Un total parcial se omite para no presentarlo como el consumo completo.
        resumen[campo] = (
            totales[campo]
            if eventos_con_tokens > 0 and vistos[campo] == eventos_con_tokens
            else None
        )
    if not disponible:
        resumen["motivo"] = "sin_eventos_step_finish_con_tokens"
    return resumen


def resumir_archivo(ruta: str | Path) -> dict:
    """Resume un archivo JSONL; archivo ausente o sin uso reportable no equivale a cero tokens."""
    ruta = Path(ruta)
    try:
        with ruta.open("r", encoding="utf-8") as archivo:
            return resumir_stream(archivo)
    except FileNotFoundError:
        return {
            "disponible": False,
            "completo": False,
            "pasos": 0,
            "eventos_con_tokens": 0,
            "lineas_invalidas": 0,
            "razon_final": None,
            **{campo: None for campo in CAMPOS},
            "motivo": "archivo_ausente",
        }
