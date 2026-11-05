"""Built-in documentation shown in the Help window (F1).

Each section is a dict: {"id", "title", "level" (1 or 2), "html"}.
Sections are built by a function so the colors follow the current theme.
Pictures live in securewrity/data/help/ and are made by tools/help_screenshots.py.

To add docs: append to the list in sections(), or from a plugin call
api.add_help_section(title, html).
"""
from __future__ import annotations

from html import escape

from .ui import theme


def kbd(*keys: str) -> str:
    """Draw keys like  [Ctrl] + [B]."""
    bg, fg = theme.t("hover"), theme.t("text")
    parts = [f"<span style='background-color:{bg}; color:{fg}; font-family:monospace;'>&nbsp;{escape(k)}&nbsp;</span>"
             for k in keys]
    return " + ".join(parts)


def img(name: str, caption: str = "", width: int = 0) -> str:
    w = f" width='{width}'" if width else ""
    cap = f"<br><span style='color:{theme.t('muted')}; font-size:12px;'>{escape(caption)}</span>" if caption else ""
    return f"<p align='center'><img src='{name}'{w}>{cap}</p>"


def steps(*items: str) -> str:
    return "<ol>" + "".join(f"<li style='margin-bottom:4px;'>{i}</li>" for i in items) + "</ol>"


def tip(text: str) -> str:
    return (f"<table width='100%' cellpadding='8' style='background-color:{theme.t('hover')};'>"
            f"<tr><td>💡 {text}</td></tr></table>")


def table(rows, head=None) -> str:
    border = theme.t("border")
    out = [f"<table cellpadding='5' cellspacing='0' style='border-color:{border};' border='1' width='100%'>"]
    if head:
        out.append("<tr>" + "".join(f"<th align='left'>{h}</th>" for h in head) + "</tr>")
    for r in rows:
        out.append("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>")
    out.append("</table>")
    return "".join(out)


def _swatch_table() -> str:
    """Regular colors on the left, pastels on the right: each as text, and as a background."""
    def cells(n):
        ink = theme.readable_text(None, n)
        return [f"<span style='color:{theme.text_color(n)}; font-weight:600;'>{escape(theme.color_label(n))}</span>",
                f"<span style='color:{ink};'>&nbsp;highlighted&nbsp;</span>"]
    rows = []
    for reg, pas in zip(theme.REGULAR_COLORS, theme.PASTEL_COLORS):
        rows.append(cells(reg) + cells(pas))
    border = theme.t("border")
    out = [f"<table cellpadding='5' cellspacing='0' border='1' style='border-color:{border};' width='100%'>",
           "<tr><th align='left'>Regular</th><th align='left'>as background</th>"
           "<th align='left'>Pastel</th><th align='left'>as background</th></tr>"]
    for (reg, pas), r in zip(zip(theme.REGULAR_COLORS, theme.PASTEL_COLORS), rows):
        out.append(f"<tr><td>{r[0]}</td><td style='background-color:{theme.bg_color(reg)};'>{r[1]}</td>"
                   f"<td>{r[2]}</td><td style='background-color:{theme.bg_color(pas)};'>{r[3]}</td></tr>")
    out.append("</table>")
    return "".join(out)


