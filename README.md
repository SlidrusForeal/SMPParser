# README

## Описание проекта
Этот проект представляет собой асинхронный парсер данных игроков с сайта "serverchichi.online". Он включает в себя функции для входа в систему, получения списка игроков, обработки профилей и генерации HTML-отчета.

## Возможности
- Асинхронный сбор данных о профилях игроков.
- Автоматическая повторная попытка при возникновении ошибок сетевого запроса.
- Кэширование данных для предотвращения избыточных запросов.
- Генерация HTML-отчета с возможностью фильтрации и поиска.
- Логирование событий и ошибок в файл.
- Сохранение неполных данных для дальнейшей обработки.

## Установка
1. Установите зависимости:

    ```bash
    pip install -r requirements.txt
    ```

2. Создайте файл `.env` и укажите в нем учетные данные:

    ```plaintext
    USERNAME=ваш_логин
    PASSWORD=ваш_пароль
    ```

## Использование
1. Запустите скрипт с помощью Python:

    ```bash
    python main.py --offset 0
    ```

2. Доступные аргументы командной строки:
    - `--offset` - С какого номера начинать обработку списка игроков (по умолчанию 0).

## Основные компоненты
- **`login(session, username, password)`**: Функция для авторизации пользователя.
- **`fetch_players(session, offset)`**: Получает список игроков с заданного офсета.
- **`parse_player_profile(html_content)`**: Извлекает информацию о профиле игрока из HTML-страницы.
- **`process_players(session, players, cache, semaphore, progress_bar)`**: Обрабатывает список игроков асинхронно.
- **`generate_html_report(cache, previous_cache)`**: Генерирует отчет в формате HTML.
- **`validate_player_data(data)`**: Проверяет наличие ключевых полей и сохраняет данные даже при их частичном отсутствии.

## Логирование
Все события записываются в файл `app.log`. Формат сообщений:

```plaintext
2025-01-24 12:00:00 - INFO - Успешный вход в систему!
2025-01-24 12:05:00 - ERROR - Ошибка при загрузке списка игроков: ClientError
2025-01-24 12:10:00 - WARNING - Невалидные данные для игрока username123, сохранены частично.
```

## Структура проекта
```
.
├── app.log
├── main.py
├── player_data.json
├── players_report.html
├── requirements.txt
├── .env
└── README.md
```

## Зависимости
- Python 3.9+
- aiohttp
- asyncio
- BeautifulSoup
- dotenv
- logging
- tenacity
- tqdm
- json
- argparse

## Авторы
Проект разработан командой энтузиастов для мониторинга игрового сервера.

