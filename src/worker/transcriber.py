import whisper

from api.app.config import WHISPER_MODEL, WHISPER_DEVICE

# Loaded once at module import time — not per job.
model = whisper.load_model(WHISPER_MODEL, device=WHISPER_DEVICE)


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
    result = model.transcribe(filepath, word_timestamps=word_timestamps)

    return {
        "text": result["text"],
        "segments": result["segments"],
    }