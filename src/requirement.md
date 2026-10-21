# Vocabulary deck workflow

The web app accepts a vocabulary list, generates English–Vietnamese vocabulary and reverse-practice cards with available pronunciation audio, and returns a downloadable `.apkg` package.

The app must not connect to Anki or add cards/decks to a user's Anki collection. The learner imports the downloaded package manually if they choose.

Preserve the existing card content, package format, and non-fatal audio lookup behavior. Do not retain uploaded source files.

Each conversion saves a folder `data/output/{hhmmss-ddmmyy}/` holding the deck (`{hhmmss-ddmmyy}_deck.apkg`) and an Excel report (`{hhmmss-ddmmyy}_report.xlsx`, filled from `src/template/report-template.xlsx`). The learner downloads only the deck; the report stays on the server.
