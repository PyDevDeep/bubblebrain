# app/core/constants.py
import re

# --- UI Messages / Responses ---
MSG_GUARDRAIL_FAILED = "Вибачте, виникла технічна затримка при обробці запиту. Будь ласка, переформулюйте питання стосовно товарів."
MSG_LEAD_SUCCESS = "Ваш запит отримано. Менеджер з вами зв'яжеться."
MSG_LEAD_FAILED = "На жаль, виникла технічна помилка при передачі вашого запиту менеджеру. Будь ласка, напишіть нам напряму в Telegram або Viber, щоб ми могли вам допомогти."
MSG_STREAM_FAILED = (
    "\n\nСервіс тимчасово недоступний. Спробуйте пізніше або зв'яжіться з менеджером."
)
MSG_SYNC_CHAT_FAILED = "Вибачте, виникла технічна затримка при обробці запиту. Спробуйте переформулювати питання або зверніться до нашого менеджера напряму."
MSG_STREAM_CHAT_FAILED = "Технічна затримка на лінії. Оновіть сторінку або напишіть нам пізніше."
MSG_SYSTEM_ERROR = "Виникла системна помилка при обробці запиту. Спробуйте пізніше."

# --- Link Texts ---
LINK_CHECKOUT = "Оформити замовлення"
LINK_TELEGRAM = "✈️ Написати в Telegram"
LINK_VIBER = "📞 Написати у Viber"

# --- Statuses ---
STATUS_INSTOCK = "В наявності"
STATUS_OUT_OF_STOCK = "Під замовлення"

# --- Supplier Availability Mappings ---
SUPP_AVAIL_IN_STOCK = "В наявності (доставка 3-5 днів)"
SUPP_AVAIL_ON_DEMAND = "Під замовлення (14-21 днів)"
SUPP_AVAIL_OUT_OF_STOCK = "Немає в наявності"
SUPP_AVAIL_CLARIFY = "Уточнюється у постачальника"

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


# --- Intent Names ---
INTENT_PRODUCT = "product"
INTENT_SEARCH = "search"
INTENT_CHECKOUT = "checkout"
INTENT_HYBRID = "hybrid"
INTENT_FAQ = "faq"
INTENT_GENERAL = "general"
INTENT_CONTACT = "contact"
INTENT_ORDER_STATUS = "order_status"

# --- Regex Patterns ---
REGEX_PHONE = re.compile(r"(?:\+380|380|0)\d{9}")
REGEX_CLEAN_QUERY = re.compile(r"[\s\-\(\)]")

# --- Common Settings ---
MAX_PAYLOAD_SIZE = 2048

# --- Scraper Settings ---
SCRAPER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
SCRAPER_TIMEOUT_DEFAULT = 7.0
SCRAPER_TIMEOUT_CONNECT = 3.0

# --- Error Messages ---
ERR_INVALID_PHONE = "Невірний формат номеру. Очікується формат +380XXXXXXXXX або 0XXXXXXXXX"
ERR_INVALID_PHONE_SHORT = "Некоректний формат телефону"

# --- Button Texts ---
BTN_SUCCESS = "✅ Успіх (Продано)"
BTN_DECLINE = "❌ Відмова"
BTN_IN_PROGRESS = "⏳ В процесі"
BTN_SUCCESS_SHORT = "✅ Успіх"
BTN_PRODUCT_LINK = "🔗 Товар на сайті"
BTN_CHANGE_PRICE = "📦 Змінити ціну (WooCommerce)"
BTN_STATUS = "Статус: {status_text}"
BTN_VIEW_PRODUCT = "View {product_name}"

