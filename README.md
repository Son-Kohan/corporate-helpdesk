# Corporate Help Desk

Система обработки заявок на FastAPI с ролевой моделью доступа, адаптивным веб-интерфейсом и поддержкой SQLite/PostgreSQL.

## Возможности

- регистрация и вход по имени/фамилии либо отдельному логину;
- роли и полностью настраиваемые права;
- отдельные страницы заявок, пользователей и ролей;
- категории заявок, автоматическое назначение исполнителя и SLA;
- отделы и просмотр заявок отдела руководителем;
- смена статуса заявки с обязательным комментарием к решению;
- массовое изменение заявок;
- вложения и подробная история изменений;
- внутренние уведомления и WebSocket-обновления;
- журнал действий;
- архивирование пользователей, безопасное удаление и сброс временного пароля;
- отчеты и экспорт заявок/пользователей в CSV;
- ограничение попыток входа, JWT и защитные HTTP-заголовки;
- миграция существующей SQLite-базы без удаления данных;
- резервное копирование, восстановление, мониторинг и Docker-развертывание.

## Локальный запуск

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python scripts/migrate.py
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Открыть: `http://127.0.0.1:8000`.

Стандартная учетная запись создается только при первом запуске:

- логин: `admin`
- пароль: `admin123`

Перед эксплуатацией обязательно измените `HELPDESK_SECRET_KEY` и `HELPDESK_ADMIN_PASSWORD`.

## Установка на Raspberry Pi

Для Raspberry Pi OS Desktop и Raspberry Pi OS Lite подготовлен автоматический установщик локального сервера:

```bash
sudo apt-get update && sudo apt-get install -y git && rm -rf ~/corporate-helpdesk && git clone https://github.com/Son-Kohan/corporate-helpdesk.git ~/corporate-helpdesk && cd ~/corporate-helpdesk && bash deploy/install-raspberry-pi.sh --enable-firewall
```

Он устанавливает Nginx и Python, создает автозапуск, ежедневные резервные копии, мониторинг и ограничивает доступ локальной сетью. После установки система открывается по адресу `http://helpdesk.local` или локальному IP Raspberry Pi.

Подробная инструкция: [`deploy/RASPBERRY_PI.md`](deploy/RASPBERRY_PI.md).

Собрать переносимый архив вместе с текущей базой:

```powershell
python scripts/build_release.py --include-data
```

## Docker и PostgreSQL

```bash
docker compose up --build
```

Приложение будет доступно на `http://localhost:8000`. В `docker-compose.yml` перед запуском необходимо заменить пароль PostgreSQL, пароль администратора и секретный ключ.

Для самостоятельного PostgreSQL укажите:

```env
HELPDESK_DATABASE_URL=postgresql+asyncpg://helpdesk:password@localhost/helpdesk
```

## Миграции

```powershell
python scripts/migrate.py
```

Команда создает недостающие таблицы, обновляет существующую SQLite-схему и добавляет стандартные каталоги.

## Резервное копирование SQLite

```powershell
python scripts/backup.py --db helpdesk.db --backup-dir backups --keep 14
python scripts/restore.py backups/helpdesk_YYYYMMDD_HHMMSS.db --target helpdesk.db
```

Для Linux предусмотрены `deploy/helpdesk-backup.service` и `deploy/helpdesk-backup.timer`.

## Тесты и контроль

```powershell
pytest
python -m compileall -q app tests
pip check
python scripts/monitor.py
```

## Основные настройки

Переменные окружения перечислены в `.env.example`. Важные параметры:

- `HELPDESK_DATABASE_URL` — SQLite или PostgreSQL;
- `HELPDESK_SECRET_KEY` — ключ JWT;
- `HELPDESK_LOGIN_ATTEMPT_LIMIT` и `HELPDESK_LOGIN_LOCK_SECONDS` — защита входа;
- `HELPDESK_MAX_ATTACHMENT_BYTES` — максимальный размер вложения;
- `HELPDESK_CORS_ORIGINS` — разрешенные источники;
- SMTP-параметры — отправка почтовых уведомлений.

Документация API: `http://127.0.0.1:8000/docs`.
