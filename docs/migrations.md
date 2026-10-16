# Homer migrations

Migration files are numbered SQL files named `NNN_description.sql`.

- Built-in Homer migrations: `lib/migrations/<driver>/`
- Project migrations: `migrations/<driver>/`
- Supported driver folders: `sqlite`, `postgres`, `oracle`, and `mysql`

Run `./homer migrate` from the Homer checkout to apply pending built-in and
project migrations. Built-in migrations run first. Applied files are recorded
in `homer_migrations`; plugin migrations remain managed separately by
`plugin:migrate`.

Applied migration files are immutable. To change a schema after a migration has
run, add a new numbered file instead of editing the old one.
