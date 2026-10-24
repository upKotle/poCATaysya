import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './style.css';

const el = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const status = el('status');
const button = el<HTMLButtonElement>('route');
const result = el('result');
const warnings = el('warnings');
const duration = el<HTMLSelectElement>('duration');
const extra = el<HTMLSelectElement>('extra');
let baselineSeconds: number | undefined;
type Point = {lat: number; lon: number};
type Config = {center: [number, number]; bounds: {south: number; north: number; west: number; east: number}};
type Segment = {geometry: {type: 'LineString'; coordinates: [number, number][]}; properties: {
  id: string; name: string; verification_status: 'draft' | 'reviewed'; source_url: string | null;
}};
type Route = {id: string; geometry: {coordinates: [number, number][]}; distance_meters: number; duration_seconds: number;
  scenic_segment_ids: string[]; scenic_category_meters?: Record<string, number>; explanation: string};
type RouteResponse = {routes: Route[]; warnings: string[]; baseline_duration_seconds?: number};
let mode: 'loop' | 'point' = 'loop';
let selected: 'a' | 'b' = 'a';
let a: Point | undefined, b: Point | undefined;
let markerA: L.Marker | undefined, markerB: L.Marker | undefined;
let line: L.Polyline | undefined;
let pending: AbortController | undefined;
let segments: Segment[] = [];
let routes: Route[] = [];
let activeRouteIndex = 0;
const variants = el('variants');
const preferenceKeys = ['water', 'architecture', 'greenery'] as const;
const preferences = () => Object.fromEntries(preferenceKeys.map(key => [key, Number(el<HTMLInputElement>(`pref-${key}`).checked)]));
const map = L.map('map').setView([55.751244, 37.618423], 12);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map).on('tileerror', () => { status.textContent = 'Не удалось загрузить часть карты. Проверьте интернет.'; });
// GeoJSON: [lon, lat]; Leaflet: [lat, lng]. Преобразуем только на границе карты.
const leafletCoordinates = (coords: [number, number][]): L.LatLngTuple[] => coords.map(([lon, lat]) => [lat, lon]);

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  let data;
  try { data = await response.json(); }
  catch { throw new Error('Backend не ответил корректно. Проверьте, что он запущен.'); }
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Проверьте параметры и выбранные точки.');
  return data as T;
}
function ready() { return Boolean(a && (mode === 'loop' || b)); }
function clearRoute() {
  pending?.abort(); pending = undefined;
  if (line) map.removeLayer(line);
  line = undefined; result.hidden = true; result.replaceChildren(); warnings.replaceChildren();
  routes = []; baselineSeconds = undefined; variants.replaceChildren(); variants.hidden = true; activeRouteIndex = 0;
  button.disabled = !ready();
}
function choose(value: 'a' | 'b') {
  selected = value;
  for (const key of ['a', 'b'] as const) {
    el(`choose-${key}`).classList.toggle('active', value === key);
    el(`choose-${key}`).setAttribute('aria-pressed', String(value === key));
  }
}
function updatePoints() {
  const format = (p?: Point) => p ? `${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}` : 'не выбрана';
  el('points').innerText = mode === 'loop' ? `Старт: ${a ? format(a) : 'не выбран'}` : `A: ${format(a)}\nB: ${format(b)}`;
  button.disabled = !ready();
}
function marker(point: Point, label: string) {
  return L.marker([point.lat, point.lon], {icon: L.divIcon({className: 'point-marker', html: label, iconSize: [32, 32], iconAnchor: [16, 16]})}).addTo(map);
}
function switchMode(next: 'loop' | 'point') {
  clearRoute(); mode = next;
  for (const key of ['loop', 'point'] as const) {
    el(`mode-${key}`).classList.toggle('active', mode === key);
    el(`mode-${key}`).setAttribute('aria-pressed', String(mode === key));
  }
  const loop = mode === 'loop';
  el('heading').textContent = loop ? 'Покататься' : 'Из A в B';
  el('instructions').textContent = loop ? 'Выберите старт на карте — найдём автомобильную поездку через участки каталога с возвращением обратно.' : 'Выберите A и B, предпочтения и допустимое дополнительное время — сравним обычный маршрут с красивыми альтернативами.';
  el('duration-field').hidden = !loop;
  el('extra-field').hidden = loop;
  el('choose-b').hidden = loop;
  el('choose-a').textContent = loop ? 'Выбрать старт' : 'Выбрать A';
  button.textContent = loop ? 'Построить поездку' : 'Найти красивый маршрут';
  if (markerB) { map.removeLayer(markerB); markerB = undefined; }
  b = undefined;
  choose(loop || !a ? 'a' : 'b'); updatePoints();
  status.textContent = loop ? 'Выберите старт и желаемое время.' : 'Выберите точки A и B.';
}
el('mode-loop').onclick = () => switchMode('loop');
el('mode-point').onclick = () => switchMode('point');
el('choose-a').onclick = () => choose('a');
el('choose-b').onclick = () => choose('b');
extra.onchange = () => { clearRoute(); status.textContent = 'Лимит изменён. Постройте маршрут заново.'; };
duration.onchange = () => { clearRoute(); status.textContent = 'Время изменено. Постройте поездку заново.'; };
for (const key of preferenceKeys) el<HTMLInputElement>(`pref-${key}`).onchange = () => {
  clearRoute(); status.textContent = 'Предпочтения изменены. Постройте поездку заново.';
};
el('reset').onclick = () => {
  clearRoute(); if (markerA) map.removeLayer(markerA); if (markerB) map.removeLayer(markerB);
  a = b = undefined; markerA = markerB = undefined; choose('a'); updatePoints();
  status.textContent = mode === 'loop' ? 'Выберите старт.' : 'Выберите точку A.';
};
async function init() {
  const [config, collection] = await Promise.all([
    api<Config>('/api/config'), api<{features: Segment[]}>('/api/scenic-segments')
  ]);
  segments = collection.features;
  for (const segment of segments) {
    L.polyline(leafletCoordinates(segment.geometry.coordinates), {color:'#bd6e22', weight:4, dashArray:'6 7', interactive:false}).addTo(map);
    const item = document.createElement('li');
    item.textContent = `${segment.properties.name} · ${segment.properties.verification_status === 'draft' ? 'черновик' : 'проверен'}`;
    el('catalog').append(item);
  }
  el('catalog-title').textContent = `Каталог: ${segments.length} дорожных участков`;
  const bounds = L.latLngBounds([config.bounds.south, config.bounds.west], [config.bounds.north, config.bounds.east]);
  L.rectangle(bounds, {color: '#478878', weight: 2, fillOpacity: 0.035, interactive: false}).addTo(map);
  map.fitBounds(bounds); status.textContent = 'Выберите старт на карте и желаемое время.';
  map.on('click', (event: L.LeafletMouseEvent) => {
    if (!bounds.contains(event.latlng)) { status.textContent = 'Выберите точку внутри выделенной области.'; return; }
    clearRoute();
    const point = {lat: event.latlng.lat, lon: event.latlng.lng};
    if (mode === 'loop' || selected === 'a') {
      a = point; if (markerA) map.removeLayer(markerA); markerA = marker(point, 'A');
      choose(mode === 'loop' ? 'a' : 'b');
    } else { b = point; if (markerB) map.removeLayer(markerB); markerB = marker(point, 'B'); }
    updatePoints();
    status.textContent = ready() ? 'Можно построить поездку.' : 'Теперь выберите точку B.';
  });
}
function renderVariants() {
  variants.replaceChildren(); variants.hidden = routes.length < 2;
  routes.forEach((route, index) => {
    const option = document.createElement('button');
    option.type = 'button';
    option.textContent = `${mode === 'point' ? (index === 0 ? 'Обычный маршрут' : `Красивый ${index}`) : `Вариант ${index + 1}`} · ≈ ${Math.max(1, Math.round(route.duration_seconds / 60))} мин · ${(route.distance_meters / 1000).toFixed(1)} км`;
    option.setAttribute('aria-pressed', String(index === activeRouteIndex));
    option.classList.toggle('active', index === activeRouteIndex);
    option.onclick = () => { showRoute(index); renderVariants(); };
    variants.append(option);
  });
}
function showRoute(index: number) {
  const route = routes[index];
  if (!route) return;
  activeRouteIndex = index;
  if (line) map.removeLayer(line);
  result.replaceChildren();
  line = L.polyline(leafletCoordinates(route.geometry.coordinates), {color:'#2463db', weight:6}).addTo(map);
  map.fitBounds(line.getBounds(), {padding:[30,30]});
  const stats = document.createElement('p'); stats.className = 'route-stats';
  stats.textContent = `${(route.distance_meters / 1000).toFixed(1)} км · ≈ ${Math.max(1, Math.round(route.duration_seconds / 60))} мин`;
  const explanation = document.createElement('p'); explanation.textContent = route.explanation;
  result.append(stats, explanation);
  if (mode === 'point' && baselineSeconds !== undefined) {
    const comparison = document.createElement('p');
    const delta = route.duration_seconds - baselineSeconds;
    comparison.textContent = `Обычный маршрут: ≈ ${(baselineSeconds / 60).toFixed(1)} мин. Разница: ${delta >= 0 ? '+' : '−'}${(Math.abs(delta) / 60).toFixed(1)} мин. Лимит: +${extra.value} мин.`;
    result.append(comparison);
  }
  if (route.scenic_category_meters) {
    const labels: Record<string,string> = {water:'вода',architecture:'архитектура',greenery:'зелень'};
    const facts = Object.entries(route.scenic_category_meters).filter(([,meters])=>meters>0).map(([key,meters])=>`${labels[key] ?? key} — ${(meters/1000).toFixed(1)} км`);
    if (facts.length) {
      const summary=document.createElement('p'); summary.className='small';
      summary.textContent='Участки по черновым оценкам каталога: '+facts.join('; ')+'. Категории могут пересекаться.';
      result.append(summary);
    }
  }
  if (route.scenic_segment_ids.length) {
    const names = document.createElement('ul');
    for (const id of route.scenic_segment_ids) {
      const segment = segments.find(s => s.properties.id === id);
      const item = document.createElement('li'); item.textContent = segment?.properties.name ?? id; names.append(item);
    }
    result.append(names);
  }
  result.hidden = false;
}
button.onclick = async () => {
  if (!ready()) return;
  clearRoute(); const controller = new AbortController(); pending = controller; button.disabled = true;
  const loop = mode === 'loop';
  status.textContent = loop ? 'Подбираем поездку через участки каталога… Это может занять до 40 секунд.' : 'Сравниваем обычный маршрут и красивые альтернативы… До 40 секунд.';
  const timer = window.setTimeout(() => controller.abort(), 50000);
  try {
    const data = await api<RouteResponse>(loop ? '/api/routes/loop' : '/api/routes/point-to-point', {
      method:'POST', headers:{'Content-Type':'application/json'}, signal:controller.signal,
      body:JSON.stringify(loop ? {start:a, target_duration_minutes:Number(duration.value), preferences:preferences()} : {start:a, end:b, max_extra_minutes:Number(extra.value), preferences:preferences()})
    });
    if (pending !== controller) return;
    for (const warning of data.warnings) {
      const item = document.createElement('li'); item.textContent = warning; warnings.append(item);
    }
    const route = data.routes[0];
    if (!route) { status.textContent = 'Подходящая поездка не найдена.'; return; }
    routes = data.routes;
    baselineSeconds = data.baseline_duration_seconds;
    renderVariants();
    showRoute(0);
    status.textContent = loop ? `Найдено поездок: ${routes.length}. Выберите вариант.` : `Обычный маршрут и красивых альтернатив: ${routes.length - 1}.`;
  } catch (error) {
    if (pending === controller) status.textContent = controller.signal.aborted ? 'Превышено время ожидания. Попробуйте ещё раз.' : error instanceof TypeError ? 'Нет соединения с backend. Проверьте его запуск.' : error instanceof Error ? error.message : 'Не удалось построить маршрут.';
  } finally {
    clearTimeout(timer); if (pending === controller) { pending = undefined; button.disabled = !ready(); }
  }
};
init().catch(() => { status.textContent = 'Не удалось загрузить настройки и каталог. Запустите backend и обновите страницу.'; });
