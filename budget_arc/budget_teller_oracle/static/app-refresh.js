(function () {
  const VERSION_KEY = "budgetArc:dataVersion";
  const PUBLISHED_KEY = "budgetArc:publishedDataVersion";
  const PENDING_KEY = "budgetArc:pendingRefreshVersion";
  const CHANNEL_NAME = "budgetArc:dataChanged";
  const refreshableEndpoints = new Set([
    "budget.dashboard",
    "budget.net_worth",
    "budget.transactions",
    "budget.budgets",
    "budget.accounts"
  ]);
  const endpoint = document.body.dataset.budgetEndpoint || "";
  const serverVersion = document.body.dataset.budgetDataVersion || "";
  const channel = "BroadcastChannel" in window ? new BroadcastChannel(CHANNEL_NAME) : null;
  let reloading = false;

  function storageGet(key) {
    try {
      return window.localStorage.getItem(key) || "";
    } catch (error) {
      return sessionGet(key);
    }
  }

  function storageSet(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (error) {
      return;
    }
  }

  function sessionGet(key) {
    try {
      return window.sessionStorage.getItem(key) || "";
    } catch (error) {
      return "";
    }
  }

  function sessionSet(key, value) {
    try {
      window.sessionStorage.setItem(key, value);
    } catch (error) {
      return;
    }
  }

  function sessionRemove(key) {
    try {
      window.sessionStorage.removeItem(key);
    } catch (error) {
      return;
    }
  }

  function isRefreshablePage() {
    return refreshableEndpoints.has(endpoint);
  }

  function reloadFresh() {
    if (!isRefreshablePage() || reloading) {
      return;
    }
    reloading = true;
    window.location.reload();
  }

  function handleChangedVersion(version) {
    if (!version) {
      return;
    }
    sessionSet(PUBLISHED_KEY, version);
    if (document.visibilityState === "visible") {
      reloadFresh();
    } else {
      sessionSet(PENDING_KEY, version);
    }
  }

  function publish(version) {
    if (!version) {
      return;
    }
    sessionSet(PUBLISHED_KEY, version);
    storageSet(PUBLISHED_KEY, version);
    storageSet(VERSION_KEY, version);
    if (channel) {
      channel.postMessage({ version });
    }
  }

  window.BudgetArcDataRefresh = { publish };

  window.addEventListener("storage", function (event) {
    if (event.key === VERSION_KEY) {
      handleChangedVersion(event.newValue || "");
    }
  });

  if (channel) {
    channel.addEventListener("message", function (event) {
      handleChangedVersion((event.data && event.data.version) || "");
    });
  }

  window.addEventListener("pageshow", function (event) {
    if (event.persisted) {
      reloadFresh();
      return;
    }
    if (sessionGet(PENDING_KEY)) {
      sessionRemove(PENDING_KEY);
      reloadFresh();
    }
  });

  window.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible" && sessionGet(PENDING_KEY)) {
      sessionRemove(PENDING_KEY);
      reloadFresh();
    }
  });

  window.addEventListener("focus", function () {
    if (sessionGet(PENDING_KEY)) {
      sessionRemove(PENDING_KEY);
      reloadFresh();
    }
  });

  if (serverVersion && storageGet(PUBLISHED_KEY) !== serverVersion) {
    publish(serverVersion);
  }
})();
