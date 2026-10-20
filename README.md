# IP API

Мини-сервис, который показывает ваш публичный IP-адрес и его геолокацию:
страна, регион, город, провайдер, организация и ASN.

Однофайловый HTTP-сервер на чистой стандартной библиотеке Python — без
зависимостей. Геоданные берутся из [ipwho.is](https://ipwho.is) и
кэшируются.

## Возможности

- Веб-страница с IP-адресом, кнопкой «скопировать» и геоданными
- Эндпоинт `/api` — только IP-адрес, plain text (удобно для скриптов)
- Корректное определение реального IP за доверенным reverse-proxy
  (`X-Forwarded-For`)
- Кэш геоданных с настраиваемым TTL; ошибки кэшируются на 60 секунд
- Тред-сервер, работает без внешних зависимостей
- Docker-образ, собирается и публикуется в GHCR автоматически

## Эндпоинты

| Путь | Ответ |
|------|-------|
| `GET /` | HTML-страница с IP и геоданными |
| `GET /api` | IP-адрес, `text/plain` |

Пример:

```console
$ curl http://localhost:8085/api
203.0.113.42
```

## Переменные окружения

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `PORT` | `8085` | Порт, на котором слушает сервис |
| `TRUSTED_PROXY` | *(пусто)* | Список IP/сетей доверенных прокси через запятую. Только они могут задавать `X-Forwarded-For`. Пример: `192.168.88.49,10.0.0.0/8` |
| `GEO_CACHE_TTL` | `3600` | Время жизни успешного результата геоданных в секундах |
| `GEO_TIMEOUT` | `5` | Таймаут запроса к ipwho.is в секундах |

## Запуск

### Docker Compose

```bash
# 1. Замените OWNER в docker-compose.yml на свой GitHub-юзернейм/орг
# 2. Запустите
docker compose up -d
```

### Docker напрямую

```bash
docker run -d --name ip-api --restart unless-stopped \
  -p 8085:8085 \
  -e TRUSTED_PROXY=192.168.88.49 \
  -e GEO_CACHE_TTL=3600 \
  -e GEO_TIMEOUT=5 \
  ghcr.io/OWNER/ip-api:latest
```

### Сборка образа из исходников

```bash
docker build -t ip-api .
docker run -d --name ip-api -p 8085:8085 ip-api
```

### Без Docker

Нужен только Python 3.10+, зависимости не требуются:

```bash
python3 app.py
```

### За reverse-proxy (Nginx)

```nginx
location / {
    proxy_pass http://127.0.0.1:8085;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

И добавьте IP прокси в `TRUSTED_PROXY`, например `TRUSTED_PROXY=127.0.0.1`.

## Как определяется IP

1. Если соединение пришло напрямую (peer не из `TRUSTED_PROXY`) —
   используется адрес самого соединения.
2. Если peer — доверенный прокси, цепочка `X-Forwarded-For`
   читается справа налево, и берётся первый адрес, который **не**
   входит в `TRUSTED_PROXY`.
3. Если цепочка пустая или содержит некорректные значения —
   используется адрес соединения.

## GitHub Actions

Ветка `main` запускает workflow `.github/workflows/ci.yml`:

1. **test** — pytest-тесты на Python 3.12
2. **docker** — сборка образа и публикация в GHCR
   (`ghcr.io/<owner>/ip-api`) с тегами `latest`, по ветке и по SHA

Для публикации образа в репозитории нужно включить
**Settings → Packages → General → Read access for workflows and actions**
(или оставить `Read and write`), если репозиторий приватный.

## Тесты

```bash
pip install pytest
pytest -q
```

## Структура проекта

```
.
├── app.py                  # весь сервис
├── tests/
│   └── test_app.py         # тесты (IP-разрешение, кэш, рендер, HTTP)
├── Dockerfile
├── docker-compose.yml
├── .github/workflows/ci.yml
└── README.md
```
