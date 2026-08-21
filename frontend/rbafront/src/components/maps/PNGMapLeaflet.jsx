import React, { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

export default function PNGMapLeaflet({
  containerId = "pngMapContainer",
  geoJsonUrl = "/data/png-provinces.geojson",
  staticData = [],
  onProvinceSelect = () => {},
}) {
  const mapRef = useRef(null);

  const normalize = (s) =>
    (s || "").trim().toLowerCase().replace(/[^a-z]/g, "");

  useEffect(() => {
    //-----------------------------------------
    // HARD RESET: DESTROY PREVIOUS MAP SAFELY
    //-----------------------------------------
    if (mapRef.current) {
      mapRef.current.remove();
      mapRef.current = null;
    }

    const container = L.DomUtil.get(containerId);

    // FIX: if container already has a map
    if (container && container._leaflet_id) {
      try {
        container._leaflet_id = null;
      } catch (e) {}
    }

    //-----------------------------------------
    // CREATE MAP
    //-----------------------------------------
    const map = L.map(containerId, {
      zoomControl: true,
      scrollWheelZoom: true,
      dragging: true,
      doubleClickZoom: true,
    });

    mapRef.current = map;

    fetch(geoJsonUrl)
      .then((r) => r.json())
      .then((geojson) => {
        //-------------------------------
        // 1) Group risk by province
        //-------------------------------
        const riskMap = new Map();

        staticData.forEach((d) => {
          const prov = normalize(d.province);
          const risk = Number(d.risk_percentage) || 0;

          if (!riskMap.has(prov)) riskMap.set(prov, []);
          riskMap.get(prov).push(risk);
        });

        const avgRisk = new Map();
        riskMap.forEach((arr, prov) => {
          avgRisk.set(prov, Math.round(arr.reduce((a, b) => a + b, 0) / arr.length));
        });

        //---------------------------------------
        // 2) Python Matplotlib Reds (Levels)
        //---------------------------------------
        const reds = [
          [255, 245, 240],
          [254, 224, 210],
          [252, 187, 161],
          [252, 146, 114],
          [251, 106, 74],
          [239, 59, 44],
          [203, 24, 29],
          [165, 15, 21],
          [103, 0, 13],
        ];

        const getColor = (value) => {
          const i = Math.min(8, Math.floor((value / 100) * 9));
          const [r, g, b] = reds[i];
          return `rgb(${r},${g},${b})`;
        };

        //---------------------------------------
        // 3) Draw map
        //---------------------------------------
        const layer = L.geoJSON(geojson, {
          style: (feature) => {
            const prov = normalize(feature.properties.PROVNAME);
            const risk = avgRisk.get(prov) || 0;

            return {
              color: "#000",
              weight: 1,
              fillColor: getColor(risk),
              fillOpacity: 1,
            };
          },
          onEachFeature: (feature, lay) => {
            const prov = normalize(feature.properties.PROVNAME);
            const risk = avgRisk.get(prov) || 0;

            lay.bindTooltip(
              `<b>${feature.properties.PROVNAME}</b><br>Risk %: ${risk}`,
              { sticky: true }
            );

            lay.on("click", () => {
              onProvinceSelect(feature.properties.PROVNAME, risk);
            });
          },
        }).addTo(map);

        map.fitBounds(layer.getBounds(), { padding: [15, 15] });

        //---------------------------------------
        // 4) Reset Button
        //---------------------------------------
        const reset = L.control({ position: "topright" });
        reset.onAdd = () => {
          const div = L.DomUtil.create("div", "leaflet-bar leaflet-control");
          div.innerHTML = `<a style="padding:6px;font-size:18px;cursor:pointer;">⟳</a>`;
          div.onclick = () => map.fitBounds(layer.getBounds(), { padding: [15, 15] });
          return div;
        };
        reset.addTo(map);

        //---------------------------------------
        // 5) Legend
        //---------------------------------------
        const legend = L.control({ position: "right" });

        legend.onAdd = () => {
          const div = L.DomUtil.create("div", "legend");
          div.style.background = "#fff";
          div.style.padding = "10px";
          div.style.border = "1px solid #ccc";
          div.innerHTML = `<b>Risk Heatmap</b><br/>`;

          [0, 20, 40, 60, 80, 100].forEach((v) => {
            div.innerHTML += `
              <div style="display:flex;align-items:center;margin-top:3px;">
                <div style="width:20px;height:12px;background:${getColor(v)};margin-right:6px;"></div>
                ${v}%
              </div>
            `;
          });

          return div;
        };

        legend.addTo(map);
      });

    //-----------------------------------------
    // Cleanup
    //-----------------------------------------
    return () => {
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
    };
  }, [containerId, geoJsonUrl, staticData]);

  return (
    <div
      id={containerId}
      style={{
        width: "100%",
        height: "550px",
        borderRadius: "8px",
        overflow: "hidden",
      }}
    />
  );
}