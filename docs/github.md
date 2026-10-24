# Проверки и публикация

## Проверки исходников

Из корня репозитория:

```sh
uv sync --project backend --python 3.12 --locked
uv run --project backend --locked pytest backend/tests -q
npm ci --prefix frontend
npm run build --prefix frontend
docker compose -f compose.external.yml config --quiet
docker compose -f compose.external.yml up --build --wait --wait-timeout 120
```

Приложение откроется на http://127.0.0.1:8080. Последняя команда требует
работающего Docker daemon. Четыре сетевых теста по умолчанию пропущены;
порядок их запуска описан в [README](../README.md).

Workflow `Checks` запускается на push и pull request: проверяет backend,
production build frontend и оба варианта контейнерного запуска.
CI не скачивает карту и не вызывает публичный OSRM. Реальная маршрутизация
проверяется отдельно интеграционными тестами.

## Публикация образа

После успешного `Checks` откройте Actions → `Publish app image` → Run workflow
и выберите основную ветку. Workflow повторно проверит приложение, соберёт
и запустит единый образ, затем опубликует его в GitHub Container Registry.
Push исходников сам по себе образ не публикует.

[Адрес образа, доступ и команды запуска](docker-external.md#готовый-образ-на-github).

В репозитории остаются исходники, тесты, lock-файлы, небольшой каталог дорог,
лицензии и инструкции. Локальные `.env`, зависимости, сборки frontend,
большие карты и графы OSRM исключены из Git.
Все 27 участков каталога пока draft и требуют ручной проверки.
