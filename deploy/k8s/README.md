# Kubernetes deployment

[English instructions](../../docs/en/deployment.md#kubernetes--containers) · [Инструкция на русском](../../docs/ru/deployment.md#kubernetes-и-контейнеры)

`mcp.yaml` is an unapplied deployment example for the real EWS backend. Replace example DNS names and image; provision the EWS/OAuth Secrets, OAuth-state PVC, CA and mailbox mapping described in the guides. It does not deploy Exchange, Keycloak or LiteLLM.

`mcp.yaml` — пример для реального EWS backend, ещё не применявшийся в кластере. Замените DNS и образ; создайте EWS/OAuth Secrets, PVC для OAuth-состояния, CA и mapping по инструкции. Exchange, Keycloak и LiteLLM этим манифестом не устанавливаются.
