# Shared phrase database (administrators)

PhraseForge can share folders and phrases with a team through **Microsoft SQL Server**
or **PostgreSQL** (Phrases > Shared database). Each PC keeps a local copy in a folder
named "Shared" and synchronizes it every minute: it downloads what others changed and
uploads what was changed on the PC. Folders can be limited to users and groups, and
every change is kept in a history from which an earlier version can be restored.

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
GRANT SELECT, INSERT, UPDATE ON dbo.pf_acl     TO [CONTOSO\PhraseForge Users];
GRANT SELECT, INSERT         ON dbo.pf_history TO [CONTOSO\PhraseForge Users];
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

## Folder permissions

**Shared database > Permissions...** lists who may do what. An entry gives a user, a group
(an AD group on SQL Server, a role on PostgreSQL) or `*` (everyone) **read**, **read and
write** or **no access** to one folder or to the whole database. For a folder, the
nearest folder that has entries for you (the folder, then its parents, then the whole
database) decides; within it, any matching entry with write access lets you write.
**Administrators** (set for the whole database) may do everything and are the only ones
who can change permissions. The last administrator cannot be removed.

When the tables are created, whoever created them becomes administrator and `*` gets read
and write on the whole database (so a stage-1 database keeps working after the upgrade).
To limit access, remove the `*` entry and add your groups.

> **Important:** these permissions are applied **by PhraseForge**. Anyone who can connect
> to the database with another program (SQL Server Management Studio, psql ...) can
> still read and change every table. For real protection, also use the database's own
> permissions, for example a separate database per department.

PhraseForge receives only what you may read: a folder you may not read never reaches your
PC, and when permissions change, the next sync removes copies you may no longer read. A
change you are not allowed to make is undone; your text is kept in the local folder
"Not saved to the shared database".

## History

Every change (created, changed, deleted, restored) is kept with who made it and when.
Right-click a shared phrase > **Shared history...** to see its versions and restore one,
also for a deleted phrase; everyone receives the restored version at the next sync.

## What is stored

| Table | Contents |
|---|---|
| `pf_meta` | schema version |
| `pf_rev` | one counter; every change takes the next number |
| `pf_folders` | id, parent, name, order, revision, deleted, changed by, changed at |
| `pf_phrases` | id, folder, description, text, format (text/HTML), triggers (JSON), revision, deleted, changed by, changed at |
| `pf_acl` | folder (empty = whole database), user / group / `*`, type, read, write, administrator |
| `pf_history` | every version of every folder and phrase: action, contents, who, when |

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
