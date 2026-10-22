# PhraseForge macro reference

Macros are written `{#name args -option value}` inside phrase content and may nest:
`{#upper {#clipboard}}`.

## Syntax
- Arguments are separated by spaces; quote text with spaces: `{#input "Your name"}`.
  Inside quotes `\"` is a literal quote; macros inside quotes still run.
- `-name value` is an option. `-name` followed by another option (or nothing) is a flag (value `1`).
  Put flags after the values they don't own. A token like `-5` (digit after `-`) is a value, not an option.
- `{{` writes a literal `{`. A literal `}` inside an argument must be quoted.
- Unknown or malformed macros are left in the text unchanged.
- A command that fails writes `[name: error]` into the output.
- Macro names are case-insensitive.
- Blocks: `{#if}…{#elseif}…{#else}…{#endif}`, `{#loop N}…{#endloop}`, `{#foreach list}…{#endforeach}`,
  `{#form}…{#endform}`. An unclosed block runs to the end of the phrase; a stray closer is literal text.

## Conditions (`{#if}` / `{#elseif}`)
Operators (must be unquoted): `==` `!=` `<` `>` `<=` `>=` (numeric when both sides are numbers),
`contains` `!contains` `startswith` `endswith` (case-insensitive), `=~` `!~` (regex), `in` (comma list),
unary `empty` / `notempty`, `and` `or` `not`, and `(` `)` as separate tokens.
A single value is true unless it is empty, `0`, `false`, `no` or `off`.

## Variables
`{#set}` writes an expansion-local variable unless `-scope global` (or another scope name) is given.
`{#var name}` reads local variables first, then form/ask values, then global variables.
`{#ask*}` commands ask once per expansion and store the answer as a local variable.

## Date format tokens
`yyyy yy MMMM MMM MM M dddd ddd dd d HH H hh h mm m ss s tt DDD zzz`, `'literal text'`;
a format containing `%` is passed to strftime. `-lang en|ar|de` for month/day names.
Offsets (`-offset`): `+3d`, `-2h`, `+1m` / `+1mo` (month), `+1y`, `+2w`, `+10wd` (workdays),
`+30min` / `+30n` (minutes), `+5s`; combine with spaces: `"+1d -2h"`.
Weekend days for `wd` come from setting `date.weekend` (default `sat,sun`).

## Keys
Key names: enter tab esc backspace delete up down left right home end pageup pagedown insert space f1–f12 win;
modifiers ctrl alt shift win, joined with `+` (`ctrl+shift+left`). Aliases: bksp, del, escape, pgup, pgdn, ins, return.

## Commands


### Logic

