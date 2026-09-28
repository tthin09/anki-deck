# Vocabulary Deck Generation

This context describes how a learner's vocabulary input becomes an Anki deck package.

## Language

**Vocabulary word**:
An English word submitted for study.
_Avoid_: Term, item

**Vocabulary list**:
The ordered set of distinct vocabulary words submitted for one conversion. Words that differ only by letter case count as the same word.
_Avoid_: Upload, batch

**Conversion**:
The creation of Anki learning cards and their media from a vocabulary list.
_Avoid_: Importing the package into Anki as part of the app's conversion

**Deck package**:
A downloadable `.apkg` file containing the generated vocabulary cards and their media. The app creates and delivers the file; the learner may import it into Anki themselves.
_Avoid_: Anki import (as an app action)

**Conversion record**:
A record of a completed conversion, identifying its deck package, uploader, creation time, and vocabulary list.
_Avoid_: User history

## Workflow invariant

The app generates and returns a downloadable deck package. It must never connect to Anki or add cards/decks directly to a user's Anki collection.
