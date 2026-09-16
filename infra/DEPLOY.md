# Despliegue en Azure (simulado)

Infraestructura de referencia para desplegar el MVP en **Azure Container Apps
(ACA)** + **Azure OpenAI Service (AOAI)** con el tráfico de datos **contenido
dentro de una VNet privada**. El objetivo del ejercicio es documentar la
arquitectura y proveer un Bicep autocontenido que se pueda validar con
`az deployment group what-if`. No se ejecuta un despliegue real.

## Arquitectura

```
                       ┌────────────────────────────────────────┐
                       │             VNet 10.30.0.0/16          │
                       │                                        │
     Usuario           │  ┌───────────────┐   ┌──────────────┐  │
     interno   ─(*)─►  │  │ Container App │──►│Azure OpenAI  │  │
     (VPN/ExpressRoute)│  │  (ingress     │   │(Private EP)  │  │
                       │  │  internal)    │   └──────────────┘  │
                       │  │  min=1 max=5  │   ┌──────────────┐  │
                       │  │  MI + AcrPull │──►│  Azure ACR   │  │
                       │  └───────────────┘   │(Private EP)  │  │
                       │          │           └──────────────┘  │
                       │          │           ┌──────────────┐  │
                       │          └──────────►│  Key Vault   │  │
                       │                      │(Private EP)  │  │
                       │                      └──────────────┘  │
                       │  Log Analytics ◄── App Insights ◄──────│
                       └────────────────────────────────────────┘

(*) Ingreso corporativo: Application Gateway + WAF en la subnet `agw`,
    o Azure Front Door Premium con Private Link. No se despliega en este
    Bicep — se deja la subnet reservada.
```

## Principios de red privada

1. **VNet dedicada `10.30.0.0/16`** con 3 subnets:
   - `aca-infra` (`/23`) delegada a `Microsoft.App/environments`.
   - `pe` (`/24`) exclusiva para Private Endpoints.
   - `agw` (`/24`) reservada para futuro Application Gateway / ingress público.
2. **Container Apps Environment** con `vnetConfiguration.internal = true` →
   sólo obtiene IP privada; sin FQDN público.
3. **Azure OpenAI**:
   - `publicNetworkAccess = Disabled`.
   - `networkAcls.defaultAction = Deny`.
   - `customSubDomainName` obligatorio para Private Link.
   - Private Endpoint en subnet `pe` con grupo `account`.
   - Autenticación con **User-Assigned Managed Identity** (rol
     *Cognitive Services OpenAI User*), sin exponer keys.
4. **Azure Container Registry Premium** con `publicNetworkAccess = Disabled` +
   Private Endpoint. La imagen se jala por red privada usando la misma MI
   (`AcrPull`).
5. **Key Vault** con `enableRbacAuthorization = true`, `publicNetworkAccess =
   disabled`, Private Endpoint, y rol *Key Vault Secrets User* asignado a la MI
   para leer secretos si el rollout lo necesita.
6. **Private DNS zones** enlazadas a la VNet:
   - `privatelink.openai.azure.com`
   - `privatelink.azurecr.io`
   - `privatelink.vaultcore.azure.net`
   Así el cliente resuelve el FQDN público del recurso a una IP privada
   automáticamente y no requiere cambios en la app.
7. **Log Analytics + App Insights** como destino de logs del entorno ACA
   (`appLogsConfiguration`) y de telemetría de la app.

## Flujo de datos

- Petición interna → ingress interno de ACA → contenedor.
- Contenedor → resuelve `https://<aoai>.openai.azure.com` por Private DNS →
  Private Endpoint → AOAI. **Nunca sale por Internet.**
- Contenedor autentica contra AOAI vía Managed Identity (Entra ID).
- Pull de imagen (`<acr>.azurecr.io/erpagent:latest`) igualmente por PE.

## Archivos

| Archivo                    | Contenido                                              |
|----------------------------|--------------------------------------------------------|
| `infra/main.bicep`         | Todos los recursos (VNet, ACA, AOAI, ACR, KV, MI, PEs, DNS) |
| `infra/main.parameters.json` | Parámetros de despliegue                             |
| `Dockerfile`               | Imagen productiva de la API (con pre-descarga de embeddings) |

## Comandos (para validar sin desplegar)

```powershell
# 1. Login y RG (una vez)
az login
az group create -n erpagent-rg -l eastus2

# 2. Build & push de la imagen al ACR privado (desde una VM en la VNet o Azure DevOps runner autohospedado):
$acr = az acr show -g erpagent-rg -n <acrname> --query loginServer -o tsv
az acr login -n <acrname>
docker build -t $acr/erpagent:v1 .
docker push $acr/erpagent:v1

# 3. What-if (simulación, no aplica cambios)
az deployment group what-if `
  -g erpagent-rg `
  -f infra/main.bicep `
  -p infra/main.parameters.json `
  -p containerImage=erpagent:v1

# 4. Deploy real (opcional)
az deployment group create `
  -g erpagent-rg `
  -f infra/main.bicep `
  -p infra/main.parameters.json `
  -p containerImage=erpagent:v1
```

## Variables de entorno en el Container App

El Bicep configura la app para hablar con **Azure OpenAI** (no OpenAI público):

```
LLM_PROVIDER                        = openai
AZURE_OPENAI_ENDPOINT               = https://<aoai>.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT             = gpt-4o-mini
AZURE_OPENAI_API_VERSION            = 2024-08-01-preview
AZURE_CLIENT_ID                     = <clientId de la MI>
APPLICATIONINSIGHTS_CONNECTION_STRING = <cx-string>
```

> En el código actual `app/services/llm.py` usa `langchain_openai.ChatOpenAI`.
> Para consumir Azure OpenAI real, se sustituye por `AzureChatOpenAI` leyendo
> estas variables (misma interfaz, mismo agente). El resto de la aplicación
> (agente, tools, RAG, guardrails) no requiere cambios.

## Notas de coste y cuotas

- ACA `Consumption` cobra sólo mientras hay tráfico; `minReplicas=1` mantiene
  un pod caliente. Bájalo a `0` en dev si no importa cold start.
- AOAI requiere **cuota asignada** por región/modelo (`gpt-4o-mini` en
  `eastus2`, `swedencentral`, etc.).
- Log Analytics: 5 GB gratis/mes; ajustar `retentionInDays` según política.
- Los Private Endpoints tienen coste fijo por hora + tráfico.

## Endurecimiento adicional recomendado

- Añadir NSGs a las subnets `pe` y `agw` con reglas explícitas.
- Application Gateway WAF v2 en la subnet `agw` con listener interno + cert
  corporativo, publicando el Container App como backend `internal.<domain>`.
- Rotación automática de secretos en Key Vault + `Managed HSM` si aplica.
- Diagnostic settings de todos los recursos hacia el mismo Log Analytics.
- Azure Policy: `deny public network access on cognitive services`,
  `require private endpoints on container registry`.
- Azure Defender for Cloud habilitado (Cloud Workload Protection).
