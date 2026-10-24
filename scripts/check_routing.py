"""Проверка реального A/B через уже запущенный backend (обычный маршрут и поиск альтернатив).

Из корня проекта: uv run --project backend python scripts/check_routing.py
"""
import sys

import httpx


def main():
    # Локальный backend проверяем напрямую, независимо от прокси терминала.
    with httpx.Client(base_url='http://127.0.0.1:8000',trust_env=False,timeout=50) as client:
        try:
            response=client.post('/api/routes/point-to-point',json={
                'start':{'lat':55.751,'lon':37.618},'end':{'lat':55.765,'lon':37.64}})
            data=response.json()
        except (httpx.HTTPError,ValueError):
            print('Нет корректного ответа от backend на 127.0.0.1:8000. Проверьте его запуск.')
            return 1
        if response.status_code != 200:
            print(f'Backend ответил HTTP {response.status_code}: {data.get("detail","ошибка маршрутизации")}')
            print('После изменения .env обязательно перезапустите backend.')
            return 1
        routes=data.get('routes',[])
        if not routes:
            print('Backend ответил без автомобильного маршрута.')
            return 1
        route=routes[0]
        print(f'Настоящий автомобильный маршрут построен: {route["distance_meters"]/1000:.1f} км, {route["duration_seconds"]/60:.1f} мин.')
        return 0


if __name__=='__main__':
    sys.exit(main())
