# Voice listening tests

Blind listening tests for the TTS vendor bake-off. Voices are anonymous clips; which system made
each one lives only in the app's secrets.

- `pairwise_app.py`: Mansa against each other system, two voices at a time (A / B / about the same
  on naturalness, intelligibility, pronunciation and overall, plus why).
- `streamlit_app.py`: every voice in a round rated 1-5 on the same four criteria, plus notes.

Answers are written to Google Sheets in Drive by a service account, through the Drive API.

## Deploy on Streamlit Community Cloud

1. New app, this repo, main file `pairwise_app.py` (a second app with `streamlit_app.py` for the
   1-5 test).
2. Advanced settings, Secrets: paste the real `secrets.toml` (layout in
   `.streamlit/secrets.toml.example`). It is never committed.

Built from `stream-tts/vendor-benchmark/listening-test/` in the stream-finetune repo, where the
audio is rebuilt (`build.py`) and the sheets and secrets are prepared (`setup_drive.py`).
