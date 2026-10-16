# Running your own Instance

An Instance is one hosted copy of Road Ready TN, run by a Helper for the Learners they give access to. It is one container on the stock `python:3.14-slim` image, with nothing to build: the repo is mounted read-only, and everything the Instance keeps (the database and its backups) lives in one writable folder, **the Instance folder**.

There are no secrets to configure. Helper accounts are made with a command inside the container, and Learner accounts from the Helper's view.

## What you need

- **Docker with Compose** (`docker compose`).
- **git**, to get the code and to update it.
- **An HTTPS reverse proxy in front of the container.** This is required. Sign-in cookies are `Secure`, so browsers only keep them over HTTPS, and the container itself only speaks plain HTTP. The container publishes its port on `127.0.0.1` only, so the proxy runs on the same machine, or joins the container's Docker network (see the comment in `compose.yaml`). Any proxy works if it:
  - passes on the browser's `Origin` header unchanged, because every sign-in and change is checked against `RRTN_ORIGIN`, and
  - sets `X-Forwarded-For` (and `X-Forwarded-Proto`), so the server knows each client's IP.

  The app sends no `Strict-Transport-Security` (HSTS) header. If you want HSTS, set it at the proxy.

## Set up

1. Clone the repo and go into it:

   ```sh
   git clone <the repo's URL> road-ready-tn
   cd road-ready-tn
   ```

2. Copy the example settings and fill them in:

   ```sh
   cp .env.example .env
   ```

   Two values are required: `RRTN_ORIGIN`, the address people will open, and `RRTN_TRUSTED_PROXY`, the proxy's IP. See [Settings](#settings). `.env` is ignored by git.

