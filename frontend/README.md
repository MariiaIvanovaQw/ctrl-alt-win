# Веб-приложение

React 19, TypeScript, Vite. Кабинеты кандидата, работодателя и модератора,
публичные страницы и экран «Как формируется тест». Фирменный стиль ФСП
по брендбуку, адаптивная вёрстка. Сторонних UI-библиотек нет.

## Запуск

Node.js 20+ и API на `http://localhost:8000` ([../backend/README.md](../backend/README.md)).

```bash
npm install
npm run dev        # http://localhost:5173
```

Адрес API задаётся `VITE_API_BASE` в `.env` (пример – `.env.example`) и
вшивается в бандл при сборке.

| Команда | Что делает |
|---|---|
| `npm run build` | проверка типов и сборка в `dist/` |
| `npm run lint` | статический анализ (oxlint) |
| `npm run typecheck` | только проверка типов |
| `npm run api:types:file` | типы `src/api/schema.ts` из `../docs/openapi.json` (`api:types` – с запущенного API) |

Образ: `docker build -f frontend/Dockerfile -t fsp-talent-web frontend` –
сборка Vite и раздача nginx с заголовками безопасности и CSP; неизвестные
пути отдают `index.html`, чтобы работали прямые ссылки.

## Устройство

```
src/
  api/         клиент HTTP, типы предметной области, справочники (ReferenceContext)
  auth/        контекст авторизации
  components/  элементы интерфейса (ui.tsx), доменные блоки (domain.tsx), каркас
  lib/         форматирование, хуки загрузки данных и черновиков форм
  pages/       экраны: public, candidate, employer, admin
  styles/      токены брендбука, база, элементы, каркас
public/brand/  логотипы ФСП, графика и шрифт JetBrains Mono из брендбука
```

`api/client.ts` хранит пару токенов (изменения расходятся между вкладками),
обновляет access-токен одним общим запросом – API считает повторное
предъявление refresh-токена кражей сессии – и превращает ответ
`{"error": {code, message, details}}` в `ApiError`. Сообщения приходят с
бэкенда на русском и показываются как есть. Типы экранов описаны вручную
в `api/types.ts`, машинная спецификация – `api/schema.ts`.

## Экраны

| Раздел | Пути |
|---|---|
| Публичные | `/`, `/vacancies`, `/how-testing-works`, `/login`, `/register`, `/consent` |
| Кандидат | `/candidate` (следующий шаг), `/profile` (анкета, PDF-резюме), `/assessment` (опрос, тест, категория), `/invitations`, `/vacancies`, `/applications`, `/tasks`, `/fsp`, `/settings` |
| Работодатель | `/employer/selection` (подборка), `/categories`, `/search`, `/candidates/:id`, `/needs`, `/invitations`, `/applications`, `/tasks`, `/webhooks`, `/company` |
| Модератор | `/admin/companies` |

Вилка зарплаты – первая строка приглашения и вакансии; данные анкеты
подписаны «заявлено кандидатом», результаты теста – «подтверждено тестом»;
у каждого места в подборке видно разложение балла; правильные ответы
теста не показываются даже в своём разборе.

## Библиотеки

react и react-dom 19.3.0, react-router-dom 7.18.4, vite 8.3.3,
@vitejs/plugin-react 6.1.2, typescript 5.9.3, openapi-typescript 7.13.0,
oxlint 1.87.0 – все MIT, кроме TypeScript (Apache-2.0). Шрифт JetBrains
Mono – SIL Open Font License 1.1 (`public/brand/fonts/OFL.txt`).
