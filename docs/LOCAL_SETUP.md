# 6.2. Инструкция по развертыванию и запуску — локальный запуск

Этот файл содержит инструкцию локального запуска из раздела 6.2 технической документации проекта. Для использования опубликованного сервиса достаточно открыть [RoboSelect](https://roboscope-5562.onrender.com/).

## Подготовка окружения

Требуются Git и Python 3.12. При отсутствии переменной `DATABASE_URL` приложение использует локальную базу SQLite. Для PostgreSQL задайте `DATABASE_URL` в окружении перед миграциями. Файл `.env` при обычном запуске `manage.py` автоматически не читается.

### Windows PowerShell

```powershell
git clone https://github.com/sadb22/roboscope.git
cd roboscope
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
$env:DEBUG="1"
$env:PASSWORDLESS_DEMO="1"
.\.venv\Scripts\python.exe manage.py migrate --noinput
.\.venv\Scripts\python.exe manage.py seed_data
```

### Linux и macOS

```bash
git clone https://github.com/sadb22/roboscope.git
cd roboscope
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
export DEBUG=1
export PASSWORDLESS_DEMO=1
python manage.py migrate --noinput
python manage.py seed_data
```

## Первичное наполнение расширенного каталога

Команда `initialize_workflow` использует существующего служебного администратора для авторства начальных данных. На новой базе создайте эту запись, затем наполните каталог и соберите статические файлы. Это не меняет демонстрационный вход посетителей: пароль им не требуется.

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py initialize_workflow
.\.venv\Scripts\python.exe manage.py collectstatic --noinput
```

Linux/macOS, с активированным окружением:

```bash
python manage.py createsuperuser
python manage.py initialize_workflow
python manage.py collectstatic --noinput
```

Если служебный администратор уже существует, повторно создавать его не нужно. Импортированные парсером данные проходят проверку перед публикацией.

## Запуск веб-приложения

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8765
```

Linux/macOS:

```bash
python manage.py runserver 127.0.0.1:8765
```

Откройте [http://127.0.0.1:8765/](http://127.0.0.1:8765/). «Вход как пользователь» сразу открывает расчёт и визуализацию по адресу `/legacy/`. «Вход как администратор» открывает ассортимент по адресу `/workspace/robots/`.

## Запуск обработчика симуляций

Второй терминал должен быть открыт в том же каталоге проекта и использовать ту же базу данных. Если вы задали `DATABASE_URL` или другие переменные только в первом терминале, повторите их во втором.

Windows PowerShell:

```powershell
$env:DEBUG="1"
$env:PASSWORDLESS_DEMO="1"
.\.venv\Scripts\python.exe manage.py simulation_worker
```

Linux/macOS:

```bash
source .venv/bin/activate
export DEBUG=1
export PASSWORDLESS_DEMO=1
python manage.py simulation_worker
```

Оставьте оба процесса работающими. Обработчик выполняет фоновые симуляции базового модуля; без него задания остаются в очереди. Для остановки каждого процесса нажмите `Ctrl+C` в соответствующем терминале.

## Проверка

С активированным виртуальным окружением выполните:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test core workflow --noinput
```

В PowerShell без активации замените `python` на `.\.venv\Scripts\python.exe`.

Проверьте открытие `/health/`, состояние обработчика `/api/worker-health/`, переход пользователя к расчёту и недоступность административных операций в пользовательской роли.

## Режим доступа и серверное развёртывание

`PASSWORDLESS_DEMO=1` включает выбор роли без паролей. Административную роль может выбрать любой посетитель; проекты привязаны к сессии браузера. При `PASSWORDLESS_DEMO=0` используется механизм учетных записей и назначенных прав. Подробнее: [PASSWORDLESS_DEMO.md](PASSWORDLESS_DEMO.md).

`runserver` предназначен для локальной разработки. Серверная версия запускается через Gunicorn с `DEBUG=0`, секретным ключом и PostgreSQL. Для Render используется [render.yaml](../render.yaml) и [scripts/render_start.py](../scripts/render_start.py); для собственного сервера — [DEPLOYMENT.md](DEPLOYMENT.md).
