import aiohttp
import asyncio
from bs4 import BeautifulSoup
import logging
from dotenv import load_dotenv
import os
from typing import Optional, Dict, List, Any
import argparse
import re
import orjson
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from collections import defaultdict
from tqdm.asyncio import tqdm_asyncio

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования: вывод в консоль и файл
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Глобальные константы
CACHE_FILE = 'player_data.json'
HTML_REPORT = 'players_report.html'
MAX_CONCURRENT_REQUESTS = 5
RETRY_ATTEMPTS = 3


class Statistics:
    """
    Класс для сбора статистики выполнения программы.
    """
    def __init__(self) -> None:
        self.start_time = datetime.now()
        self.players_processed = 0
        self.requests_made = 0
        self.retries = 0
        self.failures = defaultdict(int)
        self.success = 0

    def log_request(self) -> None:
        self.requests_made += 1

    def log_retry(self) -> None:
        self.retries += 1

    def log_failure(self, error_type: str) -> None:
        self.failures[error_type] += 1

    def log_success(self) -> None:
        self.success += 1

    def get_report(self) -> str:
        duration = datetime.now() - self.start_time
        return (
            f"Статистика выполнения:\n"
            f"- Время выполнения: {duration}\n"
            f"- Обработано игроков: {self.players_processed}\n"
            f"- Успешных запросов: {self.success}\n"
            f"- Всего запросов: {self.requests_made}\n"
            f"- Повторных попыток: {self.retries}\n"
            f"- Ошибок: {sum(self.failures.values())}\n"
            f"  - {', '.join(f'{k}: {v}' for k, v in self.failures.items())}"
        )


stats = Statistics()


