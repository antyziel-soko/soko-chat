import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import desc, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import bearer, current_user, hash_password, issue_session, resolve_token, token_digest, verify_password
from server.config import settings
from server.database import SessionLocal, get_db
from server.limiting import login_limiter, message_limiter
from server.models import Channel, Friendship, Message, Server, ServerInvite, ServerMember, Session, User
from server.schemas import ChannelCreate, Credentials, MessageCreate, MessageEdit, ServerCreate, TokenResponse, UserResponse
from server.services import can_access_channel
from server.websocket import hub

router = APIRouter()


def valid_id(value: str) -> bool:
    try:
        UUID(value)
        return True
    except ValueError:
        return False


@router.post("/auth/register", response_model=UserResponse, status_code=201)
async def register(payload: Credentials, db: AsyncSession = Depends(get_db)):
    user = User(username=payload.username, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Ta nazwa użytkownika jest już zajęta")
    return user


@router.post("/auth/login", response_model=TokenResponse)
async def login(payload: Credentials, request: Request, db: AsyncSession = Depends(get_db)):
    key = f"{request.client.host if request.client else 'unknown'}:{payload.username.casefold()}"
    if not login_limiter.allow(key, settings.login_max_attempts, settings.login_window_seconds):
        raise HTTPException(429, "Zbyt wiele prób logowania. Spróbuj później.")
    user = await db.scalar(select(User).where(User.username == payload.username))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Nieprawidłowa nazwa użytkownika lub hasło")
    token, expires = await issue_session(db, user.id)
    return TokenResponse(access_token=token, expires_at=expires)


@router.get("/users/me", response_model=UserResponse)
async def me(user: User = Depends(current_user)):
    return user


@router.post("/auth/logout", status_code=204)
async def logout(user: User = Depends(current_user), db: AsyncSession = Depends(get_db), credentials=Depends(bearer)):
    token = credentials.credentials
    session = await db.scalar(select(Session).where(Session.token_hash == token_digest(token), Session.user_id == user.id))
    if session:
        await db.delete(session)
        await db.commit()


@router.post("/auth/logout-all", status_code=204)
async def logout_all(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    sessions = (await db.scalars(select(Session).where(Session.user_id == user.id))).all()
    for session in sessions:
        await db.delete(session)
    await db.commit()


@router.delete("/users/me", status_code=204)
async def delete_account(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await db.delete(user)
    await db.commit()


@router.get("/users/lookup")
async def lookup_user(username: str = Query(min_length=3, max_length=32), user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    found = await db.scalar(select(User).where(User.username == username, User.id != user.id))
    if not found:
        raise HTTPException(404, "Nie znaleziono użytkownika Soko Chat o tej nazwie")
    return {"id": found.id, "username": found.username}


@router.get("/friends")
async def list_friends(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(User.id, User.username, Friendship.created_at)
        .join(Friendship, or_(Friendship.requester_id == User.id, Friendship.addressee_id == User.id))
        .where(
            Friendship.status == "accepted",
            or_(Friendship.requester_id == user.id, Friendship.addressee_id == user.id),
            User.id != user.id,
        )
        .order_by(User.username)
    )
    return [{"id": row.id, "username": row.username, "since": row.created_at} for row in rows]


@router.get("/friends/requests")
async def incoming_friend_requests(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(User.id, User.username, Friendship.created_at)
        .join(Friendship, Friendship.requester_id == User.id)
        .where(Friendship.addressee_id == user.id, Friendship.status == "pending")
        .order_by(Friendship.created_at)
    )
    return [{"id": row.id, "username": row.username, "requested_at": row.created_at} for row in rows]


@router.post("/friends/{user_id}/requests", status_code=201)
async def send_friend_request(user_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if not valid_id(user_id) or user_id == user.id:
        raise HTTPException(400, "Nieprawidłowy użytkownik")
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404, "Nie znaleziono użytkownika")
    existing = await db.scalar(
        select(Friendship).where(
            or_(
                (Friendship.requester_id == user.id) & (Friendship.addressee_id == target.id),
                (Friendship.requester_id == target.id) & (Friendship.addressee_id == user.id),
            )
        )
    )
    if existing:
        raise HTTPException(409, "Zaproszenie lub znajomość już istnieje")
    db.add(Friendship(requester_id=user.id, addressee_id=target.id, status="pending"))
    await db.commit()
    return {"status": "pending", "username": target.username}


@router.post("/friends/{user_id}/accept")
async def accept_friend_request(user_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if not valid_id(user_id):
        raise HTTPException(404, "Nie znaleziono zaproszenia")
    friendship = await db.scalar(
        select(Friendship).where(
            Friendship.requester_id == user_id,
            Friendship.addressee_id == user.id,
            Friendship.status == "pending",
        )
    )
    if not friendship:
        raise HTTPException(404, "Nie znaleziono zaproszenia")
    friendship.status = "accepted"
    await db.commit()
    return {"status": "accepted", "user_id": user_id}


@router.delete("/friends/{user_id}", status_code=204)
async def remove_friend_or_request(user_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if not valid_id(user_id):
        raise HTTPException(404, "Nie znaleziono znajomości")
    friendship = await db.scalar(
        select(Friendship).where(
            or_(
                (Friendship.requester_id == user.id) & (Friendship.addressee_id == user_id),
                (Friendship.requester_id == user_id) & (Friendship.addressee_id == user.id),
            )
        )
    )
    if friendship:
        await db.delete(friendship)
        await db.commit()


@router.post("/servers", status_code=201)
async def create_server(payload: ServerCreate, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    server = Server(name=payload.name, owner_id=user.id)
    db.add(server)
    await db.flush()
    db.add(ServerMember(server_id=server.id, user_id=user.id))
    db.add(Channel(server_id=server.id, name="ogólny"))
    await db.commit()
    return {"id": server.id, "name": server.name, "owner_id": server.owner_id, "created_at": server.created_at}


@router.get("/servers")
async def list_servers(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.execute(select(Server).join(ServerMember).where(ServerMember.user_id == user.id).order_by(Server.name))
    return [{"id": row.id, "name": row.name, "owner_id": row.owner_id, "created_at": row.created_at} for row in rows.scalars()]


@router.post("/servers/{server_id}/channels", status_code=201)
async def create_channel(server_id: str, payload: ChannelCreate, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if not valid_id(server_id):
        raise HTTPException(404, "Nie znaleziono serwera")
    server = await db.get(Server, server_id)
    member = await db.scalar(select(ServerMember).where(ServerMember.server_id == server_id, ServerMember.user_id == user.id))
    if not server or not member:
        raise HTTPException(404, "Nie znaleziono serwera")
    channel = Channel(server_id=server_id, name=payload.name)
    db.add(channel)
    await db.commit()
    return {"id": channel.id, "server_id": channel.server_id, "name": channel.name, "created_at": channel.created_at}


@router.get("/servers/{server_id}/channels")
async def list_channels(server_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if not valid_id(server_id):
        raise HTTPException(404, "Nie znaleziono serwera")
    member = await db.scalar(select(ServerMember).where(ServerMember.server_id == server_id, ServerMember.user_id == user.id))
    if not member:
        raise HTTPException(404, "Nie znaleziono serwera")
    rows = await db.scalars(select(Channel).where(Channel.server_id == server_id).order_by(Channel.name))
    return [{"id": c.id, "server_id": c.server_id, "name": c.name, "created_at": c.created_at} for c in rows]


@router.post("/servers/{server_id}/invites", status_code=201)
async def create_server_invite(server_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if not valid_id(server_id):
        raise HTTPException(404, "Nie znaleziono serwera")
    server = await db.get(Server, server_id)
    if not server or server.owner_id != user.id:
        raise HTTPException(404, "Nie znaleziono serwera")
    code = secrets.token_urlsafe(18)
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    db.add(ServerInvite(server_id=server_id, creator_id=user.id, code_hash=token_digest(code), expires_at=expires))
    await db.commit()
    return {"invite_code": code, "server_id": server_id, "expires_at": expires}


@router.post("/invites/{code}/join", status_code=201)
async def join_server(code: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if not 8 <= len(code) <= 128:
        raise HTTPException(404, "Zaproszenie jest nieprawidłowe lub wygasło")
    invite = await db.scalar(select(ServerInvite).where(ServerInvite.code_hash == token_digest(code)))
    if not invite:
        raise HTTPException(404, "Zaproszenie jest nieprawidłowe lub wygasło")
    expires = invite.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= datetime.now(timezone.utc):
        raise HTTPException(410, "Zaproszenie wygasło")
    member = await db.scalar(select(ServerMember).where(ServerMember.server_id == invite.server_id, ServerMember.user_id == user.id))
    if member:
        raise HTTPException(409, "Już należysz do tego serwera")
    server = await db.get(Server, invite.server_id)
    db.add(ServerMember(server_id=invite.server_id, user_id=user.id))
    await db.commit()
    return {"server_id": invite.server_id, "server_name": server.name if server else "Serwer"}


@router.get("/servers/{server_id}/members")
async def list_server_members(server_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if not valid_id(server_id):
        raise HTTPException(404, "Nie znaleziono serwera")
    member = await db.scalar(select(ServerMember).where(ServerMember.server_id == server_id, ServerMember.user_id == user.id))
    if not member:
        raise HTTPException(404, "Nie znaleziono serwera")
    rows = await db.execute(
        select(User.id, User.username, ServerMember.joined_at)
        .join(ServerMember, ServerMember.user_id == User.id)
        .where(ServerMember.server_id == server_id)
        .order_by(User.username)
    )
    return [{"id": row.id, "username": row.username, "joined_at": row.joined_at} for row in rows]


@router.get("/channels/{channel_id}/messages")
async def history(channel_id: str, before_id: str | None = None, limit: int = Query(50, ge=1, le=100), user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if not valid_id(channel_id) or not await can_access_channel(db, channel_id, user.id):
        raise HTTPException(404, "Nie znaleziono kanału")
    stmt = select(Message).where(Message.channel_id == channel_id)
    if before_id:
        if not valid_id(before_id):
            raise HTTPException(422, "Nieprawidłowy before_id")
        anchor = await db.get(Message, before_id)
        if not anchor or anchor.channel_id != channel_id:
            raise HTTPException(404, "Nie znaleziono wiadomości")
        stmt = stmt.where(Message.created_at < anchor.created_at)
    rows = await db.scalars(stmt.order_by(desc(Message.created_at)).limit(limit))
    items = list(reversed(rows.all()))
    return [message_json(m) for m in items]


def message_json(message: Message) -> dict:
    return {"id": message.id, "author_id": message.author_id, "channel_id": message.channel_id, "content": message.content, "created_at": message.created_at, "edited_at": message.edited_at}


@router.post("/channels/{channel_id}/messages", status_code=201)
async def send_message(channel_id: str, payload: MessageCreate, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if len(payload.content) > settings.message_max_length:
        raise HTTPException(422, f"Wiadomość może mieć najwyżej {settings.message_max_length} znaków")
    if not message_limiter.allow(user.id, settings.message_rate_count, settings.message_rate_window_seconds):
        raise HTTPException(429, "Wysyłasz wiadomości zbyt szybko")
    if not valid_id(channel_id) or not await can_access_channel(db, channel_id, user.id):
        raise HTTPException(404, "Nie znaleziono kanału")
    message = Message(channel_id=channel_id, author_id=user.id, content=payload.content)
    db.add(message)
    await db.commit()
    await db.refresh(message)
    result = message_json(message)
    await hub.broadcast(channel_id, {"type": "message", "message": result})
    return result


@router.patch("/messages/{message_id}")
async def edit_message(message_id: str, payload: MessageEdit, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    message = await db.get(Message, message_id) if valid_id(message_id) else None
    if not message or message.author_id != user.id:
        raise HTTPException(404, "Nie znaleziono wiadomości")
    if len(payload.content) > settings.message_max_length:
        raise HTTPException(422, "Wiadomość jest za długa")
    message.content = payload.content
    message.edited_at = datetime.now(timezone.utc)
    await db.commit()
    result = message_json(message)
    await hub.broadcast(message.channel_id, {"type": "message_edited", "message": result})
    return result


@router.delete("/messages/{message_id}", status_code=204)
async def delete_message(message_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    message = await db.get(Message, message_id) if valid_id(message_id) else None
    if not message or message.author_id != user.id:
        raise HTTPException(404, "Nie znaleziono wiadomości")
    channel_id = message.channel_id
    message_id = message.id
    await db.delete(message)
    await db.commit()
    await hub.broadcast(channel_id, {"type": "message_deleted", "message_id": message_id, "channel_id": channel_id})


@router.websocket("/ws/channels/{channel_id}")
async def channel_socket(websocket: WebSocket, channel_id: str):
    if not valid_id(channel_id):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        auth_frame = await websocket.receive_json()
        token = auth_frame.get("token") if isinstance(auth_frame, dict) and auth_frame.get("type") == "authenticate" else None
        if not isinstance(token, str) or len(token) > 256:
            await websocket.close(code=1008)
            return
        async with SessionLocal() as db:
            user = await resolve_token(db, token)
            allowed = user and await can_access_channel(db, channel_id, user.id)
        if not allowed:
            await websocket.close(code=1008)
            return
        await hub.connect(channel_id, websocket)
        await websocket.send_json({"type": "ready", "channel_id": channel_id})
        while True:
            # Keep-alive only: sending/editing is performed through authenticated HTTP endpoints.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(channel_id, websocket)
