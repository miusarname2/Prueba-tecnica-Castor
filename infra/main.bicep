// =============================================================================
//  ERP-Agent MVP  ·  Infraestructura simulada en Azure
// -----------------------------------------------------------------------------
//  Objetivo: desplegar la API FastAPI en Azure Container Apps (ACA) integrada
//  con Azure OpenAI Service (AOAI), garantizando que el tráfico entre el
//  workload y AOAI viaje **exclusivamente por red privada** (VNet + Private
//  Endpoints + Private DNS). No se expone tráfico al Internet público hacia
//  AOAI ni hacia el Container Registry.
//
//  Componentes:
//    - VNet dedicada con 3 subnets:
//        · aca-infra   (delegada a Microsoft.App/environments, /23)
//        · pe          (private endpoints, /24)
//        · agw         (application gateway / ingress opcional, /24)
//    - Log Analytics Workspace + Application Insights
//    - Azure Container Registry (Premium, publicNetworkAccess=Disabled)
//    - Azure OpenAI (S0, publicNetworkAccess=Disabled) con deployments
//      para chat (gpt-4o-mini) y embeddings (text-embedding-3-small).
//    - Key Vault (RBAC, publicNetworkAccess=Disabled) para secretos.
//    - User-Assigned Managed Identity con RBAC a AOAI/ACR/KV.
//    - Container Apps Environment vnetConfig.internal=true (sólo IP privada).
//    - Container App consumiendo la imagen del ACR y AOAI via DNS privada.
//    - Private DNS zones + Private Endpoints para AOAI, ACR y Key Vault.
//
//  Nota: este archivo es un **prototipo** para revisión. No se despliega tal
//  cual sin ajustar SKUs, cuotas regionales y política corporativa.
// =============================================================================

targetScope = 'resourceGroup'

@description('Prefijo corto para todos los recursos (3-8 chars, sólo alfanum).')
@minLength(3)
@maxLength(8)
param namePrefix string = 'erpai'

@description('Region de Azure. AOAI puede requerir regiones específicas.')
param location string = resourceGroup().location

@description('Tag de la imagen del container en el ACR (formato: repo:tag).')
param containerImage string = 'erpagent:latest'

@description('Modelo de chat en Azure OpenAI.')
param chatModel string = 'gpt-4o-mini'

@description('Versión del modelo de chat.')
param chatModelVersion string = '2024-07-18'

@description('Modelo de embeddings en Azure OpenAI (opcional).')
param embeddingModel string = 'text-embedding-3-small'

@description('Versión del modelo de embeddings.')
param embeddingModelVersion string = '1'

var suffix = uniqueString(resourceGroup().id)
var names = {
  vnet:      '${namePrefix}-vnet'
  law:       '${namePrefix}-law-${suffix}'
  appi:      '${namePrefix}-appi-${suffix}'
  acr:       toLower('${namePrefix}acr${suffix}')
  aoai:      '${namePrefix}-aoai-${suffix}'
  kv:        '${namePrefix}-kv-${suffix}'
  mi:        '${namePrefix}-mi-${suffix}'
  acaEnv:    '${namePrefix}-acaenv'
  acaApp:    '${namePrefix}-api'
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: names.vnet
  location: location
  properties: {
    addressSpace: { addressPrefixes: [ '10.30.0.0/16' ] }
    subnets: [
      {
        name: 'aca-infra'
        properties: {
          addressPrefix: '10.30.0.0/23'
          delegations: [ {
            name: 'aca-delegation'
            properties: { serviceName: 'Microsoft.App/environments' }
          } ]
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
      {
        name: 'pe'
        properties: {
          addressPrefix: '10.30.2.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
      {
        name: 'agw'
        properties: {
          addressPrefix: '10.30.3.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

resource subnetAca 'Microsoft.Network/virtualNetworks/subnets@2023-11-01' existing = {
  parent: vnet
  name: 'aca-infra'
}
resource subnetPe 'Microsoft.Network/virtualNetworks/subnets@2023-11-01' existing = {
  parent: vnet
  name: 'pe'
}

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: names.law
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    features: { enableLogAccessUsingOnlyResourcePermissions: true }
  }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: names.appi
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
    IngestionMode: 'LogAnalytics'
    publicNetworkAccessForIngestion: 'Disabled'
    publicNetworkAccessForQuery:     'Enabled'  
  }
}

resource mi 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: names.mi
  location: location
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: names.acr
  location: location
  sku: { name: 'Premium' }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Disabled'
    networkRuleBypassOptions: 'AzureServices'
  }
}

var acrPullRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
resource acrPullAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, mi.id, acrPullRoleId)
  properties: {
    principalId: mi.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPullRoleId
  }
}

resource aoai 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: names.aoai
  location: location
  kind: 'OpenAI'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: names.aoai       
    publicNetworkAccess: 'Disabled'
    disableLocalAuth: false               
    networkAcls: {
      defaultAction: 'Deny'
      virtualNetworkRules: []
      ipRules: []
    }
  }
}

resource aoaiChat 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: aoai
  name: chatModel
  sku: { name: 'Standard', capacity: 20 }
  properties: {
    model: {
      format: 'OpenAI'
      name: chatModel
      version: chatModelVersion
    }
    versionUpgradeOption: 'OnceCurrentVersionExpired'
  }
}

resource aoaiEmb 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: aoai
  name: embeddingModel
  sku: { name: 'Standard', capacity: 20 }
  properties: {
    model: {
      format: 'OpenAI'
      name: embeddingModel
      version: embeddingModelVersion
    }
  }
  dependsOn: [ aoaiChat ]
}

var aoaiUserRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
resource aoaiUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: aoai
  name: guid(aoai.id, mi.id, aoaiUserRoleId)
  properties: {
    principalId: mi.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: aoaiUserRoleId
  }
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: names.kv
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'disabled'
    networkAcls: { defaultAction: 'Deny', bypass: 'AzureServices' }
  }
}

var kvSecretsUserRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
resource kvRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, mi.id, kvSecretsUserRoleId)
  properties: {
    principalId: mi.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: kvSecretsUserRoleId
  }
}

var dnsZoneNames = {
  aoai: 'privatelink.openai.azure.com'
  acr:  'privatelink.azurecr.io'
  kv:   'privatelink.vaultcore.azure.net'
}

resource dnsAoai 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: dnsZoneNames.aoai
  location: 'global'
}
resource dnsAcr 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: dnsZoneNames.acr
  location: 'global'
}
resource dnsKv 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: dnsZoneNames.kv
  location: 'global'
}

resource dnsLinkAoai 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: dnsAoai
  name: '${names.vnet}-link'
  location: 'global'
  properties: { registrationEnabled: false, virtualNetwork: { id: vnet.id } }
}
resource dnsLinkAcr 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: dnsAcr
  name: '${names.vnet}-link'
  location: 'global'
  properties: { registrationEnabled: false, virtualNetwork: { id: vnet.id } }
}
resource dnsLinkKv 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: dnsKv
  name: '${names.vnet}-link'
  location: 'global'
  properties: { registrationEnabled: false, virtualNetwork: { id: vnet.id } }
}

// Private Endpoints
resource peAoai 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: '${names.aoai}-pe'
  location: location
  properties: {
    subnet: { id: subnetPe.id }
    privateLinkServiceConnections: [ {
      name: 'aoai'
      properties: {
        privateLinkServiceId: aoai.id
        groupIds: [ 'account' ]
      }
    } ]
  }
}
resource peAoaiDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = {
  parent: peAoai
  name: 'zg'
  properties: {
    privateDnsZoneConfigs: [ {
      name: 'aoai'
      properties: { privateDnsZoneId: dnsAoai.id }
    } ]
  }
}

resource peAcr 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: '${names.acr}-pe'
  location: location
  properties: {
    subnet: { id: subnetPe.id }
    privateLinkServiceConnections: [ {
      name: 'acr'
      properties: { privateLinkServiceId: acr.id, groupIds: [ 'registry' ] }
    } ]
  }
}
resource peAcrDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = {
  parent: peAcr
  name: 'zg'
  properties: {
    privateDnsZoneConfigs: [ {
      name: 'acr'
      properties: { privateDnsZoneId: dnsAcr.id }
    } ]
  }
}

resource peKv 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: '${names.kv}-pe'
  location: location
  properties: {
    subnet: { id: subnetPe.id }
    privateLinkServiceConnections: [ {
      name: 'kv'
      properties: { privateLinkServiceId: kv.id, groupIds: [ 'vault' ] }
    } ]
  }
}
resource peKvDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = {
  parent: peKv
  name: 'zg'
  properties: {
    privateDnsZoneConfigs: [ {
      name: 'kv'
      properties: { privateDnsZoneId: dnsKv.id }
    } ]
  }
}

resource acaEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: names.acaEnv
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
    vnetConfiguration: {
      internal: true                              
      infrastructureSubnetId: subnetAca.id
    }
    zoneRedundant: false
    workloadProfiles: [
      { name: 'Consumption', workloadProfileType: 'Consumption' }
    ]
  }
}

resource acaApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: names.acaApp
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${mi.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: acaEnv.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false                          
        targetPort: 8000
        transport: 'auto'                        
        allowInsecure: false
        stickySessions: { affinity: 'sticky' }  
      }
      registries: [ {
        server: '${acr.name}.azurecr.io'
        identity: mi.id
      } ]
      secrets: []                                
    }
    template: {
      containers: [ {
        name: 'api'
        image: '${acr.name}.azurecr.io/${containerImage}'
        resources: { cpu: json('1.0'), memory: '2.0Gi' }
        env: [
          { name: 'LLM_PROVIDER',           value: 'openai' }        
          { name: 'AZURE_OPENAI_ENDPOINT',  value: aoai.properties.endpoint }
          { name: 'AZURE_OPENAI_DEPLOYMENT',value: chatModel }
          { name: 'AZURE_OPENAI_API_VERSION', value: '2024-08-01-preview' }
          { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appi.properties.ConnectionString }
          { name: 'AZURE_CLIENT_ID',        value: mi.properties.clientId }
        ]
        probes: [
          { type: 'Liveness',  httpGet: { path: '/health', port: 8000 }, initialDelaySeconds: 20, periodSeconds: 30 }
          { type: 'Readiness', httpGet: { path: '/health', port: 8000 }, initialDelaySeconds: 5,  periodSeconds: 10 }
        ]
      } ]
      scale: {
        minReplicas: 1
        maxReplicas: 5
        rules: [ {
          name: 'http-concurrency'
          http: { metadata: { concurrentRequests: '30' } }
        } ]
      }
    }
  }
  dependsOn: [
    acrPullAssignment
    aoaiUserAssignment
    peAoaiDns
    peAcrDns
  ]
}


output resourceGroupName string  = resourceGroup().name
output vnetId string             = vnet.id
output acrLoginServer string     = acr.properties.loginServer
output aoaiEndpoint string       = aoai.properties.endpoint
output containerAppFqdn string   = acaApp.properties.configuration.ingress.fqdn
output managedIdentityId string  = mi.id
output managedIdentityClientId string = mi.properties.clientId
