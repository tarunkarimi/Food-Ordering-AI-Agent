# Backend testing and database safety

## Database selection

The application settings in `src/configs/config.py` read `DATABASE_URL` from the process environment first, then `backend/.env`. `src/db/database.py` normalizes PostgreSQL URL schemes and creates the application SQLAlchemy engine and `SessionLocal` from that setting. `get_db()` opens a `SessionLocal` session and closes it after the request; it does not roll back committed changes.

When Python is running under pytest, `src/db/database.py` requires and validates all three explicit test settings, then binds the test engine and `SessionLocal` to `TEST_DATABASE_URL`. It never falls back to `DATABASE_URL`. Test URLs must use `localhost` or a loopback IP literal; remote DNS names, Supabase hosts, and remote IP addresses are rejected without DNS resolution, including when `CI=true` is set locally. It also rejects database names containing a `prod`, `production`, or `live` segment. The target URL's database name must exactly match `TEST_DATABASE_NAME`, and that name must contain a `test`, `ci`, or `e2e` segment. The confirmation value must exactly match the name.

CI starts a dedicated PostgreSQL service with database name `food_ordering_ci`; workflows set explicit test and migration URLs for that service and use an inert placeholder for runtime `DATABASE_URL`. The local test guard remains loopback-only and does not contain a developer-enabled CI bypass. No local test database was verified during this work. Do not treat the database referenced by a local `.env` as a test database based on its presence or name alone.

## Safe commands

Run the guard's isolated unit tests from `backend/`. They use synthetic URL strings and do not import the application database module or open a connection:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_db_test_safety.py -q
```

Memory extraction, memory-aware ranking, prompts, and the database-safety
guard can be checked locally without a database:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_ai_memory_unit.py tests/test_recommendations.py tests/test_recommendation_ranking.py tests/test_personalization_prompt.py tests/test_db_test_safety.py -q
```

For any database-backed test, first obtain a dedicated, disposable PostgreSQL database from the environment owner. Have a secret manager inject its URL into `TEST_DATABASE_URL`; do not put credentials in source, terminal transcripts, or logs. In the same PowerShell session, set the non-secret designation values:

```powershell
$env:TEST_DATABASE_NAME = "food_ordering_test"
$env:TEST_DATABASE_CONFIRMATION = "I_ACKNOWLEDGE_TEST_DATABASE:food_ordering_test"
```

