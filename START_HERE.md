# Model Lab

**Model Lab** is the package name for the **M²S Model Training Pipeline** command center.

## Windows launch

```powershell
pip install -r .\requirements.txt
python .\launch.py
```

The launcher starts the existing localhost FastAPI command center when needed and opens the desktop control surface. The UI is designed for a 1760×990 display.

Model Lab navigates the real pipeline and dataset sessions. It does not implement a second copy of the crawler, cleaner, deduplicator, tokenizer, sharder, trainer, or exporter.
