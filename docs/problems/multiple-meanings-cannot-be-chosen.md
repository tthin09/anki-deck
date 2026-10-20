# Words with several meanings: the user can't choose which one

Status: open, under discussion. No fix chosen yet.

## Symptom
Many words have more than one meaning (for example "bank": ngân hàng / bờ sông). The user can't pick which meaning they want on the card. The LLM picks one on its own, usually the first or most common meaning it thinks of, and that may not be the one the user is learning.

## How it works now
- Web input (`vocabulary` in `src/web_app.py`) takes one bare word per line, with no context or hint.
- `src/agent-prompt.md` asks for one card per word, so the model writes one example sentence and one meaning, then chooses the rest from that.
- There is no step where the user sees or confirms the meaning before the deck is built.

## Fix options
1. Let the user add a hint on the same line, for example `bank - river` or `bank: the land beside a river`, and pass it to the prompt.
2. Let the user paste the sentence they met the word in, and have the model use the meaning from that sentence.
3. Two-step flow: the LLM first lists the common meanings, the user ticks the ones they want, then cards are generated.
4. Put the main meanings on the back of one card (several Vietnamese meanings separated by `;`), so nothing is lost even if the example shows only one.

## Open questions
- Should one word with two wanted meanings become one card or two cards?
- Is a free-text hint enough, or does the user want to see and pick from a list?
