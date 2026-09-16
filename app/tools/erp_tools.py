"""Herramientas del agente (function calling).

Ambas herramientas están *mocked* — no acceden a un ERP real ni a una BD
SQL Server, pero exponen contratos y errores realistas para permitir que el
agente las encadene y para probar el manejo de errores end-to-end.

Herramientas:
    - `get_erp_data(order_id)`  : simula consulta a SQL Server / ERP.
    - `calculate_tax_discrepancy(amount, region)` : lógica de negocio en Python.
"""
from __future__ import annotations

import random
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field


_ERP_ORDERS: dict[str, dict[str, Any]] = {
    "ORD-1001": {
        "order_id": "ORD-1001",
        "customer": "Acme Corp",
        "region": "CL",              
        "amount_net": 1_000_000.0,   
        "tax_declared": 190_000.0,   
        "currency": "CLP",
        "issued_at": "2024-05-14",
        "status": "posted",
    },
    "ORD-1002": {
        "order_id": "ORD-1002",
        "customer": "Globex",
        "region": "US-CA",           
        "amount_net": 8_500.0,
        "tax_declared": 500.0,       
        "currency": "USD",
        "issued_at": "2024-08-02",
        "status": "posted",
    },
    "ORD-1003": {
        "order_id": "ORD-1003",
        "customer": "Initech",
        "region": "EU-ES",           
        "amount_net": 2_400.0,
        "tax_declared": 504.0,       
        "currency": "EUR",
        "issued_at": "2024-11-28",
        "status": "posted",
    },
    "ORD-9999": {
        "order_id": "ORD-9999",
        "__corrupt__": True,
    },
}

_TAX_RATES: dict[str, float] = {
    "CL": 19.0,
    "US-CA": 7.25,
    "EU-ES": 21.0,
    "EU-DE": 19.0,
    "MX": 16.0,
}


class ERPUnavailableError(RuntimeError):
    """Se lanza cuando la 'BD ERP' no responde o devuelve datos corruptos."""


class GetERPDataInput(BaseModel):
    order_id: str = Field(..., description="ID de la orden en el ERP, ej. 'ORD-1001'.")


class CalcTaxInput(BaseModel):
    amount: float = Field(..., gt=0, description="Monto neto (base imponible) de la orden.")
    region: str = Field(
        ...,
        description="Código de región/país: CL, US-CA, EU-ES, EU-DE, MX.",
    )
    tax_declared: float | None = Field(
        default=None,
        description=(
            "Impuesto declarado en el ERP. Si se pasa, la herramienta calcula "
            "la discrepancia contra el impuesto esperado."
        ),
    )


@tool("get_erp_data", args_schema=GetERPDataInput, return_direct=False)
def get_erp_data(order_id: str) -> dict[str, Any]:
    """Consulta datos de una orden en el ERP (mock de SQL Server).

    Devuelve un diccionario con: order_id, customer, region, amount_net,
    tax_declared, currency, issued_at, status. Lanza ERPUnavailableError si
    la orden no existe o el registro está corrupto.
    """

    if random.random() < 0.01:
        raise ERPUnavailableError("Timeout consultando ERP.orders (SQL Server).")

    row = _ERP_ORDERS.get(order_id)
    if row is None:
        raise ERPUnavailableError(f"Orden {order_id!r} no encontrada en el ERP.")
    if row.get("__corrupt__"):
        raise ERPUnavailableError(f"Registro {order_id!r} corrupto en el ERP.")
    return dict(row)


@tool("calculate_tax_discrepancy", args_schema=CalcTaxInput, return_direct=False)
def calculate_tax_discrepancy(
    amount: float,
    region: str,
    tax_declared: float | None = None,
) -> dict[str, Any]:
    """Calcula la discrepancia fiscal entre el impuesto esperado y el declarado.

    Recibe el monto neto, la región y opcionalmente el impuesto declarado.
    Devuelve tasa oficial, impuesto esperado, discrepancia absoluta y
    porcentual, más un flag `is_discrepant` (True si |Δ| > 1% del esperado).
    """
    region_key = region.strip().upper()
    rate = _TAX_RATES.get(region_key)
    if rate is None:
        return {
            "region": region_key,
            "error": f"Región {region_key!r} no soportada. Válidas: {sorted(_TAX_RATES)}",
        }

    expected_tax = round(amount * rate / 100.0, 2)
    result: dict[str, Any] = {
        "region": region_key,
        "rate_pct": rate,
        "amount_net": amount,
        "expected_tax": expected_tax,
    }
    if tax_declared is not None:
        diff = round(tax_declared - expected_tax, 2)
        pct = round((diff / expected_tax) * 100.0, 2) if expected_tax else 0.0
        result.update(
            {
                "tax_declared": tax_declared,
                "discrepancy_abs": diff,
                "discrepancy_pct": pct,
                "is_discrepant": abs(pct) > 1.0,
            }
        )
    return result


ALL_TOOLS = [get_erp_data, calculate_tax_discrepancy]
