# Локальная автомобильная маршрутизация

Публичный сервер OSRM не является обязательной зависимостью. Backend по умолчанию обращается к `http://localhost:5000`. Нужен Docker и extract OSM с дорогами Москвы и запасом за рабочей областью. Подготовка данных может потребовать несколько ГБ RAM и некоторое время.
Нужен доступ к Docker daemon: сначала проверьте `docker info`. Ошибка `permission denied`
означает отсутствие доступа к службе Docker, а не ошибку маршрутизатора.

1. Скачайте актуальный `.osm.pbf` из [Geofabrik — Central Federal District](https://download.geofabrik.de/russia/central-fed-district.html). Создайте `mkdir -p data/osrm` и сохраните файл как `data/osrm/region.osm.pbf`.
Запишите дату/URL загрузки в локальный файл `data/osrm/SOURCE.txt`.
Весь этот каталог исключён из Git и Docker build context. Это большой регион; для небольшой локальной карты обрежьте его инструментом osmium, установленным отдельно:

```sh
mkdir -p data/osrm
osmium extract --bbox=37.20,55.45,38.00,56.00 \
  data/osrm/region.osm.pbf -o data/osrm/moscow.osm.pbf
```

Координаты bbox — технический запас вокруг центра, а не проверенная граница дорожного покрытия. У обрезанного extract возможны потери дальних объездов. Данные Geofabrik/OpenStreetMap распространяются по ODbL; сохраните дату скачивания для воспроизводимости.

2. Из корня проекта выполните подготовку одним и тем же закреплённым образом OSRM, автомобильный профиль и MLD pipeline:

```sh
docker run --rm -v "$PWD/data/osrm:/data" ghcr.io/project-osrm/osrm-backend:v5.27.1 \
  osrm-extract -p /opt/car.lua /data/moscow.osm.pbf
docker run --rm -v "$PWD/data/osrm:/data" ghcr.io/project-osrm/osrm-backend:v5.27.1 \
  osrm-partition /data/moscow.osrm
docker run --rm -v "$PWD/data/osrm:/data" ghcr.io/project-osrm/osrm-backend:v5.27.1 \
  osrm-customize /data/moscow.osrm
```

3. Основной запуск всего проекта через Compose:

```sh
docker compose config --quiet
docker compose up --build --wait --wait-timeout 180
```

Откройте **http://127.0.0.1:8080**. Все команды выполняются из корня проекта.
OSRM монтирует `data/osrm` только для чтения. Если каталог отсутствует, Compose
сообщит об ошибке bind mount; если не завершён MLD pipeline, OSRM не станет healthy.
Проверьте `docker compose logs osrm` и наличие файлов `moscow.osrm.*`.
Не ожидайте обязательно отдельный файл `moscow.osrm`: данные представлены набором
файлов с этим префиксом. Используйте одну версию образа на всех шагах.
Если медленный компьютер не уложился в ожидание, посмотрите логи и повторите
`docker compose up --wait --wait-timeout 300`.

Проверка работающей связки (не только healthcheck):

```sh
curl --fail http://127.0.0.1:8080/api/health
curl --fail -X POST http://127.0.0.1:8080/api/routes/point-to-point \
  -H 'Content-Type: application/json' \
  -d '{"start":{"lat":55.74,"lon":37.59},"end":{"lat":55.765,"lon":37.64},"max_extra_minutes":15,"preferences":{"water":1,"architecture":0,"greenery":0}}'
```

Поиск может занять до 40 секунд. Должна появиться геометрия дороги и обычный
маршрут; красивые альтернативы зависят от версии карты и небольшого каталога.
В браузере линия должна идти по дорогам, учитывая развязки и одностороннее движение.
Свежесть ограничений и реальную доступность дорог нужно проверять отдельно.

Остановка: `docker compose down`. Карты на диске сохранятся. После изменения
кода пересоберите приложения: `docker compose up --build --wait --wait-timeout 180`.

## Только маршрутизатор для запуска Python/Vite на компьютере

Вместо Compose можно оставить этот терминал открытым:

```sh
docker run --rm -p 127.0.0.1:5000:5000 -v "$PWD/data/osrm:/data:ro" \
  ghcr.io/project-osrm/osrm-backend:v5.27.1 \
  osrm-routed --algorithm mld /data/moscow.osrm
```

Backend запускается с `OSRM_BASE_URL=http://localhost:5000` как в README.
Этот порт не публикуется при запуске полного Compose: внутри Docker backend
обращается к `http://osrm:5000`, а браузер — к nginx на 8080.

OSRM и pipeline: [официальный репозиторий](https://github.com/Project-OSRM/osrm-backend/tree/v5.27.1).
[Ожидание готовности зависимостей Compose](https://docs.docker.com/compose/how-tos/startup-order/).
Большие карты и подготовленные `.osrm*` файлы исключены из Git. Не размещайте их в исходниках.
