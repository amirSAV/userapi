import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.core.client_manager import client_manager
from app.routers import auth, proxy, bot_api, help_router, admin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("userapi")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}...")
    logger.info(f"Storage directory: {settings.storage_path}")
    yield
    logger.info("Shutting down UserAPI, closing active Telethon clients...")
    await client_manager.close_all()
    logger.info("UserAPI shutdown complete.")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Drop-in Telegram Bot API emulator running on real Telegram user sessions with Telethon.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
async def root():
    """Redirect root to /help documentation."""
    return RedirectResponse(url="/help")


# Include routers
app.include_router(help_router.router)
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(proxy.router)
# bot_api catches /{token}/{method} and /bot{token}/{method}, so include it last
app.include_router(bot_api.router)
