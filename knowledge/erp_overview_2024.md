---
title: Panorama del ERP 2024
year: 2024
region: GLOBAL
doc_type: overview
confidential: false
---

# Panorama del ERP - Módulos y flujos

El ERP corporativo (SQL Server 2019) contiene los siguientes módulos relevantes
para el agente:

- **Ventas (`sales.orders`)**: cabecera de órdenes con `order_id`, `customer_id`,
  `region`, `amount_net`, `tax_declared`, `currency`, `issued_at`, `status`.
- **Impuestos (`tax.declarations`)**: detalle por línea con tasa aplicada.
- **Auditoría (`audit.flags`)**: banderas TAX_REVIEW, PRICE_REVIEW, FRAUD_REVIEW.

## Flujo de validación fiscal

1. Se obtiene la orden con `get_erp_data(order_id)`.
2. Se calcula la discrepancia con `calculate_tax_discrepancy(amount, region, tax_declared)`.
3. Si `is_discrepant=True`, el analista debe crear un ticket en el módulo de auditoría.

## SLA

- Consulta puntual: < 500 ms.
- Batch nocturno: 22:00 - 06:00 UTC.
