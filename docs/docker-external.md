# Один Docker-контейнер с внешним OSRM

В корневом `Dockerfile` frontend собирается через Node.js, затем готовые HTML/JS/CSS,
backend и небольшой каталог попадают в один Python-образ. FastAPI обслуживает UI
и `/api` с одного адреса. Локального OSRM, nginx и больших OSM-файлов здесь нет.
Обычный `docker-compose.yml` оставлен для отдельного варианта с локальным OSRM.

## Сборка и запуск

Из корня проекта, Docker daemon должен быть доступен:

```sh
docker info
docker compose -f compose.external.yml config --quiet
docker compose -f compose.external.yml up --build --wait --wait-timeout 120
```

Откройте **http://127.0.0.1:8080**. API-документация — на `/docs`, проверка жизни
приложения — `/api/health`. Браузеру нужен интернет для тайлов, контейнеру — для OSRM.
Healthcheck не обращается к внешнему маршрутизатору.

```sh
docker compose -f compose.external.yml logs --tail=100
docker compose -f compose.external.yml down
```

Можно обойтись без Compose:

```sh
docker build -t scenic-drive:local .
docker run --rm -p 127.0.0.1:8080:8000 scenic-drive:local
```

## Настройка сервера и прокси

По умолчанию используется `https://router.project-osrm.org`. Нужные настройки
передаются при запуске, не при сборке. `.env` обычного Python-запуска не попадает
в образ. Для Compose используются отдельные `SCENIC_*` переменные, чтобы случайно
не перенести адрес локального OSRM или localhost-прокси внутрь контейнера.

При необходимости создайте локальный `.env.docker` по образцу `.env.docker.example`
(не перезаписывайте существующий файл) и запустите:

```sh
docker compose --env-file .env.docker -f compose.external.yml up --build --wait --wait-timeout 120
```

Пример содержимого:

```dotenv
SCENIC_OSRM_BASE_URL=https://router.project-osrm.org
SCENIC_OSRM_PROXY_URL=http://host.docker.internal:10809
```

`10809` замените HTTP/mixed-портом своего клиента. Контейнерный `127.0.0.1` — сам
контейнер; `host.docker.internal` обращается к компьютеру. В Compose добавлено
соответствующее сопоставление для Linux. Прокси должен принимать подключения из
Docker-сети: если он слушает только loopback, такое подключение не пройдёт.

Для Linux есть вариант использовать loopback-прокси через сеть компьютера.
Сначала соберите образ, освободите порт 8000 (остановите обычный backend), затем:

```sh
docker run --rm --network host \
  -e OSRM_PROXY_URL=http://127.0.0.1:10809 \
  scenic-drive:local \
  uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Адрес этого варианта — **http://127.0.0.1:8000**. Он предназначен для Linux.
Сетевые настройки и локальный `.env.docker` не публикуются на GitHub.

## Правила внешнего OSRM

Публичный сервер — для разумного личного использования, максимум один запрос
в секунду, без тяжёлой нагрузки. Координаты передаются провайдеру и сохраняются
в его логах. В приложении один worker, ограничение частоты и кэш. Не запускайте
несколько реплик с общей нагрузкой на demo. Образ с внешним demo не предназначен
для публичного сервиса с несколькими пользователями.

[Условия FOSSGIS](https://routing.openstreetmap.de/about.html).
[Раздача статики FastAPI](https://fastapi.tiangolo.com/tutorial/static-files/).
[Docker host-gateway](https://docs.docker.com/reference/cli/docker/container/run/#add-host).

## Готовый образ на GitHub

Workflow `Publish app image` (`.github/workflows/publish-image.yml`) запускается
вручную во вкладке Actions из основной ветки. Он выполняет тесты, собирает образ,
запускает его и проверяет UI/API, затем публикует:

- `ghcr.io/upkotle/pocataysya:latest`;
- `ghcr.io/upkotle/pocataysya:sha-COMMIT` — точная версия для воспроизводимого запуска.

OWNER/REPOSITORY автоматически приводятся к нижнему регистру. Workflow использует
временный `GITHUB_TOKEN`; отдельный персональный токен для публикации из Actions
не нужен. Если организация запрещает Packages, потребуются её настройки доступа.
Публикация не выполняется на каждый push и не разворачивает приложение на сервере.
Образ workflow рассчитан на Linux amd64.

Для публичного образа проверьте видимость пакета в GitHub → Packages → Package
settings: первая публикация может создать приватный пакет. Публичный образ можно
скачать без авторизации; приватный требует доступа и входа в GHCR.

```sh
docker run --rm -p 127.0.0.1:8080:8000 ghcr.io/upkotle/pocataysya:latest
```

Для форка адрес пакета определяется владельцем и названием репозитория. Настройки прокси можно передать
тем же способом, что при запуске локально собранного образа.

[Публикация образов из Actions](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images).
[GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).
