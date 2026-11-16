# Food Ordering AI Agent — Frontend

## API and restaurant configuration

The frontend supports these Vite environment settings:

- `VITE_AI_API_URL`: AI backend base URL. Defaults to the same origin so the Vite proxy can route `/api` requests.
- `VITE_MENU_API_URL`: menu backend base URL. Defaults to `/menu-api`, which uses the Vite proxy in development.
- `VITE_RESTAURANT_SUBDOMAIN`: restaurant tenant requested for menu, chat, cart, and ordering-intelligence calls. Defaults to `test` for local development and mocked E2E coverage.

Configure the production tenant explicitly at build time. Menu responses are accepted only when their `subdomain` exactly matches the requested tenant.

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend using TypeScript with type-aware lint rules enabled. Check out the [TS template](https://github.com/vitejs/vite/tree/main/packages/create-vite/template-react-ts) for information on how to integrate TypeScript and Oxlint's TypeScript related rules in your project.
