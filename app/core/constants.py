# app/core/constants.py

# --- UI Messages / Responses ---
MSG_GUARDRAIL_FAILED = "Вибачте, виникла технічна затримка при обробці запиту. Будь ласка, переформулюйте питання стосовно товарів."
MSG_LEAD_SUCCESS = (
    "Ваш запит отримано. Менеджер з вами зв'яжеться. Також можете написати нам в Інстаграм..."
)
MSG_LEAD_FAILED = "На жаль, виникла технічна помилка при передачі вашого запиту менеджеру. Будь ласка, напишіть нам напряму в Telegram або Viber, щоб ми могли вам допомогти."
MSG_STREAM_FAILED = (
    "\n\nСервіс тимчасово недоступний. Спробуйте пізніше або зв'яжіться з менеджером."
)
MSG_SYNC_CHAT_FAILED = "Вибачте, виникла технічна затримка при обробці запиту. Спробуйте переформулювати питання або зверніться до нашого менеджера напряму."
MSG_STREAM_CHAT_FAILED = "Технічна затримка на лінії. Оновіть сторінку або напишіть нам пізніше."

# --- Link Texts ---
LINK_CHECKOUT = "Оформити замовлення"
LINK_TELEGRAM = "✈️ Написати в Telegram"
LINK_VIBER = "📞 Написати у Viber"

# --- Statuses ---
STATUS_INSTOCK = "В наявності"
STATUS_OUT_OF_STOCK = "Під замовлення"

# --- Search / Facts Headers ---
SEARCH_FOUND_HEADER = "Знайдено у нашому магазині:"


# --- Telegram Alert Templates ---
TELEGRAM_LEAD_TEMPLATE = (
    "🚨 <b>Новий лід від бота!</b>\n\n"
    "👤 <b>Ім'я:</b> {name}\n"
    "📞 <b>Телефон:</b> <code>{phone}</code>\n"
    "💬 <b>Контекст:</b> {context}"
)
DEFAULT_LEAD_CONTEXT = "Запит з чату"
DEFAULT_MISSING_VALUE = "Не вказано"
ALERT_MARGIN_ISSUE = (
    "🚨 <b>Невідповідність маржі!</b>\n"
    "📦 Товар: {safe_product_name}\n"
    "🌐 Наша ціна: {woo_price} грн\n"
    "📦 Постачальник: {supplier_price} грн\n"
    "📉 Маржа: {diff_woo} грн (має бути рівно {margin_threshold} грн)\n"
    "⚠️ Маржа вийшла за межі жорсткого коридору."
)
ALERT_SCRAPER_FAILED = (
    "⚠️ <b>Помилка Скрапера!</b>\n📦 Товар: {safe_product_name}\nНе вдалося отримати ціну."
)

REGEX_PRODUCT_NAME_HISTORY = r"['\"«»]([^'\"«»]+)['\"«»]"

# --- Intent Names ---
INTENT_PRODUCT = "product"
INTENT_SEARCH = "search"
INTENT_CHECKOUT = "checkout"
INTENT_HYBRID = "hybrid"
INTENT_FAQ = "faq"
INTENT_GENERAL = "general"
INTENT_CONTACT = "contact"

# --- Regex Patterns ---
REGEX_PHONE = r"(?:\+380|380|0)\d{9}"
REGEX_CLEAN_QUERY = r"[\s\-\(\)]"
