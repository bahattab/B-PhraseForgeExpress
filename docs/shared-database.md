# Shared phrase database (administrators)

PhraseForge can share folders and phrases with a team through **Microsoft SQL Server**
or **PostgreSQL** (Phrases > Shared database). Each PC keeps a local copy in a folder
named "Shared" and synchronizes it every minute: it downloads what others changed and
uploads what was changed on the PC. This is stage 1 (shared read and write). Folder
permissions per user or group come in stage 2.

## How users sign in

* **Windows account:** SQL Server integrated security (`Trusted_Connection`), or
  PostgreSQL with SSPI/GSSAPI. No password is typed or stored.
* **Database user name and password:** a SQL Server login or a PostgreSQL role. The
  server checks the password. PhraseForge stores it on the PC encrypted with Windows
  DPAPI, like its AI keys.

PhraseForge keeps no user list or password hashes of its own: the database decides who
may connect, and every change is recorded with the login the database reports
(`SUSER_SNAME()` / `current_user`).

## SQL Server

```sql
CREATE DATABASE PhraseForge;
GO
USE PhraseForge;
-- Windows sign-in: one login per AD group (or user)
CREATE LOGIN [CONTOSO\PhraseForge Users] FROM WINDOWS;
CREATE USER  [CONTOSO\PhraseForge Users] FOR LOGIN [CONTOSO\PhraseForge Users];
-- or a SQL login with a password
CREATE LOGIN pf_user WITH PASSWORD = 'change-me-Str0ng!';
CREATE USER  pf_user FOR LOGIN pf_user;
```

Create the tables once from PhraseForge (**Create tables**), signed in as a user allowed
to create tables (for example `db_owner`). Then give everyone else read and write access:

```sql
GRANT SELECT, INSERT, UPDATE ON dbo.pf_meta    TO [CONTOSO\PhraseForge Users];
GRANT SELECT, INSERT, UPDATE ON dbo.pf_rev     TO [CONTOSO\PhraseForge Users];
GRANT SELECT, INSERT, UPDATE ON dbo.pf_folders TO [CONTOSO\PhraseForge Users];
GRANT SELECT, INSERT, UPDATE ON dbo.pf_phrases TO [CONTOSO\PhraseForge Users];
```

The client needs "ODBC Driver 18 for SQL Server" (or 17) from Microsoft; the old built-in
"SQL Server" driver also works, but it cannot encrypt. The connection is encrypted by
default. Tick "Trust the server certificate" only for a server with a self-signed
certificate.

## PostgreSQL

```sql
CREATE ROLE pf_admin LOGIN PASSWORD 'change-me';
CREATE DATABASE phraseforge OWNER pf_admin;
CREATE ROLE pf_users;                         -- a group
CREATE ROLE ali LOGIN PASSWORD 'change-me' IN ROLE pf_users;
```

Sign in as `pf_admin`, click **Create tables**, then:

```sql
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO pf_users;
```

For Windows sign-in, add an `sspi` (Windows server) or `gss` (Kerberos) line for the
PhraseForge users to `pg_hba.conf`, and create a role named after each Windows user.

## What is stored

| Table | Contents |
|---|---|
| `pf_meta` | schema version |
| `pf_rev` | one counter; every change takes the next number |
| `pf_folders` | id, parent, name, order, revision, deleted, changed by, changed at |
| `pf_phrases` | id, folder, description, text, format (text/HTML), triggers (JSON), revision, deleted, changed by, changed at |

Rows are only marked deleted, never removed, so every PC learns about deletions.

## Conflicts and safety

* When two people change the same phrase, the version saved first on the server wins.
  The other version is kept as "(conflict copy)" next to it and shared too, so no text
  is lost.
* If a user deletes the local "Shared" folder, nothing is deleted on the server: the PC
  downloads everything again.
* Phrases changed by someone else arrive in PhraseForge's quarantine, so their
  `{#run}`-type macros wait for the user's approval (like a cloud sync pull).
* An administrator's `policy.toml` with `editing_disabled = true` still lets shared
  phrases arrive. A read-only team then gets `SELECT` only.
