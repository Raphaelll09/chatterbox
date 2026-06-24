"""Add the project root to sys.path so tests can import audio_postprocess."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
