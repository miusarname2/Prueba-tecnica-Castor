---
title: Política de impuestos 2024
year: 2024
region: GLOBAL
doc_type: policy
confidential: false
---

# Política de impuestos vigente 2024

Esta política aplica a todas las órdenes emitidas entre 2024-01-01 y 2024-12-31.

## Tasas oficiales por región

| Región  | Tasa (%) | Nombre local        |
|---------|----------|---------------------|
| CL      | 19.0     | IVA Chile           |
| US-CA   | 7.25     | Sales Tax California|
| EU-ES   | 21.0     | IVA España          |
| EU-DE   | 19.0     | Umsatzsteuer        |
| MX      | 16.0     | IVA México          |

## Regla de discrepancia

Una orden se considera con **discrepancia fiscal** cuando el impuesto declarado en el
ERP difiere en más de un 1% (en valor absoluto) del impuesto esperado según la tasa
oficial de la región. Estas órdenes deben marcarse como `TAX_REVIEW` para auditoría.

## Excepciones

- Órdenes exportadas (`region == "EXPORT"`) están exentas.
- Órdenes de servicios digitales B2B UE tributan en destino (reverse charge).