def clean_html_tags(text: str) -> str:
    """
    Удаляет HTML-теги и лишние пробелы из текста.
    """
    if not text:
        return ""
    text = re.sub(r'<span class="material-symbols-rounded">.*?</span>', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s+([.,!?;:])', r'\1', text)
    return text.strip()


@retry(
    stop=stop_after_attempt(RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(aiohttp.ClientError),
    before_sleep=lambda _: stats.log_retry(),
)
async def login(session: aiohttp.ClientSession, username: str, password: str) -> bool:
    """
    Выполняет авторизацию на сервере.
    """
    login_url = 'https://serverchichi.online/account/auth'
    login_data = {'username': username, 'password': password}

    try:
        async with session.post(login_url, data=login_data) as response:
            response.raise_for_status()
            logger.info("Успешный вход в систему!")
            stats.log_success()
            return True
    except aiohttp.ClientError as e:
        stats.log_failure(type(e).__name__)
        logger.error(f"Ошибка входа в систему: {e}")
        raise


@retry(
    stop=stop_after_attempt(RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type(aiohttp.ClientError),
    before_sleep=lambda _: stats.log_retry(),
)
async def fetch_players(session: aiohttp.ClientSession, offset: int) -> Optional[List[Dict[str, Any]]]:
    """
    Получает список игроков по смещению (offset).
    """
    search_url = 'https://serverchichi.online/players/search'
    data = {
        'nickname': '',
        'sort': '',
        'filter_role': {},
        'filter_status': {},
        'offset': offset
    }

    try:
        async with session.post(search_url, data=data) as response:
            stats.log_request()
            response.raise_for_status()
            stats.log_success()
            return await response.json()
    except aiohttp.ClientError as e:
        stats.log_failure(type(e).__name__)
        logger.error(f"Ошибка при загрузке списка игроков: {e}")
        raise


async def parse_player_profile(html_content: str) -> Dict[str, Optional[Any]]:
    """
    Парсит HTML-страницу профиля игрока и возвращает словарь с данными.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    profile_data: Dict[str, Optional[Any]] = {}

    try:
        # Определение статуса онлайн/оффлайн
        player_online = soup.find('div', class_='playerOnline')
        profile_data['status'] = 'онлайн' if player_online and 'active' in player_online.get('class', []) else 'оффлайн'
    except Exception as e:
        logger.error(f"Ошибка при парсинге статуса онлайн/оффлайн: {e}")
        profile_data['status'] = None

    try:
        status_main = soup.find('p', class_='status-main')
        profile_data['status_main'] = status_main.get_text(strip=True) if status_main else None
    except Exception as e:
        logger.error(f"Ошибка при парсинге status_main: {e}")
        profile_data['status_main'] = None

    try:
        player_plus_content = soup.find('div', class_='player-plus-content')
        profile_data['player_plus'] = player_plus_content.find('p').get_text(strip=True) if player_plus_content else None
    except Exception as e:
        logger.error(f"Ошибка при парсинге player-plus-content: {e}")
        profile_data['player_plus'] = None

    try:
        socials = soup.find('div', class_='socials')
        if socials:
            profile_data['socials'] = []
            for social in socials.find_all('a'):
                try:
                    name = social.get_text(strip=True)
                    url = social['href']
                    profile_data['socials'].append({'name': name, 'url': url})
                except KeyError as e:
                    logger.error(f"Ошибка при парсинге социальной сети: отсутствует атрибут {e}")
        else:
            profile_data['socials'] = None
    except Exception as e:
        logger.error(f"Ошибка при парсинге социальных сетей: {e}")
        profile_data['socials'] = None

    try:
        stats_div = soup.find('div', class_='stats')
        if stats_div:
            stats_p_tags = stats_div.find_all('p')
            profile_data['stats'] = [clean_html_tags(str(p)) for p in stats_p_tags]
        else:
            profile_data['stats'] = None
    except Exception as e:
        logger.error(f"Ошибка при парсинге статистики: {e}")
        profile_data['stats'] = None

    try:
        rp_container = soup.find('div', class_='rp-container')
        if rp_container:
            rp_cards = []
            for card in rp_container.find_all('div', class_='rp-card'):
                h3 = card.find('h3')
                p = card.find('p')
                rp_cards.append({
                    'h3': clean_html_tags(str(h3)) if h3 else '',
                    'p': clean_html_tags(str(p)) if p else ''
                })
            profile_data['rp_cards'] = rp_cards
        else:
            profile_data['rp_cards'] = None
    except Exception as e:
        logger.error(f"Ошибка при парсинге RP-карточек: {e}")
        profile_data['rp_cards'] = None

    try:
        roles_div = soup.find('div', class_='roles')
        if roles_div:
            roles = []
            for role in roles_div.find_all('span'):
                role_text = clean_html_tags(role.get_text(strip=True))
                if role_text:
                    roles.append(role_text)
            profile_data['roles'] = roles if roles else None
        else:
            profile_data['roles'] = None
    except Exception as e:
        logger.error(f"Ошибка при парсинге ролей: {e}")
        profile_data['roles'] = None

    return profile_data


def load_cache() -> Dict[str, Dict]:
    """
    Загружает кэшированные данные из файла JSON.
    """
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as file:
                return orjson.loads(file)
        except Exception as e:
            logger.error(f"Ошибка при загрузке кэша: {e}")
            return {}
    return {}


def save_cache(cache: Dict[str, Dict]) -> None:
    """
    Сохраняет кэшированные данные в файл JSON.
    """
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as file:
            orjson.dumps(cache, file, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Ошибка при сохранении кэша: {e}")


def validate_player_data(data: Dict) -> bool:
    """
    Проверяет наличие обязательных полей в данных игрока.
    """
    required_fields = ['status_main', 'stats']
    return any(field in data and data[field] is not None for field in required_fields)


async def process_player(
    session: aiohttp.ClientSession,
    player_nickname: str,
    cache: Dict[str, Dict],
    semaphore: asyncio.Semaphore
) -> Optional[Dict]:
    """
    Обрабатывает профиль одного игрока: использует кэш или загружает и парсит HTML-страницу.
    """
    async with semaphore:
        stats.players_processed += 1
        logger.debug(f"Обработка игрока: {player_nickname}")

        if player_nickname in cache:
            if validate_player_data(cache[player_nickname]):
                logger.debug(f"Используем кэш для {player_nickname}")
                return cache[player_nickname]
            else:
                logger.warning(f"Невалидные данные в кэше для {player_nickname}")

        profile_url = f'https://serverchichi.online/player/{player_nickname}'
        try:
            async with session.get(profile_url) as response:
                stats.log_request()
                response.raise_for_status()
                html = await response.text()
                profile_data = await parse_player_profile(html)

                # Дополнительный поиск ссылки на Telegram
                profile_soup = BeautifulSoup(html, 'html.parser')
                telegram_link = profile_soup.find('a', class_='social telegram')
                profile_data['telegram'] = telegram_link['href'] if telegram_link else None

                if validate_player_data(profile_data):
                    cache[player_nickname] = profile_data
                    stats.log_success()
                    return profile_data
                else:
                    logger.warning(f"Невалидные данные для {player_nickname}")
                    return None

        except aiohttp.ClientError as e:
            stats.log_failure(type(e).__name__)
            logger.error(f"Ошибка при запросе профиля {player_nickname}: {e}")
            return None


def build_player_card(nickname: str, data: Dict, previous_cache: Dict[str, Dict]) -> str:
    """
    Формирует HTML-разметку для карточки игрока.
    """
    prev_data = previous_cache.get(nickname, {})
    changes = []

    card_classes: List[str] = []
    if nickname not in previous_cache:
        card_classes.append('new')
    else:
        for key in ['status_main', 'stats', 'roles', 'player_plus']:
            if data.get(key) != prev_data.get(key):
                changes.append(key)
                card_classes.append('changed')
                break

    # Формирование HTML для социальных сетей
    socials_html = ""
    if data.get('socials'):
        socials_html = "<ul class='socials-list'>"
        for social in data['socials']:
            socials_html += (
                f"<li class='social-item'>"
                f"<span>▪ {social['name']}</span>"
                f"<a href='{social['url']}' target='_blank'>{social['url']}</a>"
                f"</li>"
            )
        socials_html += "</ul>"
    else:
        socials_html = "N/A"

    # Формирование HTML для статистики
    stats_html = ""
    if data.get('stats'):
        stats_html = "<ul class='stats-list'>"
        for stat in data['stats']:
            stats_html += f"<li>▪ {stat}</li>"
        stats_html += "</ul>"
    else:
        stats_html = "N/A"

    # Формирование HTML для РП-карточек
    rp_cards_html = ""
    if data.get('rp_cards'):
        rp_cards_html = "<div class='rp-cards-container'>"
        for card in data['rp_cards']:
            rp_cards_html += (
                f"<div class='rp-card'>"
                f"<h3>{card['h3']}</h3>"
                f"<p>{card['p']}</p>"
                f"</div>"
            )
        rp_cards_html += "</div>"
    else:
        rp_cards_html = "N/A"

    # Формирование HTML для ролей
    roles_html = ""
    if data.get('roles'):
        roles_html = "<ul class='roles-list'>"
        for role in data['roles']:
            roles_html += f"<li>▪ {role}</li>"
        roles_html += "</ul>"
    else:
        roles_html = "N/A"

    # Формирование HTML для СЧ+
    player_plus_html = f"<div class='player-plus'><p>{data['player_plus']}</p></div>" if data.get('player_plus') else "N/A"

    player_card = f"""
    <div class="player-card {' '.join(card_classes)}">
        <div class="player-header" onclick="toggleContent(this)">
            <h2>
                <a href="https://serverchichi.online/player/{nickname}" 
                   target="_blank" 
                   style="color: inherit; text-decoration: none;">
                    {nickname}
                </a>
            </h2>
            <span class="status-main">{data.get('status', 'N/A')}</span>
        </div>
        <div class="player-content">
            <div class="section">
                <h3 class="section-title">Социальные сети</h3>
                {socials_html}
            </div>
            <div class="section">
                <h3 class="section-title">Статистика</h3>
                {stats_html}
            </div>
            <div class="section">
                <h3 class="section-title">РП-карточки</h3>
                {rp_cards_html}
            </div>
            <div class="section">
                <h3 class="section-title">Роли</h3>
                {roles_html}
            </div>
            <div class="section">
                <h3 class="section-title">СЧ+</h3>
                {player_plus_html}
            </div>
        </div>
    </div>
    """
    return player_card


def generate_html_report(cache: Dict[str, Dict], previous_cache: Dict[str, Dict]) -> None:
    """
    Генерирует HTML-отчёт по игрокам и сохраняет его в файл.
    """
    css_style = """
    <style>
        .report-container {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            max-width: 1200px;
            margin: 20px auto;
            padding: 20px;
            background: #f5f5f5;
        }
        .player-card {
            background: white;
            border-radius: 10px;
            margin: 15px 0;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        .player-header {
            padding: 15px 20px;
            background: #2c3e50;
            color: white;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .player-content {
            padding: 0 20px;
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease-out;
        }
        .player-card.active .player-content {
            max-height: 2000px;
            padding: 20px;
        }
        .section-title {
            color: #3498db;
            margin: 15px 0 10px;
            border-bottom: 2px solid #3498db;
            padding-bottom: 5px;
        }
        .socials-list, .stats-list, .roles-list {
            list-style-type: none;
            padding-left: 20px;
        }
        .social-item {
            margin: 5px 0;
            display: flex;
            align-items: center;
        }
        .social-item a {
            color: #2980b9;
            text-decoration: none;
            margin-left: 10px;
        }
        .rp-card {
            background: #f8f9fa;
            padding: 10px;
            margin: 10px 0;
            border-radius: 5px;
        }
        .timestamp {
            text-align: center;
            color: #7f8c8d;
            margin: 20px 0;
        }
        .changed {
            background-color: #fff3cd;
            border-left: 3px solid #ffc107;
        }
        .new {
            background-color: #d4edda;
            border-left: 3px solid #28a745;
        }
        .controls {
            margin: 20px 0;
            padding: 10px;
            background: #fff;
            border-radius: 5px;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        button {
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            background: #3498db;
            color: white;
        }
        input {
            padding: 8px;
            border: 1px solid #ddd;
            border-radius: 4px;
            flex-grow: 1;
        }
    </style>
    """

    js_script = """
    <script>
        function toggleContent(element) {
            element.parentElement.classList.toggle('active');
        }
        function toggleAll() {
            document.querySelectorAll('.player-card').forEach(card => {
                card.classList.toggle('active');
            });
        }
        function filterByStatus(status) {
            document.querySelectorAll('.player-card').forEach(card => {
                const statusElem = card.querySelector('.player-header span');
                card.style.display = statusElem?.textContent.toLowerCase().includes(status) ? '' : 'none';
            });
        }
        function searchPlayers() {
            const input = document.getElementById('search');
            const filter = input.value.toUpperCase();
            document.querySelectorAll('.player-card').forEach(card => {
                const nickname = card.querySelector('h2').textContent.toUpperCase();
                card.style.display = nickname.includes(filter) ? '' : 'none';
            });
        }
    </script>
    """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Отчет по игрокам</title>
        {css_style}
    </head>
    <body>
        <div class="report-container">
            <h1>Отчет по игрокам сервера</h1>
            <div class="controls">
                <button onclick="toggleAll()">Раскрыть/Скрыть все</button>
                <button onclick="filterByStatus('онлайн')">Только онлайн</button>
                <button onclick="filterByStatus('оффлайн')">Только оффлайн</button>
                <input type="text" id="search" placeholder="Поиск игроков..." onkeyup="searchPlayers()">
            </div>
            <div class="timestamp">Сгенерировано: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
    """

    # Формирование карточек для каждого игрока
    for nickname, data in cache.items():
        player_card = build_player_card(nickname, data, previous_cache)
        html_content += player_card

    html_content += f"""
        </div>
        {js_script}
    </body>
    </html>
    """

    try:
        with open(HTML_REPORT, 'w', encoding='utf-8') as f:
            f.write(html_content)
        logger.info(f"HTML-отчет сохранен в файл {HTML_REPORT}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении HTML-отчета: {e}")


async def main(username: str, password: str, max_offset: int = 500) -> None:
    """
    Основная асинхронная функция: авторизация, сбор и обработка данных игроков, генерация отчёта.
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    previous_cache = load_cache()
    current_cache = previous_cache.copy()

    # Использование TCPConnector для ограничения одновременных подключений
    connector = aiohttp.TCPConnector(limit=MAX_CONCURRENT_REQUESTS)
    async with aiohttp.ClientSession(connector=connector) as session:
        if not await login(session, username, password):
            logger.error("Авторизация не удалась.")
            return

        # Получаем всех игроков по offset
        all_players: List[Dict[str, Any]] = []
        offset = 0
        while offset <= max_offset:
            try:
                players = await fetch_players(session, offset)
            except Exception as e:
                logger.error(f"Остановка запроса игроков на offset {offset}: {e}")
                break
            if not players:
                break
            all_players.extend(players)
            offset += 50

        total_players = len(all_players)
        logger.info(f"Найдено игроков: {total_players}")

        # Создаем задачи для обработки профилей игроков с визуализацией прогресса
        tasks = []
        progress_bar = tqdm_asyncio(total=total_players, desc="Сбор данных игроков", bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]", colour='GREEN')
        for player in all_players:
            nickname = player.get('minecraft_nickname')
            if nickname:
                task = asyncio.create_task(process_player(session, nickname, current_cache, semaphore))
                task.add_done_callback(lambda _: progress_bar.update(1))
                tasks.append(task)
        await asyncio.gather(*tasks)
        progress_bar.close()

    save_cache(current_cache)
    generate_html_report(current_cache, previous_cache)
    logger.info(stats.get_report())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Поиск данных игроков.")
    parser.add_argument('--max_offset', type=int, default=500, help="Максимальное значение offset.")
    parser.add_argument('--username', type=str, help="Имя пользователя для входа.")
    parser.add_argument('--password', type=str, help="Пароль для входа.")
    args = parser.parse_args()

    username = args.username or os.getenv('USERNAME')
    password = args.password or os.getenv('PASSWORD')

    if not username or not password:
        logger.error("Не удалось загрузить логин или пароль.")
        exit(1)

    asyncio.run(main(username, password, args.max_offset))
