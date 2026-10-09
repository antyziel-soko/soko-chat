from contextlib import asynccontextmanager

from fastapi import FastAPI

from server import models  # noqa: F401 — rejestruje modele w metadanych SQLAlchemy
from server.api.routes import router
from server.database import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title="Soko Chat API", version="0.1.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}
