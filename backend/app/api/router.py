from fastapi import APIRouter

from app.api.routes import auth, health, process_models, projects, providers, stage_runs

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(providers.router)
api_router.include_router(process_models.router)
api_router.include_router(projects.router)
api_router.include_router(stage_runs.router)
api_router.include_router(health.router)