3. Make the Instance folder and give it to the user the container runs as (`RRTN_UID` and `RRTN_GID` in `.env`, both `1000` unless you change them):

   ```sh
   mkdir instance
   sudo chown 1000:1000 instance
   ```

   If the owner doesn't match, the container stops at start with `RRTN_DIR /var/lib/rrtn can't be written to (Permission denied)`.

4. Start it:

   ```sh
   docker compose up -d
   ```

5. Check that it is running. After about ten seconds, `docker compose ps` shows the container as `(healthy)`. The health check asks the server for `/healthz`, which you can also try yourself on the machine:

   ```sh
   docker compose ps
   curl http://127.0.0.1:8080/healthz
   ```

   If it isn't healthy, `docker compose logs app` says why. A missing or wrong setting is named in one line.

Then point the proxy at `127.0.0.1:8080` (or your `RRTN_PORT`) and open `RRTN_ORIGIN` in a browser. You should see the sign-in page.

## Make the first Helper

```sh
docker compose exec app python -m server.manage add <name>
```

It asks for the password twice. Passwords are 8 to 128 characters and are never typed on the command line. Until a Helper exists, the log (`docker compose logs app`) names this command.

The same command manages Helper accounts later:

- `python -m server.manage password <name>` sets a new password for a Helper and ends their sign-ins.
- `python -m server.manage remove <name>` deletes a Helper.

Run each one with `docker compose exec app` in front, as above.

## Add Learners

Sign in as the Helper and use "Add a Learner". You choose the Learner's name and password there, and the Helper's view is where you rename a Learner, give them a new password ("Reset sign-in"), follow their progress, or delete them.

## Putting the app on a Learner's iPhone

1. Open the Instance in Safari and sign in as the Learner.
2. Tap Share, then Add to Home Screen. Then open the app from the Home Screen.
3. From iOS 17.2 the sign-in carries over. On older iOS, sign in once more in the app.

Signing in in Safari first lets any old progress saved in Safari be imported. If the Learner already has the old app on the Home Screen, open that same app and sign in there, without deleting it first. The old progress is kept inside that app.

## Update

Every time:

```sh
git pull
docker compose restart
```

The restart is what loads the new code, and any database changes run by themselves at start. You never need to work out which files changed.

Two cases need `docker compose up -d` as well:

- If a `git pull` changes `compose.yaml` or you change `.env`, run `docker compose up -d` so the container is made again with the new settings.
- The image's Python patch version isn't pinned. To pick up its security fixes, now and then run `docker compose pull` and then `docker compose up -d`.

## Back up and restore

To back up:

```sh
docker compose exec app python -m server.manage backup
```

This writes a consistent copy of the database to `instance/backups/<YYYY-MM-DD-HHMMSS>.db` (the time is UTC) while the Instance keeps running, and prints its path. It is safe to schedule, for example from cron. In a scheduled job, run it from the repo folder and add `-T`, because there is no terminal:

```sh
docker compose exec -T app python -m server.manage backup
```

Old backups are never deleted for you. Copy them somewhere off the machine too, because a backup in the Instance folder is lost with the disk.

To restore a backup:

1. Stop the container:

   ```sh
   docker compose stop
   ```

2. Replace `instance/rrtn.db` with the backup, and remove `instance/rrtn.db-wal` and `instance/rrtn.db-shm` if they are there:

   ```sh
   cp instance/backups/<YYYY-MM-DD-HHMMSS>.db instance/rrtn.db
   rm -f instance/rrtn.db-wal instance/rrtn.db-shm
   ```

   The file must still belong to `RRTN_UID:RRTN_GID`. If you copied it as another user, `chown` it again.

3. Start it again:

   ```sh
   docker compose start
   ```

Everything that changed since the backup is gone, such as accounts added and progress sent since then, and anyone who signed in since then signs in again.

## If sign-in is paused

Failed sign-ins are counted two ways, and too many pause new sign-ins for a while:

- **Per name:** after 10 failed tries for one name, sign-in for that name is paused for 15 minutes. Each further pause with no successful sign-in in between doubles, up to 24 hours. Names that don't exist are paused the same way.
- **Per IP:** 50 failed tries from one IP within an hour, across any names, pause that IP for 1 hour.

People already signed in are not affected. Every pause ends by itself. To end them sooner:

- For one Learner: the Helper uses "Reset sign-in" on that Learner, which also gives them a new password.
- For one Helper: `docker compose exec app python -m server.manage password <name>`.
- For everyone, names and IPs:

  ```sh
  docker compose exec app python -m server.manage unlock
  ```

Every sign-in is logged, with the time, the client IP, the name and the outcome, and so is every pause. Passwords are never logged. Read the log with `docker compose logs app`.

The per-IP count relies on `RRTN_TRUSTED_PROXY` being right. To check it, sign in once and look at `ip="…"` in the log. It should be your device's IP. If it shows the proxy's own address instead, `RRTN_TRUSTED_PROXY` doesn't match the proxy; set it to the address shown and run `docker compose up -d`.

## Settings

Settings go in `.env`, next to `compose.yaml`. After changing one, run `docker compose up -d`.

| Variable | What it does | Default |
| --- | --- | --- |
| `RRTN_ORIGIN` | **Required.** The public address people open, scheme and host only, like `https://permit.example.org`. Sign-ins and changes are accepted only from a page at this address. | none |
| `RRTN_TRUSTED_PROXY` | **Required.** The reverse proxy's IP, as the container sees it. The server takes the client's IP from `X-Forwarded-For` only on requests from this address. Use `*` to trust any address, but only when nothing but the proxy can reach the port. With a proxy on the same machine reaching `127.0.0.1`, connections arrive from the Docker network's gateway, not from `127.0.0.1`, and that address can change when the network is made again. Since only programs on the machine can reach a port published on `127.0.0.1`, `*` is the simpler choice there when no one else runs programs on it. The log shows the address the server sees (see above). | none |
| `RRTN_PORT` | The port the server listens on inside the container, and the port `compose.yaml` publishes on `127.0.0.1`. | `8080` |
| `RRTN_UID`, `RRTN_GID` | The user and group the container runs as. The Instance folder must belong to them. | `1000`, `1000` |
| `RRTN_HOST_DIR` | The Instance folder on the host: the database (`rrtn.db`) and `backups/`. | `./instance` |
| `RRTN_DIR` | The Instance folder inside the container. Leave it unset with `compose.yaml`, which mounts the folder there. | `/var/lib/rrtn` |

The server stops at start with a one-line message if `RRTN_ORIGIN` or `RRTN_TRUSTED_PROXY` is missing, if `RRTN_ORIGIN` isn't a scheme and host, if `RRTN_PORT` isn't a port number, or if it can't write to the Instance folder.
