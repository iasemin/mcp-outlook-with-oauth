# MCP Outlook with OAuth2

[English](README.md) · [Развёртывание](docs/ru/deployment.md) · [Архитектура и происхождение](docs/ru/architecture.md) · [Проверки](docs/ru/testing.md)

MCP-сервер для внутреннего Microsoft Exchange: OAuth2-вход пользователей, доступ к почте через EWS и подключение к LiteLLM. Приложение Outlook и Microsoft Graph не нужны.

**Статус:** все 12 инструментов прошли 59 вызовов на синтетическом backend через существующий LiteLLM 1.96.0 и настоящий OAuth2 Keycloak. Локальный набор — 26 тестов. **Совместимость с живым Exchange 2019 CU15 и развёртывание в Kubernetes пока не проверены.**

```text
Пользователь → LiteLLM → MCP → Exchange EWS
                  ↕      ↓
               Keycloak  JWT + scopes + sub → ящик
```

MCP принимает access tokens Keycloak, полученные через Authorization Code + PKCE. Подключение к Exchange отдельное: HTTPS + NTLM и служебная учётная запись с ограниченным impersonation. OAuth2 перед MCP не означает OAuth2 между MCP и Exchange.

## Возможности

Поиск и чтение писем, скачивание вложений, сохранение черновиков и подтверждённая отправка, флаги прочтения, перемещение, поиск адресатов и личный календарь. [Инструменты и scopes](docs/ru/deployment.md#инструменты-и-scopes).

Это самостоятельная реализация на **FastMCP** и **exchangelib**. **Код ItayElizur/mcp-outlook не копировали; проект не является его форком.** Проверенный коммит референса, отличия и причины решений перечислены [отдельно](docs/ru/architecture.md).

## Скачать исходники и собрать

```sh
git clone https://github.com/iasemin/mcp-outlook-with-oauth.git
cd mcp-outlook-with-oauth
uv sync --frozen
uv run pytest -q

docker buildx build --platform linux/amd64 \
  -t YOUR_REGISTRY/mcp-outlook-with-oauth:0.1.0 --push .
```

Готовый контейнерный образ пока не опубликован: его нужно собрать и загрузить в свой registry. Имена Python-пакета и модуля сохранены: `outlook-ews-mcp` / `outlook_mcp`.

## Развёртывание

- **Внутренний Exchange / Kubernetes:** [короткая инструкция](docs/ru/deployment.md); манифест — `deploy/k8s/mcp.yaml`.
- **Локальный OAuth-стенд:** [порядок запуска](docs/ru/testing.md). Compose поднимает Keycloak, PostgreSQL, MCP и ingress к **уже существующему** LiteLLM; LiteLLM и Exchange он не устанавливает.
- **Результаты:** [59 проверок синтетического backend](docs/all-tools-results.json). Реальных писем и учётных данных в репозитории нет.

Код проекта распространяется по MIT. Зависимости сохраняют собственные лицензии. Проект не связан с Microsoft.
