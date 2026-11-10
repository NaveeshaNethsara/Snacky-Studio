"""Hand only complete, sized files to the native browser download manager."""
import asyncio

from fastapi import HTTPException
from fastapi.responses import FileResponse

from app.files import build_content_disposition, media_type, resolve_media_file
from app.jobs import TERMINAL_STATUSES


async def browser_response(request, task):
    if task["status"] not in TERMINAL_STATUSES:
        raise HTTPException(409, "The media is still being prepared. It will save in your browser when ready.")
    if task["status"] != "completed" or not task.get("filename"):
        raise HTTPException(409, task.get("error") or "This download was cancelled. Start it again to retry.")

    if hasattr(request.app.state, "storage"):
        return await asyncio.to_thread(request.app.state.storage.response, task)

    def response():
        try:
            path = resolve_media_file(request.app.state.settings.downloads_dir, task["filename"])
            stat = path.stat()
        except (FileNotFoundError, OSError):
            raise HTTPException(404, "File not found or has been moved")
        # Content-Length and Range support give Chrome real, resumable file progress.
        return FileResponse(path, stat_result=stat, media_type=media_type(path), headers={
            "Content-Disposition": build_content_disposition(path.name), "Cache-Control": "no-store",
        })

    return await asyncio.to_thread(response)
