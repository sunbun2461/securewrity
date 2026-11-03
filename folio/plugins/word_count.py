"""Example plugin: live word count in the editor's top bar."""

PLUGIN = {"name": "Word count", "version": "1.0", "description": "Shows the word count of the open page."}


def _words(blocks):
    n = 0
    for b in blocks:
        n += len("".join(r.get("t", "") for r in b.get("content", [])).split())
        n += _words(b.get("children", []))
    return n


def register(api):
    def update(page_id=None):
        api.set_status("words", f"{_words(api.current_page_blocks())} words")

    api.events.on("page_opened", update)
    api.events.on("page_saved", update)
