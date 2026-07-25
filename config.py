import json
import os

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "provider": "ollama",
    "ollama_url": "http://localhost:11434/api/generate",
    "model_name": "llama3",
    "api_key": "",
    "hotkey": "ctrl+shift+a"
}

def load_or_create_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        print("\n[Config] Конфиг не найден. Создаем настройки по умолчанию.")
        provider = input(f"Выберите провайдера (ollama, openai, gemini, deepseek) [{DEFAULT_CONFIG['provider']}]: ").strip().lower()
        if provider not in ["ollama", "openai", "gemini", "deepseek"]:
            provider = DEFAULT_CONFIG['provider']
            
        model = input(f"Введите название модели [{DEFAULT_CONFIG['model_name']}]: ").strip()
        if not model:
            model = DEFAULT_CONFIG['model_name']
            
        api_key = input("Введите API ключ (если требуется): ").strip()
        
        config_data = {
            "provider": provider,
            "ollama_url": DEFAULT_CONFIG['ollama_url'],
            "model_name": model,
            "api_key": api_key,
            "hotkey": DEFAULT_CONFIG['hotkey']
        }
        
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
            print(f"[Config] Сохранено в {CONFIG_FILE}\n")
        except Exception as e:
            print(f"[Config] Ошибка сохранения: {e}")
            return DEFAULT_CONFIG
            
        return config_data

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {
                "provider": data.get("provider", DEFAULT_CONFIG["provider"]),
                "ollama_url": data.get("ollama_url", DEFAULT_CONFIG["ollama_url"]),
                "model_name": data.get("model_name", DEFAULT_CONFIG["model_name"]),
                "api_key": data.get("api_key", DEFAULT_CONFIG["api_key"]),
                "hotkey": data.get("hotkey", DEFAULT_CONFIG["hotkey"])
            }
    except Exception as e:
        print(f"[Config] Ошибка чтения конфига: {e}")
        return DEFAULT_CONFIG

_cfg = load_or_create_config()

PROVIDER = _cfg["provider"]
OLLAMA_URL = _cfg["ollama_url"]
MODEL_NAME = _cfg["model_name"]
API_KEY = _cfg["api_key"]
HOTKEY = _cfg["hotkey"]