(async function () {
  const status = document.getElementById("connect-status");
  const button = document.getElementById("connect");
  const institutionSearch = document.getElementById("institution-search");
  const institutionSelect = document.getElementById("institution-select");
  const institutionCustom = document.getElementById("institution-custom");
  const institutionStatus = document.getElementById("institution-status");
  let tellerConnect = null;
  let configuredInstitutionId = null;
  let setupRequestId = 0;
  let institutionSearchTimer = null;

  function show(payload) {
    status.textContent = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
  }

  function showInstitutionStatus(message) {
    if (institutionStatus) {
      institutionStatus.textContent = message;
    }
  }

  function selectedInstitutionId() {
    const custom = institutionCustom ? institutionCustom.value.trim() : "";
    if (custom) {
      return custom;
    }
    return institutionSelect ? institutionSelect.value : "";
  }

  function addInstitutionOption(id, label, products) {
    const option = document.createElement("option");
    option.value = id;
    option.textContent = products && products.length ? `${label} (${id})` : label;
    institutionSelect.appendChild(option);
  }

  function setInstitutionOptions(institutions, defaultInstitution) {
    if (!institutionSelect) {
      return;
    }

    const current = institutionSelect.value;
    institutionSelect.replaceChildren();
    addInstitutionOption("", "Teller institution picker", []);

    const seen = new Set([""]);
    if (defaultInstitution && defaultInstitution.id) {
      addInstitutionOption(
        defaultInstitution.id,
        `Configured default: ${defaultInstitution.name || defaultInstitution.id}`,
        defaultInstitution.products
      );
      seen.add(defaultInstitution.id);
    }

    for (const institution of institutions) {
      if (!institution.id || seen.has(institution.id)) {
        continue;
      }
      addInstitutionOption(institution.id, institution.name || institution.id, institution.products);
      seen.add(institution.id);
    }

    if (seen.has(current)) {
      institutionSelect.value = current;
    }
    return institutionSelect.value !== current;
  }

  async function loadInstitutions(query) {
    if (!institutionSelect) {
      return;
    }

    const cleanQuery = query.trim();
    if (cleanQuery && cleanQuery.length < 2) {
      showInstitutionStatus("Type at least 2 characters to search Teller institutions.");
      return;
    }

    const params = new URLSearchParams({ limit: "40" });
    if (cleanQuery) {
      params.set("q", cleanQuery);
    }
    showInstitutionStatus(cleanQuery ? "Searching Teller institutions..." : "Loading configured institution...");
    const response = await fetch(`./api/institutions?${params.toString()}`, { cache: "no-store" });
    const payload = await response.json();
    if (!payload.ok) {
      showInstitutionStatus(`Institution lookup failed: ${payload.message || payload.error}`);
      return;
    }

    const selectionChanged = setInstitutionOptions(payload.institutions || [], payload.defaultInstitution || null);
    if (selectionChanged) {
      refreshForInstitutionChange();
    }
    if (!cleanQuery) {
      showInstitutionStatus("Leave blank to use Teller's own institution picker.");
    } else if ((payload.institutions || []).length) {
      showInstitutionStatus(`Found ${(payload.institutions || []).length} matching Teller institutions.`);
    } else {
      showInstitutionStatus("No matching Teller institutions found. Try a broader search or use the Teller picker.");
    }
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
      const setupOptions = {
        applicationId: config.applicationId,
        environment: config.environment,
        products: config.products,
        selectAccount: "multiple",
        nonce: config.nonce,
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
      };
      if (config.institutionId) {
        setupOptions.institution = config.institutionId;
      }
      tellerConnect = TellerConnect.setup(setupOptions);

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
    await loadInstitutions("");

    button.addEventListener("click", function () {
      if (!tellerConnect) {
        show("Teller Connect is not ready yet. Refresh the page and try again.");
        return;
      }
      show("Opening Teller Connect...");
      tellerConnect.open();
    });

    if (institutionSelect) {
      institutionSelect.addEventListener("change", function () {
        if (institutionSelect.value && institutionCustom) {
          institutionCustom.value = "";
        }
        refreshForInstitutionChange();
      });
    }
    if (institutionSearch) {
      institutionSearch.addEventListener("input", function () {
        window.clearTimeout(institutionSearchTimer);
        institutionSearchTimer = window.setTimeout(function () {
          loadInstitutions(institutionSearch.value).catch(function (error) {
            showInstitutionStatus("Institution lookup failed: " + error.message);
          });
        }, 300);
      });
    }
    if (institutionCustom) {
      institutionCustom.addEventListener("change", refreshForInstitutionChange);
    }
  } catch (error) {
    show("Setup error: " + error.message);
    button.disabled = true;
  }
})();
