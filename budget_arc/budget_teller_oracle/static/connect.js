(async function () {
  const status = document.getElementById("connect-status");
  const button = document.getElementById("connect");
  const institutionSelect = document.getElementById("institution-select");
  const institutionCustom = document.getElementById("institution-custom");
  let tellerConnect = null;
  let configuredInstitutionId = null;
  let setupRequestId = 0;

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

  async function configureTellerConnect() {
    const requestId = ++setupRequestId;
    tellerConnect = null;
    button.disabled = true;
    show("Preparing Teller Connect...");

    const config = await loadConfig();
    if (!config || requestId !== setupRequestId) {
      return;
    }

    if (!window.TellerConnect || typeof TellerConnect.setup !== "function") {
      show("Teller Connect did not load. Check that cdn.teller.io is reachable from this browser/network.");
      return;
    }

    try {
      tellerConnect = TellerConnect.setup({
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
      configuredInstitutionId = config.institutionId || "";
      show(`Ready. Environment: ${config.environment}; institution: ${configuredInstitutionId || "Teller picker"}`);
    } catch (error) {
      show("Teller setup error: " + error.message);
    }
  }

  function refreshForInstitutionChange() {
    const institutionId = selectedInstitutionId();
    if (institutionId === configuredInstitutionId) {
      return;
    }
    configureTellerConnect().catch(function (error) {
      show("Setup error: " + error.message);
      button.disabled = true;
    });
  }

  try {
    await configureTellerConnect();

    button.addEventListener("click", function () {
      if (!tellerConnect) {
        show("Teller Connect is not ready yet. Refresh the page and try again.");
        return;
      }
      show("Opening Teller Connect...");
      tellerConnect.open();
    });

    if (institutionSelect) {
      institutionSelect.addEventListener("change", refreshForInstitutionChange);
    }
    if (institutionCustom) {
      institutionCustom.addEventListener("change", refreshForInstitutionChange);
    }
  } catch (error) {
    show("Setup error: " + error.message);
    button.disabled = true;
  }
})();
