(async function () {
  const status = document.getElementById("connect-status");
  const button = document.getElementById("connect");
  const institutionSearch = document.getElementById("institution-search");
  const institutionOptions = document.getElementById("institution-options");
  const institutionIdInput = document.getElementById("institution-id");
  const institutionStatus = document.getElementById("institution-status");
  let tellerConnect = null;
  let configuredInstitutionId = null;
  let setupRequestId = 0;
  let institutionSearchTimer = null;
  let institutionOptionsByLabel = new Map();
  let selectedInstitutionLabel = "";
  const pageParams = new URLSearchParams(window.location.search);
  const repairConnectionId = pageParams.get("connection_id") || "";

  function show(payload) {
    status.textContent = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
  }

  function showInstitutionStatus(message) {
    if (institutionStatus) {
      institutionStatus.textContent = message;
    }
  }

  function selectedInstitutionId() {
    return institutionIdInput ? institutionIdInput.value.trim() : "";
  }

  function institutionLabel(institution) {
    return `${institution.name || institution.id} (${institution.id})`;
  }

  function addInstitutionOption(institution) {
    const option = document.createElement("option");
    const label = institutionLabel(institution);
    option.value = label;
    institutionOptions.appendChild(option);
    institutionOptionsByLabel.set(label, institution.id);
  }

  function updateSelectedInstitutionFromInput() {
    if (!institutionSearch || !institutionIdInput) {
      return false;
    }

    const previousId = institutionIdInput.value;
    const typedValue = institutionSearch.value.trim();
    const selectedId = institutionOptionsByLabel.get(typedValue) || "";
    institutionIdInput.value = selectedId;
    selectedInstitutionLabel = selectedId ? typedValue : "";

    if (selectedId) {
      showInstitutionStatus(`Selected ${typedValue}.`);
    } else if (!typedValue) {
      showInstitutionStatus("Leave blank to use Teller's own institution picker.");
    } else {
      showInstitutionStatus("Keep typing to narrow the list, then select a suggestion.");
    }

    return previousId !== selectedId;
  }

  function setInstitutionOptions(institutions) {
    if (!institutionOptions) {
      return false;
    }

    institutionOptions.replaceChildren();
    institutionOptionsByLabel = new Map();

    for (const institution of institutions) {
      if (!institution.id) {
        continue;
      }
      addInstitutionOption(institution);
    }

    return updateSelectedInstitutionFromInput();
  }

  async function loadInstitutions(query) {
    if (!institutionOptions) {
      return;
    }

    const cleanQuery = query.trim();
    if (cleanQuery && cleanQuery.length < 2) {
      setInstitutionOptions([]);
      showInstitutionStatus("Type at least 2 characters to search Teller institutions.");
      return;
    }

    const params = new URLSearchParams({ limit: "40" });
    if (cleanQuery) {
      params.set("q", cleanQuery);
    }
    showInstitutionStatus(cleanQuery ? "Searching Teller institutions..." : "Leave blank to use Teller's own institution picker.");
    const response = await fetch(`./api/institutions?${params.toString()}`, { cache: "no-store" });
    const payload = await response.json();
    if (!payload.ok) {
      showInstitutionStatus(`Institution lookup failed: ${payload.message || payload.error}`);
      return;
    }

    if (selectedInstitutionId() && institutionSearch.value.trim() === selectedInstitutionLabel) {
      return;
    }

    const selectionChanged = setInstitutionOptions(payload.institutions || []);
    if (selectionChanged) {
      refreshForInstitutionChange();
    }
    if (!cleanQuery) {
      showInstitutionStatus("Leave blank to use Teller's own institution picker.");
    } else if ((payload.institutions || []).length) {
      if (!selectedInstitutionId()) {
        showInstitutionStatus(`Found ${(payload.institutions || []).length} matching Teller institutions. Select one from the dropdown.`);
      }
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
    if (repairConnectionId) {
      params.set("connection_id", repairConnectionId);
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
          if (payload.ok) {
            const dataVersion = payload.dataVersion || String(Date.now());
            if (window.BudgetArcDataRefresh) {
              window.BudgetArcDataRefresh.publish(dataVersion);
            }
            show("Sync complete. Loading updated accounts...");
            const accountsUrl = new URL("./accounts", window.location.href);
            accountsUrl.searchParams.set("data_version", dataVersion);
            window.location.assign(accountsUrl.toString());
          }
        },
        onExit: function () {
          show("Teller Connect closed before enrollment completed.");
        },
        onFailure: function (failure) {
          show(failure);
        }
      };
      if (config.enrollmentId) {
        setupOptions.enrollmentId = config.enrollmentId;
      } else {
        setupOptions.selectAccount = "multiple";
      }
      if (config.institutionId && !config.enrollmentId) {
        setupOptions.institution = config.institutionId;
      }
      tellerConnect = TellerConnect.setup(setupOptions);

      button.disabled = false;
      configuredInstitutionId = config.institutionId || "";
      if (config.mode === "repair") {
        show(`Ready to repair ${config.institutionName || "Teller enrollment"}. Environment: ${config.environment}`);
      } else {
        show(`Ready. Environment: ${config.environment}; institution: ${configuredInstitutionId || "Teller picker"}`);
      }
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

    if (institutionSearch) {
      institutionSearch.addEventListener("input", function () {
        if (updateSelectedInstitutionFromInput()) {
          refreshForInstitutionChange();
        }
        window.clearTimeout(institutionSearchTimer);
        if (selectedInstitutionId()) {
          return;
        }
        institutionSearchTimer = window.setTimeout(function () {
          loadInstitutions(institutionSearch.value).catch(function (error) {
            showInstitutionStatus("Institution lookup failed: " + error.message);
          });
        }, 300);
      });
    }
  } catch (error) {
    show("Setup error: " + error.message);
    button.disabled = true;
  }
})();
