# sms-semantic-filter

Remove messages about a chosen topic from an **SMS Backup & Restore** XML file by *meaning*, not keywords. Everything runs locally, so no message leaves your machine. The output is a clean XML file that restores to the phone.

## Why not a keyword filter?

In a real conversation, most messages about a topic never name it:

> **Them:** Did you call the guy about the Civic?
> **Me:** Yeah, he says 4k firm
> **Them:** Ask if he'll do 3.5 if you pay today
> **Them:** Sure. Bring cash just in case, he won't take Venmo
> **Me:** He texted back. 3.8 and he'll throw in the winter tires

Only the first message says what is being bought. The tool judges every message **together with its neighbours**, so replies like "Take it" or "Got it. I'll hit the ATM Friday" are understood in context.

## How it works

1. **Read the backup without touching it.** The file is scanned as text. Each `<sms>` / `<mms>` entry is located (quote-aware, so `>` inside a message is safe) and parsed on its own to read its fields.
2. **Stage 1: local embeddings.** [sentence-transformers](https://www.sbert.net/) embeds each message with its context and compares it to your topic description and examples. Look-alike examples ("my mom's car is in the shop") pull scores down. This shortlists candidates in seconds.
3. **Stage 2: local LLM.** A model served by [Ollama](https://ollama.com) (default `llama3.1:8b`) reads each shortlisted message in context. It answers in JSON with `remove`, `confidence` and `reason`. Clear non-matches never reach this stage, so even 17,000 messages finish on a laptop.
4. **You review before anything is deleted.** `scan` writes `report.csv` with the date, text, scores and the model's reason. Change `remove` to yes or no as you like.
5. **Surgical removal.** `apply` cuts only the flagged entries out of the original text, updates the root `count` attribute, and writes a new file. The original is never modified.
6. **Verification.** The output is re-read and checked:
   - it is well-formed XML
   - the `count` attribute matches the number of messages
   - every kept message is byte-for-byte identical to the original

### XML details this handles

- SMS Backup & Restore stores emoji as **UTF-16 surrogate-pair references** (`&#55357;&#56832;`). Strict XML parsers reject or rewrite these. This tool never re-serialises the document, so they stay exactly as the app wrote them.
- MMS text lives in `<part ct="text/plain" text="...">` and is read from there.
- The XML declaration, the comment and stylesheet lines, attribute order, `readable_date`, `contact_name`, read and status flags, and line endings are all preserved.

## Quick start

```bash
pip install -r requirements.txt
# optional stage 2:  install Ollama, then
ollama pull llama3.1:8b

python examples/make_sample.py examples/sample-backup.xml      # synthetic test data

python -m sms_filter scan  examples/sample-backup.xml --topic examples/topic.json --report report.csv
#   ...review / edit report.csv...
python -m sms_filter apply examples/sample-backup.xml --report report.csv --out cleaned.xml
python -m sms_filter verify examples/sample-backup.xml cleaned.xml --report report.csv
```

Use `--no-llm` to run embeddings only (faster, less precise). Other settings:
- `--window`: how many neighbouring messages count as context
- `--threshold`: the stage-1 similarity cut-off
- `--min-confidence`: the LLM confidence needed to flag a message

### Describing the topic

`topic.json`:

```json
{
  "description": "Anything about buying the used car from the private seller: price talks, viewing it, paying for it, picking it up ...",
  "positive_examples": ["he says 4k firm", "Bring cash just in case"],
  "negative_examples": ["My mom's car is in the shop again"]
}
```

A short description plus a handful of real examples from your own thread gives the best results. Negative examples stop look-alikes from being removed.

## Example run (embeddings only)

```
Read 26 messages from examples/sample-backup.xml
Stage 1 (embeddings): 5 candidates above 0.35
5 messages flagged for removal. Review report.csv ... Nothing has been deleted yet.
Removed 5 of 26 messages -> cleaned.xml
Verified: valid XML, count attribute correct, every kept message byte-identical to the original.
```

Embeddings alone catch the messages that are close in wording. Stage 2 (the local LLM reading context) is what catches the indirect replies, such as "Take it. Tires alone are worth a few hundred".

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests check:
- SMS, MMS, emoji (surrogate pairs) and `>` inside message bodies are all read correctly
- removing nothing gives a byte-identical file
- removal keeps every other entry identical and fixes `count`
- verification catches any change to a kept message

## Privacy

- No network calls except to your own local Ollama server.
- The sample data is synthetic.
- Keep your real backup out of the repository (`*.local.xml` is git-ignored).

## License

MIT
