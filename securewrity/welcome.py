"""First-run content that doubles as a feature tour."""


def P(text="", **props):
    return {"type": "paragraph", "content": [{"t": text}] if text else [], "props": props}


def R(*runs, type="paragraph", children=None, **props):
    return {"type": type, "content": list(runs), "props": props, "children": children or []}


def B(type, text, children=None, **props):
    return {"type": type, "content": [{"t": text}] if text else [], "props": props, "children": children or []}


def create_welcome_pages(repo, account):
    home = repo.create_page(title="Getting started", icon="👋")
    sub = repo.create_page(parent_id=home, title="A page inside a page", icon="📂")
    deeper = repo.create_page(parent_id=sub, title="Pages all the way down", icon="🪆")
    shortcuts = repo.create_page(title="Keyboard shortcuts", icon="⌨️")

    repo.save_blocks(deeper, [P("Nest pages as deep as you like. Drag them around in the sidebar to reorganise.")])
    repo.save_blocks(sub, [
        P("This is a sub-page. The breadcrumbs at the top show where you are."),
        B("page", "", page_id=deeper),
    ])
    repo.save_blocks(home, [
        R({"t": f"Welcome, {account.username}! ", "b": 1}, {"t": "This page shows what Securewrity can do. Edit or delete anything."}),
        B("callout", "Type '/' on an empty line for the block menu. Hover a block and click ⋮⋮ for more options.",
          emoji="💡", bg="blue"),
        B("toggle_h1", "Toggle headings", collapsed=False, children=[
            P("Click the ▼ arrow to fold everything under a heading. Use /toggle heading or type “#> ” then space."),
            B("toggle_h2", "A nested toggle heading", collapsed=True, children=[
                P("Hidden until you open it. Ctrl+Enter toggles the one you're typing in."),
            ]),
            B("toggle", "A regular-size toggle", collapsed=True, children=[P("Toggles can hold any blocks.")]),
        ]),
        B("toggle_h1", "Colors", collapsed=True, children=[
            B("paragraph", "Whole blocks can have a text color…", color="red"),
            B("paragraph", "…or a background color.", bg="yellow"),
            R({"t": "Select text to color "}, {"t": "just a few", "c": "purple", "b": 1},
              {"t": " words, or "}, {"t": "highlight them", "bg": "green"}, {"t": "."}),
            B("paragraph", "There are pastels too: 20 colors in all.", bg="lavender"),
            P("Type /red, /pastel mint, /blue background, etc. — or use the block ⋮⋮ menu → Color. "
              "Press F1 for help with pictures."),
        ]),
        B("toggle_h1", "Pages within pages & links", collapsed=True, children=[
            B("page", "", page_id=sub),
            R({"t": "Inline links: type [[ or press Ctrl+K. Example: "},
              {"t": "Keyboard shortcuts", "link": f"page:{shortcuts}"}, {"t": "."}),
            P("Pages that link here are listed at the bottom under “Linked from”."),
        ]),
        B("toggle_h1", "Other blocks", collapsed=True, children=[
            B("todo", "A to-do item", checked=True),
            B("todo", "Another one"),
            B("bullet", "Bulleted list", children=[B("bullet", "Tab to indent, Shift+Tab to outdent")]),
            B("numbered", "Numbered list"),
            B("numbered", "Second item"),
            B("quote", "A quote block."),
            B("divider", ""),
            B("code", "def hello():\n    print('hi from a code block')"),
        ]),
        B("toggle_h1", "Security", collapsed=True, children=[
            P("Account menu (top-left) → Security & encryption. Encrypt at any time with a password, "
              "passphrase or seed phrase, add a recovery phrase, or change your password."),
        ]),
    ])
    rows = [
        ("F1", "Help (searchable)"), ("Ctrl+P", "Search / jump to page"), ("Ctrl+N", "New page"), ("Ctrl+Shift+N", "New sub-page"),
        ("Ctrl+L", "Lock / switch user"), ("Ctrl+Shift+L", "Dark / light theme"),
        ("Ctrl+Shift+P", "Command palette"), ("Ctrl+\\", "Toggle sidebar"), ("Alt+←", "Go to parent page"),
        ("/", "Block menu"), ("[[  or  Ctrl+K", "Link to a page"),
        ("Ctrl+B / I / U / E", "Bold, italic, underline, inline code"), ("Ctrl+Shift+S", "Strikethrough"),
        ("Tab / Shift+Tab", "Indent / outdent block"), ("Ctrl+Shift+↑ / ↓", "Move block"),
        ("Ctrl+D", "Duplicate block"), ("Ctrl+Enter", "Toggle open/closed, check a to-do"),
        ("Shift+Enter", "Line break inside a block"),
        ("#  ##  ###  ####", "Headings 1–4 (type then space)"), ("#>  ##>  ###>  ####>", "Toggle headings 1–4"),
        (">", "Toggle"), ("-  or  *", "Bullet list"), ("1.", "Numbered list"), ("[]", "To-do"),
        ('"', "Quote"), ("```", "Code block"), ("---", "Divider"),
    ]
    repo.save_blocks(shortcuts, [B("bullet", "", children=[]) | {"content": [{"t": k, "code": 1}, {"t": "   " + v}]}
                                 for k, v in rows])
