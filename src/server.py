from fastapi import FastAPI, UploadFile, File, HTTPException
import aiofiles
import os
import logging
from datetime import datetime

logger = logging.getLogger("uvicorn.error")
app = FastAPI()

@app.post("/upload", responses={500: {"description": "Something went wrong"}})
async def upload(file: UploadFile):
    uploads_folder = "./uploads/"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        file.filename = f"{timestamp}_{file.filename}"
        filepath = os.path.join(uploads_folder, os.path.basename(file.filename))
        async with aiofiles.open(filepath, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                await f.write(chunk)
    except Exception:
        logger.exception("Upload failed")
        raise HTTPException(status_code=500, detail="Something went wrong")

    return {"message": f"Successfully uploaded: {file.filename}"}