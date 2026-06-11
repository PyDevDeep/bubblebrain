class ChatWidget {
  constructor(config) {
    this._config = {
      apiHost: config.apiHost,
      apiKey: config.apiKey,
      colors: {
        primary: config.colors?.primary || "#4B0082",
        secondary: config.colors?.secondary || "#6E1893",
        accent: config.colors?.accent || "#FF2603",
      },
      welcomeMessage: config.welcomeMessage || "Привіт! Чим можу допомогти?",
      placeholder: config.placeholder || "Введіть повідомлення...",
      title: config.title || "Помічник",
      position: config.position || "bottom-right",
      streaming: config.streaming !== false,
    };

    this._isOpen = false;
    this._hasOpened = false;
    this._typingIndicator = null;

    // ДОДАНО: Генерація унікальної сесії для пам'яті бота
    this._sessionId = this._generateSessionId();

    this._initDOM();
  }
  // ДОДАНО: Метод генерації ID
  _generateSessionId() {
    if (typeof crypto !== "undefined" && crypto.randomUUID) {
      return crypto.randomUUID();
    }
    return (
      Math.random().toString(36).substring(2, 15) +
      Math.random().toString(36).substring(2, 15)
    );
  }
  async _initDOM() {
    const host = document.createElement("div");
    host.id = "chat-widget-host";
    document.body.appendChild(host);

    this._shadow = host.attachShadow({ mode: "open" });

    const styleLink = document.createElement("link");
    styleLink.rel = "stylesheet";
    styleLink.href = new URL(
      "chat-widget.css",
      document.currentScript
        ? document.currentScript.src
        : window.location.href,
    ).href;

    // Фікс FOUC: Чекаємо завантаження стилів
    await new Promise((resolve) => {
      styleLink.onload = resolve;
      styleLink.onerror = () => {
        console.error("BubbleBrain: Failed to load chat-widget.css");
        resolve(); // Fallback, щоб не заблокувати повністю
      };
      this._shadow.appendChild(styleLink);
    });

    // Інжекція нової палітри
    const styleOverride = document.createElement("style");
    styleOverride.textContent = `
            :host {
                --bb-primary: ${this._config.colors.primary};
                --bb-secondary: ${this._config.colors.secondary};
                --bb-accent: ${this._config.colors.accent};
            }
            .bubble-button { background: linear-gradient(135deg, var(--bb-primary), var(--bb-secondary)); }
            .chat-header { background: linear-gradient(135deg, var(--bb-primary), var(--bb-secondary)); }
            .message { white-space: pre-wrap !important; }
            .message.user { background: linear-gradient(135deg, var(--bb-primary), var(--bb-secondary)); }
            .message.system { color: var(--bb-accent); background: #ffebee; border: 1px solid var(--bb-accent); }
            .input-row input:focus { border-color: var(--bb-primary); }
            .input-row button { background: var(--bb-primary); }
        `;
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
      this._appendMessage(
        "system",
        error.message || "Сервіс тимчасово недоступний.",
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
        body: JSON.stringify({ question: text, session_id: this._sessionId }),
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        if (response.status === 401 || response.status === 403)
          throw new Error("Помилка автентифікації.");
        if (response.status === 429)
          throw new Error("Забагато запитів. Зачекайте.");
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      let pendingText = "";
      let isUpdating = false;

      // Стейт для кнопок і форм
      let currentLinks = [];
      let requiresLead = false;

      const updateDOM = () => {
        if (!isUpdating) return;
        botBubble.textContent += pendingText;
        pendingText = "";
        this._elements.messages.scrollTop =
          this._elements.messages.scrollHeight;
        isUpdating = false;
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          if (pendingText) {
            isUpdating = true;
            updateDOM();
          }
          // Рендеримо кнопки після завершення стріму
          this._renderInteractiveElements(
            botBubble,
            currentLinks,
            requiresLead,
          );
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop();

        for (const chunk of chunks) {
          if (chunk.startsWith("data: ")) {
            const data = chunk.slice(6);
            if (data === "[DONE]") {
              if (pendingText) {
                isUpdating = true;
                updateDOM();
              }
              this._renderInteractiveElements(
                botBubble,
                currentLinks,
                requiresLead,
              );
              return;
            }
            if (data.startsWith("[ERROR]")) throw new Error(data.slice(7));

            // Перехоплювач метаданих
            if (data.startsWith("[METADATA] ")) {
              try {
                const meta = JSON.parse(data.slice(11));
                currentLinks = meta.links || [];
                requiresLead = meta.requires_lead || false;
              } catch (e) {
                console.error("Failed to parse metadata", e);
              }
              continue;
            }

            try {
              if (data.trim() !== "") {
                const parsed = JSON.parse(data);
                if (parsed.token) {
                  pendingText += parsed.token;
                }
              }
            } catch (e) {
              console.error(
                "BubbleBrain Stream: Failed to parse chunk",
                e,
                data,
              );
            }

            if (!isUpdating && pendingText !== "") {
              isUpdating = true;
              requestAnimationFrame(updateDOM);
            }
          }
        }
      }
    } catch (error) {
      console.error("BubbleBrain Stream Error:", error); // ВІДСТЕЖЕННЯ РЕАЛЬНОГО ЗБОЮ
      if (error.name === "AbortError") {
        throw new Error("Timeout запиту.");
      }
      if (botBubble.textContent.length > 0) {
        botBubble.textContent += `\n(Збій потоку: ${error.message})`;
      } else {
        throw error;
      }
    }
  }

  // МЕТОД ДЛЯ РЕНДЕРУ КНОПОК - ДОДАТИ ПІСЛЯ _sendMessageStream
  _renderInteractiveElements(container, links, requiresLead) {
    if (links.length > 0) {
      const linksContainer = document.createElement("div");
      linksContainer.className = "interactive-links";
      links.forEach((link) => {
        const btn = document.createElement("a");
        btn.href = link.url;
        btn.target = "_blank";
        btn.className = "bb-link-btn";
        btn.textContent = link.text;
        linksContainer.appendChild(btn);
      });
      container.appendChild(linksContainer);
    }

    if (requiresLead) {
      const leadContainer = document.createElement("div");
      leadContainer.className = "lead-capture-box";
      leadContainer.innerHTML = `
        <div class="lead-hint">Введіть ваш номер телефону (Telegram/Viber) нижче:</div>
      `;
      container.appendChild(leadContainer);
      this._elements.input.placeholder = "+380XXXXXXXXX";
      this._elements.input.focus();
    } else {
      this._elements.input.placeholder = this._config.placeholder;
    }

    this._elements.messages.scrollTop = this._elements.messages.scrollHeight;
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
        // ДОДАНО: Передача session_id на бекенд
        body: JSON.stringify({ question: text, session_id: this._sessionId }),
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
window.ChatWidget = ChatWidget;