# --- Alert Messages & Templates ---
ALERT_HOT_LEAD = (
    "🛒 <b>Нове ЗАМОВЛЕННЯ з Бота (Hot Lead) {lead_id}</b>\n"
    "📅 <b>Дата:</b> {now_str}\n\n"
    "👨 <b>Ім'я:</b> {name} {surname}\n"
    "📞 <b>Телефон:</b> <code>{phone}</code>\n"
    "📱 <b>Спосіб зв'язку:</b> {method}\n"
    "🚛 <b>Адреса доставки:</b> {address}\n\n"
    "🥷 <b>IP:</b> {ip}\n\n"
    "#HOT_LEAD #ID{lead_id}"
)
ALERT_BOT_LEAD = (
    "🔥 <b>НОВИЙ ЛІД З БОТА {lead_id}</b>\n"
    "📅 <b>Дата:</b> {now_str}\n\n"
    "👨 <b>Ім'я:</b> {name}\n"
    "📞 <b>Телефон:</b> <code>{phone}</code>\n"
    "📱 <b>Спосіб зв'язку:</b> {method}\n\n"
    "🥷 <b>IP:</b> {ip}\n\n"
    "#БОТ_ЛІД #ID{lead_id}"
)
ALERT_PRICE_CLARIFICATION = (
    "⚠️ <b>УТОЧНЕННЯ ЦІНИ (ЛІД)</b> <b>[ID: {lead_id}]</b>\n\n"
    "👤 <b>Ім'я:</b> Клієнт з чату\n"
    "📞 <b>Контакт:</b> <code>{phone}</code>\n"
    "📱 <b>Спосіб:</b> chat\n"
    "💬 <b>Запит:</b> '{question}'\n\n"
    "#PRICE_LEAD #ID{lead_id}"
)
ALERT_CHAT_LEAD = (
    "🔥 <b>НОВИЙ ЛІД З БОТА</b> <b>[ID: {lead_id}]</b>\n\n"
    "👤 <b>Ім'я:</b> Клієнт з чату\n"
    "📞 <b>Контакт:</b> <code>{phone}</code>\n"
    "📱 <b>Спосіб:</b> chat\n"
    "💬 <b>Запит:</b> '{question}'\n\n"
    "#BOT_LEAD #ID{lead_id}"
)
ALERT_WOO_ORDER = (
    "🔥 <b>#БОТ_ПРОДАЖ</b> [Замовлення #{order_id}]\n\n"
    "👤 <b>Клієнт:</b> {first_name} {last_name}\n"
    "📞 <b>Телефон:</b> <code>{phone}</code>\n"
    "💰 <b>Сума:</b> {total} {currency}\n"
    "📦 <b>Товари:</b>\n{items_str}\n\n"
    "#ID{session_id}"
)
CHAT_HISTORY_CAPTION = "📜 Історія переписки ({session_id})"
CHAT_HISTORY_MARKER = "[CHAT HISTORY]"
CHAT_QUERY_MARKER = "[CURRENT CLIENT QUERY]"

# --- Statistics Template ---
STATISTICS_TEMPLATE = [
    "📊 <b>Щоденна Статистика Бота ({date_str})</b>",
    "",
    "👤 <b>Унікальних користувачів:</b> {unique_users}",
    "🪙 <b>Використані токени LLM:</b> {tokens}",
    "⏱ <b>Середнє латенсі LLM:</b> {latency_avg:.2f} сек",
    "⚠️ <b>Збоїв (помилок):</b> {errors}",
    "🏷 <b>Алерти цін:</b> {price_alerts}",
    "",
    "📩 <b>Звичайних лідів:</b> {leads_contact}",
    "🔥 <b>Хот лідів:</b> {leads_hot}",
    "✅ <b>Конверсій через бота:</b> {conversions}",
    "",
    "🛍 <b>WooCommerce Замовлення (за 24 год):</b>",
    "   Всього: {woo_total}",
    "   В обробці: {woo_processing}",
    "   На утриманні: {woo_on_hold}",
    "   Виконано (Оплачено): {woo_paid}",
]

