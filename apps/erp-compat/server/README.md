# Raj Ads ERP API

Java 21 / Spring Boot API for operator balance settlement records.

## Run locally

```bash
SPRING_DATASOURCE_URL='jdbc:h2:mem:erp;MODE=PostgreSQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1' \
SPRING_DATASOURCE_USERNAME=sa SPRING_DATASOURCE_PASSWORD='' \
mvn spring-boot:run
```

The first empty database bootstraps the development user `admin` / `admin123`. Override it only for a new empty database with `ERP_BOOTSTRAP_ADMIN_USERNAME` and `ERP_BOOTSTRAP_ADMIN_PASSWORD`; an existing database is never given a replacement administrator automatically.

The API is served at `http://localhost:8080/api/v1`, OpenAPI is at `/swagger-ui.html`, and readiness is `/actuator/health/readiness`.

Authentication uses an HttpOnly server session. `POST /api/v1/auth/login` is CSRF-exempt; call `GET /api/v1/auth/csrf` before other writes, then send the returned `X-XSRF-TOKEN` value (the endpoint also writes `XSRF-TOKEN`). Vite development origins on localhost are allowed by default.

For production use PostgreSQL via `SPRING_DATASOURCE_URL`, `SPRING_DATASOURCE_USERNAME`, and `SPRING_DATASOURCE_PASSWORD`; use a non-default bootstrap password before the first launch.
