"""Finance-novel library (shared by Benny and 叮當): list, import, progress, delete."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

__all__ = ["router"]

router = APIRouter()


class ProgressRequest(BaseModel):
    chapter: int | None = Field(default=None, ge=1, le=100000)


@router.get("/novels")
async def list_novels(request: Request) -> dict[str, object]:
    library = request.app.state.novels
    return {
        "inbox": str(library.inbox),
        "books": [book.as_dict() for book in await library.books()],
    }


@router.post("/novels/import")
async def import_novels(request: Request) -> dict[str, object]:
    results = await request.app.state.novels.import_inbox()
    return {"results": results}


@router.put("/novels/{book_id}/progress")
async def set_progress(book_id: int, values: ProgressRequest, request: Request) -> dict[str, object]:
    library = request.app.state.novels
    if not any(book.id == book_id for book in await library.books()):
        raise HTTPException(status_code=404, detail="book not found")
    await library.set_progress(book_id, values.chapter)
    return {"id": book_id, "progress": values.chapter}


@router.delete("/novels/{book_id}")
async def delete_novel(book_id: int, request: Request) -> dict[str, object]:
    if not await request.app.state.novels.delete(book_id):
        raise HTTPException(status_code=404, detail="book not found")
    return {"deleted": True, "id": book_id}
