# Установка Help Desk 1.0 на Raspberry Pi OS Desktop

Система устанавливается как локальный сервер:

- Nginx принимает запросы компьютеров локальной сети на порту `80`;
- Uvicorn доступен только внутри Raspberry Pi на `127.0.0.1:8000`;
- Nginx разрешает подключения только из указанной локальной подсети;
- проброс портов на роутере не требуется;
- приложение и Nginx автоматически запускаются после перезагрузки;
- база SQLite ежедневно копируется в `/opt/helpdesk/backups`.

## Подготовка Raspberry Pi

1. Установите Raspberry Pi OS Desktop или Raspberry Pi OS Lite.
2. Подключите Raspberry Pi к той же локальной сети, что и рабочие компьютеры.
3. Желательно закрепить адрес Raspberry Pi в настройках DHCP роутера.
4. Перенесите папку проекта на Raspberry Pi, например в `~/helpdesk_project`.

Готовый архив для переноса можно собрать на основном компьютере:

```powershell
python scripts/build_release.py --include-data
```

Архив появится в папке `release`. Вариант `with-data` содержит текущую базу с пользователями и заявками.

## Установка

Откройте терминал в папке проекта:

```bash
cd ~/helpdesk_project
bash deploy/install-raspberry-pi.sh --copy-data --enable-firewall
```

`--copy-data` переносит текущую базу `helpdesk.db` с пользователями и заявками. Без этого параметра будет создана новая база.

Для чистой установки напрямую из GitHub достаточно одной команды:

```bash
sudo apt-get update && sudo apt-get install -y git && rm -rf ~/corporate-helpdesk && git clone https://github.com/Son-Kohan/corporate-helpdesk.git ~/corporate-helpdesk && cd ~/corporate-helpdesk && bash deploy/install-raspberry-pi.sh --enable-firewall
```

Если установщик не смог определить локальную подсеть, укажите ее вручную:

```bash
bash deploy/install-raspberry-pi.sh --copy-data --enable-firewall --lan 192.168.1.0/24
```

После установки система будет доступна с компьютеров локальной сети:

```text
http://helpdesk.local
http://IP-АДРЕС-RASPBERRY-PI
```

## Проверка

```bash
bash /opt/helpdesk/deploy/diagnose-raspberry-pi.sh
systemctl status helpdesk
systemctl status nginx
```

## Обновление

Перенесите новую версию проекта на Raspberry Pi и выполните из новой папки:

```bash
bash deploy/update-raspberry-pi.sh
```

Перед обновлением автоматически создается резервная копия базы.

## Удаление сервиса

Удалить службы, но сохранить базу и файлы:

```bash
bash /opt/helpdesk/deploy/uninstall-raspberry-pi.sh
```

Удалить службы и все данные:

```bash
bash /opt/helpdesk/deploy/uninstall-raspberry-pi.sh --purge-data
```

## Резервные копии

Проверить таймер:

```bash
systemctl list-timers helpdesk-backup.timer
```

Создать копию вручную:

```bash
sudo systemctl start helpdesk-backup.service
```

## Локальная безопасность

- Не включайте проброс портов `80`, `443` или `8000` на роутере.
- Не помещайте Raspberry Pi в DMZ.
- После первого входа смените пароль администратора.
- Если адреса локальной сети изменились, повторно запустите установщик с правильным параметром `--lan`.
