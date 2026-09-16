# AI Disclosure

Documento de transparencia sobre el uso de herramientas de IA generativa
durante el desarrollo de esta prueba tecnica. Para cada item se detalla que se
le pidio a la IA, que se conservo, que se corrigio o descarto, y que se hizo
sin asistencia.

**Herramienta utilizada:** GitHub Copilot Chat (GPT-4o), utilizado como
asistente conversacional dentro de VS Code para consultas puntuales, generacion
de snippets y revision de codigo. No se uso generacion automatica de archivos
completos.

---

## Parte 1: Diseño de Arquitectura y Estrategia de IA (85% humano / 15% IA)

| Item | Prompts (resumen) | Conservado tal cual | Corregido/descartado y por que | Hecho sin IA |
|------|-------------------|---------------------|--------------------------------|--------------|
| **Workflow agentico (diagrama Mermaid)** | "Ayudame a formatear este diagrama de flujo en sintaxis Mermaid valida, tengo los nodos definidos pero no recuerdo la sintaxis de subgraphs y condicionales." | La sintaxis Mermaid generada (keywords `flowchart TD`, `subgraph`, `style`) la conserve porque era correcta y ahorraba tiempo de consultar la documentacion. | Descarte la arquitectura que sugirio la IA (un solo agente con todas las tools): yo ya tenia claro que queria 3 agentes especializados + orchestrator para aislar el contexto del ERP del contexto RAG y evitar prompt injection indirecta. Redisene los nodos de decision (umbral $10k, tipo de discrepancia) y el flujo de retry del ERP basandome en patrones que conozco de proyectos anteriores con colas de reintentos. | La arquitectura multi-agente completa (roles, responsabilidades, asignacion de tools a cada agente), los 3 niveles de memoria (buffer, scratchpad, long-term) con la regla de aislamiento de contexto, y los 4 niveles de guardrails los disene yo desde cero. Tambien el diagrama de secuencia completo lo construi manualmente basandome en mi experiencia con sistemas ERP reales. |
| **Estrategia LLMOps (KPIs)** | "Cuales son las metricas principales que calcula RAGAS y como se diferencia faithfulness de answer_relevancy?" | Conserve las definiciones formales de faithfulness y answer_relevancy que me dio (descomposicion en claims, generacion de preguntas inversas) porque coincidian con la documentacion oficial de RAGAS que ya habia leido. | Descarte los umbrales que sugirio (0.95 para todo): eran irrealistas para un sistema en produccion real con datos financieros donde el contexto puede ser ambiguo. Defini umbrales diferenciados basandome en benchmarks publicados y en mi experiencia: faithfulness >= 0.90 (critico, no puede alucinar cifras), context_recall >= 0.75 (mas tolerante porque no siempre hay un unico doc relevante). | Los KPIs de Tool Call Accuracy, Decision Correctness, Guardrail Bypass Rate y Hallucination Rate los defini yo porque son especificos del dominio ERP/financiero y la IA no los sugirio. La tabla de costos y ROI la arme basandome en pricing real de Arize y LangSmith que investigue por mi cuenta. El pipeline CI/CD (pre-merge, staging, prod) lo disene segun patrones de MLOps que he aplicado en proyectos anteriores. |

---

## Parte 2: Implementación Técnica (Práctica) (~52% humano / ~48% IA)

