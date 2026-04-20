(function () {
  const data = JSON.parse(document.getElementById("app-data").textContent);
  const collator = new Intl.Collator("ru", { sensitivity: "base" });
  const baseStylePalette = {
    marker_blue: "#1d4f91",
    marker_teal: "#147a7e",
    marker_orange: "#c76a0e",
    marker_purple: "#6a49a5",
    marker_darkred: "#8f2d2d",
    marker_magenta: "#a83f92",
    marker_black: "#25313c",
    marker_gray: "#6b7280",
    marker_pink: "#c25b7c",
    marker_lime: "#648b23",
    marker_olive: "#6d7f2e",
    marker_gold: "#b98915",
    marker_maroon: "#7b3f32",
    marker_navy: "#244f88",
    marker_darkblue: "#1f5a8b",
    marker_darkgreen: "#2d6a4f",
    marker_darkcyan: "#176c76",
    marker_darkorange: "#b85c12",
    marker_redbrown: "#8c4338",
    area_green: "#2e8b57",
    area_red: "#b43838",
    area_yellow: "#c69a18",
    area_blue: "#2c5aa0",
    area_cyan: "#177e89",
    area_indigo: "#4058a7",
    area_brown: "#8a5a2b",
    line_isogloss_major: "#8f2d2d",
    line_isogloss_minor: "#8f2d2d",
    boundary_district: "#8b95a0"
  };

  const pointsById = new Map(data.points.map((item) => [item.point_id, item]));
  const featuresById = new Map(data.features.map((item) => [item.feature_id, item]));
  const observationsByPoint = groupBy(data.observations, "point_id");
  const observationsByFeature = groupBy(data.observations, "feature_id");
  const districtPoints = groupPointsByDistrict();
  const districtStats = buildDistrictStats();
  const allAreas = (data.geojson.areas || []).concat(data.geojson.areas_provisional || []);
  const manualAreas = (data.geojson.areas || []).slice();
  const provisionalAreas = (data.geojson.areas_provisional || []).slice();
  const isoglosses = (data.geojson.isoglosses || []).concat(data.geojson.isoglosses_provisional || []);
  const borderBounds = getGeoJsonBounds(data.geojson.border);
  const sortedFeatures = data.features.slice().sort((left, right) => collator.compare(left.alphabet_key || left.feature_name, right.alphabet_key || right.feature_name));
  const atlasSections = (data.meta.sections || []).slice();
  const questionColorPalette = ["#2c5aa0", "#c76a0e", "#147a7e", "#6a49a5", "#8f2d2d", "#648b23"];

  const ui = {
    demoBanner: document.getElementById("demo-banner"),
    themeNightButton: document.getElementById("theme-night-button"),
    themeClassicButton: document.getElementById("theme-classic-button"),
    repositoryLink: document.getElementById("repository-link"),
    searchInput: document.getElementById("global-search"),
    searchResults: document.getElementById("search-results"),
    sectionTabs: document.getElementById("section-tabs"),
    layerControls: document.getElementById("layer-controls"),
    featureCount: document.getElementById("feature-count"),
    questionSelect: document.getElementById("question-select"),
    featureList: document.getElementById("feature-list"),
    selectionCard: document.getElementById("selection-card"),
    legend: document.getElementById("legend"),
    mapStatus: document.getElementById("map-status"),
    mapSourceNote: document.getElementById("map-source-note"),
    modal: document.getElementById("instruction-modal"),
    instructionContent: document.getElementById("instruction-content")
  };

  const state = {
    theme: data.meta.ui_theme || "night",
    search: "",
    section: atlasSections[0] || "",
    selectedFeatureIds: [],
    selectedFeatureId: "",
    selectedPointId: "",
    selectedDistrict: "",
    basemapStatus: "fallback",
    layers: { districts: true, points: true, areas: true, isoglosses: true }
  };

  const map = L.map("map", {
    zoomControl: true,
    attributionControl: true,
    minZoom: data.meta.map.min_zoom,
    maxZoom: data.meta.map.max_zoom,
    maxBounds: borderBounds ? borderBounds.pad(0.015) : undefined,
    maxBoundsViscosity: 1.0,
    worldCopyJump: false
  });

  map.attributionControl.setPrefix("");
  const baseMap = createBaseMap();

  map.createPane("districts");
  map.getPane("districts").style.zIndex = "410";
  map.createPane("areas");
  map.getPane("areas").style.zIndex = "420";
  map.createPane("isoglosses");
  map.getPane("isoglosses").style.zIndex = "430";
  map.createPane("points");
  map.getPane("points").style.zIndex = "440";

  const layerGroups = {
    districts: L.layerGroup().addTo(map),
    areas: L.layerGroup().addTo(map),
    isoglosses: L.layerGroup().addTo(map),
    points: L.layerGroup().addTo(map)
  };

  initialize();

  function initialize() {
    applyTheme(readStoredTheme() || data.meta.ui_theme || "night");
    if (baseMap) {
      baseMap.addTo(map);
    }
    renderDemoBanner();
    renderThemeSwitch();
    renderSectionTabs();
    renderLayerControls();
    renderInstructionContent();
    renderSourceNote();
    renderRepositoryLink();
    bindEvents();
    refresh({ fitMap: true });
  }

  function bindEvents() {
    ui.themeNightButton.addEventListener("click", () => updateTheme("night"));
    ui.themeClassicButton.addEventListener("click", () => updateTheme("classic"));

    ui.searchInput.addEventListener("input", (event) => {
      state.search = event.target.value.trim();
      refresh({ fitMap: false });
    });

    document.getElementById("instruction-button").addEventListener("click", () => setModal(true));
    document.getElementById("close-instruction-button").addEventListener("click", () => setModal(false));
    document.getElementById("clear-selection-button").addEventListener("click", () => {
      state.selectedFeatureIds = [];
      state.selectedFeatureId = "";
      state.selectedPointId = "";
      state.selectedDistrict = "";
      refresh({ fitMap: true });
    });

    ui.questionSelect.addEventListener("change", (event) => {
      const featureId = event.target.value;
      if (!featureId) {
        return;
      }
      applyFeatureSelection(featureId, { clearSpatialSelection: true });
      refresh({ fitMap: true });
    });

    ui.modal.addEventListener("click", (event) => {
      if (event.target === ui.modal || event.target.classList.contains("modal__backdrop")) {
        setModal(false);
      }
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        setModal(false);
      }
    });
  }

  function refresh(options) {
    const settings = Object.assign({ fitMap: false }, options || {});
    renderThemeSwitch();
    renderSectionTabs();
    renderSearchResults();
    renderFeatureList();
    renderSelectionCard();
    renderLegend();
    renderMap(settings.fitMap);
    renderStatus();
  }

  function renderDemoBanner() {
    ui.demoBanner.innerHTML = data.meta.demo_mode ? `<strong>Демо-режим</strong><div class="panel-note">${escapeHtml(data.meta.demo_notice)}</div>` : "";
  }

  function renderThemeSwitch() {
    ui.themeNightButton.classList.toggle("is-active", state.theme === "night");
    ui.themeClassicButton.classList.toggle("is-active", state.theme === "classic");
  }

  function renderRepositoryLink() {
    ui.repositoryLink.href = data.meta.repository_url || "#";
  }

  function updateTheme(theme) {
    try {
      window.localStorage.setItem("dialect-map-theme", theme);
    } catch (error) {
      // Ignore storage errors in restricted embedded environments.
    }
    applyTheme(theme);
    renderThemeSwitch();
  }

  function applyTheme(theme) {
    state.theme = theme || "night";
    document.documentElement.setAttribute("data-theme", state.theme);
  }

  function readStoredTheme() {
    try {
      return window.localStorage.getItem("dialect-map-theme");
    } catch (error) {
      return "";
    }
  }

  function renderSourceNote() {
    const firstSource = (data.meta.boundary_sources || [])[0];
    const boundaryLabel = firstSource ? ` · границы: ${firstSource.name}` : "";
    const baseLabel = data.meta.map.base_label || "реальная подложка";
    ui.mapSourceNote.textContent = state.basemapStatus === "online" ? `Основа: ${baseLabel}${boundaryLabel}` : `Основа: ${baseLabel} недоступна, показан локальный резервный фон${boundaryLabel}`;
  }

  function renderSectionTabs() {
    ui.sectionTabs.innerHTML = "";
    atlasSections.forEach((section) => {
      const button = buttonElement("tab-button" + (state.section === section ? " is-active" : ""), section, () => {
        state.section = section;
        normalizeSelectionForSection();
        refresh({ fitMap: false });
      });
      ui.sectionTabs.appendChild(button);
    });
  }

  function renderLayerControls() {
    ui.layerControls.innerHTML = "";
    [["districts", "Границы районов"], ["points", "Населённые пункты"], ["areas", "Ареалы"], ["isoglosses", "Изоглоссы"]].forEach(([key, label]) => {
      const wrapper = document.createElement("label");
      wrapper.className = "layer-checkbox";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = Boolean(state.layers[key]);
      input.addEventListener("change", () => {
        state.layers[key] = input.checked;
        refresh({ fitMap: false });
      });
      const span = document.createElement("span");
      span.textContent = label;
      wrapper.append(input, span);
      ui.layerControls.appendChild(wrapper);
    });
  }

  function renderSearchResults() {
    const query = normalizeText(state.search);
    if (!query) {
      ui.searchResults.innerHTML = '<div class="panel-note">Поиск работает по населённым пунктам, районам, вопросам и вариантам ответа.</div>';
      return;
    }

    const pointItems = data.points.filter((item) => normalizeText([item.settlement, item.district, item.region].join(" ")).includes(query)).slice(0, 8).map((item) => resultItem(item.settlement, item.district, () => {
      state.selectedPointId = item.point_id;
      state.selectedDistrict = item.district;
      clearSearch();
      refresh({ fitMap: true });
    }));

    const districtItems = Array.from(districtStats.values()).filter((item) => normalizeText(item.name).includes(query)).slice(0, 8).map((item) => resultItem(item.name, `${item.pointCount} пунктов · ${item.observationCount} наблюдений`, () => {
      state.selectedDistrict = item.name;
      state.selectedPointId = "";
      clearSearch();
      refresh({ fitMap: true });
    }));

    const featureItems = getVisibleFeatures().filter((item) => featureMatchesQuery(item, query)).slice(0, 8).map((item) => resultItem(item.feature_name, item.section, () => {
      applyFeatureSelection(item.feature_id, { clearSpatialSelection: true });
      clearSearch();
      refresh({ fitMap: true });
    }));

    ui.searchResults.innerHTML = "";
    [buildSearchGroup("Населённые пункты", pointItems), buildSearchGroup("Районы", districtItems), buildSearchGroup("Вопросы", featureItems)].filter(Boolean).forEach((group) => ui.searchResults.appendChild(group));
    if (!ui.searchResults.children.length) {
      ui.searchResults.innerHTML = '<div class="panel-note">Совпадений не найдено.</div>';
    }
  }

  function renderFeatureList() {
    const visibleFeatures = getVisibleFeatures();
    ui.featureCount.textContent = `Показано вопросов: ${visibleFeatures.length} из ${data.features.length}`;
    ui.featureList.innerHTML = "";
    ui.questionSelect.innerHTML = "";

    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = state.section ? `Выберите вопрос атласа ${state.section}` : "Выберите вопрос";
    ui.questionSelect.appendChild(placeholder);

    visibleFeatures.forEach((feature) => {
      const observationCount = (observationsByFeature.get(feature.feature_id) || []).length;
      const isSelected = state.selectedFeatureIds.includes(feature.feature_id);
      const isPrimary = state.selectedFeatureId === feature.feature_id;
      const option = document.createElement("option");
      option.value = feature.feature_id;
      option.textContent = feature.feature_name;
      option.selected = isPrimary;
      ui.questionSelect.appendChild(option);
      ui.featureList.appendChild(buttonElement("feature-item" + (isSelected ? " is-selected" : "") + (isPrimary ? " is-primary" : ""), `<span class="feature-item__title">${escapeHtml(feature.feature_name)}</span><div class="feature-meta">${escapeHtml(feature.section)} · ${escapeHtml(feature.subsection)}</div><div class="feature-meta">Наблюдений: ${observationCount}</div>`, () => {
        applyFeatureSelection(feature.feature_id, { clearSpatialSelection: true });
        refresh({ fitMap: true });
      }, true));
    });

    if (!visibleFeatures.length) {
      ui.questionSelect.disabled = true;
    } else {
      ui.questionSelect.disabled = false;
    }
  }

  function renderSelectionCard() {
    const selectedPoint = pointsById.get(state.selectedPointId);
    const selectedDistrict = districtStats.get(state.selectedDistrict);
    const selectedFeature = featuresById.get(state.selectedFeatureId);

    if (selectedPoint) {
      ui.selectionCard.innerHTML = renderPointCard(selectedPoint);
      bindDynamicButtons();
      return;
    }
    if (selectedDistrict) {
      ui.selectionCard.innerHTML = renderDistrictCard(selectedDistrict);
      bindDynamicButtons();
      return;
    }
    if (selectedFeature) {
      ui.selectionCard.innerHTML = renderFeatureCard(selectedFeature);
      bindDynamicButtons();
      return;
    }
    ui.selectionCard.innerHTML = '<p class="empty-state">Выберите населённый пункт, район или вопрос.</p>';
  }

  function renderPointCard(point) {
    const allObservations = (observationsByPoint.get(point.point_id) || []).slice().sort((left, right) => {
      const leftFeature = featuresById.get(left.feature_id);
      const rightFeature = featuresById.get(right.feature_id);
      return collator.compare(leftFeature ? leftFeature.feature_name : left.feature_id, rightFeature ? rightFeature.feature_name : right.feature_id);
    });

    const featureButtons = allObservations.map((observation) => {
      const feature = featuresById.get(observation.feature_id);
      const active = state.selectedFeatureId === observation.feature_id;
      return `<button type="button" class="chip-button${active ? " is-active" : ""}" data-action="select-feature" data-feature-id="${escapeAttribute(observation.feature_id)}">${escapeHtml(feature ? feature.feature_name : observation.feature_id)}</button>`;
    }).join("");

    const observationRows = allObservations.length ? allObservations.map((observation) => {
      const feature = featuresById.get(observation.feature_id);
      const variants = [observation.attested_value, observation.secondary_value].filter(Boolean).join(" / ");
      return `<li><strong>${escapeHtml(feature ? feature.feature_name : observation.feature_id)}</strong>: ${escapeHtml(variants || "ответ не указан")}<div class="feature-meta">${escapeHtml([observation.source_year, observation.collector].filter(Boolean).join(" · "))}</div></li>`;
    }).join("") : "<li>Для этого пункта наблюдения пока не добавлены.</li>";

    return `<h3 class="selection-card__title">${escapeHtml(point.settlement)}</h3><div class="selection-card__subtitle">${escapeHtml(point.district)}</div><div class="selection-card__table"><div class="selection-card__label">Регион</div><div class="selection-card__value">${escapeHtml(point.region)}</div><div class="selection-card__label">Координаты</div><div class="selection-card__value">${formatCoordinate(point.latitude)}, ${formatCoordinate(point.longitude)}</div><div class="selection-card__label">Комментарий</div><div class="selection-card__value">${escapeHtml(point.comment || "—")}</div><div class="selection-card__label">Наблюдений</div><div class="selection-card__value">${allObservations.length}</div></div><div class="selection-card__section"><div class="field-label">Вопросы в пункте</div><div class="chip-cloud">${featureButtons || '<span class="panel-note">Наблюдения не заполнены.</span>'}</div></div><div class="selection-card__section"><div class="field-label">Ответы по вопросам</div><ul class="selection-card__list">${observationRows}</ul></div>`;
  }

  function renderDistrictCard(district) {
    const pointButtons = district.points.map((point) => `<button type="button" class="chip-button" data-action="select-point" data-point-id="${escapeAttribute(point.point_id)}">${escapeHtml(point.settlement)}</button>`).join("");
    const topFeatures = district.topFeatures.length ? district.topFeatures.map((item) => `<li>${escapeHtml(item.name)} (${item.count})</li>`).join("") : "<li>Для выбранного района наблюдений пока нет.</li>";
    return `<h3 class="selection-card__title">${escapeHtml(district.name)}</h3><div class="selection-card__subtitle">${escapeHtml(district.adminType)}</div><div class="selection-card__table"><div class="selection-card__label">Населённых пунктов</div><div class="selection-card__value">${district.pointCount}</div><div class="selection-card__label">Наблюдений</div><div class="selection-card__value">${district.observationCount}</div><div class="selection-card__label">Вопросов</div><div class="selection-card__value">${district.featureCount}</div></div><div class="selection-card__section"><div class="field-label">Пункты в районе</div><div class="chip-cloud">${pointButtons || '<span class="panel-note">Пункты пока не привязаны.</span>'}</div></div><div class="selection-card__section"><div class="field-label">Краткая сводка по району</div><ul class="selection-card__list">${topFeatures}</ul></div>`;
  }

  function renderFeatureCard(feature) {
    const observations = observationsByFeature.get(feature.feature_id) || [];
    const manualAreaCount = manualAreas.filter((item) => item.properties.feature_id === feature.feature_id).length;
    const provisionalAreaCount = provisionalAreas.filter((item) => item.properties.feature_id === feature.feature_id).length;
    const relatedFeatureNames = state.selectedFeatureIds.filter((featureId) => featureId !== feature.feature_id).map((featureId) => {
      const item = featuresById.get(featureId);
      return item ? item.feature_name : featureId;
    });
    const mapCoverageNote = buildFeatureCoverageNote(observations.length, manualAreaCount, provisionalAreaCount, relatedFeatureNames.length ? getVisibleIsoglosses().length : 0);
    const settlementButtons = Array.from(new Set(observations.map((item) => item.point_id))).map((pointId) => pointsById.get(pointId)).filter(Boolean).sort((left, right) => collator.compare(left.settlement, right.settlement)).map((point) => `<button type="button" class="chip-button" data-action="select-point" data-point-id="${escapeAttribute(point.point_id)}">${escapeHtml(point.settlement)}</button>`).join("");
    const examples = feature.example_list || [];
    const multiFeatureNote = relatedFeatureNames.length ? `Одновременно выбраны и другие вопросы: ${relatedFeatureNames.join(", ")}.` : "";
    return `<h3 class="selection-card__title">${escapeHtml(feature.feature_name)}</h3><div class="selection-card__subtitle">${escapeHtml(feature.section)} · ${escapeHtml(feature.subsection)}</div>${multiFeatureNote ? `<div class="panel-note">${escapeHtml(multiFeatureNote)}</div>` : ""}<div class="selection-card__table"><div class="selection-card__label">Вопрос</div><div class="selection-card__value">${escapeHtml(feature.question_text || "—")}</div><div class="selection-card__label">Варианты ответа</div><div class="selection-card__value">${escapeHtml(buildLinguisticUnits(feature).join(", ") || "—")}</div><div class="selection-card__label">Наблюдений</div><div class="selection-card__value">${observations.length}</div><div class="selection-card__label">Ручной ареал</div><div class="selection-card__value">${manualAreaCount ? `да (${manualAreaCount})` : "нет"}</div><div class="selection-card__label">Предварительный ареал</div><div class="selection-card__value">${provisionalAreaCount ? `да (${provisionalAreaCount})` : "нет"}</div><div class="selection-card__label">Изоглоссы</div><div class="selection-card__value">${state.selectedFeatureIds.length === 2 ? (getVisibleIsoglosses().length ? `да (${getVisibleIsoglosses().length})` : "нет") : "только для пары вопросов"}</div></div>${mapCoverageNote ? `<div class="panel-note">${escapeHtml(mapCoverageNote)}</div>` : ""}<div class="selection-card__section"><div class="field-label">Примеры ответов</div>${examples.length ? `<ul class="selection-card__list">${examples.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : '<div class="panel-note">Примеры пока не добавлены.</div>'}</div><div class="selection-card__section"><div class="field-label">Населённые пункты</div><div class="chip-cloud">${settlementButtons || '<span class="panel-note">Пункты пока не заполнены.</span>'}</div></div>`;
  }

  function bindDynamicButtons() {
    ui.selectionCard.querySelectorAll("[data-action='select-feature']").forEach((button) => {
      button.addEventListener("click", () => {
        applyFeatureSelection(button.getAttribute("data-feature-id"), { clearSpatialSelection: true });
        refresh({ fitMap: true });
      });
    });

    ui.selectionCard.querySelectorAll("[data-action='select-point']").forEach((button) => {
      button.addEventListener("click", () => {
        const pointId = button.getAttribute("data-point-id");
        const point = pointsById.get(pointId);
        state.selectedPointId = pointId;
        state.selectedDistrict = point ? point.district : "";
        refresh({ fitMap: true });
      });
    });
  }

  function renderLegend() {
    const rows = ['<div class="legend-row"><span class="legend-point"></span><span>Населённый пункт</span></div>', '<div class="legend-row"><span class="legend-point is-selected"></span><span>Выбранный пункт</span></div>', '<div class="legend-row"><span class="legend-line"></span><span>Граница района</span></div>', '<div class="legend-row"><span class="legend-area"></span><span>Ручной ареал</span></div>', '<div class="legend-row"><span class="legend-area is-provisional"></span><span>Предварительный ареал</span></div>', '<div class="legend-row"><span class="legend-line is-isogloss"></span><span>Изоглосса между двумя вопросами</span></div>'];
    if (state.selectedFeatureIds.length) {
      rows.push('<div class="field-label">Активные вопросы</div>');
      state.selectedFeatureIds.forEach((featureId) => {
        const feature = featuresById.get(featureId);
        rows.push(`<div class="legend-row"><span class="legend-swatch" style="background:${getFeatureBaseColor(featureId)}"></span><span>${escapeHtml(feature ? feature.feature_name : featureId)}${featureId === state.selectedFeatureId ? " (активный)" : ""}</span></div>`);
      });
    }
    ui.legend.innerHTML = rows.join("");
  }

  function renderMap(shouldFitMap) {
    layerGroups.districts.clearLayers();
    layerGroups.areas.clearLayers();
    layerGroups.isoglosses.clearLayers();
    layerGroups.points.clearLayers();

    const fitBounds = [];
    if (state.layers.districts) {
      renderDistrictLayers(fitBounds);
    }
    if (state.layers.areas && state.selectedFeatureIds.length) {
      renderAreaLayers(fitBounds);
    }
    if (state.layers.isoglosses && state.selectedFeatureIds.length === 2) {
      renderIsoglossLayers(fitBounds);
    }
    if (state.layers.points) {
      renderPointLayers(fitBounds);
    }
    if (shouldFitMap) {
      fitMapToCurrentSelection(fitBounds);
    }
  }

  function renderDistrictLayers(fitBounds) {
    if (data.geojson.border) {
      const borderLayer = L.geoJSON(data.geojson.border, { pane: "districts", style: { color: "#3f5366", weight: 2.6, fillOpacity: 0.18, fillColor: "#e8eef3" } }).addTo(layerGroups.districts);
      collectLayerBounds(fitBounds, borderLayer);
    }
    if (!data.geojson.districts) {
      return;
    }
    const districtLayer = L.geoJSON(data.geojson.districts, {
      pane: "districts",
      style: (feature) => districtStyle(feature, false),
      onEachFeature: (feature, layer) => {
        const districtName = getDistrictName(feature);
        layer.bindTooltip(districtName, { sticky: true, className: "district-tooltip" });
        layer.on("mouseover", () => layer.setStyle(districtStyle(feature, true)));
        layer.on("mouseout", () => layer.setStyle(districtStyle(feature, false)));
        layer.on("click", () => {
          state.selectedDistrict = districtName;
          state.selectedPointId = "";
          refresh({ fitMap: true });
        });
      }
    }).addTo(layerGroups.districts);
    collectLayerBounds(fitBounds, districtLayer);
  }

  function renderAreaLayers(fitBounds) {
    getVisibleAreas().forEach((feature) => {
      const isProvisional = feature.properties.source === "auto";
      const fillColor = getFeatureBaseColor(feature.properties.feature_id);
      const layer = L.geoJSON(feature, { pane: "areas", style: { color: fillColor, weight: isProvisional ? 2.1 : 1.9, dashArray: isProvisional ? "7 4" : null, fillColor, fillOpacity: isProvisional ? 0.14 : 0.24 } }).bindPopup(buildAreaPopup(feature)).addTo(layerGroups.areas);
      collectLayerBounds(fitBounds, layer);
    });
  }

  function renderIsoglossLayers(fitBounds) {
    getVisibleIsoglosses().forEach((feature) => {
      const styleCode = feature.properties.style_code || "line_isogloss_major";
      const layer = L.geoJSON(feature, { pane: "isoglosses", style: { color: baseStylePalette[styleCode] || baseStylePalette.line_isogloss_major, weight: styleCode === "line_isogloss_minor" ? 2 : 3, dashArray: styleCode === "line_isogloss_minor" ? "8 6" : null, opacity: 0.95 } }).bindPopup(buildIsoglossPopup(feature)).addTo(layerGroups.isoglosses);
      collectLayerBounds(fitBounds, layer);
    });
  }

  function renderPointLayers(fitBounds) {
    getVisiblePoints().forEach((point) => {
      const isSelected = point.point_id === state.selectedPointId;
      const hasFeatureFocus = Boolean(state.selectedFeatureId);
      const hasObservationInFocus = state.selectedFeatureIds.some((featureId) => Boolean(findPointObservation(point.point_id, featureId)));
      const markerRadius = isSelected ? 6.4 : hasObservationInFocus ? 4.2 : 2.2;
      if (isSelected) {
        L.circleMarker([point.latitude, point.longitude], { pane: "points", radius: markerRadius + 4.8, color: "transparent", weight: 0, fillColor: pointFillColor(point), fillOpacity: 0.18, interactive: false }).addTo(layerGroups.points);
      }
      const marker = L.circleMarker([point.latitude, point.longitude], {
        pane: "points",
        radius: markerRadius,
        color: isSelected ? "#0f1720" : hasObservationInFocus ? "#f8fbff" : "#dbe3ea",
        weight: isSelected ? 2.1 : hasObservationInFocus ? 1.1 : 0.4,
        fillColor: pointFillColor(point),
        fillOpacity: isSelected ? 0.98 : hasObservationInFocus ? 0.95 : (hasFeatureFocus ? 0.5 : 0.7)
      });
      marker.bindTooltip(`${point.settlement} (${point.district})`, { sticky: true, className: "point-hover-tooltip", direction: "top", offset: [0, -8] });
      marker.on("click", () => {
        state.selectedPointId = point.point_id;
        state.selectedDistrict = point.district;
        refresh({ fitMap: true });
      });
      marker.addTo(layerGroups.points);
      if (isSelected) {
        marker.bringToFront();
        L.marker([point.latitude, point.longitude], { pane: "points", interactive: false, keyboard: false, icon: L.divIcon({ className: "point-selection-label-anchor", html: `<div class="point-selection-label">${escapeHtml(point.settlement)}</div>`, iconSize: [0, 0], iconAnchor: [-10, 10] }) }).addTo(layerGroups.points);
      }
      if (!state.selectedFeatureIds.length || hasObservationInFocus || isSelected) {
        fitBounds.push(marker.getLatLng());
      }
    });
  }

  function districtStyle(feature, hovered) {
    const selected = getDistrictName(feature) === state.selectedDistrict;
    return { color: selected ? "#53667a" : hovered ? "#6f7d89" : baseStylePalette.boundary_district, weight: selected ? 2.1 : hovered ? 1.7 : 1.15, fillColor: selected ? "#d9e4ee" : hovered ? "#edf3f8" : "#f7fafc", fillOpacity: selected ? 0.28 : hovered ? 0.2 : 0.12 };
  }

  function fitMapToCurrentSelection(bounds) {
    if (state.selectedPointId) {
      const point = pointsById.get(state.selectedPointId);
      if (point) {
        map.setView([point.latitude, point.longitude], Math.max(data.meta.map.focus_zoom, map.getZoom()));
        return;
      }
    }
    if (state.selectedDistrict) {
      const districtLayer = findDistrictLayer(state.selectedDistrict);
      if (districtLayer && districtLayer.getBounds().isValid()) {
        map.fitBounds(districtLayer.getBounds().pad(0.2));
        return;
      }
    }
    if (bounds.length) {
      map.fitBounds(L.latLngBounds(bounds).pad(0.14));
      return;
    }
    if (borderBounds) {
      map.fitBounds(borderBounds.pad(0.04));
    }
  }

  function renderInstructionContent() {
    const lines = String(data.ui_notes || "")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);

    if (!lines.length) {
      ui.instructionContent.innerHTML = "<p>Инструкция пока не добавлена.</p>";
      return;
    }

    const sections = [];
    let currentSection = null;

    lines.forEach((line) => {
      if (/^\d+\.\s+/.test(line)) {
        if (currentSection) {
          sections.push(currentSection);
        }
        currentSection = { title: line.replace(/^\d+\.\s+/, ""), items: [] };
        return;
      }

      const bulletText = line.replace(/^[-•]+\s*/, "");
      if (!currentSection) {
        currentSection = { title: "", items: [] };
      }
      currentSection.items.push(bulletText);
    });

    if (currentSection) {
      sections.push(currentSection);
    }

    ui.instructionContent.innerHTML = sections
      .map((section) => {
        const title = section.title ? `<h3>${escapeHtml(section.title)}</h3>` : "";
        const items = section.items.length
          ? `<ul class="instruction-list">${section.items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
          : "";
        return `<section class="instruction-section">${title}${items}</section>`;
      })
      .join("");
  }

  function renderStatus() {
    const parts = [`Пунктов на карте: ${getVisiblePoints().length}`];
    if (state.selectedFeatureIds.length) {
      parts.push(`Вопросов: ${state.selectedFeatureIds.length}`);
    }
    if (state.selectedFeatureId) {
      const feature = featuresById.get(state.selectedFeatureId);
      parts.push(`Активный вопрос: ${feature ? feature.feature_name : state.selectedFeatureId}`);
    }
    if (state.selectedFeatureIds.length === 2) {
      parts.push(`Изоглосс: ${getVisibleIsoglosses().length}`);
    }
    if (state.selectedDistrict) {
      parts.push(`Район: ${state.selectedDistrict}`);
    }
    if (state.selectedPointId) {
      const point = pointsById.get(state.selectedPointId);
      if (point) {
        parts.push(`Пункт: ${point.settlement}`);
      }
    }
    ui.mapStatus.textContent = parts.join(" · ");
  }

  function setModal(open) {
    ui.modal.classList.toggle("is-open", open);
    ui.modal.setAttribute("aria-hidden", open ? "false" : "true");
    document.body.classList.toggle("modal-open", open);
  }

  function buildSearchGroup(title, buttons) {
    if (!buttons.length) {
      return null;
    }
    const wrapper = document.createElement("div");
    wrapper.className = "search-group";
    const heading = document.createElement("div");
    heading.className = "search-group-title";
    heading.textContent = title;
    wrapper.appendChild(heading);
    buttons.forEach((button) => wrapper.appendChild(button));
    return wrapper;
  }

  function resultItem(label, meta, onClick) {
    return buttonElement("result-button", `<strong>${escapeHtml(label)}</strong><div class="result-meta">${escapeHtml(meta)}</div>`, onClick, true);
  }

  function buttonElement(className, content, onClick, isHtml) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    if (isHtml) {
      button.innerHTML = content;
    } else {
      button.textContent = content;
    }
    button.addEventListener("click", onClick);
    return button;
  }

  function applyFeatureSelection(featureId, options) {
    const settings = Object.assign({ clearSpatialSelection: false }, options || {});
    const isSelected = state.selectedFeatureIds.includes(featureId);
    const isPrimary = state.selectedFeatureId === featureId;
    if (!isSelected) {
      if (state.selectedFeatureIds.length >= 2) {
        state.selectedFeatureIds = state.selectedFeatureIds.slice(1);
      }
      state.selectedFeatureIds = state.selectedFeatureIds.concat(featureId);
      state.selectedFeatureId = featureId;
    } else if (!isPrimary) {
      state.selectedFeatureId = featureId;
    } else {
      state.selectedFeatureIds = state.selectedFeatureIds.filter((item) => item !== featureId);
      state.selectedFeatureId = state.selectedFeatureIds[state.selectedFeatureIds.length - 1] || "";
    }
    if (settings.clearSpatialSelection) {
      state.selectedPointId = "";
      state.selectedDistrict = "";
    }
  }

  function normalizeSelectionForSection() {
    if (!state.section) {
      return;
    }
    state.selectedFeatureIds = state.selectedFeatureIds.filter((featureId) => {
      const feature = featuresById.get(featureId);
      return feature && feature.section === state.section;
    });
    if (!state.selectedFeatureIds.includes(state.selectedFeatureId)) {
      state.selectedFeatureId = state.selectedFeatureIds[state.selectedFeatureIds.length - 1] || "";
    }
  }

  function getVisibleFeatures() {
    const query = normalizeText(state.search);
    return sortedFeatures.filter((feature) => (!state.section || feature.section === state.section) && (!query || featureMatchesQuery(feature, query)));
  }

  function getVisiblePoints() {
    const query = normalizeText(state.search);
    return data.points.filter((point) => {
      if (point.latitude == null || point.longitude == null) {
        return false;
      }
      if (state.selectedPointId && point.point_id === state.selectedPointId) {
        return true;
      }
      if (state.selectedDistrict && point.district !== state.selectedDistrict) {
        return false;
      }
      if (!matchesPointSearch(point, query)) {
        return false;
      }
      return true;
    });
  }

  function getVisibleAreas() {
    return allAreas.filter((feature) => state.selectedFeatureIds.includes(feature.properties.feature_id) && getAreaScope(feature) === "feature");
  }

  function getVisibleIsoglosses() {
    if (state.selectedFeatureIds.length !== 2) {
      return [];
    }
    const selectedPair = state.selectedFeatureIds.slice().sort();
    return isoglosses.filter((feature) => {
      const pair = (feature.properties.feature_pair || []).slice().sort();
      return pair.length === 2 && pair[0] === selectedPair[0] && pair[1] === selectedPair[1];
    });
  }

  function buildLinguisticUnits(feature) {
    return [feature.linguistic_unit_1, feature.linguistic_unit_2, feature.linguistic_unit_3].filter(Boolean);
  }

  function findPointObservation(pointId, featureId) {
    return (observationsByPoint.get(pointId) || []).find((item) => item.feature_id === featureId);
  }

  function getAreaScope(feature) {
    return feature.properties.scope || (feature.properties.attested_value ? "value" : "feature");
  }

  function buildFeatureCoverageNote(observationCount, manualAreaCount, provisionalAreaCount, isoglossCount) {
    if (!observationCount) {
      return "Для этого вопроса пока нет наблюдений в наборе данных.";
    }
    if (manualAreaCount || provisionalAreaCount || isoglossCount) {
      return "";
    }
    return "Для этого вопроса сейчас показаны связанные точки без отдельного ареала и без изоглоссы.";
  }

  function createBaseMap() {
    if (!L.maplibreGL || typeof maplibregl === "undefined") {
      return null;
    }
    const layer = L.maplibreGL({ style: "https://tiles.openfreemap.org/styles/liberty" });
    state.basemapStatus = "online";
    return layer;
  }

  function groupBy(items, key) {
    const buckets = new Map();
    items.forEach((item) => {
      const groupKey = item[key];
      const current = buckets.get(groupKey) || [];
      current.push(item);
      buckets.set(groupKey, current);
    });
    return buckets;
  }

  function groupPointsByDistrict() {
    const buckets = new Map();
    data.points.forEach((point) => {
      const current = buckets.get(point.district) || [];
      current.push(point);
      buckets.set(point.district, current);
    });
    buckets.forEach((points, district) => {
      points.sort((left, right) => collator.compare(left.settlement, right.settlement));
      buckets.set(district, points);
    });
    return buckets;
  }

  function buildDistrictStats() {
    const stats = new Map();
    if (data.geojson.districts) {
      data.geojson.districts.features.forEach((feature) => {
        const name = getDistrictName(feature);
        stats.set(name, { name, adminType: (feature.properties && feature.properties.admin_type) || "район", points: districtPoints.get(name) || [], pointCount: (districtPoints.get(name) || []).length, observationCount: 0, featureCounts: new Map(), featureCount: 0, topFeatures: [] });
      });
    }
    data.points.forEach((point) => {
      if (!stats.has(point.district)) {
        stats.set(point.district, { name: point.district, adminType: "район", points: districtPoints.get(point.district) || [], pointCount: (districtPoints.get(point.district) || []).length, observationCount: 0, featureCounts: new Map(), featureCount: 0, topFeatures: [] });
      }
    });
    data.observations.forEach((observation) => {
      const point = pointsById.get(observation.point_id);
      if (!point || !stats.has(point.district)) {
        return;
      }
      const item = stats.get(point.district);
      item.observationCount += 1;
      item.featureCounts.set(observation.feature_id, (item.featureCounts.get(observation.feature_id) || 0) + 1);
    });
    stats.forEach((item) => {
      item.featureCount = item.featureCounts.size;
      item.topFeatures = Array.from(item.featureCounts.entries()).map(([featureId, count]) => {
        const feature = featuresById.get(featureId);
        return { name: feature ? feature.feature_name : featureId, count };
      }).sort((left, right) => right.count - left.count || collator.compare(left.name, right.name)).slice(0, 6);
    });
    return stats;
  }

  function getFeatureBaseColor(featureId) {
    const selectedIndex = state.selectedFeatureIds.indexOf(featureId);
    if (selectedIndex >= 0) {
      return questionColorPalette[selectedIndex % questionColorPalette.length];
    }
    return questionColorPalette[Math.abs(hashString(featureId)) % questionColorPalette.length];
  }

  function pointFillColor(point) {
    if (!state.selectedFeatureIds.length) {
      return "#3d78a8";
    }
    if (state.selectedFeatureId && findPointObservation(point.point_id, state.selectedFeatureId)) {
      return getFeatureBaseColor(state.selectedFeatureId);
    }
    for (const featureId of state.selectedFeatureIds) {
      if (findPointObservation(point.point_id, featureId)) {
        return getFeatureBaseColor(featureId);
      }
    }
    return "#aebbc7";
  }

  function featureMatchesQuery(feature, query) {
    return normalizeText([feature.feature_name, feature.section, feature.subsection, feature.alphabet_key, feature.question_text, feature.linguistic_unit_1, feature.linguistic_unit_2, feature.linguistic_unit_3, (feature.example_list || []).join(" ")].join(" ")).includes(query);
  }

  function matchesPointSearch(point, query) {
    if (!query) {
      return true;
    }
    return normalizeText([point.settlement, point.district, point.region].join(" ")).includes(query);
  }

  function hashString(value) {
    let hash = 0;
    for (const symbol of String(value || "")) {
      hash = ((hash << 5) - hash) + symbol.charCodeAt(0);
      hash |= 0;
    }
    return hash;
  }

  function findDistrictLayer(districtName) {
    let result = null;
    layerGroups.districts.eachLayer((layer) => {
      if (layer.feature && getDistrictName(layer.feature) === districtName) {
        result = layer;
      }
    });
    return result;
  }

  function collectLayerBounds(target, layer) {
    if (layer.getBounds && layer.getBounds().isValid()) {
      target.push(layer.getBounds().getSouthWest(), layer.getBounds().getNorthEast());
    }
  }

  function getGeoJsonBounds(geojson) {
    if (!geojson) {
      return null;
    }
    const layer = L.geoJSON(geojson);
    const bounds = layer.getBounds();
    return bounds.isValid() ? bounds : null;
  }

  function buildAreaPopup(feature) {
    const featureMeta = featuresById.get(feature.properties.feature_id);
    const featureLabel = featureMeta ? featureMeta.feature_name : feature.properties.feature_id;
    return `<strong>${escapeHtml(feature.properties.title || "Ареал")}</strong><br>Вопрос: ${escapeHtml(featureLabel)}<br>Источник: ${feature.properties.source === "auto" ? "предварительная генерация" : "ручной GeoJSON"}<br>${escapeHtml(feature.properties.status_note || "")}`;
  }

  function buildIsoglossPopup(feature) {
    const pair = feature.properties.feature_pair || [];
    const labels = pair.map((featureId) => {
      const featureMeta = featuresById.get(featureId);
      return featureMeta ? featureMeta.feature_name : featureId;
    });
    return `<strong>Изоглосса</strong><br>Пара вопросов: ${escapeHtml(labels.join(" ↔ "))}<br>Источник: ${feature.properties.source === "auto" ? "автоматическая демонстрационная линия" : "ручной GeoJSON"}<br>Стиль: ${escapeHtml(feature.properties.style_code || "line_isogloss_major")}`;
  }

  function getDistrictName(feature) {
    return (feature.properties && feature.properties.name) || "Район";
  }

  function clearSearch() {
    state.search = "";
    ui.searchInput.value = "";
  }

  function normalizeText(value) {
    return String(value || "").toLowerCase().replace(/ё/g, "е").replace(/[-']/g, " ").replace(/\s+/g, " ").trim();
  }

  function formatCoordinate(value) {
    return value == null ? "—" : Number(value).toFixed(4);
  }

  function escapeHtml(value) {
    return String(value || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function escapeAttribute(value) {
    return escapeHtml(value).replace(/\"/g, "&quot;");
  }
})();