After the database owner confirms the target and its schema is prepared, run a narrowly selected test from `backend/`, for example:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_auth_sessions.py -q
```

The database-backed authenticated integration regression is
`tests/test_authenticated_persistence_regressions.py`. CI runs it after the
`food_ordering_ci` service migrations with:

```powershell
uv run pytest tests/test_authenticated_persistence_regressions.py -q
```

That regression creates two synthetic verified users directly, mocks OTP
delivery, menu access, and HTTP order-service calls, then deletes only those
user IDs in a fixture finalizer. Do not run it locally unless an owner has
separately verified a dedicated test database.

Conversational memory persistence and authenticated chat-context regressions
also run only after the workflow migrations, using its isolated PostgreSQL
service:

```powershell
uv run pytest tests/test_ai_memory_integration.py tests/test_ai_memory_persistence_regressions.py -q
```

The new persistence regression creates synthetic users and deletes only its
own rows. The authenticated API tests use synthetic signup users, mock OTP
delivery, and delete only IDs recorded by each test through existing foreign
key cascades; run these DB-backed tests only in the isolated CI database unless
a separate disposable test database has been verified.

The memory-aware recommendation service and ranking tests are deterministic
and database-independent:

```powershell
uv run pytest tests/test_recommendations.py tests/test_recommendation_ranking.py -q
```

The suite does not create a database fixture, wrap each test in a rollback, or consistently clean up rows. Many tests commit users, sessions, carts, preferences, and order history. Do not run database-backed tests against a shared, development, staging, or production database. The test guard requires a literal loopback target and does not resolve hostnames; it cannot prove which local process is listening on that port, so verify the local service identity before running integration tests.

The shared `tests/conftest.py` replaces route-level OTP delivery with a no-op for every pytest test. OTP codes are never written to logs, including in local development; configure a mail or SMS provider for delivery. Tests that call non-test menu or order services must still mock those calls; database isolation alone does not isolate external systems.

Menu PostgreSQL persistence integration tests are CI-only and additionally
require a loopback database host. The menu migration URL, when set, must point
to the same database as `MENU_DATABASE_URL`. The GitHub Actions service is the
supported disposable target; do not run these tests against any remote host.

The Full Stack CI workflow runs authenticated checkout and cancellation persistence regressions after migrations. Its database-independent order-status, OTP-delivery, and observability unit tests run in the same job. The frontend job runs the mocked Chromium E2E suite after lint/build; each test intercepts API requests and blocks unexpected external requests. The menu-backend CI job uses its own ephemeral PostgreSQL 16 service, applies the menu-owned schema migration, runs mocked API tests, then runs PostgreSQL persistence, ownership, cancellation, idempotency, and concurrency regressions. The backend CI job separately migrates both schemas before its in-process order lifecycle regression. Application replicas do not run migrations at startup.

The menu backend protects order creation, status, and cancellation endpoints with the internal `X-Menu-Service-Key` header. Backend local runs must set `MENU_SERVICE_API_KEY` to the same synthetic value configured for `menu-backend`; CI supplies a test-only value. Configure the same high-entropy value (at least 32 characters) in the secret manager for both deployed services. Do not print or commit the key. Public menu and health endpoints do not require it.

Menu-backend order status and cancellation lookups require both the exact `subdomain` and authenticated `user_id`; mismatches return 404 before state is read or changed. Checkout requires the service key, owner, tenant, and a stable `Idempotency-Key`; the PostgreSQL unique constraint scopes that key to owner and tenant. Repeated cancellation is idempotent.

The menu migration is independent from backend Alembic history. Run it once from `menu-backend/` as a controlled release step using `MENU_MIGRATION_DATABASE_URL`; application startup never runs migrations. The current Render free-service configuration has no configured one-shot release runner, so production rollout must provide a separate migration runner before enabling the new menu backend version.

## Recommendation ingredient-data limitation

The current `menu-backend` menu items do not define an ingredient list or a
completeness indicator. Recommendation filtering therefore treats an explicit
disliked food as unsafe when the current menu text does not establish a match
and the item has no complete ingredient metadata. Items are eligible for a
known non-match only when `ingredients` is present and
`ingredients_complete` is explicitly `true`; a matching ingredient is always
excluded. Vegan recommendations likewise require an explicit vegan dietary
label or a non-empty complete ingredient list that contains no known animal
ingredients. Until the menu contract supplies these fields consistently, this
conservative behavior can return fewer or no recommendations for users with
explicit restrictions.

## E2E user provisioning

`scripts/provision_e2e_user.py` changes or creates the fixed Playwright account and resets its login-throttle state. It now refuses to proceed unless `TEST_DATABASE_URL`, `TEST_DATABASE_NAME`, and the matching `TEST_DATABASE_CONFIRMATION` are present and valid. Its session factory is bound directly to the designated test URL; it does not use `SessionLocal` from the application database. Provisioning still modifies the selected database, so run it only after confirming the target is disposable and migrated.

Only after that confirmation and after securely supplying the variables above, the provisioning command is:

```powershell
.\.venv\Scripts\python.exe scripts/provision_e2e_user.py
```

The provisioning script does not run migrations. Main-backend Alembic requires an explicit `MIGRATION_DATABASE_URL`; it never falls back to `DATABASE_URL`. Menu Alembic likewise requires `MENU_MIGRATION_DATABASE_URL` and never falls back to `MENU_DATABASE_URL`. For local or test migrations, inject these values only after independently confirming the target is disposable and migrated schema changes are intended.