| Command | Syntax | Description |
|---|---|---|
| `if` | `{#if cond}...{#elseif cond}...{#else}...{#endif}` | Conditional block. Operators: == != < > <= >= contains !contains startswith endswith =~ !~ in, unary empty/notempty, and/or/not, parentheses. Operators must be unquoted. |
| `loop` | `{#loop N -join sep}...{#endloop}` | Repeat the body N times. Use {#loopindex} inside. |
| `foreach` | `{#foreach "a,b,c" -sep , -join sep}...{#endforeach}` | Repeat the body for each item; {#item} is the current item. |
| `loopindex` | `{#loopindex -zero}` | Current loop iteration (1-based; -zero for 0-based). |
| `loopcount` | `{#loopcount}` | Number of iterations of the current loop. |
| `item` | `{#item}` | Current item of {#foreach}. |

### Forms

| Command | Syntax | Description |
|---|---|---|
| `form` | `{#form -title "Title"}fields...{#endform}` | Show one dialog with all field macros inside the block; read values later with {#formvalue name}. |
| `formedit` (aliases: formeditbox) | `{#formedit name -label "Label" -default x}` | Form field: single-line text. Inside {#form} it adds a field; alone it asks immediately and outputs the value. |
| `formmemo` | `{#formmemo name -label "Label" -default x}` | Form field: multi-line text. Inside {#form} it adds a field; alone it asks immediately and outputs the value. |
| `formcombo` (aliases: formcombobox) | `{#formcombo name -label "Label" -default x}` | Form field: drop-down (-options a,b). Inside {#form} it adds a field; alone it asks immediately and outputs the value. |
| `formcheckbox` | `{#formcheckbox name -label "Label" -default x}` | Form field: checkbox (-on text -off text -checked). Inside {#form} it adds a field; alone it asks immediately and outputs the value. |
| `formradio` | `{#formradio name -label "Label" -default x}` | Form field: radio group (-options a,b). Inside {#form} it adds a field; alone it asks immediately and outputs the value. |
| `formdate` | `{#formdate name -label "Label" -default x}` | Form field: date picker (-format). Inside {#form} it adds a field; alone it asks immediately and outputs the value. |
| `formnumber` | `{#formnumber name -label "Label" -default x}` | Form field: number. Inside {#form} it adds a field; alone it asks immediately and outputs the value. |
| `formlabel` | `{#formlabel name -label "Label" -default x}` | Form field: static label. Inside {#form} it adds a field; alone it asks immediately and outputs the value. |
| `formvalue` | `{#formvalue name}` | Value entered in a form field, input or choose (-name). |
| `input` | `{#input "Prompt" -default x -name var -multiline}` | Ask the user for text. |
| `inputmemo` | `{#inputmemo "Prompt" -default x -name var}` | Ask the user for multi-line text. |
| `choose` | `{#choose "Prompt" -options "a,b,c" -multi -join ", " -name var}` | Let the user pick from a list. |
| `message` (aliases: msgbox) | `{#message "Text" -title "Title"}` | Show a message box (no output). |
| `ask` | `{#ask "var" -prompt "Label" -default "x" -multiline}` | Ask once per expansion; stores the answer in a local variable and outputs it. |
| `askchoice` | `{#askchoice "var" -prompt "Label" -options "a\|b\|c"}` | Ask once for one option from a list (first option is the default); outputs it. |
| `askcheck` | `{#askcheck "var" -prompt "Label" -checked}` | Ask once with a checkbox; stores "1" or "0" and outputs nothing. Test it with {#if {#var "var"} == "1"}. |
| `askdate` | `{#askdate "var" -prompt "Label" -format "yyyy-MM-dd"}` | Ask once for a date with a calendar; outputs it. |
| `fileselect` | `{#fileselect -title "Pick a file" -ext txt -file name -dir "C:\"}` | Show a file open dialog and output the chosen path. |
| `filesave` | `{#filesave -title "Save as" -ext txt -file name -dir "C:\"}` | Show a file save dialog and output the chosen path. |
| `docgen` | `{#docgen -header "Select paragraphs" -folder "Templates/Letters" -save "C:\out.txt" -open}` | Document Generator: pick phrases of a folder (in order) and output them together; optionally save the document to a file. |
| `formseparator` | `{#formseparator}` | Form field: horizontal separator line. |
| `formslider` | `{#formslider name -label "Label" -min 0 -max 100 -default 50}` | Form field: numeric slider (shown as a number box where sliders are not supported). |
| `formphrases` | `{#formphrases name -label "Label" -folder "A/B"}` | Form field: drop-down of the phrases in a folder; outputs the chosen phrase (macros run). |
| `formenum` | `{#formenum name -label "Label" -options "a\|b\|c" -delim ", " -last " and "}` | Form field: enumeration group (checklist); outputs checked items joined with the delimiters. |

### Date & time

| Command | Syntax | Description |
|---|---|---|
| `date` | `{#date -format "yyyy-MM-dd" -offset +3d -lang en}` | Current date. Offset units: y, m/mo (month), w, d, wd (workday), h, min, s. |
| `time` | `{#time -format "HH:mm" -offset +30min}` | Current time. |
| `datetime` | `{#datetime -format "yyyy-MM-dd HH:mm"}` | Current date and time. |
| `timestamp` | `{#timestamp}` | Unix timestamp (seconds). |
| `datecalc` | `{#datecalc 2026-01-31 -offset +1m -format "dd.MM.yyyy" -diff 2026-03-01 -unit days}` | Date arithmetic on a given date (ISO, dd.MM.yyyy or 'today'). With -diff returns the difference (unit days\|weeks\|workdays). |
| `timecalc` | `{#timecalc 09:30 -offset +45min -format "HH:mm" -diff 17:00}` | Time arithmetic. With -diff returns minutes between the two times. |
| `datepick` | `{#datepick "Prompt" -format "yyyy-MM-dd" -name var}` | Ask the user for a date with a calendar. |

### Numbers

| Command | Syntax | Description |
|---|---|---|
| `calc` | `{#calc 2*(3+4) -decimals 2}` | Safe arithmetic: + - * / // % ^ ( ) and round abs min max sqrt floor ceil. |
| `random` | `{#random 1 100}` | Random integer between min and max (inclusive). |
| `randomtext` | `{#randomtext "red\|green\|blue" -sep \|}` | Random item from a list. |
| `counter` | `{#counter invoice -start 1 -step 1 -pad 4}` | Persistent counter; returns the next value each time. |
| `number` | `{#number 1234.5 -decimals 2 -thousands ","}` | Format a number. |

### Keys & cursor

| Command | Syntax | Description |
|---|---|---|
| `cursor` | `{#cursor}` | Place the caret here after expansion. |
| `key` (aliases: keys) | `{#key ctrl+shift+left -repeat 2}` | Press a key or chord. Names: enter tab esc backspace delete up down left right home end pageup pagedown insert space f1-f12 win; modifiers ctrl alt shift win. |
| `enter` | `{#enter N}` | Press enter (optionally N times). |
| `tab` | `{#tab N}` | Press tab (optionally N times). |
| `esc` | `{#esc N}` | Press esc (optionally N times). |
| `bksp` | `{#bksp N}` | Press backspace (optionally N times). |
| `del` | `{#del N}` | Press delete (optionally N times). |
| `up` | `{#up N}` | Press up (optionally N times). |
| `down` | `{#down N}` | Press down (optionally N times). |
| `left` | `{#left N}` | Press left (optionally N times). |
| `right` | `{#right N}` | Press right (optionally N times). |
| `home` | `{#home N}` | Press home (optionally N times). |
| `end` | `{#end N}` | Press end (optionally N times). |
| `pgup` | `{#pgup N}` | Press pageup (optionally N times). |
| `pgdn` | `{#pgdn N}` | Press pagedown (optionally N times). |
| `ins` | `{#ins N}` | Press insert (optionally N times). |
| `f1` | `{#f1 N}` | Press f1 (optionally N times). |
| `f2` | `{#f2 N}` | Press f2 (optionally N times). |
| `f3` | `{#f3 N}` | Press f3 (optionally N times). |
| `f4` | `{#f4 N}` | Press f4 (optionally N times). |
| `f5` | `{#f5 N}` | Press f5 (optionally N times). |
| `f6` | `{#f6 N}` | Press f6 (optionally N times). |
| `f7` | `{#f7 N}` | Press f7 (optionally N times). |
| `f8` | `{#f8 N}` | Press f8 (optionally N times). |
| `f9` | `{#f9 N}` | Press f9 (optionally N times). |
| `f10` | `{#f10 N}` | Press f10 (optionally N times). |
| `f11` | `{#f11 N}` | Press f11 (optionally N times). |
| `f12` | `{#f12 N}` | Press f12 (optionally N times). |
| `sleep` (aliases: wait) | `{#sleep 500}` | Pause output for N milliseconds. |
| `mouse` | `{#mouse click -x 100 -y 200}` | Mouse click\|rclick\|dblclick\|move at x,y. |

### Text

| Command | Syntax | Description |
|---|---|---|
| `nl` | `{#nl N}` | Insert a line break as text (N times). |
| `tabchar` | `{#tabchar}` | Insert a tab character as text. |
| `upper` | `{#upper text}` | UPPER CASE. |
| `lower` | `{#lower text}` | lower case. |
| `title` | `{#title text}` | Title Case Each Word. |
| `capitalize` | `{#capitalize text}` | Capitalize the first letter. |
| `trim` | `{#trim text}` | Remove surrounding white space. |
| `replace` | `{#replace text old new -i}` | Replace text (\n and \t allowed in old/new). |
| `regexreplace` | `{#regexreplace text pattern replacement -i}` | Regex replace (\1 groups). |
| `regexget` | `{#regexget text pattern -group 1 -all -sep ", " -i}` | Extract text matching a regex. |
| `substr` | `{#substr text start length}` | Substring; start is 1-based (negative counts from end). |
| `length` | `{#length text}` | Number of characters. |
| `padleft` | `{#padleft text width -char 0}` | Pad on the left to width. |
| `padright` | `{#padright text width -char .}` | Pad on the right to width. |
| `reverse` | `{#reverse text}` | Reverse the text. |
| `urlencode` | `{#urlencode text}` | Percent-encode for URLs. |
| `urldecode` | `{#urldecode text}` | Decode percent-encoding. |
| `htmlencode` | `{#htmlencode text}` | Escape < > & " for HTML. |
| `base64` | `{#base64 text -decode}` | Base64 encode (or -decode). |
| `strpos` | `{#strpos text sub -regex -i}` | 1-based position of the first occurrence of sub in text (0 if not found). |
| `lastpos` | `{#lastpos text sub -regex -i}` | 1-based position of the last occurrence of sub in text (0 if not found). |
| `sentence` | `{#sentence text}` | Begin sentences with uppercase. |
| `ucfirst` | `{#ucfirst text}` | UPPER CASE first character. |
| `lcfirst` | `{#lcfirst text}` | lower case first character. |
| `ucwords` | `{#ucwords text}` | UPPER CASE first char of each word. |
| `lcwords` | `{#lcwords text}` | lower case first char of each word. |
| `ltrim` | `{#ltrim text}` | Trim leading spaces. |
| `rtrim` | `{#rtrim text}` | Trim trailing spaces. |
| `ascii` | `{#ascii 65}` | Character with the given ASCII/Unicode code (decimal, or 0x hex). |

### Clipboard

| Command | Syntax | Description |
|---|---|---|
| `clipboard` (aliases: insertclipboard) | `{#clipboard}` | Current clipboard text. |
| `clipboardhistory` | `{#clipboardhistory 1}` | Clipboard history entry (0 = newest). |
| `setclipboard` | `{#setclipboard text}` | Put text on the clipboard (no output). |
| `selection` | `{#selection}` | Text that was selected when the phrase was triggered. |
| `group` | `{#group 1}` | Capture group N of the regex trigger (1 = first group). |

### System

| Command | Syntax | Description |
|---|---|---|
| `appname` | `{#appname}` | Exe name of the focused application. |
| `windowtitle` | `{#windowtitle}` | Title of the focused window. |
| `env` | `{#env USERPROFILE}` | Environment variable. |
| `username` | `{#username}` | Windows user name. |
| `computername` | `{#computername}` | Computer name. |
| `uuid` | `{#uuid}` | Random UUID. |
| `run` | `{#run "notepad.exe" -args "file.txt" -wait -dir "C:\" -exitcode}` | Start a program. -exitcode outputs its exit code (implies -wait). |
| `open` (aliases: openfolder, url) | `{#open "C:\folder or file or https://url"}` | Open a file, folder or URL. |
| `waitfor` | `{#waitfor "Window title" -timeout 10 -abort}` | Wait until a window whose title contains the text is focused. -abort cancels on timeout. |
| `focus` | `{#focus -process notepad.exe -title "Untitled" -state normal\|max\|min\|none -timeout 5}` | Bring an application window to the front. |
| `web` | `{#web "https://example.com" -browser default\|chrome\|edge\|firefox}` | Open a web page. |

### Variables

| Command | Syntax | Description |
|---|---|---|
| `set` | `{#set name value -scope local\|global}` | Set a variable (local to this expansion by default; global persists). |
| `var` (aliases: get) | `{#var name -scope global -default x}` | Read a variable. |
| `unset` | `{#unset name -scope global}` | Clear a variable. |

### Phrases

| Command | Syntax | Description |
|---|---|---|
| `insert` | `{#insert "Phrase description" -autotext abbr -folder "A/B" -pick manual\|random\|N -same}` | Insert another phrase (its macros run too): by description, by its autotext, or picked from a folder. |
| `setphrase` | `{#setphrase "Description" "content" -target "Existing phrase" -folder "A/B"}` | Create a phrase, or replace the content of -target (no output). |

### Files & data

| Command | Syntax | Description |
|---|---|---|
| `textfile` (aliases: embed, embedfile, embfile, wordfile) | `{#textfile "C:\path\file.txt" -line 3 -encoding utf-8}` | Contents of a text file (or one 1-based line). |
| `image` (aliases: imgfile) | `{#image "C:\path\picture.png"}` | Paste an image file. |
| `xls` | `{#xls "C:\data.xlsx" -sheet Sheet1 -cell B2}` | Read one Excel cell. |
| `xlsfind` | `{#xlsfind "C:\data.xlsx" "key" -sheet Sheet1 -searchcol A -returncol C}` | Find a row whose search column equals the key and return another column. |
| `xml` | `{#xml "file.xml or <xml>" -path "./item/name" -attr id -all -sep ", "}` | Extract from XML (ElementTree path syntax). |
| `sql` | `{#sql "C:\db.sqlite" "SELECT name FROM t" -sep ", " -rowsep "\n"}` | Query a SQLite database (read-only). |
| `json` | `{#json text -path "data.items[0].name"}` | Extract a value from JSON text. |
| `document` | `{#document "C:\letter.docx"}` | Insert the text of an external document (.docx, .rtf, .html, .txt, ...). |
| `csv` | `{#csv "C:\data.csv" -fromrow 1 -torow 1 -fromcol 1 -tocol 1 -colsep ", " -rowsep "\n" -delimiter ,}` | Read a range of cells from a CSV file (1-based rows/columns). |
| `xlsfindcol` | `{#xlsfindcol "C:\data.xlsx" "search text" -sheet 1 -letter}` | Number (or -letter) of the first column containing a cell equal to the search text (0 = not found). |
| `xlsfindrow` | `{#xlsfindrow "C:\data.xlsx" "search text" -sheet 1}` | Number of the first row containing a cell equal to the search text (0 = not found). |
| `dbquery` | `{#dbquery "SELECT name FROM t" -engine sqlite\|odbc -database "C:\db.sqlite" -connection "DSN=..." -sep ", " -rowsep "\n"}` | Query a database: SQLite file (read-only) or any ODBC connection string (needs pyodbc). |
| `outlook` | `{#outlook subject}` | Field of the e-mail currently open/selected in Outlook: title, firstname, lastname, senderemail, recipientemail, subject, body, gender. Outputs nothing if Outlook is not available. |
| `ad` | `{#ad email -user current}` | ActiveDirectory attribute of the current user (name, email, nickname, telephone, street, zip, city, ... or any LDAP attribute). Outputs nothing outside a domain. |

### Internet

| Command | Syntax | Description |
|---|---|---|
| `http` | `{#http "https://example.com" -method POST -body "x" -header "A: b; C: d" -timeout 30}` | HTTP request; outputs the response body. |
| `mail` | `{#mail -to a@b.com -cc c@d.com -bcc e@f.com -subject "Hi" -body "Text" -attach "C:\file.pdf" -send}` | Create an e-mail. -attach and -send use Outlook; otherwise the default mail app opens. |

### AI

| Command | Syntax | Description |
|---|---|---|
| `ai` (aliases: chatgpt, openai) | `{#ai "prompt" -provider openai\|anthropic\|ollama\|openrouter -model name -system "role"}` | Insert an AI model's answer. |
| `translate` | `{#translate text -to Arabic -from English}` | Translate text using the AI provider. |

### OCR

| Command | Syntax | Description |
|---|---|---|
| `ocr` | `{#ocr -lang Arabic -linebreaks}` | Select a screen region and insert its text (Capture2Text). Languages: Arabic, English, Russian. |
| `ocrfile` | `{#ocrfile "C:\image.png" -lang English}` | OCR an image file. |

### Output

| Command | Syntax | Description |
|---|---|---|
| `gender` | `{#gender -male "He" -female "She" -neutral "It"}` | Gender-O-Matic: outputs the male/female/neutral form. The gender comes from variable 'gender' (m/f/n) or is asked once per expansion. |
| `notify` | `{#notify "Title" "Text" -click "output when clicked"}` | Show a desktop notification (no output). |
| `outputfile` | `{#outputfile "C:\out.txt" "contents" -append -open -encoding utf-8}` | Write contents to a file (no output). -open opens it afterwards. -template copies a .dot(x) template to the target first (contents are appended as text for .txt targets only). |
| `pastefile` | `{#pastefile "C:\file.pdf"}` | Paste a file (as a file, like Explorer copy/paste) via the clipboard. |
| `pastemethod` | `{#pastemethod auto\|type\|paste -delay 0}` | Override the output method for this phrase (place at the beginning). -delay = ms between keys. |
| `setlanguage` | `{#setlanguage "ar-SA"}` | Switch the keyboard layout of the target application (language tag or name). |

Every command also accepts `-caption "Name"`: the label shown on the macro chip in the editor (set by the macro dialogs' Name field); it does not change the output.

