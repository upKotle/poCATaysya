# Сторонние данные и компоненты

Код Scenic Drive: [MIT](LICENSE). Зависимости сохраняют собственные лицензии;
списки точных версий находятся в `backend/uv.lock` и `frontend/package-lock.json`.

- Дорожный каталог: © OpenStreetMap contributors, [ODbL 1.0](data/moscow/LICENSE.md).
- Тайлы карты: OpenStreetMap Standard, © OpenStreetMap contributors.
  [Лицензирование](https://www.openstreetmap.org/copyright),
  [правила использования тайлов](https://operations.osmfoundation.org/policies/tiles/).
  Скриншот интерфейса включает карту OSM с видимой атрибуцией;
  он не является независимым картографическим набором данных.
- Маршрутизатор OSRM: [BSD-2-Clause](https://github.com/Project-OSRM/osrm-backend/blob/v5.27.1/LICENSE.TXT).
- Leaflet: [BSD-2-Clause](https://github.com/Leaflet/Leaflet/blob/v1.9.4/LICENSE).
- Необязательный внешний OSRM: [условия FOSSGIS](https://routing.openstreetmap.de/about.html).
  Он не включён в исходники и не нужен при локальном запуске маршрутизатора.

Большие OSM-extract и подготовленные графы OSRM не распространяются с этим репозиторием.
Их источник, лицензия и дата скачивания должны сохраняться при собственной подготовке.
