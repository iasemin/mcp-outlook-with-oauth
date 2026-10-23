# Kubernetes deployment

[English instructions](../../docs/en/deployment.md#kubernetes--containers) · [Инструкция на русском](../../docs/ru/deployment.md#kubernetes-и-контейнеры)

`mcp.yaml` is an unapplied deployment example for the real EWS backend. Replace example DNS names and image; provision the Secret, CA and mailbox mapping described in the guides. It does not deploy Exchange, Keycloak or LiteLLM.

`mcp.yaml` — пример для реального EWS backend, ещё не применявшийся в кластере. Замените DNS и образ; создайте Secret, CA и mapping по инструкции. Exchange, Keycloak и LiteLLM этим манифестом не устанавливаются.
