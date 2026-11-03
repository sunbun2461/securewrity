"""Example plugin: one journal page per day, filed under a "Journal" page."""
import datetime

PLUGIN = {"name": "Daily journal", "version": "1.0",
          "description": "Ctrl+Shift+J opens today's journal page (creates it if needed)."}


def register(api):
    def today():
        repo = api.repo
        journal = next((p for p in repo.children(None) if p["title"] == "Journal"), None)
        jid = journal["id"] if journal else api.create_page("Journal", open_it=False)
        if not journal:
            repo.update_page(jid, icon="📔")
        title = datetime.date.today().strftime("%Y-%m-%d — %A")
        page = next((p for p in repo.children(jid) if p["title"] == title), None)
        if page:
            api.open_page(page["id"])
        else:
            api.create_page(title, parent_id=jid, blocks=[
                {"type": "h2", "content": [{"t": "Today"}]},
                {"type": "todo", "content": []},
                {"type": "h2", "content": [{"t": "Notes"}]},
                {"type": "paragraph", "content": []},
            ])

    api.add_command("Open today's journal", today, shortcut="Ctrl+Shift+J")
