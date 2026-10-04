from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from app.services.preview_service import render_preview_png
from app.services.sr_service import run_super_resolution, ModelNotAvailableError


router = APIRouter(
    prefix="/processing",
    tags=["Processing"],
)


PROCESSED_DIR = Path("processed")
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


# Temporary project state
processing_state = {
    "status": "idle",
    "stage": "Waiting for input",
    "progress": 0,
    "input_filename": None,
    "output_filename": None,
    "input_resolution": "10m",
    "target_resolution": "≤4m",
}


class SuperResolutionRequest(BaseModel):
    filename: str


def _state_response():
    return {
        "status": processing_state["status"],
        "stage": processing_state["stage"],
        "progress": processing_state["progress"],
        "input_filename": processing_state["input_filename"],
        "output_filename": processing_state["output_filename"],
        "input_resolution": processing_state["input_resolution"],
        "target_resolution": processing_state["target_resolution"],
    }


# --------------------------------------------------
# Processing Status (the website polls this to fill the progress bar)
# --------------------------------------------------

@router.get("/status")
def processing_status():
    return _state_response()


# --------------------------------------------------
# Start Super Resolution
# --------------------------------------------------

@router.post("/super-resolution")
def super_resolution(request: SuperResolutionRequest):

    filename = Path(request.filename).name

    processed_file = PROCESSED_DIR / filename

    if not processed_file.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"Processed file not found: {filename}. "
                "Please preprocess the image first."
            ),
        )

    # Mark as running before we start the (potentially slow) inference call.
    processing_state["status"] = "running"
    processing_state["stage"] = "Loading AI model"
    processing_state["progress"] = 0
    processing_state["input_filename"] = filename
    processing_state["output_filename"] = None

    output_filename = f"{processed_file.stem}_sr_4x.tif"
    output_file = PROCESSED_DIR / output_filename

    def report_progress(done_tiles: int, total_tiles: int):
        # Stay at 99% until the file is completely written
        percent = int(done_tiles * 100 / total_tiles) if total_tiles else 0
        processing_state["progress"] = min(percent, 99)
        processing_state["stage"] = (
            f"Enhancing image ({done_tiles} of {total_tiles} tiles)"
        )

    try:
        result = run_super_resolution(
            input_path=str(processed_file),
            output_path=str(output_file),
            progress_callback=report_progress,
        )
    except ModelNotAvailableError as error:
        processing_state["status"] = "failed"
        processing_state["stage"] = "Model unavailable"
        raise HTTPException(status_code=503, detail=str(error))
    except ValueError as error:
        processing_state["status"] = "failed"
        processing_state["stage"] = "Invalid input"
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        processing_state["status"] = "failed"
        processing_state["stage"] = "Inference error"
        raise HTTPException(
            status_code=500,
            detail=f"Super resolution inference failed: {error}",
        )

    processing_state["status"] = "completed"
    processing_state["stage"] = "Completed"
    processing_state["progress"] = 100
    processing_state["output_filename"] = output_filename

    return {
        "status": "completed",
        "message": (
            f"Super resolution completed: {result['input_width']}x"
            f"{result['input_height']} -> {result['output_width']}x"
            f"{result['output_height']} (x{result['scale_factor']})."
        ),
        "filename": filename,
        "input_path": str(processed_file),
        "output": output_filename,
        "target_resolution": "≤4m",
    }


# --------------------------------------------------
# Processing Results
# --------------------------------------------------

@router.get("/results")
def get_results():
    return _state_response()


# --------------------------------------------------
# Serve Processed GeoTIFF
# --------------------------------------------------

@router.get("/output/{filename}")
def get_output_file(filename: str):

    safe_filename = Path(filename).name

    file_path = PROCESSED_DIR / safe_filename

    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Output file not found: {safe_filename}",
        )

    return FileResponse(
        path=file_path,
        media_type="image/tiff",
        filename=safe_filename,
    )


# --------------------------------------------------
# Preview picture (PNG) of a processed GeoTIFF
# --------------------------------------------------

@router.get("/preview/{filename}")
def get_preview(filename: str):

    safe_filename = Path(filename).name

    if not safe_filename.lower().endswith((".tif", ".tiff")):
        raise HTTPException(
            status_code=400,
            detail="Previews are only available for GeoTIFF files",
        )

    file_path = PROCESSED_DIR / safe_filename

    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"File not found: {safe_filename}",
        )

    try:
        png = render_preview_png(str(file_path))
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Could not create the preview: {error}",
        )

    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "no-cache"},
    )