def sections() -> list[dict]:
    S = []

    def sec(id_, title, html, level=1):
        S.append({"id": id_, "title": title, "level": level, "html": html})

    # ---------------------------------------------------------------- start
    sec("start", "Getting started", f"""
<p>Securewrity is a private notebook. Pages hold <b>blocks</b>: a line of text, a heading, a toggle,
a to-do, a divider and so on. Pages can hold other pages, and everything is listed in the sidebar on the left.</p>
{tip(f"Press {kbd('F1')} any time to open this help. Type in the search box at the top left to find a topic.")}
""")
    sec("accounts", "Accounts and the Guest user", f"""
<p>When Securewrity starts it shows the list of accounts.</p>
<ul>
<li><b>Guest</b> opens straight away. No password, no encryption. Good for trying things out.</li>
<li><b>Create account</b> makes a named account. You choose how it is protected: nothing, a password,
a passphrase or a seed phrase. See <a href='#protect'>Protecting an account</a>.</li>
</ul>
<p>Each account has its own pages, settings and theme. To switch accounts, lock with {kbd('Ctrl', 'L')}.</p>
""", 2)
    sec("first-page", "Your first page", f"""
{steps(f"Click <b>+ New page</b> in the sidebar, or press {kbd('Ctrl', 'N')}.",
       "Type a title and press Enter. The cursor moves into the page.",
       "Just start typing. Every Enter makes a new block.",
       f"Type {kbd('/')} on an empty line to pick what kind of block it is.")}
<p>Changes save by themselves about half a second after you stop typing. {kbd('Ctrl', 'S')} saves right away.</p>
""", 2)

    # ---------------------------------------------------------------- writing
    sec("writing", "Writing", f"""
<p>A page is a list of blocks. Press Enter for a new block, {kbd('/')} to choose its type, and
{kbd('Tab')} to tuck a block inside the one above it.</p>
""")
    sec("slash", "The / menu: adding blocks", f"""
<p>Type {kbd('/')} anywhere in a text block. A menu of everything you can add appears under the cursor.</p>
{img("slash.png", "Typing / opens the block menu")}
{steps(f"Keep typing to filter. For example <code>/tog</code> shows only the toggles, <code>/div</code> finds the divider.",
       f"Use {kbd('↑')} and {kbd('↓')} to choose, then {kbd('Enter')}. Or click an item.",
       f"{kbd('Esc')} closes the menu and leaves the / as text.")}
<p>What you can add:</p>
{table([
    ["Text", "A plain paragraph"],
    ["Toggle", "Regular-size text with an arrow. Everything indented under it folds away."],
    ["Heading 1 – 4", "Big to smallest section headings"],
    ["Toggle heading 1 – 4", "A heading that folds away everything under it"],
    ["Bulleted / Numbered list", "Lists. Press Tab to nest an item."],
    ["To-do list", "A checkbox item"],
    ["Quote, Callout", "Highlighted text. A callout has an emoji you can click to change."],
    ["Code", "Monospace text, no formatting"],
    ["Divider", "A horizontal line"],
    ["Page", "A new page inside this one"],
    ["Link to page", "A link to a page that already exists"],
], ["Block", "What it is"])}
{tip("Colors are in the / menu too: type <code>/red</code>, <code>/pastel</code> or <code>/mint background</code>.")}
""", 2)
    sec("toggles", "Toggles and toggle headings", f"""
<p>A toggle hides and shows the blocks inside it. Click the arrow ▶ / ▼ to open or close it.</p>
{img("toggles.png", "Toggle headings and a regular toggle. The closed one hides its contents.")}
<p><b>Make one:</b></p>
{steps("Type <code>/toggle</code> and pick <b>Toggle</b> (regular text size) or <b>Toggle heading 1–4</b>.",
       f"Or type a shortcut at the start of an empty line and then a space: "
       f"<code>&gt;</code> for a toggle, <code>#&gt;</code> <code>##&gt;</code> <code>###&gt;</code> <code>####&gt;</code> for toggle headings 1 to 4.",
       "Press Enter on an open toggle and the new line goes inside it.")}
<p><b>Put things inside:</b> press {kbd('Tab')} on the line under a toggle to move it in, {kbd('Shift', 'Tab')} to move it back out.</p>
<p><b>Open or close from the keyboard:</b> {kbd('Ctrl', 'Enter')}.</p>
{tip("An empty open toggle shows a grey 'Empty toggle' hint. Click it to start typing inside.")}
""", 2)
    sec("markdown", "Typing shortcuts", f"""
<p>Type one of these at the start of a line, then press {kbd('Space')}. The line turns into that block.</p>
{table([
    ["<code>#</code> <code>##</code> <code>###</code> <code>####</code>", "Heading 1, 2, 3, 4"],
    ["<code>#&gt;</code> <code>##&gt;</code> <code>###&gt;</code> <code>####&gt;</code>", "Toggle heading 1, 2, 3, 4"],
    ["<code>&gt;</code>", "Toggle"],
    ["<code>-</code> or <code>*</code>", "Bulleted list"],
    ["<code>1.</code>", "Numbered list"],
    ["<code>[]</code>", "To-do"],
    ["<code>\"</code>", "Quote"],
    ["<code>```</code>", "Code block (no space needed)"],
    ["<code>---</code>", "Divider (no space needed)"],
], ["Type", "You get"])}
""", 2)
    sec("paste", "Pasting from AI, Notion or the web", f"""
<p>Paste with {kbd('Ctrl', 'V')} and Markdown turns into real blocks: headings, toggles, lists, to-dos,
code, dividers, callouts, colors, <b>bold</b>, <i>italic</i> and links. Indented lines go inside the line above them.</p>
<p><b>Asking an AI for a page:</b> ask for "Markdown" or "Notion format". These are understood:</p>
{table([
    ["<code># Title</code> … <code>#### Title</code>", "Headings 1–4"],
    ["<code>## ▶ Title</code>, <code>▶ ## Title</code>, <code>##&gt; Title</code>, <code>## Title {{toggle=\"true\"}}</code>",
     "Toggle heading. The lines under it, up to the next heading or toggle, go inside."],
    ["<code>▶ Text</code> or <code>&lt;details&gt;&lt;summary&gt;Text&lt;/summary&gt;…&lt;/details&gt;</code>", "Toggle"],
    ["<code>- item</code>, <code>1. item</code>, <code>- [ ] task</code>, <code>- [x] done</code>", "Lists and to-dos"],
    ["<code>&gt; 💡 text</code>, <code>&lt;callout icon=\"💡\"&gt;text&lt;/callout&gt;</code>, <code>&gt; [!NOTE]</code>", "Callout"],
    ["<code>&gt; text</code>", "Quote"],
    ["<code>&lt;span color=\"red\"&gt;text&lt;/span&gt;</code>, <code>color=\"mint background\"</code>",
     "Colored words (any of the 20 color names, add <i>background</i> for a highlight)"],
    ["<code>## Heading {{color=\"blue\"}}</code>", "Color a whole block"],
    ["<code>```</code> fences, <code>---</code>, <code>| tables |</code>", "Code, divider. Tables become a lined-up code block."],
], ["Write", "You get"])}
{tip("A prompt that works well: <i>Write this as Markdown for Notion. Write toggle headings as "
     "<code>## ▶ Title</code> (one # per heading level), plain toggles as <code>▶ Text</code>, to-dos as "
     "<code>- [ ]</code>, and colors as &lt;span color=\"red\"&gt;…&lt;/span&gt;. Give it to me in a code block.</i> "
     "Then use the code block's Copy button.")}
<p>A line starting with ▶ but no # becomes a regular-size toggle. The lines under it go inside, up to the next ▶ line
or heading.</p>
<p><b>Copying from a web page or a chat window</b> (selecting the text rather than using a Copy button) works too: the
headings, lists, bold and links come across.</p>
<p><b>Plain text:</b> {kbd('Ctrl', 'Shift', 'V')} pastes exactly what you copied, with no conversion.</p>
<p><b>Whole files, folders and Notion exports:</b> click <b>📥 Import</b> at the bottom of the sidebar.</p>
<ul>
<li><b>Markdown files or Notion .zip…</b> picks one or more <code>.md</code> files, or the <code>.zip</code>
Notion gives you from <i>Settings → Export → Markdown &amp; CSV</i> (no need to unzip it).</li>
<li><b>A folder of pages…</b> picks a folder; every <code>.md</code> file inside becomes a page.</li>
</ul>
<p>Sub-pages come across as sub-pages: a folder named like a file (<code>Trip.md</code> and <code>Trip/</code>)
holds that page's sub-pages, and other folders become pages of their own. Links between the files turn into
links to the new pages. To put the import inside an existing page, right-click it in the sidebar →
<b>Import Markdown here…</b>.</p>
<p>Not supported yet: images (they become links), real tables, columns and databases.</p>
""", 2)
    sec("lists", "Lists and to-dos", f"""
<p>Press Enter at the end of a list item to start the next one. Press Enter on an empty item to stop the list.</p>
<p>{kbd('Tab')} nests an item under the one above, {kbd('Shift', 'Tab')} moves it back out.</p>
<p>Tick a to-do by clicking its box, or with {kbd('Ctrl', 'Enter')}.</p>
""", 2)
    sec("text-format", "Bold, italic and other formatting", f"""
<p>Select some words. A small toolbar appears above them.</p>
{img("toolbar.png", "The toolbar that appears when you select text")}
{table([
    [kbd('Ctrl', 'B'), "Bold"], [kbd('Ctrl', 'I'), "Italic"], [kbd('Ctrl', 'U'), "Underline"],
    [kbd('Ctrl', 'Shift', 'S'), "Strikethrough"], [kbd('Ctrl', 'E'), "Inline code"],
    [kbd('Ctrl', 'K'), "Link the selected words to a page or a web address"],
    [kbd('Shift', 'Enter'), "Line break inside the same block"],
], ["Keys", "Does"])}
""", 2)

    # ---------------------------------------------------------------- colors
    sec("colors", "Colors", f"""
<p>There are 20 colors: 10 regular and 10 pastel. Each one can color the <b>text</b> or the <b>background</b>.</p>
{_swatch_table()}
""")
    sec("color-words", "Coloring selected words", f"""
{steps("Select the words with the mouse, or with Shift and the arrow keys.",
       "In the toolbar that appears, click <b>🎨 Color ▾</b>.",
       "Click a swatch. The top grid sets the text color, the bottom grid sets the background (highlight).")}
{img("palette.png", "The color picker: text colors on top, backgrounds below, regular and pastel rows")}
<p>To remove a color, pick the first swatch, <b>Default</b>.</p>
""", 2)
    sec("color-block", "Coloring a whole block", f"""
<p>Two ways:</p>
<ul>
<li>Type {kbd('/')} and the color name, for example <code>/blue</code>, <code>/pastel rose</code> or
<code>/yellow background</code>, then Enter.</li>
<li>Hover over the block, click the ⋮⋮ handle on its left, then <b>Color</b>.</li>
</ul>
{img("blockmenu.png", "The ⋮⋮ block menu")}
""", 2)

    # ---------------------------------------------------------------- pages
    sec("pages", "Pages inside pages", f"""
<p>Any page can hold other pages, as deep as you like. They show as a tree in the sidebar.</p>
{img("sidebar.png", "The sidebar: favorites, the page tree, trash, settings and help")}
<ul>
<li><b>New sub-page:</b> hover over a page in the sidebar and click its <b>+</b>, or press {kbd('Ctrl', 'Shift', 'N')}
to add one inside the open page, or type <code>/page</code> inside a page.</li>
<li><b>Move a page:</b> drag it in the sidebar onto another page, or use ⋯ → <b>Move to…</b> at the top right of the page.</li>
<li><b>Go up a level:</b> click the path at the top of the page, or press {kbd('Alt', '←')}.</li>
<li><b>Favorite:</b> click ☆ at the top right. Favorites are listed at the top of the sidebar.</li>
</ul>
""")
    sec("links", "Linking pages", f"""
{steps(f"Type {kbd('[')}{kbd('[')} or press {kbd('Ctrl', 'K')} (with or without words selected).",
       "Start typing a page name and press Enter. You can also paste a web address.",
       "Click the link to open it.")}
{img("link.png", "Picking a page to link to")}
<p>To add a whole block that links to a page, type <code>/link</code> and pick <b>Link to page</b>.</p>
<p>At the bottom of every page, <b>Linked from</b> lists the pages that link to it.</p>
""", 2)
    sec("search", "Finding a page", f"""
<p>Press {kbd('Ctrl', 'P')} or click <b>Search</b> in the sidebar. Type part of a title or of the text on a page.</p>
""", 2)
    sec("trash", "Deleting and the Trash", f"""
<p>Deleted pages go to the <b>Trash</b> (bottom of the sidebar). From there you can restore them or delete them for good.
Sub-pages go with their parent.</p>
""", 2)

    # ---------------------------------------------------------------- blocks
    sec("blocks", "Moving and changing blocks", f"""
<p>Hover over a block and a ⋮⋮ handle appears on its left. Click it for: <b>Turn into</b> another type, <b>Color</b>,
Duplicate, Move up / down, Indent / Outdent and Delete. Right-clicking text shows the same options.</p>
{table([
    [kbd('Ctrl', 'Shift', '↑') + " / " + kbd('↓'), "Move the block up / down"],
    [kbd('Tab') + " / " + kbd('Shift', 'Tab'), "Indent / outdent"],
    [kbd('Ctrl', 'D'), "Duplicate"],
    [kbd('Backspace') + " at the start", "Join with the block above"],
    [kbd('Ctrl', 'Z'), "Undo typing inside a block"],
], ["Keys", "Does"])}
""")

    # ---------------------------------------------------------------- security
    sec("security", "Security and encryption", f"""
<p>Named accounts can be encrypted. When they are, your pages are stored scrambled (AES-256-GCM) and can only be
read with your password, passphrase or seed phrase. While the account is open, the readable copy exists only in memory.</p>
{tip("There is no 'forgot password'. Nobody, including the program, can open an encrypted account without one of its "
     "credentials. Turn on the recovery seed phrase and keep it written down somewhere safe.")}
""")
    sec("protect", "Protecting an account", f"""
<p>When you create an account, or later from the account menu → <b>Security &amp; encryption</b>, choose one:</p>
{img("protect.png", "Choosing how to protect an account")}
{table([
    ["None", "No password. Anyone using this computer can open it. You can add protection later."],
    ["Password", "At least 8 characters."],
    ["Passphrase", "Several words. Securewrity can make one up for you."],
    ["Seed phrase", "Securewrity makes 12 or 24 words. Those words <i>are</i> the key. "
                    "You must type 3 of them back to show you saved it."],
], ["Option", "Notes"])}
<p>With a password or passphrase you can also tick <b>Also create a recovery seed phrase</b>. Either one will unlock the account.</p>
""", 2)
    sec("encrypt-later", "Encrypting later, changing or removing", f"""
<p>Open the account menu (your name, top left) → <b>Security &amp; encryption</b>. From there you can:</p>
<ul>
<li><b>Encrypt now</b> an account that has no protection. The unprotected file is overwritten and deleted.</li>
<li><b>Change</b> a password or passphrase, <b>add</b> a recovery seed phrase, or <b>remove</b> one way of unlocking.</li>
<li><b>Remove encryption</b> to go back to an unprotected account.</li>
</ul>
<p>The Guest account can't be encrypted. Create a named account instead.</p>
""", 2)
    sec("autolock", "Locking", f"""
<p>{kbd('Ctrl', 'L')} locks right away and goes back to the account list. Encrypted accounts also lock by themselves
after 15 minutes without use. Change that time in <b>Settings</b>.</p>
""", 2)

    # ---------------------------------------------------------------- other
    sec("settings", "Settings and themes", f"""
<p><b>Settings</b> (bottom of the sidebar) has the theme (dark or light), text size, auto-lock time and whether to
reopen the last page. {kbd('Ctrl', 'Shift', 'L')} flips between dark and light.</p>
""")
    sec("shortcuts", "Keyboard shortcuts", table([
        [kbd('F1'), "Help"],
        [kbd('Ctrl', 'P'), "Find a page"],
        [kbd('Ctrl', 'N'), "New page"],
        [kbd('Ctrl', 'Shift', 'N'), "New page inside this one"],
        [kbd('Ctrl', 'Shift', 'P'), "Command palette (every command by name)"],
        [kbd('Ctrl', '\\'), "Show / hide the sidebar"],
        [kbd('Ctrl', 'Shift', 'L'), "Dark / light theme"],
        [kbd('Ctrl', 'L'), "Lock / switch user"],
        [kbd('Ctrl', 'S'), "Save now"],
        [kbd('Alt', '←'), "Go to the parent page"],
        [kbd('Ctrl', 'Shift', 'J'), "Today's journal page (Daily journal plugin)"],
        [kbd('/'), "Block menu"],
        [kbd('[') + kbd('[') + " or " + kbd('Ctrl', 'K'), "Link"],
        [kbd('Ctrl', 'Enter'), "Open / close a toggle, tick a to-do"],
        [kbd('Ctrl', 'Q'), "Quit"],
    ], ["Keys", "Does"]))
    sec("plugins", "Plugins", f"""
<p>Plugins add features. Turn the included ones on or off from the account menu → <b>Plugins</b>:
Markdown export, Daily journal and Word count.</p>
<p>To write your own, put a <code>.py</code> file in <code>~/.local/share/securewrity/plugins/</code>. The README in the
project folder shows an example. Plugins can add commands, shortcuts, block types and sections to this help.</p>
""")
    sec("data", "Where your notes are stored", f"""
<p>Everything is in <code>~/.local/share/securewrity/users/&lt;name&gt;/</code>. Encrypted accounts are one file,
<code>data.securewrity</code>, plus a <code>.bak</code> copy of the previous save. Unprotected accounts use <code>data.db</code>.</p>
<p>To back up, copy that folder. An encrypted backup still needs your password to open.</p>
""")
    return S
