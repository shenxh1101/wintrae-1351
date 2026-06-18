from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.database import engine, Base
from app.init_db import init_db
from app.routers import user, store, query, admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    init_db()
    yield


app = FastAPI(
    title="连锁自助洗衣柜后台服务",
    description="统一处理下单、投柜和取件流程的后端服务",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(user.router)
app.include_router(store.router)
app.include_router(query.router)
app.include_router(admin.router)


@app.get("/", tags=["健康检查"])
def root():
    return {"service": "连锁自助洗衣柜后台服务", "version": "1.0.0", "status": "running"}
