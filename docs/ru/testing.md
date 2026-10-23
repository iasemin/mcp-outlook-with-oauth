# Локальные проверки и результаты

[English](../en/testing.md)

## Повторить стенд

Нужны Docker, Python ≥3.12, uv и **существующий LiteLLM в Docker** с БД и management API. Проверенная версия шлюза — 1.96.0. Этот репозиторий LiteLLM не разворачивает.

```sh
uv sync --frozen
uv run python scripts/init_lab.py
# При необходимости заменить LITELLM_NETWORK в созданном .env
# и имя контейнера LiteLLM в deploy/nginx/default.conf.
docker compose up -d --build
# Дождаться healthy у Keycloak и MCP.
uv run python scripts/sync_keycloak.py
uv run python scripts/litellm_admin.py
uv run python scripts/acceptance.py
uv run python scripts/all_tools_acceptance.py
```

Значения по умолчанию соответствуют проверенному окружению: сеть `litellm_guardrails_default`, контейнер LiteLLM `litellm_guardrails-litellm-1`. Для другого контейнера задать `LITELLM_CONTAINER` при запуске Python-скриптов и изменить upstream nginx. `init_lab.py` перезаписывает `.env`; сетевые настройки править после него. `LITELLM_URL` заменяет адрес скриптов по умолчанию `http://localhost:8400`.

`litellm_admin.py` читает настроенный admin key существующего шлюза через Docker exec **в память**, затем регистрирует `outlook_lab` через management API. Запускать только администратору этого шлюза. Отдельные пользовательские ключи ограничены этим MCP. Внешние модели не вызываются.

Локальные адреса: ingress LiteLLM `:8400`, Keycloak `:8800`, MCP `:8766/mcp`, health `:8766/healthz`. Новые порты привязаны к localhost. Ingress сохраняет внутренний доступ без изменения глобальных IP-правил шлюза. Keycloak start-dev, HTTP localhost и сгенерированные пользователи — только для лаборатории.

Пароли и токены создаются в игнорируемых `.local/` и `.env`. Каталог приватен на хосте; права bind-файлов realm/mapping позволяют чтение UID контейнеров. Не добавлять их в Git. Секреты повторно используются, не ротируются; sync обновляет scope bindings уже импортированного realm. Почтовый клиент не использует password grant; setup отдельно работает с локальным bootstrap admin.

## Что проверили

Прогон 23.10.2026:

- **26 API/unit-тестов**: подпись, issuer, audience, срок, будущие claims, отказ ID token, scopes и привязка subject.
- **12 из 12 инструментов**, **59 вызовов через LiteLLM**: 29 успехов и 30 ожидаемых отказов. [Машиночитаемый отчёт](../all-tools-results.json).
- Настоящий Authorization Code + PKCE S256, хранение токенов пользователя шлюзом, истечение реального 45-секундного токена, автоматический и явный refresh.
- Синтетические письма/черновики, флаги, перемещение/восстановление, фильтрация адресатов, личные события; байты/hash скачанного вложения.
- Отказы при доступе к чужим объектам, узком scope, неверных аргументах, отсутствии подтверждения и повторной отправке.

```sh
uv run pytest -q
uv run ruff check src tests scripts
```

Полный tool-прогон отказывается работать, если `/healthz` сообщает backend не demo. Lifecycle-скрипт также ожидает синтетические данные. Python-тест имитирует браузерное localhost-исключение Secure cookies только для лабораторных пользователей; эту обработку нельзя переносить в удалённый production-клиент.

Синтетический backend не доставляет почту и не эмулирует Exchange. EWS-аутентификация, RBAC, доставка и CU15 ещё не проверены. Kubernetes YAML разобран, но не испытан в кластере. Тесты с mock не являются доказательством живого подключения Exchange.

Остановка: `docker compose stop`. `docker compose down` удалит контейнеры стенда, сохранив PostgreSQL volume. Существующий LiteLLM и его запись `outlook_lab` не удаляются. Хранить сгенерированные секреты вместе с сохранённой БД Keycloak.
