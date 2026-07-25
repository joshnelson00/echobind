import logging

import torch
import whisper

from common.config import WHISPER_MODEL, WHISPER_DEVICE

logger = logging.getLogger(__name__)

_model = None


def get_model():
    global _model

    if _model is not None:
        return _model

    requested_device = WHISPER_DEVICE.lower()
    if requested_device == "cuda" and not torch.cuda.is_available():
        logger.warning("CUDA requested for Whisper but not available; falling back to CPU")
        requested_device = "cpu"

    _model = whisper.load_model(WHISPER_MODEL, device=requested_device)
    return _model


def transcribe(filepath: str, word_timestamps: bool = False) -> dict:
    """
    Runs Whisper transcription.

    Returns:
        {
            "text": full transcript text,
            "segments": Whisper's segment-level (and optionally word-level)
                         timestamps, each with a "text" and "no_speech_prob",
        }
    """
    model = get_model()
    result = model.transcribe(filepath, word_timestamps=word_timestamps)

    return {
        "text": result["text"],
        "segments": result["segments"],
    }