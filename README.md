# Лабораторная работа № 2 — контейнеризация и деплой веб-API

## Состав проекта

- `app/` — FastAPI-приложение, модели SQLAlchemy и подключение к PostgreSQL.
- `Dockerfile` — двухступенчатая сборка `builder` / `runtime`, запуск под непривилегированным пользователем.
- `docker-compose.yml` — API, PostgreSQL, Redis, Nginx, Prometheus и Grafana с healthcheck.
- `nginx.conf` — reverse proxy к API.
- `prometheus.yml`, `alerts.yml` — сбор метрик и правила алертов.
- `grafana/` — источник данных и dashboard для Grafana.
- `.github/workflows/ci.yml` — автоматические тесты и сборка образа при push/pull request.
- `tests/` — базовые тесты CRUD, валидации, Swagger и `/metrics`.

## Быстрый запуск в Windows PowerShell

1. Установите и запустите Docker Desktop с backend WSL 2. В VS Code откройте эту папку.
2. Создайте локальный файл конфигурации:

   ```powershell
   Copy-Item .env.example .env
   ```

3. Проверьте Docker и Compose:

   ```powershell
   docker --version
   docker compose version
   docker info
   ```

4. Соберите и запустите весь стек:

   ```powershell
   docker compose up --build -d
   ```

5. Посмотрите состояние контейнеров и логи:

   ```powershell
   docker compose ps
   docker compose logs --tail 100 api
   ```

6. Откройте в браузере:
   - Swagger напрямую: <http://localhost:8000/docs>
   - Swagger через Nginx: <http://localhost:8080/docs>
   - Health: <http://localhost:8000/health>
   - Prometheus: <http://localhost:9090/targets>
   - Grafana: <http://localhost:3000> (логин `admin`, пароль из `.env`, по умолчанию `admin123`)

## Проверка API через Swagger

1. В `/docs` раскройте `POST /tasks` → **Try it out**.
2. Используйте JSON:

   ```json
   {"title":"Прочитать методичку","description":"Проверить TODO API","completed":false}
   ```

3. Нажмите **Execute**. Ожидается HTTP `201` и объект задачи с числовым `id`.
4. Выполните `GET /tasks`, затем `GET /tasks/{task_id}`.
5. Для завершения задачи выполните `PUT /tasks/{task_id}` с телом `{"completed":true}`.
6. Выполните `GET /stats` и `DELETE /tasks/{task_id}`.
7. Для проверки обработки ошибок запросите несуществующий ID: ожидается `404`.

## Метрики и мониторинг

После нескольких API-запросов откройте `http://localhost:9090/targets`: цель `todo-api` должна иметь состояние `UP`. В Prometheus можно выполнить запросы:

- `todo_api_requests_total` — число API-запросов.
- `rate(todo_api_requests_total[5m])` — скорость поступления запросов.
- `histogram_quantile(0.95, sum by (le) (rate(todo_api_request_duration_seconds_bucket[5m])))` — p95 времени ответа.
- `todo_tasks_total` — количество задач в PostgreSQL.

В Grafana откройте **Dashboards → TODO API → TODO API — мониторинг**. На dashboard предусмотрены панели числа запросов, p95 и количества задач. Данные на графиках появятся после scrape и создания нескольких задач; при необходимости обновите страницу.

## Локальные тесты без Docker

При установленном Python 3.11 из корня проекта выполните:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## Остановка

```powershell
docker compose down
```

Команда удаляет контейнеры, но сохраняет данные в именованных volumes. Чтобы удалить ещё и учебные данные PostgreSQL/Redis/мониторинга, используйте `docker compose down -v`.

## Важные замечания

- Пароли из `.env.example` предназначены только для локальной учебной среды. Не публикуйте `.env` и не используйте эти значения в production.
- Образы Prometheus/Grafana фиксированы на версиях для воспроизводимости учебной работы.
- HTTPS и аутентификация API из дополнительных заданий отдельно не включены в базовый вариант.

## Сравнение размеров Docker-образов

`Dockerfile.baseline` оставляет инструменты сборки в единственной стадии и нужен только для учебного сравнения. Выполните:

```powershell
docker build -f Dockerfile.baseline -t todo-api:baseline .
docker build --target runtime -f Dockerfile -t todo-api:multistage .
docker images todo-api
```

Запишите реальные значения `SIZE` из вывода в отчет. Результат зависит от платформы, версии базового образа и кэша; не подставляйте заранее придуманные размеры.