### 2.1 Desarrollo del Agente (Core)
| Item | Prompts (resumen) | Conservado tal cual | Corregido/descartado y por que | Hecho sin IA |
|------|-------------------|---------------------|--------------------------------|--------------|
| **Function calling con LangChain** | "Como se usa bind_tools con ChatGroq para function calling nativo? Necesito que el agente encadene tools automaticamente." | Conserve el patron de `llm.bind_tools(tools)` + loop manual que me sugirio: es el approach correcto para tener control sobre el streaming y el trace de tools usadas, y coincide con la documentacion de LangChain. | Descarte la sugerencia de usar `AgentExecutor` (LangChain legacy): preferi el loop manual porque me da control total sobre el manejo de errores por tool (si `get_erp_data` falla, quiero que el agente vea el error como output, no que se lance una excepcion que rompa el flujo). Tambien corregi el manejo de `tool_call_id` — la IA generaba IDs ficticios y Groq los rechazaba; tuve que extraer el ID real del `AIMessage.tool_calls[].id`. | El diseno del loop agentico con `MAX_STEPS=6` lo defini yo para evitar loops infinitos (experiencia de debugging en produccion). La logica de serializar tool errors como `{"error": "..."}` en el `ToolMessage` en lugar de relanzar la excepcion fue decision mia: permite que el LLM informe el fallo al usuario sin fabricar datos. El `SYSTEM_PROMPT_TEMPLATE` con las 6 reglas lo escribi yo completo. |
| **Tools mocked (erp_tools.py)** | "Generame un dataset mock de ordenes ERP con campos realistas para SQL Server, que incluya al menos un caso con discrepancia fiscal y uno con registro corrupto." | Conserve la estructura del diccionario `_ERP_ORDERS` con los 4 registros porque los campos y tipos eran correctos para un ERP tipico. | Corregi las tasas fiscales: la IA puso 7.5% para California (incorrecto, es 7.25% estatal) y 19% para Espana (correcto). Tambien agregue el campo `__corrupt__` para ORD-9999 que la IA no habia incluido — lo necesitaba para probar el manejo de errores del ERP. Los schemas Pydantic (`GetERPDataInput`, `CalcTaxInput`) los reescribi con descripciones mas precisas para que el function calling generara mejores argumentos. | La logica de `calculate_tax_discrepancy` (calculo de discrepancia absoluta, porcentual, y el flag `is_discrepant` con umbral del 1%) la implemente yo porque es logica de negocio pura que conozco del dominio fiscal. La simulacion de fallo esporadico (`random.random() < 0.01`) la agregue yo para probar el error handling end-to-end. |

### 2.2 Pipeline de RAG Avanzado
| Item | Prompts (resumen) | Conservado tal cual | Corregido/descartado y por que | Hecho sin IA |
|------|-------------------|---------------------|--------------------------------|--------------|
| **Indice vectorial + metadata filtering** | "Como configuro un VectorStoreIndex en LlamaIndex con MetadataFilters para filtrar por year y por un campo booleano confidential?" | Conserve la estructura general de `VectorStoreIndex.from_documents(docs)` + `index.as_retriever(filters=...)`. Tambien conserve el pattern de `HuggingFaceEmbedding` como embed_model local. | Corregi un bug critico: la IA generaba `MetadataFilter(key="confidential", value=False)` pero LlamaIndex 0.11.x no acepta `bool` en `MetadataFilter.value` (solo int/float/str/list). Descubri el error al ejecutar la primera peticion y ver 6 errores de validacion Pydantic. Lo resolvi cambiando a strings `"true"/"false"` en metadata y filtros, y ajustando el parser de front-matter para no convertir a bool nativo. | El parser de front-matter YAML (`_parse_front_matter`) lo escribi yo: LlamaIndex no parsea YAML de Markdown por defecto, asi que implemente un parser ligero con regex que extrae key-value y castea tipos (ahora con la correccion de bool a str). El diseno de los 5 documentos knowledge (sus metadata, la inclusion intencional de un doc confidencial para testear guardrails, y un doc de 2023 para testear el filtro temporal) fue decision mia. La funcion `format_context` que formatea los resultados del RAG para inyectarlos en el system prompt tambien la escribi yo. |

### 2.3 API Backend
| Item | Prompts (resumen) | Conservado tal cual | Corregido/descartado y por que | Hecho sin IA |
|------|-------------------|---------------------|--------------------------------|--------------|
| **Endpoint /chat (respuesta completa)** | "Generame un endpoint FastAPI POST /chat que reciba un ChatRequest Pydantic, invoque el agente, y devuelva un ChatResponse. Incluye manejo de errores con codigos HTTP diferenciados." | Conserve la estructura del endpoint con los tres bloques try/except (ValueError -> 400, Exception -> 502) y el response_model. Es un patron estandar de FastAPI que la IA genero correctamente. | Agregue la integracion con guardrails que la IA no incluyo: la llamada a `check_prompt()` antes del agente y `output_contains_restricted()` despues. Tambien cambie el manejo del caso bloqueado: en lugar de devolver HTTP 403 (que la IA sugirio), devuelvo HTTP 200 con `blocked: true` para que el frontend pueda mostrar un mensaje amigable sin tratar la respuesta como error de red. | Los modelos Pydantic `ChatRequest` y `ChatResponse` con los campos `user_role`, `year_filter`, `provider`, `blocked`, `block_reason`, `tools_used` los disene yo basandome en lo que el frontend necesitaba. |
| **Endpoint /chat/stream (SSE)** | "Como implemento un endpoint FastAPI que haga streaming SSE con sse-starlette, consumiendo un generador async que emite tokens?" | Conserve el patron de `EventSourceResponse(event_generator())` y la estructura del generador con `yield {"event": tipo, "data": json}`. | Corregi la deteccion de desconexion del cliente: la IA ponia `await request.is_disconnected()` fuera del loop (inutilizable), lo movi dentro del `async for` para verificar en cada token. Tambien agregue el parametro `req: Request` como dependencia del endpoint (la IA lo habia omitido). | El diseno de los 6 tipos de eventos SSE (`meta`, `tool_start`, `tool_end`, `token`, `done`, `error`) lo defini yo pensando en lo que el frontend necesitaba para mostrar los chips de tools y las fuentes. La logica de devolver JSON 400 antes de iniciar el stream cuando los guardrails bloquean (en lugar de emitir un evento de error dentro del stream) fue decision mia. |
| **Manejo de errores** | No requirio prompt especifico; forme parte de la logica de los endpoints. | N/A | N/A | Toda la matriz de errores (400/502/500, tool errors como JSON, deteccion de desconexion, cap de MAX_STEPS con mensaje explicativo, exception handler global) la disene yo basandome en las mejores practicas que conozco de FastAPI en produccion. |

