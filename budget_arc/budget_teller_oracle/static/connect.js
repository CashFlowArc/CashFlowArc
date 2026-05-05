(async function () {
  const status = document.getElementById("connect-status");
  const button = document.getElementById("connect");
  const institutionSelect = document.getElementById("institution-select");
  const institutionCustom = document.getElementById("institution-custom");

  function show(payload) {
    status.textContent = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
  }

  function selectedInstitutionId() {
    const custom = institutionCustom ? institutionCustom.value.trim() : "";
    if (custom) {
      return custom;
    }
    return institutionSelect ? institutionSelect.value : "";
  }

  async function loadConfig() {
    const params = new URLSearchParams();
    const institutionId = selectedInstitutionId();
    if (institutionId) {
      params.set("institution_id", institutionId);
    }
    const url = params.toString() ? `./api/config?${params.toString()}` : "./api/config";
    const configResponse = await fetch(url, { cache: "no-store" });
    const config = await configResponse.json();
    if (!config.ok) {
      show(config);
      button.disabled = true;
      return null;
    }
    return config;
  }

  try {
    const initialConfig = await loadConfig();
    if (!initialConfig) {
      return;
    }
    show(`Ready. Environment: ${initialConfig.environment}; institution: ${initialConfig.institutionId || "picker"}`);

    button.addEventListener("click", async function () {
      button.disabled = true;
      const config = await loadConfig();
      if (!config) {
        button.disabled = false;
        return;
      }
      show(`Ready. Environment: ${config.environment}; institution: ${config.institutionId || "picker"}`);
      const tellerConnect = TellerConnect.setup({
        applicationId: config.applicationId,
        environment: config.environment,
        products: config.products,
        selectAccount: "multiple",
        nonce: config.nonce,
        institution: config.institutionId || undefined,
        onSuccess: async function (enrollment) {
          show("Enrollment received. Verifying signature, encrypting token, and syncing Oracle...");
          const response = await fetch("./api/teller/enrollment", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRF-Token": config.csrfToken
            },
            body: JSON.stringify({ nonce: config.nonce, enrollment })
          });
          const payload = await response.json();
          show(payload);
        },
        onExit: function () {
          show("Teller Connect closed before enrollment completed.");
        },
        onFailure: function (failure) {
          show(failure);
        }
      });

      button.disabled = false;
      tellerConnect.open();
    });
  } catch (error) {
    show("Setup error: " + error.message);
    button.disabled = true;
  }
})();
