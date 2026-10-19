# Script format for scripts with more than one voice

Give the script as plain text. **One line per beat.** Blank lines between lines are allowed but not needed.

## The rules

1. **Narrator** - a line with no name is read by the narrator.

       The ship was found adrift in 1872.

2. **A named voice** - start the line with the speaker's name in **ALL CAPS**, then a colon and a space.

       JUDGE: The court will hear the evidence.
       JOAN OF ARC: I was sent by God.

3. **Same thing, with the name in brackets** - `VOICE (Name):` also works. Use it for a person who is quoted.

       VOICE (Joan of Arc): All I said and revoked, I said for fear of the fire.

4. **A shot with no voice** - start the line with `[VISUAL 4s]` (2 to 8 seconds), then describe what is shown.

       [VISUAL 4s] The screen darkens; a candle flame shivers over an aged paper card.

5. **Same speaker, same spelling** - `JUDGE` and `JUDGE` are one voice; `JUDGE` and `THE JUDGE` are two.

## What to avoid

- **A narration line must not start with an ALL-CAPS word followed by a colon.** `NASA: the agency said...` would be read as a speaker called "Nasa". Write "NASA said..." instead.
- A colon inside a sentence is fine: `Charge: heresy. May 24th, 1431: life in prison.` is narration, because it does not start with an ALL-CAPS name.
- Do not put the visual style, notes or headings in the script. Every line is spoken or shown. Send the style brief separately.
- Keep each line to what can be said in about 8-10 seconds. Long speeches should be split into several lines.
- Do not write stage directions in brackets inside a line. Use a `[VISUAL ...]` line.
- Use at most 3 or 4 named voices; each one needs its own voice chosen in the app.

## Example

    JUDGE: The court will hear the evidence.
    Charge: heresy. May 24th, 1431: life in prison. Six days later: death.
    JUDGE: Exhibit A. The articles of accusation.
    The charges: men's dress, refusing the Church, certainty of heaven.
    [VISUAL 4s] The screen darkens; a candle flame shivers.
    Of the abjuration, she said:
    VOICE (Joan of Arc): All I said and revoked, I said for fear of the fire.
    Why she wore them again is disputed.
    JUDGE: The court asks: was justice done?

## In the app (for whoever imports the script)

1. Open the project's **Content** tab and tick **Read this script with a cast of voices** *before* importing.
2. Import the script.
3. Pick a voice for **Narrator**, **Judge** and **Joan of Arc** in the dropdowns that appear under the checkbox.
4. Run scene planning, then generate the voiceover.
