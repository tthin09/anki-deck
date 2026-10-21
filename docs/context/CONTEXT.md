# Vocabulary Deck Generation

This context describes how a learner's vocabulary input becomes an Anki deck package.

## Language

**Vocabulary entry**:
An English word or phrase submitted for study, as the learner typed it (after any typo correction).
_Avoid_: Term, item, vocabulary word

**Phrase**:
A vocabulary entry of more than one word, such as "as well as". A phrase has no part of speech, IPA, or audio; it still gets a meaning, an example sentence, and a practice card.
_Avoid_: Expression, collocation

**Typo correction**:
Research replacing a misspelt entry with the word the AI is confident the learner meant, shown to the learner as a correction.
_Avoid_: Autocorrect, spell check

**Vocabulary list**:
The ordered set of distinct vocabulary entries submitted for one research. Entries that differ only by letter case count as the same entry.
_Avoid_: Upload, batch

**Research**:
The step between input and conversion in which the AI lists the senses of every entry in the vocabulary list for the learner to choose from.
_Avoid_: Lookup, preview

**Sense**:
One distinct meaning of a vocabulary entry found by research: the entry, its part of speech (none for a phrase), a Vietnamese meaning, and an example sentence. Meanings that are interchangeable in use are one sense. Each chosen sense becomes one vocabulary card and one practice card.
_Avoid_: Card (before conversion), meaning (the Vietnamese text inside a sense), candidate

**Conversion**:
The creation of Anki learning cards and their media from the learner's chosen senses.
_Avoid_: Importing the package into Anki as part of the app's conversion

**Deck package**:
A downloadable `.apkg` file containing the generated vocabulary cards and their media. The app creates and delivers the file; the learner may import it into Anki themselves.
_Avoid_: Anki import (as an app action)

**Vocabulary card**:
The main card for one chosen sense: the entry, its part of speech and IPA (words only), Vietnamese meaning, and an example sentence different from the sense's.
_Avoid_: Card (unqualified), forward card

**Practice card**:
A fill-in-the-blank card for one chosen sense, using a new sentence with the same meaning and part of speech as its vocabulary card.
_Avoid_: Reverse card

**Verification**:
The AI's second look at generated vocabulary and practice cards, correcting cards whose part of speech, meaning, or sentences disagree, before the deck package is built.
_Avoid_: Review (means studying in Anki), double check, proofreading

**Conversion record**:
A record of a completed conversion, identifying its deck package, uploader, creation time, and vocabulary list.
_Avoid_: User history

## Workflow invariant

The app generates and returns a downloadable deck package. It must never connect to Anki or add cards/decks directly to a user's Anki collection.
