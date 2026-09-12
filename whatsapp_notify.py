#!/usr/bin/env python3
"""Post league updates to WhatsApp after NFL games go final.

Sending is opt-in. Without --send this only prints the message it would post,
so you can wire the whole pipeline up and watch it run without anything
reaching a real group chat.

One-time setup (opens a real browser window; scan the QR with your phone):

    python3 whatsapp_notify.py --login

That writes a logged-in browser profile to ~/.endzone/whatsapp-profile, after
which sends run headless against the saved session.

    python3 whatsapp_notify.py --refresh              # dry run: show the update
    python3 whatsapp_notify.py --refresh --send       # actually post it
    python3 whatsapp_notify.py --watch 300 --send     # poll every 5 minutes

Games already announced are recorded in notify_state.json, so a repeated run
stays quiet until something new goes final.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import nfl_scores
import season as season_model

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "notify_config.json"
NOTIFY_STATE_PATH = BASE_DIR / "notify_state.json"

DEFAULT_CONFIG = {
    "chat": "Endzone League",
    "board_url": "http://localhost:5173",
    "profile_dir": "~/.endzone/whatsapp-profile",
}

WHATSAPP_URL = "https://web.whatsapp.com/"


class WhatsAppError(RuntimeError):
    """The browser could not complete the send."""


# --------------------------------------------------------------------------- config/state

def load_config(path: Path = CONFIG_PATH) -> dict:
    config = dict(DEFAULT_CONFIG)
    if path.exists():
        with path.open() as f:
            config.update(json.load(f))
    return config


def load_notify_state(path: Path = NOTIFY_STATE_PATH) -> dict:
    if not path.exists():
        return {"announced": [], "last_sent_at": None}
    with path.open() as f:
        return json.load(f)


def save_notify_state(state: dict, path: Path = NOTIFY_STATE_PATH) -> None:
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w") as f:
        json.dump(state, f, indent=2)
    tmp_path.replace(path)


def new_final_games(results: dict, announced: Sequence[str]) -> List[dict]:
    seen = set(announced)
    games = [g for g in results.get("games", []) if g["completed"] and g["id"] not in seen]
    return sorted(games, key=lambda g: (g["week"], g["kickoff"] or ""))


# --------------------------------------------------------------------------- message

def compose_message(state: dict, new_games: Sequence[dict], board_url: Optional[str] = None) -> str:
    """Build the WhatsApp update: what just happened, then where everyone stands."""
    weeks = sorted({g["week"] for g in new_games})
    week_label = f"Week {weeks[0]}" if len(weeks) == 1 else f"Weeks {weeks[0]}-{weeks[-1]}"

    headline = "; ".join(nfl_scores.describe(game) for game in new_games)
    lines = [f"*Endzone · {week_label}*", "", headline, "", "*Leaderboard*"]

    # Single spaces only: WhatsApp renders in a proportional font, so padded
    # columns never line up, and a contenteditable rewrites runs of spaces into
    # non-breaking ones on the way in.
    for entry in state["leaderboard"]:
        lines.append(f"{entry['rank']}. {entry['name']} — {entry['points']:.1f} pts "
                     f"({entry['title_odds']:.0f}% title)")

    played, total = state["games_played"], state["games_total"]
    lines += ["", f"_{played} of {total} games played · title odds from "
                  f"{state['sims']:,} simulated finishes_"]
    if board_url:
        lines.append(f"Full board: {board_url}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- whatsapp

def _resolve_profile_dir(config: dict) -> Path:
    return Path(config["profile_dir"]).expanduser()


def _launch(playwright, config: dict, headless: bool):
    profile_dir = _resolve_profile_dir(config)
    profile_dir.mkdir(parents=True, exist_ok=True)
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=headless,
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )


def _import_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depends on the local env
        raise WhatsAppError(
            "Playwright is not installed. Run:\n"
            "  pip install -r requirements.txt\n"
            "  python3 -m playwright install chromium"
        ) from exc
    return sync_playwright


def login(config: dict, timeout_s: float = 180.0) -> None:
    """Open a real browser window so the QR code can be scanned once."""
    sync_playwright = _import_playwright()
    with sync_playwright() as playwright:
        context = _launch(playwright, config, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(WHATSAPP_URL, wait_until="domcontentloaded")
        print("Scan the QR code in the browser window with WhatsApp on your phone…")
        try:
            page.wait_for_selector("#side", timeout=timeout_s * 1000)
        except Exception as exc:
            raise WhatsAppError("Timed out waiting for the QR scan to complete.") from exc
        # Let WhatsApp finish writing the session to the profile before closing.
        page.wait_for_timeout(5000)
        print(f"Logged in. Session saved to {_resolve_profile_dir(config)}")
        context.close()


def _open_chat(page, chat: str) -> None:
    """Search for a chat by name and open it."""
    search = page.locator('#side div[contenteditable="true"]').first
    search.wait_for(state="visible", timeout=30000)
    search.click()
    # A stale query from a previous run would otherwise narrow the results.
    page.keyboard.press("ControlOrMeta+A")
    page.keyboard.press("Backspace")
    search.type(chat, delay=40)
    page.wait_for_timeout(1500)

    result = page.locator(f'#pane-side span[title="{chat}"]').first
    try:
        result.wait_for(state="visible", timeout=15000)
    except Exception as exc:
        raise WhatsAppError(
            f"No chat titled {chat!r} was found. The name in notify_config.json must "
            "match the chat title in WhatsApp exactly."
        ) from exc
    result.click()
    page.wait_for_selector('footer div[contenteditable="true"]', timeout=30000)


def _type_message(page, message: str, timeout_s: float = 30.0) -> None:
    """Type a multi-line message; Shift+Enter keeps it in one WhatsApp message."""
    box = page.locator('footer div[contenteditable="true"]').last
    box.click()
    for index, line in enumerate(message.split("\n")):
        if index:
            page.keyboard.press("Shift+Enter")
        if line:
            page.keyboard.type(line, delay=8)

    typed = box.inner_text().strip()
    if not typed:
        raise WhatsAppError("The message box stayed empty; WhatsApp Web may have changed layout.")

    page.keyboard.press("Enter")
    # WhatsApp clears the compose box only once the message is actually posted.
    # Watching for that is more reliable than looking for a delivery tick, which
    # would also match every older message already in the thread.
    try:
        box.wait_for(state="attached", timeout=5000)
        page.wait_for_function(
            "el => el.innerText.trim() === ''",
            arg=box.element_handle(),
            timeout=timeout_s * 1000,
        )
    except Exception as exc:
        raise WhatsAppError(
            "The message was typed but the compose box never cleared, so it may not have sent."
        ) from exc


def send_whatsapp(message: str, config: dict, headless: bool = True, timeout_s: float = 60.0) -> None:
    sync_playwright = _import_playwright()
    chat = config["chat"]
    with sync_playwright() as playwright:
        context = _launch(playwright, config, headless=headless)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(WHATSAPP_URL, wait_until="domcontentloaded")
            try:
                page.wait_for_selector("#side", timeout=timeout_s * 1000)
            except Exception as exc:
                raise WhatsAppError(
                    "WhatsApp Web is not logged in on this profile. Run:\n"
                    "  python3 whatsapp_notify.py --login"
                ) from exc

            _open_chat(page, chat)
            _type_message(page, message)
            # Give the client a moment to flush the send to the server before the
            # browser context is torn down.
            page.wait_for_timeout(3000)
        finally:
            context.close()


# --------------------------------------------------------------------------- pipeline

def run_once(config: dict, do_refresh: bool, do_send: bool, headless: bool = True,
             force: bool = False) -> Optional[str]:
    """Check for newly-final games and post an update. Returns the message, if any."""
    results = nfl_scores.refresh() if do_refresh else nfl_scores.load_results()
    if not results.get("games"):
        raise SystemExit("No cached scores. Run: python3 nfl_scores.py --refresh")

    notify_state = load_notify_state()
    games = new_final_games(results, notify_state["announced"])
    if not games and not force:
        return None
    if not games and force:
        # --force re-announces the most recent week so a send can be tested on demand.
        finished = [g for g in results["games"] if g["completed"]]
        if not finished:
            raise SystemExit("No completed games to announce yet.")
        latest = max(g["week"] for g in finished)
        games = [g for g in finished if g["week"] == latest]

    state = season_model.build_season_state(results)
    message = compose_message(state, games, config.get("board_url"))

    if not do_send:
        return message

    send_whatsapp(message, config, headless=headless)
    notify_state["announced"] = sorted(set(notify_state["announced"]) | {g["id"] for g in games})
    notify_state["last_sent_at"] = results.get("fetched_at")
    save_notify_state(notify_state)
    return message


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--login", action="store_true", help="one-time QR login in a visible browser")
    p.add_argument("--refresh", action="store_true", help="pull fresh scores from ESPN first")
    p.add_argument("--send", action="store_true", help="actually post to WhatsApp")
    p.add_argument("--force", action="store_true",
                   help="re-announce the latest week even if it was already sent")
    p.add_argument("--headed", action="store_true", help="show the browser while sending")
    p.add_argument("--watch", type=int, metavar="SECONDS",
                   help="poll on this interval instead of running once")
    args = p.parse_args()

    config = load_config()

    if args.login:
        login(config)
        return

    def cycle() -> None:
        message = run_once(config, do_refresh=args.refresh or bool(args.watch),
                           do_send=args.send, headless=not args.headed, force=args.force)
        if message is None:
            print("No newly-final games; nothing to announce.")
            return
        if args.send:
            print(f"Sent to {config['chat']!r}:\n")
        else:
            print(f"DRY RUN — would send to {config['chat']!r} (add --send to post):\n")
        print(message)

    if not args.watch:
        cycle()
        return

    print(f"Polling every {args.watch}s. Ctrl-C to stop.")
    while True:
        try:
            cycle()
        except (nfl_scores.ScoreFetchError, WhatsAppError) as exc:
            print(f"[warn] {exc}", file=sys.stderr)
        time.sleep(args.watch)


if __name__ == "__main__":
    main()
