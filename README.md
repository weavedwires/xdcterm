# XDCterm

Terminal emulator for Delta Chat.

![XDCterm icon](frontend/public/icon.png)

---

## Зачем

XDCterm — это терминальный эмулятор, работающий через WebXDC внутри Delta Chat и других WebXDC-совместимых мессенджеров. Позволяет запускать полноценную shell-сессию на сервере прямо из чата, без установки дополнительного ПО на стороне клиента. Подходит для администрирования, отладки и выполнения команд на удалённой машине через знакомый интерфейс мессенджера.

---

## Установка

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
uv run bot.py
```

После запуска бот регистрируется в Delta Chat. Пользователи получают доступ через `/start` или SecureJoin.

### Запуск на постоянку

Сервис запускается от непривилегированного пользователя через systemd.

```bash
cp xdcterm.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now xdcterm
sudo loginctl enable-linger user
```

### Ссылки и логи использования терминала

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