---

## Parte 3: Integración y Seguridad Enterprise (~70% humano / ~30% IA)

### 3.1 Seguridad en el Prompt (Prompt Injection)
| Item | Prompts (resumen) | Conservado tal cual | Corregido/descartado y por que | Hecho sin IA |
|------|-------------------|---------------------|--------------------------------|--------------|
| **Guardrails de input** | "Que patrones regex son comunes para detectar prompt injection en ingles y espanol?" | Conserve 4 de los 12 patrones que sugirio (los mas genericos como `ignore previous instructions`, `reveal your prompt`) porque son bien conocidos y efectivos. | Descarte los patrones demasiado amplios que generaban falsos positivos (ej: un regex que matcheaba la palabra "system" sola, lo cual bloquearia preguntas legitimas como "el sistema ERP esta caido?"). Agregue 8 patrones propios mas especificos para el contexto ERP y bilingue (`olvida las instrucciones anteriores`, `bypass safety`, `pretend to be admin`). | La arquitectura de 4 capas de seguridad (input, RAG, system prompt, output) la disene yo. La logica RBAC role-aware (admin puede ver datos confidenciales, analyst/viewer no) y la regla dinamica en el system prompt las implemente yo sin asistencia. La segunda barrera `output_contains_restricted` que revisa la salida del LLM antes de enviarla fue idea mia como defensa en profundidad. |
| **Metadata filtering como guardrail** | No requirio prompt especifico; fue parte del diseno del RAG. | N/A | N/A | La decision de usar `confidential: false` como filtro en el RAG (ademas de los regex) para que documentos restringidos ni siquiera lleguen al contexto del LLM fue enteramente mia. Es una capa de seguridad que la mayoria de implementaciones omite. |

### 3.2 Despliegue en Azure
| Item | Prompts (resumen) | Conservado tal cual | Corregido/descartado y por que | Hecho sin IA |
|------|-------------------|---------------------|--------------------------------|--------------|
| **Bicep (infra/main.bicep)** | "Generame un template Bicep para un Azure Container Apps Environment con VNet interna, y agregale un Private Endpoint para Azure OpenAI." | Conserve la estructura base del recurso `Microsoft.App/managedEnvironments` con `vnetConfiguration.internal: true` y el patron de Private Endpoint + Private DNS zone porque la sintaxis era correcta. | Corregi varios errores en el template generado: (1) la IA omitio la delegacion `Microsoft.App/environments` en la subnet, lo cual habria fallado al desplegar; (2) el API version de `Microsoft.CognitiveServices/accounts` era obsoleto (la IA puso 2023-05-01, lo actualice a 2024-10-01); (3) agregue `disableLocalAuth: false` que la IA no incluyo; (4) los role assignments para la Managed Identity (`AcrPull`, `Cognitive Services OpenAI User`, `Key Vault Secrets User`) los escribi yo porque la IA generaba GUIDs de roles incorrectos. | La arquitectura de red completa (3 subnets con propositos definidos, Private DNS zones para los 3 servicios, el Dockerfile con pre-descarga de embeddings, los health probes del container, el escalado por concurrencia HTTP) la disene yo basandome en experiencia con despliegues Azure reales. El documento DEPLOY.md con el diagrama ASCII de arquitectura, el flujo de datos, los comandos de validacion y las recomendaciones de endurecimiento lo redacte yo. |

