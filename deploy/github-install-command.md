# Установка из GitHub

```bash
sudo apt-get update && sudo apt-get install -y git && rm -rf ~/corporate-helpdesk && git clone https://github.com/Son-Kohan/corporate-helpdesk.git ~/corporate-helpdesk && cd ~/corporate-helpdesk && bash deploy/install-raspberry-pi.sh --enable-firewall
```

Обновление установленной системы:

```bash
cd ~/corporate-helpdesk && git pull --ff-only && bash deploy/update-raspberry-pi.sh
```

Рабочая база `helpdesk.db`, вложения, журналы и резервные копии в GitHub не публикуются.
