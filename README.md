# XDCterm

Terminal emulator for Delta Chat.

![XDCterm icon](frontend/public/icon.png)

---

## Зачем

XDCterm — это терминальный эмулятор, работающий через WebXDC внутри Delta Chat и других WebXDC-совместимых мессенджеров. Позволяет запускать полноценную shell-сессию на сервере прямо из чата, без установки дополнительного ПО на стороне клиента. Подходит для администрирования, отладки и выполнения команд на удалённой машине через знакомый интерфейс мессенджера.

---

## Установка

Build order — сначала frontend, потом backend.

### Frontend

```bash
cd frontend
npm install
npm run build
```

Собирает `dist-release/xdcterm.xdc`.

### Backend

```bash
cd backend
uv sync
```

### Инициализация аккаунта и тестовый запуск

```bash
cd backend
uv run bot.py init DCACCOUNT:nine.testrun.org
uv run bot.py serve
```

Подставьте свой сервер вместо `nine.testrun.org`.

### Деплой (systemd user service)

Содержимое `xdcterm.service`:

```ini
[Unit]
Description=xdcterm Delta Chat bot
After=network-online.target

[Service]
Type=simple
Environment=TERM=xterm-256color
WorkingDirectory=/home/user/python/xdcterm
ExecStart=/home/user/.local/bin/uv run --directory backend bot.py serve
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

```bash
# скопировать сервис
cp xdcterm.service ~/.config/systemd/user/

# перечитать юниты
systemctl --user daemon-reload

# запустить
systemctl --user enable --now xdcterm

# включить автозапуск после перезагрузки
sudo loginctl enable-linger user
```

### Логи

```bash
journalctl --user -u xdcterm -f
```


---

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Отправляет WebXDC-приложение в чат |
| `/list`  | Показывает активные PTY-сессии |

Первые `/start` от нового пользователя — он автоматически добавляется.  
Первый пользователь бота становится администратором (получает уведомления об открытии/закрытии сессий).

---

## Фичи

- Полноценный PTY-терминал через Delta Chat WebXDC
- Поддержка sixel-графики (xterm.js ImageAddon)
- Несколько одновременных сессий
- SecureJoin-онбординг без ручного добавления
- Первый пользователь — автоматический администратор
- Уведомления админу об открытии/закрытии сессий
- Автозакрытие неактивных PTY через 60 секунд
- Кастомный шрифт JetBrains Mono Nerd Font

---

## Протокол

Бинарный протокол поверх WebXDC realtime. Первый байт — команда, остальное — payload.

| Байт | Команда | Payload |
|------|---------|---------|
| `0x49` | INPUT | UTF-8 ввод с клавиатуры → PTY |
| `0x4f` | OUTPUT | Вывод PTY (stdout) → терминал |
| `0x45` | EXIT | (нет payload) — PTY завершён |
| `0x52` | RESIZE | 4 bytes: cols hi/lo, rows hi/lo |
| `0x43` | LIFECYCLE | 1 byte: `0x01` = open, `0x00` = close |

Heartbeat: фронтенд шлёт `LIFECYCLE_OPEN` каждую секунду, пока видим.  
`LIFECYCLE_CLOSE` — при hide/pagehide.

---

## Лицензия

0BSD. Полный текст — в файле [LICENSE](LICENSE).
