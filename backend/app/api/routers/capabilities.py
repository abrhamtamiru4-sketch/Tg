"""Capabilities API router - exposes the capability matrix."""
from fastapi import APIRouter
from app.telegram.capability_registry import get_registry
router = APIRouter()

@router.get("/")
async def get_capabilities():
    registry = get_registry()
    return {"api_version": registry.current_api_version, "capabilities": registry.matrix()}

@router.get("/{name}")
async def get_capability(name: str):
    from fastapi import HTTPException
    registry = get_registry()
    try:
        cap = registry.get(name)
        return {"name": cap.name, "method": cap.telegram_method, "available": registry.is_available(name),
                "status": cap.status.value, "fallback": cap.fallback, "docs": cap.documentation_url}
    except KeyError:
        raise HTTPException(404, f"Capability not found: {name}")
