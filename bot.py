import os, json, logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import Command
from gtts import gTTS
from dotenv import load_dotenv
from pydub import AudioSegment
import aiohttp
import speech_recognition as sr
from datetime import datetime
from aiogram.enums.parse_mode import ParseMode
from aiogram.client.default import DefaultBotProperties

# Set ffmpeg path
AudioSegment.converter = "C:/Users/user/AppData/Local/Microsoft/WinGet/Links/ffmpeg.exe"

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL_ID = os.getenv("MODEL_ID")

# Init Bot
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()

# Ensure logs/memory exists
os.makedirs("logs", exist_ok=True)
memory_path = "memory.json"
if not os.path.exists(memory_path):
    with open(memory_path, "w") as f: json.dump({}, f)


def stylize_text(text: str) -> str:
    # Emphasize key ideas and fix weird patterns
    import re
    text = re.sub(r"\byou 💡", "you", text)  # kill weird emoji replacement
    text = re.sub(r"\*(.*?)\*", r"*\1*", text)  # italics
    text = re.sub(r"\*\*(.*?)\*\*", r"**\1**", text)  # bold

    if "great job" in text.lower():
        text += " 🎉"
    if "error" in text.lower() or "fail" in text.lower():
        text += " ⚠️"
    return text


def load_memory():
    try:
        with open(memory_path, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}


def save_memory(memory):
    with open(memory_path, "w") as f:
        json.dump(memory, f, indent=4)


def update_user_memory(user_id, message):
    memory = load_memory()
    user_data = memory.get(str(user_id), {"chat_history": []})
    user_data["chat_history"].append(message)
    memory[str(user_id)] = user_data
    save_memory(memory)


def log_chat(user_id, user_text, bot_text):
    with open(f"logs/{user_id}.txt", "a", encoding="utf-8") as f:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{ts}]\nYou: {user_text}\nAI: {bot_text}\n\n")


async def query_mistral(user_id, prompt):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://t.me/RedGPTrobot",
    }
    data = {
        "model": MODEL_ID,
        "messages": [
            {"role": "system", "content": "You're a Gen Z assistant with big brother vibes. Be chill, casual, and real. Use **bold**, *italics*, and natural emojis if they add something. No cringe, just smart and helpful."},
            {"role": "user", "content": prompt},
        ],
    }
    async with aiohttp.ClientSession() as session:
        async with session.post("https://openrouter.ai/api/v1/chat/completions", json=data, headers=headers) as resp:
            result = await resp.json()
            return result["choices"][0]["message"]["content"]


@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("Salom, Akbar! Send text or voice. Use /voice to toggle voice replies. Use /clear to reset history.")


@dp.message(Command("voice"))
async def toggle_voice(message: Message):
    memory = load_memory()
    uid = str(message.from_user.id)
    current = memory.get(uid, {}).get("voice_reply", False)
    memory.setdefault(uid, {})["voice_reply"] = not current
    save_memory(memory)
    status = "enabled ✅" if not current else "disabled ❌"
    await message.answer(f"Voice reply is now {status}.")


@dp.message(F.voice)
async def voice_handler(message: Message):
    file_id = message.voice.file_id
    file = await bot.get_file(file_id)
    file_path = file.file_path
    voice_ogg = f"{message.from_user.id}_voice.ogg"
    voice_wav = f"{message.from_user.id}_voice.wav"

    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            with open(voice_ogg, "wb") as f:
                f.write(await resp.read())

    AudioSegment.from_file(voice_ogg).export(voice_wav, format="wav")

    recognizer = sr.Recognizer()
    with sr.AudioFile(voice_wav) as source:
        audio = recognizer.record(source)
        try:
            text = recognizer.recognize_google(audio)
        except sr.UnknownValueError:
            await message.answer("Sorry, couldn't understand the voice.")
            return

    await handle_chat(message, text)


@dp.message(F.text)
async def text_handler(message: Message):
    await handle_chat(message, message.text)


async def handle_chat(message: Message, user_input: str):
    user_id = str(message.from_user.id)
    update_user_memory(user_id, user_input)

    raw_reply = await query_mistral(user_id, user_input)
    reply = stylize_text(raw_reply)

    log_chat(user_id, user_input, reply)
    update_user_memory(user_id, reply)

    memory = load_memory()
    wants_voice = memory.get(user_id, {}).get("voice_reply", False)

    if wants_voice:
        tts = gTTS(reply)
        mp3_path = f"{user_id}_reply.mp3"
        tts.save(mp3_path)
        await message.answer_voice(voice=FSInputFile(mp3_path))
    else:
        await message.answer(reply)


@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    user_id = str(message.from_user.id)
    memory = load_memory()
    if user_id in memory:
        del memory[user_id]
        save_memory(memory)

    log_path = f"logs/{user_id}.txt"
    if os.path.exists(log_path):
        os.remove(log_path)

    await message.answer("✅ Chat history and logs were successfully cleared.")


if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    asyncio.run(dp.start_polling(bot))
