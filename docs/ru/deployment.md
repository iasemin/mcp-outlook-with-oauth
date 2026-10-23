# Развёртывание и настройка

[English](../en/deployment.md) · [Архитектура](architecture.md)

## Сборка

```sh
git clone https://github.com/iasemin/mcp-outlook-with-oauth.git
cd mcp-outlook-with-oauth
docker buildx build --platform linux/amd64 \
  -t YOUR_REGISTRY/mcp-outlook-with-oauth:0.2.0 --push .
```

Готовый образ пока не опубликован. Архитектура сборки должна совпадать с нодами Kubernetes; на Apple Silicon сборка по умолчанию ARM64.

## Что подготовить на Exchange

Два тестовых ящика и отдельную служебную AD-учётную запись. В Exchange Management Shell заменить примеры alias/логина и проверить scope до выдачи прав:

```powershell
Get-ExchangeServer | Format-Table Name,AdminDisplayVersion
Get-WebServicesVirtualDirectory | Format-List Identity,InternalUrl,WindowsAuthentication,ExtendedProtectionTokenChecking
Get-CASMailbox mcp-test-a@corp.example | Format-List Ews*
New-ManagementScope -Name "OutlookMCP-TestMailboxes" -RecipientRestrictionFilter "(Alias -eq 'mcp-test-a') -or (Alias -eq 'mcp-test-b')"
Get-Recipient -Filter (Get-ManagementScope "OutlookMCP-TestMailboxes").RecipientFilter | Format-Table Alias,PrimarySmtpAddress
New-ManagementRoleAssignment -Name "OutlookMCP-TestImpersonation" -Role ApplicationImpersonation -User "CORP\svc-outlook-mcp" -CustomRecipientWriteScope "OutlookMCP-TestMailboxes"
```

Preview должен содержать только согласованные ящики. Другие назначения не должны расширять права службы. Не выдавать impersonation на всю организацию. Адаптер использует EWS HTTPS + NTLM; при запрете NTLM понадобится другой адаптер. TLS и Extended Protection сохраняются, включая принятую схему балансировки.

