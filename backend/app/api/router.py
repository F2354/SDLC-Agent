from fastapi import APIRouter

from app.api.routes import (
    artifacts,
    agents,
    auth,
    code,
    events,
    filesystem,
    health,
    process_models,
    projects,
    mcp,
    skills,
    providers,
    stage_runs,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(artifacts.router)
api_router.include_router(agents.router)
api_router.include_router(code.router)
api_router.include_router(events.router)
api_router.include_router(filesystem.router)
api_router.include_router(providers.router)
api_router.include_router(process_models.router)
api_router.include_router(projects.router)
api_router.include_router(mcp.router)
api_router.include_router(skills.router)
api_router.include_router(stage_runs.router)
api_router.include_router(health.router)
