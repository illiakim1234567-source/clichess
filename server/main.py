from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import chess
import uuid
import time
from threading import Lock

app = FastAPI()

# --- DATA STORAGE ---
games = {}       # game_id -> {"board": chess.Board, "white": player_id, "black": player_id, "created_at": float}
players = {}     # player_id -> {"game_id": str, "color": "white"/"black"}
queue = []       # list of player_ids waiting for opponent
queue_lock = Lock()


# --- MODELS ---
class JoinResponse(BaseModel):
    player_id: str
    status: str   # "waiting" | "matched"
    game_id: str | None = None
    color: str | None = None


class PollResponse(BaseModel):
    status: str         # "waiting" | "your_turn" | "opponent_turn" | "game_over"
    board: str | None = None
    color: str | None = None
    game_id: str | None = None
    result: str | None = None
    turn: str | None = None


class MoveRequest(BaseModel):
    player_id: str
    move: str


class MoveResponse(BaseModel):
    board: str
    game_over: bool
    result: str | None = None


# --- ROUTES ---

@app.post("/join", response_model=JoinResponse)
def join_game():
    """Player joins the matchmaking queue. Returns immediately with status."""
    player_id = str(uuid.uuid4())

    with queue_lock:
        if queue:
            # Match with waiting player
            opponent_id = queue.pop(0)

            # Make sure opponent is still waiting (not expired)
            if opponent_id not in players or players[opponent_id].get("game_id"):
                # Opponent gone — put self in queue instead
                players[player_id] = {"game_id": None, "color": None}
                queue.append(player_id)
                return JoinResponse(player_id=player_id, status="waiting")

            game_id = str(uuid.uuid4())
            board = chess.Board()

            games[game_id] = {
                "board": board,
                "white": opponent_id,
                "black": player_id,
                "created_at": time.time(),
            }

            players[opponent_id] = {"game_id": game_id, "color": "white"}
            players[player_id] = {"game_id": game_id, "color": "black"}

            return JoinResponse(
                player_id=player_id,
                status="matched",
                game_id=game_id,
                color="black",
            )
        else:
            # No opponent yet — add to queue
            players[player_id] = {"game_id": None, "color": None}
            queue.append(player_id)
            return JoinResponse(player_id=player_id, status="waiting")


@app.get("/poll/{player_id}", response_model=PollResponse)
def poll(player_id: str):
    """Client polls this to check if matched / whose turn it is."""
    if player_id not in players:
        raise HTTPException(status_code=404, detail="Player not found")

    info = players[player_id]

    if info["game_id"] is None:
        return PollResponse(status="waiting")

    game_id = info["game_id"]
    color = info["color"]
    game = games[game_id]
    board: chess.Board = game["board"]

    if board.is_game_over():
        return PollResponse(
            status="game_over",
            board=str(board),
            color=color,
            game_id=game_id,
            result=board.result(),
        )

    current_turn = "white" if board.turn else "black"
    status = "your_turn" if current_turn == color else "opponent_turn"

    return PollResponse(
        status=status,
        board=str(board),
        color=color,
        game_id=game_id,
        turn=current_turn,
    )


@app.post("/move", response_model=MoveResponse)
def make_move(data: MoveRequest):
    if data.player_id not in players:
        raise HTTPException(status_code=404, detail="Player not found")

    info = players[data.player_id]
    if info["game_id"] is None:
        raise HTTPException(status_code=400, detail="Not in a game yet")

    game = games[info["game_id"]]
    board: chess.Board = game["board"]
    color = info["color"]

    # Check it's this player's turn
    current_turn = "white" if board.turn else "black"
    if current_turn != color:
        raise HTTPException(status_code=400, detail="Not your turn")

    # Try SAN first (e4, Nf3), then UCI (e2e4)
    try:
        board.push_san(data.move)
    except Exception:
        try:
            board.push(chess.Move.from_uci(data.move))
        except Exception:
            raise HTTPException(status_code=400, detail="Illegal move")

    game_over = board.is_game_over()
    result = board.result() if game_over else None

    return MoveResponse(board=str(board), game_over=game_over, result=result)