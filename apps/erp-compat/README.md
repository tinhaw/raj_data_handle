# ERP compatibility source snapshot

This directory is the high-fidelity migration source imported from
`/Users/dinghao/Documents/code/raj-ads-manage` at commit
`7a64926d9b7261744d616672bbfa31732b81a661` on 2026-08-27.

Status: **imported; shared identity/remote registry, local P3 core and P4
redemption compatibility schema integrated; production migration not run**.

The executable entry point is disabled unless
`ERP_COMPATIBILITY_MODE_ENABLED=true` is supplied explicitly. Legacy Flyway
migrations and every remote operation are independently disabled by default.
Those switches are safeguards, not deployment instructions.

The snapshot intentionally preserves the deployed ERP page structure, API
contracts, business services, state machines and regression tests. It is not a
second identity or remote-account application. The production Compose definition
mounts it only as a compatibility process over the same `data_handle` database;
the process remains inactive until the separately authorised application/schema
release is executed.

Before activation it must be adapted as follows:

1. Remove the legacy login, password and independent session lifecycle. Reuse
   the Raj Data Handle user and session records.
2. Replace legacy remote-market and remote-connection credential persistence
   with `SourceConfig` and `RemoteAccount` compatibility adapters.
3. Local operator, ledger, lock, import and audit tables use Alembic 0036;
   redemption campaigns, task groups, batches and issues use Alembic 0037.
   Never run the imported Flyway chain against `data_handle`.
4. The compatibility API is mounted in deployment code under
   `/erp-api/api/v1`; the seven ERP business pages now use the imported page
   modules under their formal routes. Unified users/settings/remote-account
   pages intentionally remain owned by the main application.
5. Keep every remote check, tag sync, create, publish, cancel and download
   operation disabled until the corresponding capability and one-time
   execution authorization have both been validated.

The active identity/data ownership contract is documented in
`docs/erp-compatibility-boundary.md`.

Upstream build artifacts, dependency directories and the upstream `data/`
directory were not imported.
