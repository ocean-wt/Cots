from fastapi import FastAPI
from app.api.v1 import chat
from app.core.config import settings

app = FastAPI(title=settings.PROJECT_NAME)

app.include_router(chat.router, prefix="/api/v1/chat", tags=["chat"])

@app.get("/")
def read_root():
    return {"message": "Welcome to Cots"}