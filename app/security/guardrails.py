"""Capa de validación de prompts (defensa contra prompt injection y RBAC).

Se ejecuta antes de invocar al agente. Realiza dos comprobaciones:

1. **Prompt injection**: detecta patrones típicos de intentos de override del
   system prompt (ej. "ignore previous instructions", "reveal your prompt",
   "actúa como si no tuvieras restricciones", etc.).

2. **RBAC sobre datos restringidos**: detecta consultas que pidan salarios,
   nómina, datos de RRHH u otras entidades marcadas como restringidas cuando el
   rol del usuario no es `admin`. Estas quedan **bloqueadas** aunque el LLM
   quisiera responder.

El resultado se devuelve como un `GuardResult(allowed, reason, category)` para
que la API pueda decidir si:
  - bloquea la petición y devuelve un mensaje fijo (recomendado); o
  - deja pasar la petición pero adjunta la sospecha al system prompt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


GuardCategory = Literal["ok", "prompt_injection", "restricted_data", "off_topic"]


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    category: GuardCategory
    reason: str


_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"disregard\s+(the\s+)?(above|previous|prior)\s+(instructions|prompt|rules)",
        r"forget\s+(all\s+)?(previous|prior)\s+(instructions|context)",
        r"olvid[ae]\s+(las\s+)?instrucciones\s+(anteriores|previas)",
        r"ignora\s+(las\s+)?instrucciones\s+(anteriores|previas|del\s+sistema)",
        r"reveal\s+(your|the)\s+(system\s+)?prompt",
        r"muestra(\s+me)?\s+(tu|el)\s+(prompt|system\s+prompt|instrucciones)",
        r"act\s+as\s+(if\s+)?you\s+(have\s+)?no\s+restrictions",
        r"jailbreak|DAN\s+mode|developer\s+mode",
        r"you\s+are\s+now\s+(a|an)\s+.*(unfiltered|uncensored|without\s+rules)",
        r"bypass\s+(the\s+)?(safety|security|filter|guardrail)",
        r"pretend\s+(to\s+be|you\s+are)\s+.*(no\s+restrictions|admin|root)",
    )
)

_RESTRICTED_KEYWORDS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(rf"\b{p}\b", re.IGNORECASE)
    for p in (
        r"salari[oa]s?",
        r"n[oó]mina",
        r"payroll",
        r"salary",
        r"salaries",
        r"sueldo(s)?",
        r"remuneraci[oó]n(es)?",
        r"compensaci[oó]n\s+laboral",
        r"tabla\s+salarial",
        r"HR\s+data",
        r"datos\s+de\s+RR\.?HH\.?",
        r"nivel\s+ejecutivo\s+de\s+compensaci[oó]n",
    )
)


def check_prompt(message: str, user_role: str) -> GuardResult:
    """Valida el mensaje de entrada.

    Reglas:
    - Cualquier patrón de prompt injection => bloqueado.
    - Cualquier keyword de datos restringidos con rol != admin => bloqueado.
    """
    text = (message or "").strip()
    if not text:
        return GuardResult(False, "off_topic", "El mensaje está vacío.")

    for pat in _INJECTION_PATTERNS:
        if pat.search(text):
            return GuardResult(
                allowed=False,
                category="prompt_injection",
                reason=(
                    "Se detectó un intento de prompt injection. La petición fue "
                    "bloqueada antes de llegar al modelo."
                ),
            )

    if user_role != "admin":
        for pat in _RESTRICTED_KEYWORDS:
            if pat.search(text):
                return GuardResult(
                    allowed=False,
                    category="restricted_data",
                    reason=(
                        "Tu rol no permite consultar datos de nómina/salarios ni "
                        "información restringida de RR.HH."
                    ),
                )

    return GuardResult(True, "ok", "OK")


def output_contains_restricted(response_text: str, user_role: str) -> bool:
    """Segunda barrera: revisa la salida del LLM antes de enviarla al usuario.

    Aunque el input haya pasado, el modelo podría intentar filtrar datos
    restringidos leídos del contexto RAG. Si detectamos keywords sensibles
    y el rol no es admin, marcamos la respuesta como bloqueada.
    """
    if user_role == "admin":
        return False
    for pat in _RESTRICTED_KEYWORDS:
        if pat.search(response_text or ""):
            return True
    return False
