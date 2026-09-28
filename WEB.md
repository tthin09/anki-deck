# Run the local web converter

Docker Desktop must be running. This release binds to **localhost only**; do not expose it to the internet as-is.

1. Create `data/accounts.json` (a persistent host folder outside the container) and `.env` in the repository root. Set `GEMINI_API_KEY=...` in `.env`. Do not commit either file.
2. Generate a hash for each account. With Python and the dependencies in `src/requirements.txt` plus `fastapi` installed, run `python src/web_app.py --hash-password`. Enter the password at the prompt. Alternatively, once the image is built, run `docker compose run --rm --no-deps -it web python src/web_app.py --hash-password`.
3. Put the generated hashes in `data/accounts.json`, for example:

   ```json
   {"alice": "<salt:hash from step 2>", "bob": "<another salt:hash>"}
   ```

4. Run `docker compose up --build -d` and open http://127.0.0.1:8000. Stop with `docker compose down`. Never use `down -v` for persistent data. Back up `data/` regularly.

The container stores `data/accounts.json`, `data/conversions.csv`, and `data/archive/*.apkg` on the host. Each completed conversion automatically downloads a copy to the user's browser. There is no package history UI; the server archive is for the operator. Uploads are read in the browser and are not kept separately. Change an account password by replacing its hash in `accounts.json`, then log out and in again; existing sessions expire after eight hours or on container restart.

For local development: install Python dependencies with `pip install -r src/requirements.txt fastapi uvicorn httpx` and JS dependencies with `npm --prefix web ci`. Start `uvicorn web_app:app --app-dir src --reload --port 8000` after building the UI with `npm --prefix web run build`. Run tests with `python -m unittest discover -s test -p test_web.py`.

Before any public deployment, add TLS, a trusted reverse proxy, secure cookies, request rate limits, backup/retention procedures, and multi-instance-safe storage. This local single-process version intentionally omits those controls.