# --- Guardrails / Prompt Injection ---
INJECTION_PATTERNS = [
    # English patterns
    r"(?is)\bignore\b.{0,20}\b(?:previous|all)?\s*instructions\b",
    r"(?is)\bforget\b.{0,20}\b(?:previous|all)?\s*instructions\b",
    r"(?is)\bsystem\s*prompt\b",
    r"(?is)\bdisregard\b.{0,20}\b(?:previous|all)?\s*instructions\b",
    r"(?is)\byou\s*are\s*now\b",
    r"(?is)\bact\s*as\b",
    r"(?is)\bfrom\s*now\s*on\b",
    r"(?is)\bprint\b.{0,20}\b(?:instructions|prompt)\b",
    r"(?is)new\s*rules",
    r"(?is)new\s*instructions",
    # Ukrainian patterns
    r"(?is)(?:ігноруй|проігноруй|забудь|відкинь).{0,20}(?:всі|попередні)?\s*(?:інструкції|вказівки|правила)",
    r"(?is)системний\s*промпт",
    r"(?is)поводься\s*як",
    r"(?is)дій\s*як",
    r"(?is)відтепер\s*ти",
    r"(?is)нові\s*правила",
    r"(?is)нові\s*інструкції",
    r"(?is)виведи.{0,20}(?:інструкції|промпт|правила)",
    # Russian patterns
    r"(?is)(?:игнорируй|проигнорируй|забудь|отбрось).{0,20}(?:все|предыдущие)?\s*(?:инструкции|указания|правила)",
    r"(?is)системный\s*промпт",
    r"(?is)веди\s*себя\s*как",
    r"(?is)действуй\s*как",
    r"(?is)отныне\s*ты",
    r"(?is)новые\s*правила",
    r"(?is)новые\s*инструкции",
    r"(?is)выведи.{0,20}(?:инструкции|промпт|правила)",
]

# --- Intent Handler Instructions ---
INSTR_PRICE_CHANGED_ALERT = (
    "КРИТИЧНО: Нам потрібно уточнити актуальну ціну на цей товар. "
    "КАТЕГОРИЧНО ЗАБОРОНЕНО казати клієнту, що ціна змінилася, або давати посилання на чекаут. "
    "Прямо зараз попроси клієнта залишити номер телефону тут або написати нашому менеджеру в Telegram/Viber для узгодження фінальної ціни."
)
FACT_CHECKOUT_PRODUCT = (
    "Data: Product '{product_name}', актуальна та підтверджена ціна {woo_price} UAH. Conditions: {status_text}.\n"
    "CRITICAL: Товар знайдено і ціна підтверджена. Запропонуй оформити замовлення. If 'In stock' - 1-3 days. 'Under order' - 14-20 days.\n"
    "УВАГА: Бекенд вже згенерував UI-форму (кнопку) оформлення замовлення. КАТЕГОРИЧНО ЗАБОРОНЕНО питати у клієнта будь-які деталі замовлення (номер телефону, ПІБ, адресу, спосіб доставки чи оплати) безпосередньо в чаті! Просто скажи клієнту натиснути кнопку оформлення замовлення (або посилання), яка з'явилась."
)
FACT_INFO_PRODUCT = (
    "Data: Product '{product_name}', Ціна {woo_price} UAH. Conditions: {status_text}.\n"
    "CRITICAL: If 'In stock' - 1-3 days. 'Under order' - 14-20 days. DO NOT PUT LINKS IN TEXT!"
)
INSTR_SEARCH_FALLBACK = "Бекенд знайшов товари за розширеним пошуком або категорією. Якщо клієнт питав загалом (наприклад 'монітори 4к'), просто презентуй їх. ТІЛЬКИ якщо клієнт шукав КОНКРЕТНУ модель, ввічливо скажи, що її немає і запропонуй ці альтернативи."
INSTR_ORDER_ID_MISSING = "Не вдалося визначити номер замовлення. Попроси клієнта вказати точний номер замовлення (тільки цифри)."
INSTR_ORDER_NOT_FOUND = "Замовлення з номером {order_id} не знайдено. Перепроси та спитай, чи можливо клієнт помилився цифрою або номером."
INSTR_ORDER_STATUS = "Клієнт запитує про своє замовлення. Використовуй надані дані (статус, суму, товари, доставку), щоб ввічливо відповісти йому. Не вигадуй інформацію, якої немає."
INSTR_NO_PHONE_IN_CHAT = "КРИТИЧНО: Бекенд вже згенерував UI-форму/кнопку для клієнта. В тексті повідомлення категорично ЗАБОРОНЕНО просити клієнта писати номер телефону, ПІБ, способи доставки чи оплати в чат. Всі дані клієнт має ввести у форму."
INSTR_NO_PREPAYMENT = "УВАГА: Вартість товару менше 40 000 грн. ЗАБОРОНЕНО згадувати про будь-яку 'передоплату', 'аванс' або умови для сум понад 40 тис. Це заплутує клієнта."
