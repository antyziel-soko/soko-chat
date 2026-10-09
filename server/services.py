from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.models import Channel, ServerMember


async def can_access_channel(db: AsyncSession, channel_id: str, user_id: str) -> bool:
    result = await db.execute(
        select(Channel.id).join(ServerMember, ServerMember.server_id == Channel.server_id)
        .where(Channel.id == channel_id, ServerMember.user_id == user_id)
    )
    return result.scalar_one_or_none() is not None
