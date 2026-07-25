# 👁️ Screen AI Assistant

> Desktop AI assistant for instant screen analysis using OCR and LLMs.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![PyQt6](https://img.shields.io/badge/PyQt6-6.x-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Features

- 📷 Select any area of the screen
- 🤖 Analyze text with AI
- 🌐 Translate between languages
- 📚 Get explanations for terms
- 💬 Ask questions about selected content
- 🖱️ Draggable & resizable answer windows
- 🧠 Supports multiple AI providers:
  - Ollama
  - OpenAI
  - DeepSeek
  - Gemini

## Screenshot

> *(add screenshot here)*

![preview](docs/screenshot.png)

## Installation

```bash
git clone https://github.com/yourname/screen-ai-assistant.git
cd screen-ai-assistant

pip install PyQt6 easyocr opencv-python numpy requests openai google-genai keyboard

python main.py
```

## Configuration

On the first launch the application will ask you to configure:

- AI provider
- model
- API key (if required)

The configuration is automatically saved to `config.json`.

## Hotkeys

| Key | Action |
|------|--------|
| **Ctrl + Shift + A** | Select screen area |
| **Esc** | Cancel / Clear overlay |

## Project Structure

```
screen-helper/
├── main.py
├── processor.py
├── config.py
└── README.md
```

## License

MIT