Записать точную сборку CU15/SU/HU и реальные результаты. [Microsoft: ограниченный impersonation](https://learn.microsoft.com/en-us/exchange/client-developer/exchange-web-services/how-to-configure-impersonation), [Extended Protection](https://learn.microsoft.com/en-us/exchange/plan-and-deploy/post-installation-tasks/security-best-practices/exchange-extended-protection).

## AAS (Keycloak на стенде), MCP и LiteLLM

**OAuth2-клиент AAS — сам MCP.** Зарегистрировать confidential client `outlook-mcp`, передать его секрет только MCP:

- Authorization Code, PKCE S256; callback `https://YOUR_MCP/auth/callback`.
- Access token: стабильный `sub`, ожидаемые `iss`, `aud=outlook-mcp`, `exp`, `typ=Bearer`, `scope`; текущий verifier поддерживает RS256 JWT. Для opaque-токенов или другого контракта AAS потребуется адаптер.
- Scopes из таблицы ниже выдаются по политикам IdP. На тестовом Keycloak они optional; парольный grant выключен.

MCP публикует `/.well-known/oauth-authorization-server`, `/register`, `/authorize`, `/token`, `/auth/callback` и `/mcp`. В ingress нужно открыть все эти пути, `/consent` и protected-resource discovery. MCP сам обменивает код и обновляет токены у AAS. Пользователь подтверждает доступ на consent-странице MCP, затем входит в AAS. Пароль пользователя вводится только на стороне AAS.

LiteLLM регистрируется **у MCP**, а не у AAS: `POST https://YOUR_MCP/register` с `redirect_uris=["https://YOUR_LITELLM/callback"]`, `token_endpoint_auth_method="none"`, `grant_types=["authorization_code","refresh_token"]`, `response_types=["code"]`. Ответ содержит отдельный downstream `client_id`. Разрешённый redirect заранее задать в `OUTLOOK_CLIENT_REDIRECT_URIS`.

В LiteLLM: HTTP URL `https://YOUR_MCP/mcp`, `auth_type=oauth2`, `oauth2_flow=authorization_code`, полученный client ID, endpoints `https://YOUR_MCP/authorize` и `https://YOUR_MCP/token`, нужные scopes. Не передавать LiteLLM client ID/secret AAS. Для discovery issuer — MCP; issuer AAS остаётся в настройках самого MCP. На стенде используются раздельные browser/Docker URL и ручные endpoints без issuer в LiteLLM.

Каждому пользователю нужен отдельный LiteLLM `user_id` и разрешённый virtual key. LiteLLM хранит MCP-токены; upstream access/refresh tokens AAS хранятся **в MCP в зашифрованном виде**. Сохранить постоянный signing key и каталог OAuth-состояния: потеря любого из них потребует повторной регистрации LiteLLM у MCP и входа пользователей. Смена signing key также меняет ключ шифрования. Резервные копии считать секретными.

Это меняет роль MCP в OAuth, но не транспорт EWS: пока используется служебная AD-учётка с impersonation. Получение паролей из AAS и вход в Exchange пользовательским токеном не реализованы. Их нельзя вывести из стандартного OAuth2 без контракта платформы.

## Настройки MCP и файлы

| Переменная | Пример |
|---|---|
| OUTLOOK_AUTH_MODE | `proxy` (по умолчанию); `resource` — прежний режим проверки токенов |
| OUTLOOK_AUTHORIZATION_ENDPOINT | `https://aas.corp.example/authorize` |
| OUTLOOK_TOKEN_ENDPOINT | `https://aas.corp.example/token` |
| OUTLOOK_OAUTH_CLIENT_ID | `outlook-mcp` — зарегистрирован в AAS |
| OUTLOOK_OAUTH_CLIENT_SECRET_FILE | `/run/oauth-secrets/aas-client-secret` |
| OUTLOOK_OAUTH_SIGNING_KEY_FILE | `/run/oauth-secrets/oauth-signing-key` — постоянный случайный секрет, ≥32 символов |
| OUTLOOK_OAUTH_STORAGE_DIR | `/var/lib/outlook-mcp/oauth` — постоянный том, запись для UID 10001 |
| OUTLOOK_CLIENT_REDIRECT_URIS | `["https://YOUR_LITELLM/callback"]` — JSON-список точных URL |
| OUTLOOK_TOKEN_ENDPOINT_AUTH_METHOD | `client_secret_basic` (по умолчанию) или `client_secret_post` |
| OUTLOOK_BACKEND | `ews` (`demo` — только синтетические данные) |
| OUTLOOK_ISSUER | `https://sso.corp.example/realms/corp` |
| OUTLOOK_JWKS_URI | `https://sso.corp.example/realms/corp/protocol/openid-connect/certs` |
| OUTLOOK_AUDIENCE | `outlook-mcp` |
| OUTLOOK_PUBLIC_URL | `https://mail-mcp.corp.example` — origin **без** `/mcp` |
| OUTLOOK_EWS_ENDPOINT | `https://exchange.corp.example/EWS/Exchange.asmx` |
| OUTLOOK_EWS_USERNAME | `CORP\svc-outlook-mcp` |
| OUTLOOK_EWS_PASSWORD_FILE | `/run/secrets/ews-password` |
| OUTLOOK_MAPPING_FILE | `/run/config/mailboxes.json` |
| REQUESTS_CA_BUNDLE / SSL_CERT_FILE | `/run/ca/ca.pem` |

Пароль монтируется отдельным секретом. CA bundle должен обеспечивать доверие к Exchange и Keycloak; проверку сертификатов не отключать. Внутренний порт контейнера — **8766**.

`mailboxes.json` управляется администратором и содержит реальные UUID `sub` из Keycloak:

```json
{
  "KEYCLOAK_SUBJECT_A": "mcp-test-a@corp.example",
  "KEYCLOAK_SUBJECT_B": "mcp-test-b@corp.example"
}
```

## Kubernetes и контейнеры

Использовать `deploy/k8s/mcp.yaml`. Заменить DNS и image. В namespace `outlook-mcp` подготовить:

- Secret `outlook-ews`: ключи `username`, `ews-password`.
- Secret `outlook-oauth`: ключи `aas-client-secret`, `oauth-signing-key`.
- PVC `outlook-oauth-state` для шифрованного OAuth-состояния (UID 10001).
- ConfigMap `outlook-mailbox-mapping`: ключ `mailboxes.json`.
- ConfigMap `outlook-ca`: ключ `ca.pem`.
- Доступ к registry и внутренний TLS ingress для MCP и его OAuth-путей по правилам вашей платформы.

В манифесте одна реплика, стратегия Recreate и PVC: HTTP MCP stateless, но OAuth-прокси хранит состояние. Не масштабировать этот файловый store на несколько реплик; для этого потребуется общий сетевой backend и проверка конкурентного refresh. Demo также хранит письма в памяти. Манифест не проверен в кластере.

Для внутреннего Docker-хоста с существующим LiteLLM есть `compose.internal.yaml`: заполнить `deploy/internal.env.example`, смонтировать файлы из `.local/internal`, использовать отдельный Compose project. Exchange и Keycloak этим файлом не устанавливаются.

## Инструменты и scopes

| Scope | Инструменты |
|---|---|
| Валидный пользователь из mapping, без operation scope | whoami |
| outlook.read | list_folders, search_emails, get_email, get_attachment |
| outlook.write | save_draft, mark_email_read, move_email |
| outlook.send | send_draft; дополнительно confirm=true |
| contacts.read | search_contacts |
| calendar.read | list_events |
| calendar.write | save_event |

Ограничения: выдача ≤100 объектов, тело письма ≤50 000 символов, файловые EWS-вложения ≤5 МиБ. Запись в календарь создаёт личное событие без приглашений. Удаление — перемещение в корзину через `move_email`. `confirm=true` не заменяет разрешение человека.

## Приёмка и обновления

1. OAuth-вход → `whoami`: правильный SMTP, backend=ews. Этот инструмент не обращается к Exchange.
2. `list_folders` → `search_emails` → `get_email` на подготовленном реальном письме.
3. Скачать вложение и сверить байты/hash; найти адресата; прочитать подготовленный календарный интервал.
4. Сохранить/прочитать настоящий черновик; изменить/вернуть флаг прочтения; переместить/восстановить тестовое письмо (EWS ID может измениться); создать событие и проверить в OWA.
5. После явного разрешения отправить только между тестовыми ящиками: проверить Sent Items **и получение адресатом**. При timeout не отправлять повторно вслепую.
6. Проверить отказ B в доступе к объектам A, запрет write/send с узким scope, истечение/refresh токенов и отказ Exchange в impersonation за пределами scope.

Проверять MCP `isError`, а не только HTTP 200. `/healthz` отражает процесс и возвращает `exchange_verified=false`; это не доказательство доступа к ящику. Форматы реальных EWS-ответов могут отличаться от demo.

После изменения mapping/secrets/config перезапустить Deployment. Откат: остановить только этот MCP, убрать доступ в LiteLLM, отозвать его OAuth-сессии и созданные для испытания Exchange role/scope. Синтетические acceptance-скрипты не использовать для отправки реальной почты.
