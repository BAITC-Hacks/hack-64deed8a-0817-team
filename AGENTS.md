# AGENTS.md — rules for every coding agent in this repo

## Scope
- Work only inside this repository. Never create, clone or init other repos, worktrees or branches.
- Never touch servers, SSH, cloud consoles or anything outside this repo.
- Edit only the files your role owns (backend/, frontend/, docs). Ask before touching another role's files.

## Honesty
- No mocks, stubs or canned answers in core features. Every result comes from real computation, a real model call or real data.
- If a key is missing or an external call fails, return a clear error (HTTP 4xx/503 + JSON `{"error": "..."}`). Never fake success.
- Never invent facts, numbers, metrics or features, in code, UI or README.

## Robustness
- Validate every input (types, ranges, required fields, file size/format).
- Bad input -> readable 4xx JSON error. Never return raw tracebacks or 500 pages to the client.
- Every external HTTP/LLM call has an explicit timeout and handled failure.

## Config & security
- Config only via environment variables. `.env` is never committed; every variable is listed in `.env.example` with an empty or safe value.
- Pin every dependency version exactly (`==` in requirements.txt, exact versions in package.json / lockfile committed).
- Docker ports bind to 127.0.0.1 only: `"127.0.0.1:8000:8000"`, never `"8000:8000"`.
- Sample input data lives in `samples/` and is enough to run the main scenario.

## Structure
- Flat, obvious layout: backend `routers/`, `services/`, `models/`; frontend `src/`.
- No file over ~300 lines; split by responsibility.
- Delete dead code, unused files and commented-out blocks before pushing.
- The README architecture section must match the real code. Update it in the same commit when structure changes.

## Git
- Small commits, short English imperative messages ("Add tariff scoring endpoint").
- `git pull --rebase` before every push. Never force-push. Never rewrite pushed history.
- Run `git status` before committing; never commit `.env`, keys, caches or build output.