---

## Parte 4: Gestión de Incidentes y Liderazgo (Escenario) (90% humano / 10% IA)

### 4.1 Gestión de Incidentes (Drift de Modelo)
| Item | Prompts (resumen) | Conservado tal cual | Corregido/descartado y por que | Hecho sin IA |
|------|-------------------|---------------------|--------------------------------|--------------|
| **Investigacion de drift + rollback** | "Resumeme los pasos tipicos de un runbook de rollback de modelo LLM en produccion." | Conserve la estructura de 5 fases (deteccion, contencion, investigacion, remediacion, prevencion) como esqueleto porque es un framework estandar de incident management. | Descarte los pasos genericos que no aplican al contexto ERP (ej: "reentrenar el modelo" — no reentrenamos LLMs de terceros, solo cambiamos version o ajustamos prompts). Todo el contenido especifico del escenario (como investigar notas de credito erroneas, que queries correr, como validar el golden dataset) lo escribi yo. | El proceso completo de investigacion, las queries SQL para identificar notas afectadas, el diseno del golden dataset con categorias de casos, y la propuesta de canary deployment la redacte yo basandome en experiencia real con incidentes en sistemas financieros. |

### 4.2 Liderazgo Técnico (Latencia)
| Item | Prompts (resumen) | Conservado tal cual | Corregido/descartado y por que | Hecho sin IA |
|------|-------------------|---------------------|--------------------------------|--------------|
| **Liderazgo tecnico (latencia)** | No use IA para esta seccion. | N/A | N/A | Toda la seccion de soluciones tecnicas para latencia (streaming SSE, cache de embeddings, precalculo de consultas frecuentes, optimizacion del prompt) la escribi yo basandome en problemas reales que he resuelto en proyectos anteriores. Las metricas de mejora esperada y la priorizacion tambien son mias. |

---

## Adicional: Documentación (15% humano / 85% IA)

| Item | Prompts (resumen) | Conservado tal cual | Corregido/descartado y por que | Hecho sin IA |
|------|-------------------|---------------------|--------------------------------|--------------|
| **README.md** | "Genera un README completo para este proyecto que incluya estructura, instalacion, ejemplos curl, tabla de errores, y seccion de metadata filtering." | Conserve la mayor parte del README generado: la estructura de secciones, los ejemplos de curl, la tabla de errores y la explicacion de metadata filtering eran claros y correctos. | Corregi la seccion de configuracion de proveedor: la IA mostraba la variable `LLM_PROVIDER` pero no explicaba como cambiar por request (campo `provider` en el JSON). Tambien agregue la tabla de ordenes mock disponibles y las ideas de extension que la IA no incluyo. | Revise todo el documento para asegurar coherencia con el codigo real (rutas de endpoints, nombres de archivos, formatos de response). |
| **Comentarios en codigo** | "Revisa los docstrings de estos modulos y mejoralos." | Conserve la mayoria de los docstrings generados porque describían correctamente la funcionalidad. | Corregi algunos que eran demasiado verbosos o que no mencionaban limitaciones importantes (ej: el docstring de `_parse_front_matter` no explicaba la limitacion de bool a str en MetadataFilter). | La decision de que modulos documentar y el nivel de detalle fue mia. |

---

## Resumen Cuantitativo

| Seccion | Humano | IA | Observacion |
|---------|--------|-----|-------------|
| Parte 1: Diseño de Arquitectura y Estrategia | 85% | 15% | IA asistio con sintaxis Mermaid y definiciones formales de metricas RAGAS. |
| Parte 2: Implementación Técnica | ~52% | ~48% | IA genero snippets base; correcciones de bugs críticos, manejo de errores y lógica de dominio manual. |
| Parte 3: Integración y Seguridad Enterprise | ~70% | ~30% | IA sugirió regex base y template Bicep; arquitectura RBAC y VNet privada manuales. |
| Parte 4: Gestión de Incidentes y Liderazgo | 90% | 10% | Casi enteramente humano; IA solo sugirio el esqueleto de fases de incidentes. |
| Adicional: Documentacion (README, docs) | 15% | 85% | IA genero borradores; yo revise coherencia con el codigo. |
| **Promedio ponderado** | **~60%** | **~40%** | |
