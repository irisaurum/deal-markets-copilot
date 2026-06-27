# Setup Guide

## 1. Запуск без установки зависимостей

```bash
python3 run.py --demo
```

Откройте `output/deal_markets_brief.html`.

## 2. Live-режим

```bash
python3 run.py --live
```

Live-режим получает публичные новости и данные MOEX. Первый запуск создаёт baseline;
следующие запуски показывают новые события относительно него.

## 3. Настройка покрытия

В `config.json` измените:

- `coverage` — компании и тикеры;
- `deal_queries` — общерыночные запросы;
- `deal_hypotheses` — внутренние сценарии наблюдения;
- `workflow.deal_categories` — разрешённые категории;
- `thresholds` — минимальный score для dashboard и Telegram.

## 4. GitHub Pages

1. Создайте публичный GitHub-репозиторий.
2. Загрузите проект в ветку `main`.
3. Откройте **Settings → Pages**.
4. Выберите **Source: GitHub Actions**.
5. Откройте **Actions → Update Deal Desk → Run workflow**.

После успешного deployment GitHub покажет постоянную Pages-ссылку.

## 5. Telegram — опционально

Скопируйте `.env.example` в `.env` и заполните значения только локально:

```text
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Не добавляйте `.env` в Git. Для GitHub Actions используйте **Settings → Secrets and
variables → Actions**.

## Проверка

```bash
python3 -m unittest discover -s tests -v
```
