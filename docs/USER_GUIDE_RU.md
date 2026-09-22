# Полное руководство пользователя

Это пошаговая инструкция по переносу рабочего `.bat`-профиля из
[`zapret-discord-youtube`](https://github.com/Flowseal/zapret-discord-youtube)
на маршрутизатор Keenetic/Netcraze или OpenWrt с пакетом
[`nfqws2-keenetic`](https://github.com/nfqws/nfqws2-keenetic).

Инструкция рассчитана в том числе на пользователя, который раньше не работал с Python, SSH и Entware.

> Важно: конвертер не устанавливает прошивку и сам пакет `nfqws2-keenetic`.
> На уже подготовленный Keenetic готовый комплект можно установить автоматически
> через Web API по [отдельной инструкции](AUTO_INSTALL_RU.md) либо скопировать
> вручную по этому руководству. Для OpenWrt пока используется ручная установка.

## Содержание

1. [Что получится в итоге](#1-что-получится-в-итоге)
2. [Что потребуется](#2-что-потребуется)
3. [Обозначения в командах](#3-важные-обозначения-в-командах)
4. [Подготовка Keenetic/Netcraze](#4-подготовка-keeneticnetcraze)
5. [Подготовка OpenWrt](#5-подготовка-openwrt)
6. [Определение WAN-интерфейса](#6-определение-wan-интерфейса)
7. [Подготовка компьютера](#7-подготовка-компьютера)
8. [Запуск конвертера](#8-запуск-конвертера)
9. [Все параметры](#9-все-параметры-конвертера)
10. [Проверка результата](#10-проверка-результата-на-компьютере)
11. [Политика доступа Keenetic](#11-политика-доступа-keenetic)
12. [Копирование на Keenetic](#12-копирование-на-keenetic)
13. [Копирование на OpenWrt](#13-копирование-на-openwrt)
14. [Проверка после установки](#14-проверка-после-установки)
15. [Обновление профиля](#15-обновление-профиля)
16. [Откат](#16-откат)
17. [Проблемы конвертера](#17-решение-проблем-конвертера)
18. [Проблемы роутера](#18-решение-проблем-роутера)
19. [Что не нужно делать](#19-что-не-нужно-делать)
20. [Контрольный список](#20-минимальный-контрольный-список)
21. [Полезные ссылки](#21-полезные-ссылки)

## 1. Что получится в итоге

Общая последовательность выглядит так:

1. На компьютере находится профиль Flowseal, который уже работает у вашего провайдера.
2. Конвертер читает его `.bat`-файл, списки доменов/IP и бинарные fake-шаблоны.
3. Создаётся штатный `nfqws2.conf` и каталоги `lists/` и `blobs/`.
4. Комплект копируется на роутер.
5. Штатная служба `nfqws2-keenetic` загружает конфиг и создаёт правила NFQUEUE.
6. Вы проверяете работу с устройства, подключённого через роутер.

Конвертер не переносит Windows-драйвер WinDivert и `winws.exe`: на Linux-роутере они не нужны. Стратегии переводятся в синтаксис zapret2 `--lua-desync`.

## 2. Что потребуется

### На компьютере

- Windows 10/11, Linux или macOS;
- Python 3.9 или новее;
- этот проект с конвертером;
- полностью распакованный `zapret-discord-youtube`, включая каталоги `bin/` и `lists/`;
- свободное место для выходного комплекта и, при необходимости, ZIP-архива.

### На роутере

- Keenetic/Netcraze с Entware либо OpenWrt;
- установленный актуальный `nfqws2-keenetic`;
- модули ядра Netfilter/NFQUEUE;
- доступ к роутеру по SSH;
- достаточно оперативной и постоянной памяти для выбранных списков.

### Что нужно знать заранее

- IP-адрес роутера, обычно `192.168.1.1`;
- SSH-порт: на Keenetic часто `222`, на OpenWrt обычно `22`;
- имя WAN-интерфейса, например `eth3`, `eth2.2`, `ppp0` или `pppoe-wan`;
- какой профиль Flowseal работает на вашем ПК;
- нужен ли обход всем устройствам или только отдельной политике Keenetic.

## 3. Важные обозначения в командах

В примерах используются условные значения:

| Значение | Что подставить вместо него |
|---|---|
| `C:\Tools\zapret-discord-youtube` | путь к распакованному Flowseal |
| `C:\Tools\KeeneticZapret` | путь к этому конвертеру |
| `192.168.1.1` | IP вашего роутера |
| `222` | SSH-порт Keenetic; для OpenWrt обычно `22` |
| `eth3` | фактический WAN-интерфейс |
| `general (ALT11).bat` | ваш рабочий профиль Flowseal |

Команды с приглашением `PS>` выполняются в PowerShell на компьютере. Команды с приглашением `root@router:~#` выполняются по SSH на роутере. Не вводите команды Linux в командную строку KeeneticOS.

## 4. Подготовка Keenetic/Netcraze

Если `nfqws2-keenetic` уже установлен и запускается, перейдите к разделу 6.

### 4.1. Подготовьте KeeneticOS

1. Установите Entware на встроенную память или USB-накопитель по официальной инструкции Keenetic.
2. В веб-интерфейсе Keenetic установите компонент **Модули ядра подсистемы Netfilter**: **OPKG → Kernel modules for Netfilter**.
3. Если такого пункта нет, сначала установите компонент **Протокол IPv6**.
4. В разделе интернет-фильтров временно отключите сторонние DNS-фильтры: NextDNS, SkyDNS, Яндекс DNS и подобные. После успешной проверки возвращайте их по одному.
5. Желательно отключить использование DNS-серверов провайдера и настроить собственный DoT/DoH.
6. Сохраните резервную копию конфигурации самого роутера через веб-интерфейс.

### 4.2. Подключитесь именно к Entware

В PowerShell на компьютере:

```powershell
ssh root@192.168.1.1 -p 222
```

Либо подключитесь по Telnet к KeeneticOS и выполните:

```sh
exec sh
```

В дальнейших командах должны существовать каталоги `/opt/etc` и `/opt/bin`.

Проверьте:

```sh
ls -ld /opt /opt/etc /opt/bin
```

### 4.3. Удалите старую первую версию только при её наличии

Сначала посмотрите установленные пакеты:

```sh
opkg list-installed | grep -E 'nfqws|zapret'
```

Если установлен старый `nfqws-keenetic`, сохраните его конфиги и удалите конфликтующие пакеты:

```sh
opkg remove nfqws-keenetic-web nfqws-keenetic
```

Не удаляйте уже установленный `nfqws2-keenetic`.

### 4.4. Установите `nfqws2-keenetic`

```sh
opkg update
opkg install ca-certificates wget-ssl
opkg remove wget-nossl
mkdir -p /opt/etc/opkg
echo "src/gz nfqws2-keenetic https://nfqws.github.io/nfqws2-keenetic/all" > /opt/etc/opkg/nfqws2-keenetic.conf
opkg update
opkg install nfqws2-keenetic
```

Проверьте установку:

```sh
opkg info nfqws2-keenetic
service nfqws2-keenetic status
ls -l /opt/etc/nfqws2/nfqws2.conf
```

Веб-интерфейс `nfqws-keenetic-web` для работы конвертера не требуется. Если вы
хотите установить результат без SCP, используйте автоматически создаваемую
папку `web-import/` и отдельную [инструкцию по веб-интерфейсу](WEB_INTERFACE_RU.md).

## 5. Подготовка OpenWrt

Если пакет уже установлен, перейдите к разделу 6.

Подключитесь:

```powershell
ssh root@192.168.1.1 -p 22
```

Узнайте версию:

```sh
cat /etc/openwrt_release
```

### 5.1. OpenWrt 24.10 и старее (`opkg`)

```sh
opkg update
opkg install ca-certificates wget-ssl
opkg remove wget-nossl
wget -O /tmp/nfqws2-keenetic.pub https://nfqws.github.io/nfqws2-keenetic/openwrt/nfqws2-keenetic.pub
opkg-key add /tmp/nfqws2-keenetic.pub
echo "src/gz nfqws2-keenetic https://nfqws.github.io/nfqws2-keenetic/openwrt" > /etc/opkg/nfqws2-keenetic.conf
opkg update
opkg install nfqws2-keenetic
```

### 5.2. OpenWrt 25.xx/Snapshot (`apk`)

```sh
apk --update-cache add ca-certificates wget-ssl
apk del wget-nossl
wget -O /etc/apk/keys/nfqws2-keenetic.pem https://nfqws.github.io/nfqws2-keenetic/openwrt/nfqws2-keenetic.pem
echo "https://nfqws.github.io/nfqws2-keenetic/openwrt/packages.adb" > /etc/apk/repositories.d/nfqws2-keenetic.list
apk --update-cache add nfqws2-keenetic
```

Проверьте:

```sh
service nfqws2-keenetic status
ls -l /etc/nfqws2/nfqws2.conf
```

На OpenWrt каталог конфигурации — `/etc/nfqws2`, без префикса `/opt`.

## 6. Определение WAN-интерфейса

Неправильный интерфейс — одна из наиболее частых причин ситуации «служба запустилась, но ничего не изменилось».

На роутере выполните:

```sh
ip -4 route show default
ip -6 route show default
```

Пример ответа:

```text
default via 100.64.0.1 dev eth3
```

Нужное имя находится после `dev`: в этом примере это `eth3`.

Если команды `ip` нет:

```sh
route -n
ifconfig
```

Типовые, но не гарантированные значения:

- обычное проводное подключение Keenetic: `eth3` или `eth2.2`;
- PPPoE на Keenetic: `ppp0`;
- OpenWrt с PPPoE: `pppoe-wan`;
- туннель или второй провайдер: отдельное имя интерфейса.

Если активны несколько провайдеров, конвертер допускает список через пробел:

```powershell
--interface "eth3 nwg1"
```

После переключения подключения интерфейс может измениться. Проверяйте маршруты повторно.

## 7. Подготовка компьютера

### 7.1. Проверьте Python

В PowerShell:

```powershell
py -3 --version
```

Подходит Python 3.9 и новее. Если команда `py` отсутствует, попробуйте:

```powershell
python --version
```

Далее можно заменять `py -3` на `python`.

Если Python не установлен, установите его с официального сайта Python и включите опцию добавления Python в `PATH`.

### 7.2. Проверьте каталог Flowseal

Он должен содержать примерно следующее:

```text
zapret-discord-youtube/
├── bin/
├── lists/
├── general.bat
├── general (ALT).bat
├── general (ALT11).bat
└── service.bat
```

Проверьте в PowerShell:

```powershell
Get-ChildItem "C:\Tools\zapret-discord-youtube"
Get-ChildItem "C:\Tools\zapret-discord-youtube\bin" -Filter *.bin
Get-ChildItem "C:\Tools\zapret-discord-youtube\lists"
```

Если скопирован только один `.bat` без `bin/` и `lists/`, полноценная конвертация невозможна.

### 7.3. Выберите профиль

Лучший исходник — тот `.bat`, который уже проверен на компьютере у того же провайдера.

Перед выбором:

1. Запустите профиль Flowseal на ПК.
2. Проверьте YouTube, веб-версию Discord и голосовой канал Discord.
3. Запомните точное имя `.bat`.
4. Остановите Flowseal после проверки, чтобы при тестировании роутера он не создавал ложное впечатление, будто работает роутер.

Если рабочий профиль неизвестен, конвертируйте профили по одному в разные выходные каталоги. Не смешивайте результаты нескольких профилей.

## 8. Запуск конвертера

### 8.1. Графический мастер — рекомендуемый способ

На Windows дважды щёлкните файл:

```text
Запустить конвертер.cmd
```

Выберите папку Flowseal, стратегию и параметры роутера, затем нажмите
**Конвертировать**. Подробное описание каждого элемента окна приведено в
[инструкции графического мастера](GUI_RU.md).

Следующие подразделы нужны для запуска через командную строку.

### 8.2. Перейдите в каталог проекта

```powershell
Set-Location "C:\Tools\KeeneticZapret"
```

Проверьте интерфейс командной строки:

```powershell
py -3 -m zapret_keenetic --help
```

Устанавливать Python-пакет необязательно. Конвертер не требует сторонних зависимостей.

### 8.3. Базовый пример для Keenetic

```powershell
py -3 -m zapret_keenetic `
  "C:\Tools\zapret-discord-youtube" `
  "general (ALT11).bat" `
  --output ".\converted\alt11-keenetic" `
  --target keenetic `
  --interface eth3 `
  --game-filter disabled `
  --archive
```

Та же команда одной строкой:

```powershell
py -3 -m zapret_keenetic "C:\Tools\zapret-discord-youtube" "general (ALT11).bat" -o ".\converted\alt11-keenetic" --target keenetic --interface eth3 --game-filter disabled --archive
```

### 8.4. Базовый пример для OpenWrt

```powershell
py -3 -m zapret_keenetic `
  "C:\Tools\zapret-discord-youtube" `
  "general.bat" `
  --output ".\converted\general-openwrt" `
  --target openwrt `
  --interface pppoe-wan `
  --game-filter disabled `
  --archive
```

### 8.5. Как читать позиционные аргументы

В команде обязательно идут:

1. `source` — путь к корню Flowseal;
2. `profile` — имя `.bat` внутри этого каталога;
3. `-o`/`--output` — новый или пустой выходной каталог.

Если в пути или имени есть пробелы и скобки, заключайте значение в двойные кавычки.

## 9. Все параметры конвертера

| Параметр | По умолчанию | Назначение |
|---|---:|---|
| `source` | обязательный | корневой каталог `zapret-discord-youtube` |
| `profile` | обязательный | исходный `.bat`-профиль |
| `-o`, `--output` | обязательный | новый или пустой каталог результата |
| `--target keenetic` | `keenetic` | пути `/opt/etc/nfqws2` |
| `--target openwrt` | — | пути `/etc/nfqws2` |
| `--interface NAME` | `eth3` | один или несколько WAN-интерфейсов |
| `--game-filter disabled` | `disabled` | не добавлять игровые диапазоны портов |
| `--game-filter all` | — | игровые профили TCP и UDP |
| `--game-filter tcp` | — | только игровой TCP |
| `--game-filter udp` | — | только игровой UDP |
| `--ipset-mode loaded` | `loaded` | при пустом `ipset-all.txt` взять наполненный `.backup` |
| `--ipset-mode current` | — | использовать ровно текущий `ipset-all.txt` |
| `--no-ipv6` | выключен | записать `IPV6_ENABLED=0` |
| `--policy-name NAME` | `nfqws` | имя политики доступа Keenetic |
| `--policy-exclude` | выключен | обрабатывать всех, кроме устройств политики |
| `--queue-num N` | `300` | номер NFQUEUE; менять только при конфликте |
| `--strict` | выключен | считать предупреждение ошибкой конвертации |
| `--archive` | выключен | создать ZIP рядом с выходным каталогом |
| `--version` | — | показать версию конвертера |

### 9.1. Выбор Game Filter

Используйте `disabled`, если вам нужны только сайты, YouTube и Discord. Это наиболее экономный вариант для роутера.

`all`, `tcp` и `udp` добавляют широкий диапазон `1024-65535`. Это увеличивает объём трафика через NFQUEUE и нагрузку на CPU. Включайте игровые профили только при реальной необходимости.

### 9.2. Выбор IPSet mode

- `loaded` подходит большинству пользователей Flowseal. Если `lists/ipset-all.txt` является пустой заглушкой, конвертер использует `ipset-all.txt.backup`.
- `current` полезен, если текущий список уже обновлён внешним скриптом или вы намеренно хотите оставить его пустым.

Большой IP-список расходует память роутера. На слабом устройстве перед установкой сравните размеры:

```powershell
Get-Item "C:\Tools\zapret-discord-youtube\lists\ipset-all.txt*" | Select-Object Name,Length
```

### 9.3. IPv6

Не отключайте IPv6 автоматически только потому, что сайт не работает. Сначала проверьте, установлен ли модуль IPv6/Netfilter и корректен ли WAN-интерфейс.

Используйте `--no-ipv6`, если:

- IPv6 действительно отключён у провайдера и на роутере;
- старое ядро не поддерживает необходимые `ip6tables`-модули;
- журнал явно указывает на ошибку инициализации IPv6.

## 10. Проверка результата на компьютере

После успешного запуска появится каталог:

```text
converted/alt11-keenetic/
├── nfqws2.conf
├── REPORT.md
├── report.json
├── blobs/
└── lists/
```

Если использован `--archive`, рядом будет `alt11-keenetic.zip`.

### 10.1. Обязательно прочитайте `REPORT.md`

```powershell
Get-Content -Encoding utf8 ".\converted\alt11-keenetic\REPORT.md"
```

Значения диагностики:

- `INFO` — пояснение, обычно не мешающее запуску;
- `WARNING` — часть исходного профиля переведена приблизительно или отсутствует ресурс;
- `missing-list` — обязательный список не найден;
- `missing-blob` — не найден бинарный fake-шаблон;
- `unsupported-option`/`unsupported-mode` — параметр не переведён;
- `hostfakesplit-altorder` — информационная запись: altorder=1 сохранён встроенной функцией совместимости;
- `multiport-limit` — слишком много портов для одного правила `xt_multiport`.

Не устанавливайте комплект с `missing-blob`, `unsupported-mode` или `multiport-limit`, пока не разберётесь с предупреждением.

Отсутствующие файлы вида `list-general-user.txt`, `list-exclude-user.txt` и `ipset-exclude-user.txt` считаются необязательными: конвертер создаёт для них пустые файлы и пишет `INFO`.

### 10.2. Проверьте конфиг

```powershell
Select-String -Path ".\converted\alt11-keenetic\nfqws2.conf" -Pattern "ISP_INTERFACE|TCP_PORTS|UDP_PORTS|IPV6_ENABLED|POLICY"
```

Проверьте:

- `ISP_INTERFACE` совпадает с выводом маршрутов роутера;
- для Keenetic пути начинаются с `/opt/etc/nfqws2`;
- для OpenWrt пути начинаются с `/etc/nfqws2`;
- `TCP_PORTS` и `UDP_PORTS` не пусты, если соответствующий трафик нужен;
- в конфиге нет Windows-путей `C:\...`;
- в конфиге нет старых опций `--dpi-desync`.

Быстрые проверки:

```powershell
Select-String ".\converted\alt11-keenetic\nfqws2.conf" "C:\\"
Select-String ".\converted\alt11-keenetic\nfqws2.conf" "--dpi-desync"
```

Обе команды в нормальном результате не должны ничего найти.

## 11. Политика доступа Keenetic

Этот раздел не относится к OpenWrt.

### Вариант A: обрабатывать весь трафик

Не создавайте в Keenetic политику с именем, указанным в `POLICY_NAME`. Если политика не найдена, штатный пакет обрабатывает весь трафик.

### Вариант B: только выбранные устройства

1. В Keenetic откройте **Приоритеты подключений → Политики доступа в интернет**.
2. Создайте политику `nfqws`.
3. Отметьте в ней интерфейс провайдера.
4. Добавьте нужные телефоны, телевизоры и компьютеры.
5. Конвертируйте с параметрами по умолчанию либо явно задайте:

```powershell
--policy-name nfqws
```

При `POLICY_EXCLUDE=0` обрабатываются только устройства этой политики.

### Вариант C: все, кроме выбранных устройств

Создайте политику исключений и используйте:

```powershell
--policy-name nfqws-bypass --policy-exclude
```

В неё добавляются устройства, для которых обработка не нужна.

После изменения политики перезапустите службу.

## 12. Копирование на Keenetic

Этот раздел описывает установку по SSH/SCP. Для установки через вкладки
`nfqws-keenetic-web` перейдите к [инструкции по веб-интерфейсу](WEB_INTERFACE_RU.md)
и используйте папку `web-import/`.

Ниже предполагается:

- результат находится в `C:\Tools\KeeneticZapret\converted\alt11-keenetic`;
- роутер имеет адрес `192.168.1.1`;
- SSH работает на порту `222`.

### 12.1. Создайте временный каталог на роутере

В PowerShell:

```powershell
ssh root@192.168.1.1 -p 222 "mkdir -p /opt/tmp/nfqws2-converted"
```

### 12.2. Передайте только необходимые файлы

```powershell
scp -P 222 ".\converted\alt11-keenetic\nfqws2.conf" root@192.168.1.1:/opt/tmp/nfqws2-converted/
scp -P 222 -r ".\converted\alt11-keenetic\lists" root@192.168.1.1:/opt/tmp/nfqws2-converted/
scp -P 222 -r ".\converted\alt11-keenetic\blobs" root@192.168.1.1:/opt/tmp/nfqws2-converted/
```

ZIP создаётся для хранения и ручной передачи, но для `scp` удобнее использовать распакованный каталог. На роутере может не быть `unzip`.

### 12.3. Проверьте загрузку

```powershell
ssh root@192.168.1.1 -p 222
```

На роутере:

```sh
find /opt/tmp/nfqws2-converted -maxdepth 2 -type f -print
```

Должны быть видны `nfqws2.conf`, файлы в `lists/` и `blobs/`.

### 12.4. Создайте резервную копию

```sh
stamp=$(date +%Y%m%d-%H%M%S)
tar -czf "/opt/tmp/nfqws2-backup-$stamp.tar.gz" -C /opt/etc nfqws2
echo "Backup: /opt/tmp/nfqws2-backup-$stamp.tar.gz"
```

Скопируйте имя файла резервной копии в заметки. Для дополнительной защиты можно скачать архив на компьютер через `scp`.

### 12.5. Установите комплект

```sh
service nfqws2-keenetic stop
mkdir -p /opt/etc/nfqws2/lists /opt/etc/nfqws2/blobs
cp -f /opt/tmp/nfqws2-converted/nfqws2.conf /opt/etc/nfqws2/nfqws2.conf
for f in /opt/tmp/nfqws2-converted/lists/*; do [ -f "$f" ] && cp -f "$f" /opt/etc/nfqws2/lists/; done
for f in /opt/tmp/nfqws2-converted/blobs/*; do [ -f "$f" ] && cp -f "$f" /opt/etc/nfqws2/blobs/; done
chmod 644 /opt/etc/nfqws2/nfqws2.conf
chmod 755 /opt/etc/nfqws2/lists /opt/etc/nfqws2/blobs
find /opt/etc/nfqws2/lists /opt/etc/nfqws2/blobs -type f -exec chmod 644 {} \;
service nfqws2-keenetic start
```

Не заменяйте `/opt/etc/init.d/S51nfqws2` и не отключайте `validate_config`.

## 13. Копирование на OpenWrt

Предполагается SSH-порт `22` и результат `general-openwrt`.

### 13.1. Загрузка

```powershell
ssh root@192.168.1.1 -p 22 "mkdir -p /tmp/nfqws2-converted"
scp -P 22 ".\converted\general-openwrt\nfqws2.conf" root@192.168.1.1:/tmp/nfqws2-converted/
scp -P 22 -r ".\converted\general-openwrt\lists" root@192.168.1.1:/tmp/nfqws2-converted/
scp -P 22 -r ".\converted\general-openwrt\blobs" root@192.168.1.1:/tmp/nfqws2-converted/
ssh root@192.168.1.1 -p 22
```

### 13.2. Резервная копия и установка

```sh
stamp=$(date +%Y%m%d-%H%M%S)
tar -czf "/root/nfqws2-backup-$stamp.tar.gz" -C /etc nfqws2
service nfqws2-keenetic stop
mkdir -p /etc/nfqws2/lists /etc/nfqws2/blobs
cp -f /tmp/nfqws2-converted/nfqws2.conf /etc/nfqws2/nfqws2.conf
for f in /tmp/nfqws2-converted/lists/*; do [ -f "$f" ] && cp -f "$f" /etc/nfqws2/lists/; done
for f in /tmp/nfqws2-converted/blobs/*; do [ -f "$f" ] && cp -f "$f" /etc/nfqws2/blobs/; done
chmod 644 /etc/nfqws2/nfqws2.conf
chmod 755 /etc/nfqws2/lists /etc/nfqws2/blobs
find /etc/nfqws2/lists /etc/nfqws2/blobs -type f -exec chmod 644 {} \;
service nfqws2-keenetic start
```

## 14. Проверка после установки

### 14.1. Статус службы

```sh
service nfqws2-keenetic status
```

При запуске должны выводиться сведения о версии, пользовательских desync-профилях и очереди `300`. Предупреждение `seccomp: Invalid argument` на старом ядре может быть безопасным, если после него служба продолжает запуск.

### 14.2. Процесс

```sh
ps | grep '[n]fqws2'
```

Должен существовать процесс `nfqws2`.

### 14.3. Правила NFQUEUE

```sh
iptables-save | grep nfqws
```

В выводе должны присутствовать правила с:

- правильным интерфейсом после `-o`/`-i`;
- нужными TCP/UDP-портами;
- `NFQUEUE`;
- номером очереди из `NFQUEUE_NUM`, обычно `300`.

При включённом IPv6:

```sh
ip6tables-save | grep nfqws
```

### 14.4. Журнал

```sh
logread | grep -i nfqws
```

Для временной расширенной диагностики можно установить `LOG_LEVEL=1` в конфиге, перезапустить службу и после проверки вернуть `0`, чтобы не засорять журнал.

### 14.5. Проверка с клиентского устройства

1. Полностью остановите Flowseal/zapret на тестовом ПК.
2. Убедитесь, что устройство подключено к проверяемому Keenetic/OpenWrt, а не к мобильной сети или другому VPN.
3. Если используется политика Keenetic, проверьте членство устройства.
4. Закройте браузер/Discord и откройте заново, чтобы создать новые соединения.
5. Проверьте:
   - главную страницу YouTube;
   - запуск нескольких видео и перемотку;
   - Discord в браузере;
   - голосовой канал и демонстрацию экрана;
   - остальные домены из выбранного профиля.
6. Сравните результат после `service nfqws2-keenetic stop` и после `start`. Это помогает отличить эффект роутера от кэша или другого обхода.

## 15. Обновление профиля

Профили и списки Flowseal меняются. Не редактируйте старый сгенерированный конфиг бесконечно вручную.

Рекомендуемый порядок обновления:

1. Обновите или заново распакуйте Flowseal на компьютере.
2. Проверьте выбранный `.bat` на ПК.
3. Создайте новый выходной каталог, например `alt11-2026-08-13`.
4. Запустите конвертер повторно.
5. Сравните новый `REPORT.md` со старым.
6. Сделайте новую резервную копию роутера.
7. Установите новый комплект и проверьте.
8. Не удаляйте последний рабочий backup до окончания проверки.

Чтобы обновить сам `nfqws2-keenetic` на Keenetic/Entware:

```sh
opkg update
opkg upgrade nfqws2-keenetic
```

После обновления пакета повторно проверьте совместимость конфига и статус службы.

## 16. Откат

### 16.1. Быстро отключить обработку

```sh
service nfqws2-keenetic stop
```

После остановки проверьте, что правила удалены:

```sh
iptables-save | grep nfqws
```

### 16.2. Восстановить Keenetic из backup

Посмотрите имя архива:

```sh
ls -lh /opt/tmp/nfqws2-backup-*.tar.gz
```

Затем подставьте точное имя:

```sh
service nfqws2-keenetic stop
mv /opt/etc/nfqws2 "/opt/etc/nfqws2.failed-$(date +%Y%m%d-%H%M%S)"
tar -xzf /opt/tmp/nfqws2-backup-YYYYMMDD-HHMMSS.tar.gz -C /opt/etc
service nfqws2-keenetic start
```

После успешного восстановления каталог `/opt/etc/nfqws2.failed` можно удалить вручную позднее.

### 16.3. Восстановить OpenWrt из backup

```sh
service nfqws2-keenetic stop
mv /etc/nfqws2 "/etc/nfqws2.failed-$(date +%Y%m%d-%H%M%S)"
tar -xzf /root/nfqws2-backup-YYYYMMDD-HHMMSS.tar.gz -C /etc
service nfqws2-keenetic start
```

## 17. Решение проблем конвертера

### `py` или `python` не найден

Python не установлен или не добавлен в `PATH`. Установите Python 3.9+ и перезапустите PowerShell.

### `No module named zapret_keenetic`

Команда запущена не из корня проекта. Выполните `Set-Location` в каталог, где находятся `pyproject.toml` и папка `zapret_keenetic`.

### `Профиль не найден`

Проверьте точное имя:

```powershell
Get-ChildItem "C:\Tools\zapret-discord-youtube" -Filter *.bat | Select-Object Name
```

Используйте кавычки вокруг имени со скобками и пробелами.

### `Выходной каталог не пуст`

Укажите новое имя каталога. Конвертер намеренно не перезаписывает существующий результат:

```powershell
--output ".\converted\alt11-v2"
```

### `missing-list`

Проверьте, что передан корневой каталог полной сборки Flowseal, а не каталог только с `.bat`.

### `missing-blob`

Профиль ссылается на файл из `bin/`, которого нет. Обновите/распакуйте Flowseal полностью. Не подменяйте blob произвольным файлом.

### `hostfakesplit-altorder`

Начиная с 0.4.0rc1 порядок `altorder=1` сохраняется встроенной Lua-функцией совместимости. Это информационная запись; `--strict` её не отклоняет. Порядок первого теста: [TEST_1_10_3_RU.md](TEST_1_10_3_RU.md).

### Нужна проверка всех неоднозначностей

Добавьте:

```powershell
--strict
```

Информационные сообщения о пустых пользовательских списках не считаются ошибкой, предупреждения считаются.

## 18. Решение проблем роутера

### `iptables: No chain/target/match by that name`

На Keenetic обычно не установлен компонент **Модули ядра подсистемы Netfilter**. Установите его через веб-интерфейс. На старой прошивке сначала может потребоваться компонент IPv6.

Проверьте модули:

```sh
lsmod | grep -E 'nfnetlink_queue|xt_NFQUEUE|xt_multiport|xt_connbytes'
```

### `can't initialize ip6tables table`

Установите IPv6/Netfilter-модули либо повторно сгенерируйте конфиг с `--no-ipv6`, если IPv6 не используется.

### Служба запущена, но сайты не работают

Проверяйте по порядку:

1. `ISP_INTERFACE` совпадает с `ip route show default`.
2. Устройство входит в нужную политику Keenetic.
3. Правила присутствуют в `iptables-save`.
4. На тестовом устройстве остановлены VPN, прокси и ПК-версия zapret.
5. Отключено или корректно настроено аппаратное ускорение/flow offloading.
6. Временно отключён IntelliQOS.
7. Сторонний интернет-фильтр не перехватывает DNS/трафик.
8. Браузер и приложение создали новые соединения после перезапуска.
9. Выбранный исходный профиль действительно работает у этого провайдера.

На Keenetic можно попробовать изменить состояние сетевого ускорителя и снова проверить. При аппаратном offloading пакеты могут обходить обычный путь Netfilter.

### Работает YouTube, но не Discord Voice

Проверьте:

- есть ли в `UDP_PORTS` диапазоны Discord;
- присутствуют ли UDP-правила в `iptables-save`;
- выбран ли профиль с `filter-l7=discord,stun`;
- не заблокирован ли UDP отдельной политикой/фаерволом;
- тестируется ли новое голосовое соединение после перезапуска службы.

### Работают сайты, но не игры

Профиль, вероятно, создан с `--game-filter disabled`. Повторите конвертацию с `all`, `tcp` или `udp`. Учтите рост нагрузки.

### Высокая загрузка CPU или падает скорость

1. Отключите Game Filter.
2. Используйте более узкий профиль/список.
3. Проверьте размер `ipset-all.txt`.
4. Убедитесь, что через NFQUEUE не направлены ненужные порты.
5. Сравните нагрузку командой `top` до и после запуска службы.

### Не хватает памяти

```sh
free
du -h /opt/etc/nfqws2/lists/* 2>/dev/null
du -h /etc/nfqws2/lists/* 2>/dev/null
```

На слабом маршрутизаторе используйте меньшие списки и `--game-filter disabled`. Не включайте огромный IPSet без необходимости.

### `readlink: not found` или `dirname: not found`

Для Entware:

```sh
opkg install busybox
```

Либо установите `coreutils-readlink` и `coreutils-dirname`.

### Ошибка загрузки `Packages.gz`

Проверьте системное время, DNS и SSL. Для Entware переустановите:

```sh
opkg install --force-reinstall wget-ssl
```

## 19. Что не нужно делать

- Не копируйте `winws.exe`, `WinDivert.dll` или `.sys`-драйверы на роутер.
- Не вставляйте сырой текст `.bat` в `nfqws2.conf`.
- Не переименовывайте blob-файлы после генерации: конфиг ссылается на конкретные имена.
- Не удаляйте штатную валидацию `nfqws2-keenetic`.
- Не заменяйте init-скрипт архивом из стороннего обсуждения.
- Не тестируйте одновременно с включённым zapret/VPN на клиентском ПК.
- Не включайте Game Filter «на всякий случай» на слабом роутере.
- Не удаляйте backup до нескольких дней стабильной работы.

## 20. Полезные ссылки

- [Исходные профили Flowseal](https://github.com/Flowseal/zapret-discord-youtube)
- [Официальная установка nfqws2-keenetic](https://github.com/nfqws/nfqws2-keenetic)
- [Документация zapret2](https://github.com/bol-van/zapret2/blob/master/docs/manual.md)
- [Обсуждение ранней попытки конвертации](https://github.com/Flowseal/zapret-discord-youtube/discussions/10996)
