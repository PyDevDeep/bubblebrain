(function () {
  // Шукаємо поточний тег script для парсингу data-атрибутів
  const currentScript = document.currentScript;

  // Пріоритет: window.ChatWidgetConfig > data-атрибути
  const config = window.ChatWidgetConfig || {};

  if (currentScript) {
    if (!config.apiHost && currentScript.dataset.apiHost)
      config.apiHost = currentScript.dataset.apiHost;
    if (!config.apiKey && currentScript.dataset.apiKey)
      config.apiKey = currentScript.dataset.apiKey;
    if (!config.primaryColor && currentScript.dataset.primaryColor)
      config.primaryColor = currentScript.dataset.primaryColor;
  }

  if (!config.apiHost || !config.apiKey) {
    console.error(
      "BubbleBrain Widget: Missing required configuration (apiHost, apiKey)",
    );
    return;
  }

  // Додаємо скрипт з логікою, якщо він ще не завантажений
  if (typeof window.ChatWidget === "undefined") {
    const scriptUrl = new URL(
      "chat-widget.js",
      currentScript ? currentScript.src : window.location.href,
    ).href;
    const script = document.createElement("script");
    script.src = scriptUrl;
    script.onload = () => {
      window.ChatWidgetInstance = new window.ChatWidget(config);
    };
    document.head.appendChild(script);
  } else {
    window.ChatWidgetInstance = new window.ChatWidget(config);
  }
})();
