class ChatWidget {
  constructor(config) {
    this._config = {
      apiHost: config.apiHost,
      apiKey: config.apiKey,
      primaryColor: config.primaryColor || "#3B81F6",
      welcomeMessage: config.welcomeMessage || "Привіт! Чим можу допомогти?",
      placeholder: config.placeholder || "Введіть повідомлення...",
      title: config.title || "Помічник",
      position: config.position || "bottom-right",
      streaming: config.streaming !== false,
    };

    this._isOpen = false;
    this._hasOpened = false;
    this._typingIndicator = null;

    this._initDOM();
  }

  async _initDOM() {
    const host = document.createElement("div");
    host.id = "chat-widget-host";
    document.body.appendChild(host);

    this._shadow = host.attachShadow({ mode: "open" });

    // Завантажуємо CSS (в prod можна інлайнити)
    const styleLink = document.createElement("link");
    styleLink.rel = "stylesheet";
    styleLink.href = new URL(
      "chat-widget.css",
      document.currentScript
        ? document.currentScript.src
        : window.location.href,
    ).href;
    this._shadow.appendChild(styleLink);

    // Встановлюємо кастомний колір
    const styleOverride = document.createElement("style");
    styleOverride.textContent = `:host { --bb-primary: ${this._config.primaryColor}; }`;
    this._shadow.appendChild(styleOverride);

    this._renderUI();
    this._attachEvents();
  }

  _renderUI() {
    const wrapper = document.createElement("div");

    const posStyle =
      this._config.position === "bottom-left" ? "left: 24px; right: auto;" : "";

    wrapper.innerHTML = `
            <div class="bubble-button" style="${posStyle}">
                <svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zM12 18c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm1-6h-2v-4h2v4z"/></svg>
            </div>
            <div class="chat-window" style="${posStyle}">
                <div class="chat-header">
                    <span>${this._config.title}</span>
                    <span class="chat-close">&times;</span>
                </div>
                <div class="messages-container"></div>
                <div class="input-row">
                    <input type="text" placeholder="${this._config.placeholder}" />
                    <button>Send</button>
                </div>
            </div>
        `;
    this._shadow.appendChild(wrapper);

    this._elements = {
      bubble: this._shadow.querySelector(".bubble-button"),
      window: this._shadow.querySelector(".chat-window"),
      closeBtn: this._shadow.querySelector(".chat-close"),
      messages: this._shadow.querySelector(".messages-container"),
      input: this._shadow.querySelector("input"),
      sendBtn: this._shadow.querySelector("button"),
    };
  }

  _attachEvents() {
    this._elements.bubble.addEventListener("click", () => this.toggleWindow());
    this._elements.closeBtn.addEventListener("click", () =>
      this.toggleWindow(),
    );

    this._elements.sendBtn.addEventListener("click", () => this._handleSend());
    this._elements.input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this._handleSend();
      }
    });
  }

  toggleWindow() {
    this._isOpen = !this._isOpen;
    if (this._isOpen) {
      this._elements.window.classList.add("open");
      this._elements.input.focus();

      if (!this._hasOpened) {
        this._appendMessage("bot", this._config.welcomeMessage);
        this._hasOpened = true;
      }
    } else {
      this._elements.window.classList.remove("open");
    }
  }

  _appendMessage(role, text) {
    const msg = document.createElement("div");
    msg.className = `message ${role}`;
    msg.textContent = text;
    this._elements.messages.appendChild(msg);
    this._elements.messages.scrollTop = this._elements.messages.scrollHeight;
    return msg;
  }

  _showTypingIndicator() {
    this._typingIndicator = document.createElement("div");
    this._typingIndicator.className = "message bot typing-indicator";
    this._typingIndicator.innerHTML = "<span></span><span></span><span></span>";
    this._elements.messages.appendChild(this._typingIndicator);
    this._elements.messages.scrollTop = this._elements.messages.scrollHeight;
  }

  _removeTypingIndicator() {
    if (this._typingIndicator) {
      this._typingIndicator.remove();
      this._typingIndicator = null;
    }
  }

  async _handleSend() {
    const text = this._elements.input.value.trim();
    if (!text) return;

    this._elements.input.value = "";
    this._elements.sendBtn.disabled = true;
    this._elements.input.disabled = true;

    this._appendMessage("user", text);

    try {
      if (this._config.streaming) {
        await this._sendMessageStream(text);
      } else {
        this._showTypingIndicator();
        await this._sendMessageSync(text);
      }
    } catch (error) {
      this._removeTypingIndicator();
      console.error("Chat Error:", error);
      this._appendMessage(
        "system",
        error.message || "Сервіс тимчасово недоступний. Спробуйте пізніше.",
      );
    } finally {
      this._elements.sendBtn.disabled = false;
      this._elements.input.disabled = false;
      this._elements.input.focus();
    }
  }

  async _sendMessageStream(text) {
    const botBubble = this._appendMessage("bot", "");
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);

    try {
      const response = await fetch(`${this._config.apiHost}/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": this._config.apiKey,
          Accept: "text/event-stream",
        },
        body: JSON.stringify({ question: text }),
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        if (response.status === 401 || response.status === 403)
          throw new Error("Помилка автентифікації.");
        if (response.status === 429)
          throw new Error("Забагато запитів. Зачекайте хвилину.");
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop(); // Залишаємо неповний чанк у буфері

        for (const chunk of chunks) {
          if (chunk.startsWith("data: ")) {
            const data = chunk.slice(6);
            if (data === "[DONE]") return;
            if (data.startsWith("[ERROR]")) throw new Error(data.slice(7));

            botBubble.textContent += data;
            this._elements.messages.scrollTop =
              this._elements.messages.scrollHeight;
          }
        }
      }
    } catch (error) {
      if (error.name === "AbortError") {
        throw new Error("Запит зайняв забагато часу. Спробуйте ще раз.");
      }
      if (botBubble.textContent.length > 0) {
        botBubble.textContent += "\n(Відповідь обірвана)";
      } else {
        throw error;
      }
    }
  }

  async _sendMessageSync(text) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);

    try {
      const response = await fetch(`${this._config.apiHost}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": this._config.apiKey,
        },
        body: JSON.stringify({ question: text }),
        signal: controller.signal,
      });

      clearTimeout(timeoutId);
      this._removeTypingIndicator();

      if (!response.ok) {
        if (response.status === 401 || response.status === 403)
          throw new Error("Помилка автентифікації.");
        if (response.status === 429)
          throw new Error("Забагато запитів. Зачекайте хвилину.");
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      this._appendMessage("bot", data.answer);
    } catch (error) {
      if (error.name === "AbortError")
        throw new Error("Запит зайняв забагато часу. Спробуйте ще раз.");
      throw error;
    }
  }
}

// Експортуємо клас для використання в embed.js
window.ChatWidget = ChatWidget;
