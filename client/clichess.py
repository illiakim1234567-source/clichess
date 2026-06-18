#!/usr/bin/env python3
"""
clichess — terminal chess with online matchmaking
Usage: python clichess.py [--host http://localhost:8000]
"""

import requests
import time
import sys
import argparse

# Unicode pieces: uppercase = white (our side shown at bottom), lowercase = black
PIECES = {
    "P": "♙", "N": "♘", "B": "♗", "R": "♖", "Q": "♕", "K": "♔",
    "p": "♟", "n": "♞", "b": "♝", "r": "♜", "q": "♛", "k": "♚",
    ".": "·",
}

POLL_INTERVAL = 1.5  # seconds between polls while waiting for opponent's move


def clear_line():
    print("\r\033[K", end="")


def render_board(board_str: str, color: str) -> str:
    """
    board_str: python-chess str(board) — 8 lines, pieces separated by spaces.
    Flip board if playing as black so your pieces are always at the bottom.
    """
    rows = board_str.strip().split("\n")
    pieces_rows = [row.split() for row in rows]

    if color == "black":
        pieces_rows = [row[::-1] for row in reversed(pieces_rows)]
        files = "  h g f e d c b a"
        ranks = list("12345678")
    else:
        files = "  a b c d e f g h"
        ranks = list("87654321")

    lines = [files]
    for i, row in enumerate(pieces_rows):
        rendered = " ".join(PIECES.get(p, p) for p in row)
        lines.append(f"{ranks[i]} {rendered} {ranks[i]}")
    lines.append(files)
    return "\n".join(lines)


def find_game(host: str) -> tuple[str, str, str]:
    """Join matchmaking queue, wait until matched. Returns (player_id, game_id, color)."""
    print("🔍 Looking for an opponent...")

    r = requests.post(f"{host}/join")
    r.raise_for_status()
    data = r.json()
    player_id = data["player_id"]

    if data["status"] == "matched":
        print(f"✅ Matched! You are playing as {data['color'].upper()}.")
        return player_id, data["game_id"], data["color"]

    # Waiting in queue — poll until matched
    dots = 0
    while True:
        dots = (dots % 3) + 1
        print(f"\r⏳ Waiting for opponent{'.' * dots}   ", end="", flush=True)
        time.sleep(POLL_INTERVAL)

        r = requests.get(f"{host}/poll/{player_id}")
        r.raise_for_status()
        data = r.json()

        if data["status"] != "waiting":
            print()  # newline after dots
            print(f"✅ Matched! You are playing as {data['color'].upper()}.")
            return player_id, data["game_id"], data["color"]


def play(host: str, player_id: str, game_id: str, color: str):
    last_board = None

    while True:
        # Poll for current state
        r = requests.get(f"{host}/poll/{player_id}")
        r.raise_for_status()
        state = r.json()

        board_str = state.get("board")
        status = state["status"]

        # Print board only when it changed
        if board_str and board_str != last_board:
            print("\n" + render_board(board_str, color) + "\n")
            last_board = board_str

        if status == "game_over":
            result = state.get("result", "?")
            if result == "1-0":
                winner = "White"
            elif result == "0-1":
                winner = "Black"
            else:
                winner = None

            if winner:
                you_won = (winner.lower() == color)
                print(f"🏁 Game over — {winner} wins! {'🎉 You won!' if you_won else '😞 You lost.'}")
            else:
                print(f"🏁 Game over — Draw! ({result})")
            break

        elif status == "opponent_turn":
            print("⏳ Waiting for opponent's move...", end="\r", flush=True)
            time.sleep(POLL_INTERVAL)

        elif status == "your_turn":
            print(f"♟  Your turn ({color}). Enter move (e.g. e4, Nf3, e2e4): ", end="")
            try:
                move = input().strip()
            except (EOFError, KeyboardInterrupt):
                print("\n👋 Disconnected.")
                sys.exit(0)

            if not move:
                continue

            try:
                r = requests.post(f"{host}/move", json={
                    "player_id": player_id,
                    "move": move,
                })
                if r.status_code == 400:
                    print(f"❌ {r.json().get('detail', 'Illegal move')}. Try again.")
                    continue
                r.raise_for_status()
            except requests.RequestException as e:
                print(f"⚠️  Network error: {e}")
                time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="clichess — terminal chess")
    parser.add_argument("--host", default="http://localhost:45678", help="Server URL")
    args = parser.parse_args()

    print("♟  Welcome to clichess!")
    print(f"   Server: {args.host}\n")

    try:
        player_id, game_id, color = find_game(args.host)
        play(args.host, player_id, game_id, color)
    except KeyboardInterrupt:
        print("\n👋 Bye!")
    except requests.ConnectionError:
        print(f"\n❌ Cannot connect to server at {args.host}")
        print("   Make sure the server is running: uvicorn server:app --reload")
        sys.exit(1)


if __name__ == "__main__":
    main()