# Securewrity

A lightweight, local, Notion-style notebook for Linux (built and tested for Debian / Kali).
Native Qt desktop app: no browser, no server, no cloud.

- **Toggle headings** (H1–H4) and regular-size toggles that fold everything inside them
- **Colors**: 20 colors (10 regular, 10 pastel) for text or background, per block or for selected words
- **Pages inside pages**, any depth, with a draggable **sidebar** tree, favorites and trash
- **Drag blocks** by their ⋮⋮ handle, including into toggles; **select blocks** (Ctrl+A twice = whole page) to delete, copy or move them together; page-wide **undo / redo** (Ctrl+Z / Ctrl+Shift+Z or the arrows)
- **Links**: sub-page blocks, “link to page” blocks, inline `[[` links, and a “Linked from” backlinks list
- **@ mentions**: `@today`, `@next friday`, `@nov 12` drop in a date (click it for a calendar); `@` + a page name links that page
- Headings, bullets, numbered lists, to-dos, quotes, callouts, code, dividers
- **Paste Markdown / "Notion format"** from an AI, Notion or a web page and it becomes real blocks (toggles, colors, callouts, to-dos…); sidebar → 📥 Import brings in `.md` files, folders and Notion export `.zip`s with their sub-pages and links
- **Images**: paste a screenshot, drag picture files in, or `/image`; resize by dragging the edge. Stored inside the (encrypted) notes file
- **Tables** like Notion's: `/table`, or paste / import a Markdown table; Tab between cells, + for rows and columns, drag borders to resize
- `/` slash menu, Markdown shortcuts (`# `, `- `, `[] `, `#> ` …), find on page (Ctrl+F), search all notes from the sidebar (Ctrl+Shift+F), jump to a page (Ctrl+P), dark and light themes
- **Accounts**: a Guest account (no password) plus any number of user accounts
- **Encryption**, optional and available at any time: password, passphrase (can be generated) or a
  generated **seed phrase** (12/24-word BIP39), or a mix of them (e.g. password + recovery seed phrase)
- **Help** (F1, the ? button, or Help in the sidebar): searchable docs with screenshots and a clickable contents list; problems are logged to `~/.local/share/securewrity/securewrity.log` (no note contents)
- **Plugins**: drop a `.py` file into `~/.local/share/securewrity/plugins/`

## Install (Kali / Debian)

```bash
git clone <this repo> ~/securewrity && cd ~/securewrity
./install.sh          # apt installs python3-pyqt6, python3-cryptography, emoji font; adds menu entry
securewrity                 # or launch "Securewrity" from the app menu
```

To run it without installing: `python3 -m securewrity` from the repo folder. Needs Python 3.11+.

## Security model

| | |
|---|---|
| Cipher | AES-256-GCM (authenticated, so tampering is detected) |
| Key derivation | scrypt (N=2¹⁷, r=8, p=1, ~128 MiB) per credential |
| Key layout | A random data key encrypts the database. Each credential (password, passphrase, seed) wraps a copy of that key. Changing your password or adding a recovery phrase never re-encrypts your notes. |
| At rest | `~/.local/share/securewrity/users/<name>/data.securewrity`. While unlocked, the database exists **only in memory**. Every save writes a freshly encrypted file atomically and keeps one `.bak`. |
| Encrypt later | Converts the plain `data.db` to an encrypted file, then overwrites and deletes the plaintext (best effort: SSDs and journaling filesystems may keep old blocks, so use full-disk encryption too). |
| Auto-lock | 15 minutes idle by default for encrypted accounts (Settings). Ctrl+L locks immediately. |

There is **no password recovery** without a credential. Use the recovery seed phrase option.

What it does **not** protect against:

- A weak password. scrypt makes each guess slow, but a short or common password can still be guessed offline.
- Anyone (or any malware) using your computer while the account is unlocked.
- Swap and hibernation. While unlocked, your notes are in memory and the system may write memory to disk.
  Use encrypted swap, or full-disk encryption (the Kali installer offers "encrypted LVM").
- Leftover plaintext after "encrypt later" on SSDs and journaling filesystems (see above).
- Copies you make yourself: Markdown exports and anything copied to the clipboard.
- Metadata: account names, which protection each account uses, file sizes and save times are visible.

Saving is crash-safe: the new file is fully written before it replaces the old one, the previous
version is kept as `.bak`, and on unlock a missing or damaged file falls back to the newest intact copy.
Unprotected accounts (and Guest) are plain SQLite files, readable by anyone with access to your home directory.

## Writing a plugin

```python
# ~/.local/share/securewrity/plugins/hello.py
PLUGIN = {"name": "Hello", "version": "1.0", "description": "Example"}

def register(api):
    api.add_command("Say hello", lambda: api.notify("Hello!"), shortcut="Ctrl+Alt+H")
    api.add_page_command("Count blocks", lambda page_id: api.notify(str(len(api.repo.get_blocks(page_id)))))
    api.events.on("page_saved", lambda page_id: ...)
    api.add_help_section("Hello", "<p>Shows up in the Help window.</p>")
```

Plugins can also add whole new **block types** (they appear in the `/` menu automatically).
See `securewrity/blocks/registry.py` and `securewrity/blocks/builtin.py`. Full API: `securewrity/plugin_api.py`.
Bundled examples are in `securewrity/plugins/`: Markdown export, daily journal (Ctrl+Shift+J), word count.
Enable or disable plugins in the account menu → Plugins.

## Project layout

```
securewrity/
  core/       crypto, seed phrases, accounts, encrypted storage, data access (no GUI code)
  blocks/     block-type registry + built-in block types   ← extend here
  ui/         Qt windows: login, protection wizard, sidebar, editor, dialogs, theme
  plugins/    bundled plugins
  plugin_api.py, app.py
tests/        python3 -m unittest discover -s tests -t .
tools/        help_screenshots.py regenerates the Help pictures (securewrity/data/help/)
```

## Known limitations (v0.1)

- No selecting text across several blocks at once (each block is its own editor)
- Undo (Ctrl+Z) works inside a block, not for block-level operations like delete
- No images or attachments yet (a good first plugin or block type)
