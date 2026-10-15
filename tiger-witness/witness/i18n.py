"""Local-language messaging: dependency-free language detection (script ranges + stopword voting) and
translated system phrases so the agent answers in the language the user wrote in, even with the offline provider."""
from __future__ import annotations
import re

_SCRIPTS = [  # (lang, regex of a script that identifies it)
    ("te", r"[\u0C00-\u0C7F]"), ("ta", r"[\u0B80-\u0BFF]"), ("kn", r"[\u0C80-\u0CFF]"), ("ml", r"[\u0D00-\u0D7F]"),
    ("bn", r"[\u0980-\u09FF]"), ("gu", r"[\u0A80-\u0AFF]"), ("pa", r"[\u0A00-\u0A7F]"), ("hi", r"[\u0900-\u097F]"),
    ("ar", r"[\u0600-\u06FF]"), ("he", r"[\u0590-\u05FF]"), ("th", r"[\u0E00-\u0E7F]"), ("ko", r"[\uAC00-\uD7AF]"),
    ("ja", r"[\u3040-\u30FF]"), ("zh", r"[\u4E00-\u9FFF]"), ("ru", r"[\u0400-\u04FF]"), ("el", r"[\u0370-\u03FF]"),
]
_STOP = {
    "en": "the and is are you to of for my me please what can with this that it on in at",
    "es": "el la los las de que y en por para mi es una un con como qué puedes favor",
    "fr": "le la les de des et est en pour mon ma je vous un une avec que qui sur s'il",
    "de": "der die das und ist ich du nicht ein eine mit für mein bitte was zu auf",
    "pt": "o a os as de que e em para meu minha é um uma com você por favor não",
    "it": "il lo la gli le di che e è per mio mia un una con non sono favore",
    "id": "yang dan di ke dari ini itu untuk saya tolong apa dengan tidak bisa ada",
    "sw": "na ya wa kwa ni la za katika tafadhali nini mimi wewe hii",
    "tr": "ve bir bu da de için ne ben sen lütfen mi ile çok",
    "nl": "de het een en is van ik je niet voor met mijn alsjeblieft wat",
}
_STOPSETS = {k: set(v.split()) for k, v in _STOP.items()}


def detect(text: str, default: str = "en") -> str:
    t = text or ""
    counts = {lang: len(re.findall(rx, t)) for lang, rx in _SCRIPTS}
    if counts.get("ja") and counts.get("zh"):
        counts["zh"] = 0  # kana present => Japanese
    best = max(counts, key=counts.get)
    if counts[best] >= 2:
        return best
    words = re.findall(r"[a-zà-ÿ']+", t.lower())
    if not words:
        return default
    score = {k: sum(w in s for w in words) for k, s in _STOPSETS.items()}
    lang = max(score, key=score.get)
    return lang if score[lang] > 0 else default


NAMES = {"en": "English", "es": "Spanish", "fr": "French", "de": "German", "pt": "Portuguese", "it": "Italian",
         "id": "Indonesian", "sw": "Swahili", "tr": "Turkish", "nl": "Dutch", "hi": "Hindi", "te": "Telugu",
         "ta": "Tamil", "kn": "Kannada", "ml": "Malayalam", "bn": "Bengali", "gu": "Gujarati", "pa": "Punjabi",
         "ar": "Arabic", "he": "Hebrew", "th": "Thai", "ko": "Korean", "ja": "Japanese", "zh": "Chinese",
         "ru": "Russian", "el": "Greek"}

PHRASES = {
    "needs_approval": {
        "en": "I need your approval before I {what}.", "es": "Necesito tu aprobación antes de {what}.",
        "fr": "J'ai besoin de ton accord avant de {what}.", "de": "Ich brauche deine Freigabe, bevor ich {what}.",
        "pt": "Preciso da sua aprovação antes de {what}.", "it": "Ho bisogno della tua approvazione prima di {what}.",
        "hi": "{what} करने से पहले मुझे आपकी मंज़ूरी चाहिए।", "te": "{what} చేయడానికి ముందు మీ అనుమతి కావాలి.",
        "ta": "{what} செய்வதற்கு முன் உங்கள் ஒப்புதல் தேவை.", "ar": "أحتاج إلى موافقتك قبل {what}.",
        "zh": "在{what}之前需要你的批准。", "ja": "{what}の前にあなたの承認が必要です。", "ko": "{what} 전에 승인이 필요합니다.",
        "ru": "Мне нужно ваше одобрение, прежде чем {what}.", "id": "Saya perlu persetujuan Anda sebelum {what}.",
        "sw": "Ninahitaji idhini yako kabla ya {what}.", "tr": "{what} önce onayına ihtiyacım var.",
    },
    "done": {
        "en": "Done.", "es": "Hecho.", "fr": "C'est fait.", "de": "Erledigt.", "pt": "Feito.", "it": "Fatto.",
        "hi": "हो गया।", "te": "పూర్తయింది.", "ta": "முடிந்தது.", "ar": "تم.", "zh": "完成了。", "ja": "完了しました。",
        "ko": "완료했습니다.", "ru": "Готово.", "id": "Selesai.", "sw": "Imekamilika.", "tr": "Tamamlandı.",
    },
    "blocked": {
        "en": "I didn't do that: {why}", "es": "No lo hice: {why}", "fr": "Je ne l'ai pas fait : {why}",
        "de": "Das habe ich nicht getan: {why}", "pt": "Não fiz isso: {why}", "it": "Non l'ho fatto: {why}",
        "hi": "मैंने यह नहीं किया: {why}", "te": "నేను అది చేయలేదు: {why}", "ta": "நான் அதைச் செய்யவில்லை: {why}",
        "ar": "لم أفعل ذلك: {why}", "zh": "我没有执行：{why}", "ja": "実行しませんでした：{why}", "ko": "실행하지 않았습니다: {why}",
        "ru": "Я этого не сделал: {why}", "id": "Saya tidak melakukannya: {why}", "sw": "Sikufanya hivyo: {why}",
        "tr": "Bunu yapmadım: {why}",
    },
    "remembered": {
        "en": "Got it, I'll remember that.", "es": "Entendido, lo recordaré.", "fr": "Compris, je m'en souviendrai.",
        "de": "Verstanden, ich merke es mir.", "pt": "Entendido, vou lembrar.", "it": "Capito, lo ricorderò.",
        "hi": "समझ गया, मैं यह याद रखूँगा।", "te": "సరే, నేను గుర్తుంచుకుంటాను.", "ta": "சரி, நினைவில் வைத்துக்கொள்கிறேன்.",
        "ar": "حسنًا، سأتذكر ذلك.", "zh": "好的，我会记住。", "ja": "了解、覚えておきます。", "ko": "알겠습니다, 기억할게요.",
        "ru": "Понял, запомню.", "id": "Baik, akan saya ingat.", "sw": "Sawa, nitakumbuka.", "tr": "Tamam, hatırlayacağım.",
    },
}


def phrase(key: str, lang: str, **kw) -> str:
    table = PHRASES[key]
    return table.get(lang, table["en"]).format(**kw)
