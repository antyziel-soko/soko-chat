from datetime import datetime
from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated

Username = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+$")]
Password = Annotated[str, StringConstraints(min_length=12, max_length=128)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class Credentials(BaseModel):
    username: Username
    password: Password


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class UserResponse(BaseModel):
    id: str
    username: str
    created_at: datetime


class ServerCreate(BaseModel):
    name: Name


class ChannelCreate(BaseModel):
    name: Name


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class MessageEdit(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
