# Backend testing and database safety

## Database selection

The application settings in `src/configs/config.py` read `DATABASE_URL` from the process environment first, then `backend/.env`. `src/db/database.py` normalizes PostgreSQL URL schemes and creates the application SQLAlchemy engine and `SessionLocal` from that setting. `get_db()` opens a `SessionLocal` session and closes it after the request; it does not roll back committed changes.

When Python is running under pytest, `src/db/database.py` instead requires and validates all three explicit settings below, then binds the test engine and `SessionLocal` to `TEST_DATABASE_URL`. It never falls back to `DATABASE_URL`. Outside CI, it rejects a target that has the same host, port, and database name as the configured application database. CI may share the application's configured URL only when the database name contains a `ci` segment, as it points at the workflow's dedicated service. The check parses URL metadata only; it does not connect to PostgreSQL or verify the remote server's identity. The target URL's database name must exactly match `TEST_DATABASE_NAME`, and that name must contain a `test`, `ci`, or `e2e` segment. The confirmation value must exactly match the name.

CI already starts a dedicated PostgreSQL service with database name `food_ordering_ci`; both backend workflows now designate it explicitly and permit the CI-only same-target case. No local test database was verified during this work. Do not treat the database referenced by a local `.env` as a test database based on its presence or name alone.

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

The suite does not create a database fixture, wrap each test in a rollback, or consistently clean up rows. Many tests commit users, sessions, carts, preferences, and order history. Do not run database-backed tests against a shared, development, staging, or production database. This guard checks explicit target configuration and naming; it cannot prove ownership or isolation of the remote database without an out-of-band verification by its owner.

Database isolation does not isolate other external effects. Signup and verification API tests can call OTP delivery, which may send email or SMS when SMTP/Twilio settings are active. Checkout and order tests may call a configured menu/order service; some tests patch those calls, but not all have been audited for that purpose. Before running those tests, use test-only provider settings and confirm external delivery/order endpoints are disabled or mocked.

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

The provisioning script does not run migrations. Alembic uses the application `DATABASE_URL`; do not run migration commands for testing until the test target has been independently confirmed and `DATABASE_URL` has been safely directed to that target for the migration process.
