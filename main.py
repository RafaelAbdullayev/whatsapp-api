# main.py - WhatsApp AI Moderator API Server (FULL VERSION)

import os
import json
import re
import logging
import asyncio
import aiohttp
from datetime import datetime, timedelta
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# ===========================================================
# 🔑 API НАСТРОЙКИ
# ===========================================================
VIRUSTOTAL_API_KEY = os.getenv("VIRUSTOTAL_API_KEY")
VIRUSTOTAL_URL = "https://www.virustotal.com/api/v3/urls"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ===========================================================
# МОДЕЛИ ДАННЫХ
# ===========================================================
class MessageRequest(BaseModel):
    message: str
    sender: str
    chat_id: str
    is_group: bool

class ModeratorResponse(BaseModel):
    action: str
    reason: str
    response_text: str
    ai_reply: str = ""

# ===========================================================
# СИСТЕМА ПРЕДУПРЕЖДЕНИЙ
# ===========================================================
WARNINGS_FILE = "warnings.json"
CACHE_FILE = "vt_cache.json"

def load_json(file):
    try:
        with open(file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_json(file, data):
    with open(file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def add_warning(sender, chat_id):
    warnings = load_json(WARNINGS_FILE)
    key = f"{sender}_{chat_id}"
    now = datetime.now()
    
    if key in warnings:
        last_warning = datetime.fromisoformat(warnings[key]["last_warning"])
        if now - last_warning > timedelta(hours=24):
            warnings[key] = {"count": 1, "last_warning": now.isoformat()}
        else:
            warnings[key]["count"] += 1
            warnings[key]["last_warning"] = now.isoformat()
    else:
        warnings[key] = {"count": 1, "last_warning": now.isoformat()}
    
    save_json(WARNINGS_FILE, warnings)
    return warnings[key]["count"]

def get_warning_count(sender, chat_id):
    warnings = load_json(WARNINGS_FILE)
    key = f"{sender}_{chat_id}"
    if key in warnings:
        last_warning = datetime.fromisoformat(warnings[key]["last_warning"])
        if datetime.now() - last_warning > timedelta(hours=24):
            del warnings[key]
            save_json(WARNINGS_FILE, warnings)
            return 0
        return warnings[key]["count"]
    return 0

# ===========================================================
# 🤖 ФУНКЦИЯ ДЛЯ AI ОТВЕТОВ
# ===========================================================

async def get_ai_reply(message, sender):
    if not DEEPSEEK_API_KEY:
        logger.warning("⚠️ DeepSeek API key не настроен!")
        return None
    
    try:
        system_prompt = """Sən WhatsApp moderator botsan. Qrupda vakansiya paylaşımı üçün nəzərdə tutulub.
Sənin xarakterin: Dostcanlı və peşəkarsan. Azərbaycan dilində danışırsan. Qısa və aydın cavablar verirsən.
Cavabların qısa və faydalı olsun."""
        
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message}
                ],
                "temperature": 0.7,
                "max_tokens": 300
            }
            
            async with session.post(DEEPSEEK_API_URL, headers=headers, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    ai_reply = data["choices"][0]["message"]["content"]
                    logger.info(f"🤖 AI ответ для {sender}: {ai_reply[:100]}...")
                    return ai_reply
                else:
                    logger.error(f"❌ DeepSeek API error: {response.status}")
                    return None
                    
    except Exception as e:
        logger.error(f"❌ DeepSeek error: {e}")
        return None

# ===========================================================
# 🛑 СПИСКИ ДЛЯ ПРОВЕРКИ
# ===========================================================

# АЗЕРБАЙДЖАНСКИЕ МАТЫ (ПОЛНЫЙ СПИСОК)
AZERBAIJANI_BAD_WORDS = [
    "sik", "sikir", "sikim", "siksən", "sikər", "sikdir", "sikiş",
    "sikmək", "sikmiş", "sikdiyim", "sikdiyimin", "sikdiyin", "sikdiyi",
    "amcıq", "amcığ", "amına", "amına qoyim", "göt", "götü", "götvərən",
    "qəhbə", "qehbe", "orospu", "malaş", "peyser", "peysər",
    "siktir", "siktir get", "siktir burdan", "cıqqa", "oblo", "oblosan", "vərəvər"
]

# РУССКИЕ МАТЫ (ПОЛНЫЙ СПИСОК)
RUSSIAN_BAD_WORDS = [
    "хуй", "хуя", "хуе", "хуйня", "пизда", "пизде", "пизду", "ебать", "ебу",
    "ебал", "ебаный", "ёбаный", "блядь", "блять", "бля", "сука", "суки",
    "мудак", "пидор", "шлюха", "гандон", "нахер", "нахрен", "нахуй",
    "пошёл", "иди", "соси", "залупа", "член", "курва"
]

# АНГЛИЙСКИЕ МАТЫ
ENGLISH_BAD_WORDS = [
    "fuck", "fucking", "fucker", "motherfucker", "shit", "bitch",
    "dick", "pussy", "whore", "asshole", "bastard", "cunt", "cock", "wanker"
]

# ТУРЕЦКИЕ МАТЫ
TURKISH_BAD_WORDS = [
    "amk", "siktir", "orospu", "pezevenk", "yavşak", "ibne", "piç",
    "gerizekalı", "mall", "salak", "aptal", "dangalak"
]

ALL_BAD_WORDS = list(set(AZERBAIJANI_BAD_WORDS + RUSSIAN_BAD_WORDS + ENGLISH_BAD_WORDS + TURKISH_BAD_WORDS))

BAD_WORDS_REGEX = re.compile('|'.join([re.escape(w) for w in ALL_BAD_WORDS]), re.IGNORECASE)

# СПИСОК СОЦИАЛЬНЫХ СЕТЕЙ ДЛЯ БЛОКИРОВКИ
SOCIAL_MEDIA_BLACKLIST = [
    "instagram.com", "instagr.am", "ig.me", "instagram",
    "facebook.com", "fb.com", "fb.me", "facebook",
    "tiktok.com", "tiktok",
    "t.me", "telegram.org", "telegram.me", "telegram",
    "twitter.com", "x.com", "youtube.com", "youtu.be", 
    "vk.com", "vkontakte", "ok.ru", "odnoklassniki", 
    "snapchat.com", "pinterest.com", "linkedin.com", "discord.com", "twitch.tv"
]

# КЛЮЧЕВЫЕ СЛОВА ДЛЯ РАСПОЗНАВАНИЯ РЕКЛАМЫ
COMMERCIAL_KEYWORDS = [
    "reklam", "elan", "təklif", "xidmət", "məhsul", "endirim", 
    "aksiya", "kampaniya", "sifariş", "çatdırılma", "kredit",
    "biznes", "kommersiya", "satılır", "satılık", "kirayə",
    "реклама", "услуги", "скидка", "акция", "бизнес", "продается"
]

# Список казино
CASINO_BLACKLIST = [
    "vavada", "pinup", "playfortuna", "riobet", "casino-x", "mystake", 
    "1xbet", "fonbet", "olimpbet", "888casino", "casino", "kazino", 
    "казино", "poker", "bet", "stavka", "ставка", "mostbet", "ggbet"
]

# Телефонные коды Азербайджана
AZERBAIJANI_CODES = [
    '50', '51', '55', '70', '77', '10', '99',
    '12', '18', '22', '24', '26', '31', '40', '44', '60'
]

# Банковские карты
BANK_CARD_PATTERNS = [
    r'4[0-9]{3}[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}',
    r'5[1-5][0-9]{2}[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}',
    r'\b[0-9]{16}\b',
    r'kart\s*n[ıi]?[n]?[ıi]?',
    r'card\s*number',
]

BANK_CARD_REGEX = re.compile('|'.join(BANK_CARD_PATTERNS), re.IGNORECASE)
SOCIAL_MEDIA_REGEX = re.compile('|'.join([re.escape(site) for site in SOCIAL_MEDIA_BLACKLIST]), re.IGNORECASE)
COMMERCIAL_KEYWORDS_REGEX = re.compile(r'\b(?:' + '|'.join([re.escape(kw) for kw in COMMERCIAL_KEYWORDS]) + r')\b', re.IGNORECASE)

# ===========================================================
# ФУНКЦИИ ПРОВЕРКИ
# ===========================================================

def check_bad_words(text):
    if BAD_WORDS_REGEX.search(text.lower()):
        return True, BAD_WORDS_REGEX.search(text.lower()).group()
    return False, None

def check_bank_card(text):
    card_match = BANK_CARD_REGEX.search(text)
    if card_match:
        return True, card_match.group()
    cleaned = re.sub(r'[\s-]', '', text)
    card_16 = re.search(r'\b[0-9]{16}\b', cleaned)
    if card_16 and not re.search(r'(\+994|994|0)[0-9]{9,12}', cleaned):
        return True, card_16.group()
    return False, None

def extract_domains(text):
    url_pattern = r'https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}'
    urls = re.findall(url_pattern, text.lower())
    domains = [url.replace('http://', '').replace('https://', '').replace('www.', '').split('/')[0] for url in urls]
    return domains

def check_casino_blacklist(domain):
    domain_lower = domain.lower()
    for casino in CASINO_BLACKLIST:
        if casino in domain_lower:
            return True, casino
    return False, None

def check_social_media(text):
    if SOCIAL_MEDIA_REGEX.search(text.lower()):
        return True, SOCIAL_MEDIA_REGEX.search(text.lower()).group()
    return False, None

def check_commercial_content(text):
    if COMMERCIAL_KEYWORDS_REGEX.search(text.lower()):
        return True, COMMERCIAL_KEYWORDS_REGEX.search(text.lower()).group()
    return False, None

def is_vacancy(text):
    if not text or len(text.strip()) < 10:
        return False
        
    text_lower = text.lower()
    
    vacancy_indicators = [
        "vakansiya", "iş", "işçi", "iş yeri", "işə", "mühasib", "mühəndis",
        "menecer", "operator", "satış", "kuryer", "sürücü", "təmizlik",
        "xadimə", "aşpaz", "ofisiant", "barmen", "maaş", "əmək haqqı",
        "cv", "rezume", "təcrübə", "şirkət", "firma", "tələb olunur",
        "axtarılır", "вакансия", "работа", "требуется", "vacancy", "job"
    ]
    
    for keyword in vacancy_indicators:
        if keyword in text_lower:
            return True
    
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    if re.search(email_pattern, text):
        return True
    
    return False

def check_photo_indication(text):
    photo_indicators = [
        r'\bşəkil\b', r'\bfoto\b', r'\bфото\b', r'\bphoto\b'
    ]
    photo_regex = re.compile('|'.join(photo_indicators), re.IGNORECASE)
    return bool(photo_regex.search(text))

def is_whatsapp_link(text):
    if not text:
        return False
    whatsapp_pattern = r'https?://chat\.whatsapp\.com/[A-Za-z0-9]+'
    return bool(re.search(whatsapp_pattern, text, re.IGNORECASE))

def is_vacancy_whatsapp(text):
    text_lower = text.lower()
    vacancy_keywords = [
        'vakansiya', 'iş', 'vacancy', 'job', 'вакансия', 'работа',
        'sürücü', 'mühasib', 'mühəndis', 'operator', 'tələb olunur',
        'axtarılır', 'işçi', 'iş yeri', 'iş axtarıram', 'şirkət', 'firma'
    ]
    for keyword in vacancy_keywords:
        if keyword in text_lower:
            return True
    phone_pattern = r'\b0[1-9][0-9]{8}\b|\b\+994[0-9]{9}\b'
    if re.search(phone_pattern, text):
        return True
    return False

# ===========================================================
# 🎯 ОСНОВНАЯ ФУНКЦИЯ МОДЕРАЦИИ
# ===========================================================
@app.post("/moderate", response_model=ModeratorResponse)
async def moderate_message(request: MessageRequest):
    message_lower = request.message.lower()
    user_mention = f"@{request.sender.split('@')[0]}"
    
    logger.info(f"📨 Сообщение от {request.sender}: {request.message[:50]}")
    
    is_talking_to_bot = any([
        request.message.lower().startswith(('бот', 'bot', '!bot', '@bot', 'salam bot', 'hi bot')),
        not request.is_group
    ])
    
    # 1. ПРОВЕРКА НА МАТЫ
    has_bad, bad_word = check_bad_words(request.message)
    if has_bad:
        logger.warning(f"🚫 Найден мат: '{bad_word}'")
        count = add_warning(request.sender, request.chat_id)
        if count >= 3:
            return ModeratorResponse(
                action="ban", 
                reason="Мат", 
                response_text=f"{user_mention} 🚫 Söyüş söymək qadağandır!\n⚠️ 3 dəfə qayda pozduğunuza görə qrupdan kənarlaşdırıldınız."
            )
        return ModeratorResponse(
            action="delete", 
            reason="Мат", 
            response_text=f"{user_mention} ⚠️ XƏBƏRDARLIQ {count}/3!\n❌ Söyüş söymək qadağandır!"
        )
    
    # 2. ПРОВЕРКА НА ФОТОГРАФИИ
    if check_photo_indication(request.message):
        logger.warning(f"📸 Обнаружено упоминание о фотографии")
        count = add_warning(request.sender, request.chat_id)
        if count >= 3:
            return ModeratorResponse(action="ban", reason="Photo sharing", response_text=f"{user_mention} 🚫 QADAĞANDIR!")
        return ModeratorResponse(action="delete", reason="Photo sharing", response_text=f"{user_mention} ⚠️ XƏBƏRDARLIQ {count}/3!\n❌ Şəkil paylaşmaq qadağandır!")
    
    # 3. ПРОВЕРКА НА WHATSAPP ССЫЛКИ
    if is_whatsapp_link(request.message):
        if is_vacancy_whatsapp(request.message):
            logger.info("✅ WhatsApp ссылка с вакансией - разрешена")
            return ModeratorResponse(action="nothing", reason="WhatsApp Group Link", response_text="")
        else:
            count = add_warning(request.sender, request.chat_id)
            if count >= 3:
                return ModeratorResponse(action="ban", reason="WhatsApp link", response_text=f"{user_mention} 🚫 WhatsApp linki yalnız vakansiya ilə paylaşıla bilər!")
            return ModeratorResponse(action="delete", reason="WhatsApp link", response_text=f"{user_mention} ⚠️ XƏBƏRDARLIQ {count}/3!\n❌ WhatsApp linki yalnız vakansiya ilə paylaşın!")
    
    # 4. ПРОВЕРКА НА СОЦИАЛЬНЫЕ СЕТИ
    is_social, social_site = check_social_media(request.message)
    if is_social:
        logger.warning(f"🔗 Обнаружена ссылка на соцсеть: {social_site}")
        count = add_warning(request.sender, request.chat_id)
        if count >= 3:
            return ModeratorResponse(action="ban", reason="Social media link", response_text=f"{user_mention} 🚫 Sosial media linkləri paylaşmaq qadağandır!")
        return ModeratorResponse(action="delete", reason="Social media link", response_text=f"{user_mention} ⚠️ XƏBƏRDARLIQ {count}/3!\n❌ Sosial media linki paylaşmaq qadağandır!")
    
    # 5. ПРОВЕРКА НА КОММЕРЧЕСКУЮ РЕКЛАМУ
    is_commercial, commercial_word = check_commercial_content(request.message)
    if is_commercial and not is_vacancy(request.message):
        logger.warning(f"💰 Обнаружена коммерческая реклама: {commercial_word}")
        count = add_warning(request.sender, request.chat_id)
        if count >= 3:
            return ModeratorResponse(action="ban", reason="Commercial advertisement", response_text=f"{user_mention} 🚫 İcazəsiz reklam paylaşımı qadağandır!")
        return ModeratorResponse(action="delete", reason="Commercial advertisement", response_text=f"{user_mention} ⚠️ XƏBƏRDARLIQ {count}/3!\n❌ Reklam paylaşımı üçün admin icazəsi tələb olunur!")
    
    # 6. ПРОВЕРКА НА БАНКОВСКИЕ КАРТЫ
    is_card, card_number = check_bank_card(request.message)
    if is_card:
        logger.warning(f"💳 Обнаружена банковская карта: {card_number}")
        count = add_warning(request.sender, request.chat_id)
        if count >= 3:
            return ModeratorResponse(action="ban", reason="Bank card", response_text=f"{user_mention} 🚫 Bank kartı məlumatlarını paylaşmaq qadağandır!")
        return ModeratorResponse(action="delete", reason="Bank card", response_text=f"{user_mention} ⚠️ XƏBƏRDARLIQ {count}/3!\n❌ Bank kartı paylaşmaq qadağandır!")

    # 7. ПРОВЕРКА ССЫЛОК (КАЗИНО)
    domains = extract_domains(message_lower)
    if domains:
        for domain in domains:
            is_casino, casino_name = check_casino_blacklist(domain)
            if is_casino:
                logger.warning(f"⚠️ Опасная ссылка: {domain}")
                count = add_warning(request.sender, request.chat_id)
                if count >= 3:
                    return ModeratorResponse(action="ban", reason="Casino", response_text=f"{user_mention} 🚫 Kazino linkləri paylaşmaq qadağandır!")
                return ModeratorResponse(action="delete", reason="Casino", response_text=f"{user_mention} ⚠️ XƏBƏRDARLIQ {count}/3!\n❌ Kazino linki paylaşmaq qadağandır!")

    # 8. ВАКАНСИИ - разрешаем
    if is_vacancy(request.message):
        logger.info("✅ Сообщение распознано как вакансия, разрешаем")
        return ModeratorResponse(action="nothing", reason="Vacancy", response_text="")

    # 9. ПРОВЕРКА НА КОРОТКИЕ СООБЩЕНИЯ
    words = message_lower.split()
    word_count = len(words)
    
    if word_count < 7:
        if is_talking_to_bot:
            ai_reply = await get_ai_reply(request.message, request.sender)
            if ai_reply:
                return ModeratorResponse(action="reply", reason="AI Reply", response_text="", ai_reply=ai_reply)
        
        logger.warning(f"✂️ Короткое сообщение ({word_count} слов), удаляем")
        count = add_warning(request.sender, request.chat_id)
        return ModeratorResponse(action="delete", reason="Short message", response_text=f"{user_mention} ⚠️ QISA MESAJ! Mesajınız silindi.\n❌ Səbəb: Mesajınız çox qısadır ({word_count} söz).")

    # 10. НОРМАЛЬНОЕ СООБЩЕНИЕ
    if is_talking_to_bot:
        ai_reply = await get_ai_reply(request.message, request.sender)
        if ai_reply:
            return ModeratorResponse(action="reply", reason="AI Reply", response_text="", ai_reply=ai_reply)
    
    logger.info("✅ Сообщение нормальное, пропускаем")
    return ModeratorResponse(action="nothing", reason="Normal", response_text="")

# ===========================================================
# 📊 ДОПОЛНИТЕЛЬНЫЕ ENDPOINTS
# ===========================================================
@app.get("/health")
@app.head("/health")  # Для UptimeRobot
async def health_check():
    return {
        "status": "ok", 
        "bad_words_count": len(ALL_BAD_WORDS),
        "casino_blacklist": len(CASINO_BLACKLIST),
        "social_media_blacklist": len(SOCIAL_MEDIA_BLACKLIST),
        "commercial_keywords": len(COMMERCIAL_KEYWORDS),
        "phone_codes": len(AZERBAIJANI_CODES),
        "bank_card_patterns": len(BANK_CARD_PATTERNS),
        "ai_enabled": bool(DEEPSEEK_API_KEY)
    }

@app.post("/clear_all_warnings")
async def clear_all_warnings():
    save_json(WARNINGS_FILE, {})
    return {"status": "ok", "message": "✅ Bütün xəbərdarlıqlar silindi!"}

@app.get("/warnings")
async def get_warnings():
    return load_json(WARNINGS_FILE)

@app.post("/add_to_blacklist/{item_type}/{item}")
async def add_to_blacklist(item_type: str, item: str):
    global CASINO_BLACKLIST, SOCIAL_MEDIA_BLACKLIST, COMMERCIAL_KEYWORDS
    
    if item_type == "casino":
        if item not in CASINO_BLACKLIST:
            CASINO_BLACKLIST.append(item.lower())
            return {"status": "ok", "message": f"✅ {item} casino siyahısına əlavə edildi!"}
    elif item_type == "social":
        if item not in SOCIAL_MEDIA_BLACKLIST:
            SOCIAL_MEDIA_BLACKLIST.append(item.lower())
            global SOCIAL_MEDIA_REGEX
            SOCIAL_MEDIA_REGEX = re.compile('|'.join([re.escape(site) for site in SOCIAL_MEDIA_BLACKLIST]), re.IGNORECASE)
            return {"status": "ok", "message": f"✅ {item} sosial media siyahısına əlavə edildi!"}
    elif item_type == "commercial":
        if item not in COMMERCIAL_KEYWORDS:
            COMMERCIAL_KEYWORDS.append(item.lower())
            global COMMERCIAL_KEYWORDS_REGEX
            COMMERCIAL_KEYWORDS_REGEX = re.compile(r'\b(?:' + '|'.join([re.escape(kw) for kw in COMMERCIAL_KEYWORDS]) + r')\b', re.IGNORECASE)
            return {"status": "ok", "message": f"✅ {item} kommersiya sözləri siyahısına əlavə edildi!"}
    
    return {"status": "error", "message": "❌ Artıq siyahıda var və ya səhv tip!"}

@app.post("/test_message")
async def test_message(text: str):
    results = {
        "text": text[:200],
        "has_bad_words": False,
        "bad_words_found": [],
        "has_bank_card": False,
        "bank_card_found": None,
        "has_social_media": False,
        "social_media_found": None,
        "has_commercial": False,
        "commercial_found": None,
        "is_vacancy": False,
        "word_count": len(text.split()),
        "actions": []
    }
    
    has_bad, bad_word = check_bad_words(text)
    if has_bad:
        results["has_bad_words"] = True
        results["bad_words_found"].append(bad_word)
        results["actions"].append(f"⛔ Silinecek (söyüş)")
    
    is_social, social_site = check_social_media(text)
    if is_social:
        results["has_social_media"] = True
        results["social_media_found"] = social_site
        results["actions"].append(f"⛔ Silinecek (sosial media)")
    
    is_commercial, commercial_word = check_commercial_content(text)
    if is_commercial and not is_vacancy(text):
        results["has_commercial"] = True
        results["commercial_found"] = commercial_word
        results["actions"].append(f"⛔ Silinecek (reklam)")
    
    is_card, card_number = check_bank_card(text)
    if is_card:
        results["has_bank_card"] = True
        results["bank_card_found"] = card_number
        results["actions"].append(f"⛔ Silinecek (bank kartı)")
    
    if is_vacancy(text):
        results["is_vacancy"] = True
        results["actions"].append("✅ İcazə verilir (vakansiya)")
    
    if len(text.split()) < 7 and not results["is_vacancy"] and not results["has_bank_card"] and not results["has_bad_words"]:
        results["actions"].append(f"⛔ Silinecek (qısa mesaj)")
    
    if not results["actions"]:
        results["actions"].append("✅ İcazə verilir (normal mesaj)")
    
    return results

if __name__ == "__main__":
    import uvicorn
    print("=" * 70)
    print("🚀 WhatsApp AI Moderator Server (Full Version)")
    print("📡 Server runs on http://0.0.0.0:10000")
    print(f"📊 Bad words count: {len(ALL_BAD_WORDS)}")
    print("=" * 70)
    uvicorn.run(app, host="0.0.0.0", port=10000)
