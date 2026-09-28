# Vocabulary Deck Web App

The hosted web app turns submitted vocabulary into downloadable Anki `.apkg` packages. The FastAPI backend serves the built frontend, authenticates users from `data/accounts.json`, and saves completed packages and `conversions.csv` under `data/history/`.

See [`../WEB.md`](../WEB.md) for deployment and development instructions. The generator logic in `anki_deck.py` is shared with the web backend; it is not a standalone customer executable.
