import React, { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

export default function PNGMapSWT({ staticData = [], onProvinceSelect = () => {} }) {
  const mapRef = useRef(null);
  const containerId = "swtHeatMapContainer";

  // SAME AS GST — removes spaces & non letters
  const normalize = (s) =>
    (s || "").trim().toLowerCase().replace(/[^a-z]/g, "");

  useEffect(() => {

    console.log(
      "%cSTATIC DATA RECEIVED BY MAP:",
      "color:#ff5722;font-size:16px;font-weight:bold",
      staticData
    );

    if (mapRef.current) {
      mapRef.current.remove();
      mapRef.current = null;
    }

    const container = L.DomUtil.get(containerId);
    if (!container) return;

    if (container._leaflet_id) container._leaflet_id = null;

    const map = L.map(containerId, {
      zoomControl: true,
      dragging: true,
      scrollWheelZoom: true,
    });

    mapRef.current = map;

    fetch("/data/png-provinces.geojson")
      .then((r) => r.json())
      .then((geojson) => {
        const dataLookup = new Map();
        

        // BUILD LOOKUP FROM API
        staticData.forEach((d) => {
          const apiRaw = d.province;
          const apiNorm = normalize(apiRaw);
          console.log(
                "%cLOOKUP KEY ADDED:",
                "color:green;font-weight:bold",
                `"${apiNorm}"`
              );


          console.log(
            "%cAPI Province →",
            "color:#2196f3;font-weight:bold",
            `"${apiRaw}" -> "${apiNorm}"`
          );

          dataLookup.set(apiNorm, {
            fraud_count: d.fraud_count ?? 0,
            risk_percentage: d.risk_percentage ?? 0,
          });
        });

        const getColor = (value) => {
          const reds = [
            [255, 245, 240],[254, 224, 210],[252, 187, 161],
            [252, 146, 114],[251, 106, 74],[239, 59, 44],
            [203, 24, 29],[165, 15, 21],[103, 0, 13],
          ];
          const i = Math.min(8, Math.floor((value / 100) * 9));
          return `rgb(${reds[i][0]},${reds[i][1]},${reds[i][2]})`;
        };

        const provinceLayer = L.geoJSON(geojson, {
          style: (feature) => {
            const geoRaw = feature.properties.PROVNAME;
            const geoNorm = normalize(geoRaw);

            const match = dataLookup.has(geoNorm);

            console.log(
              `%cMatching Province:`,
              "color:purple;font-weight:bold",
              `GeoJSON="${geoRaw}" → Norm="${geoNorm}" → Match=`,
              match ? "%cYES" : "%cNO",
              match
                ? "color:green;font-weight:bold"
                : "color:red;font-weight:bold"
            );

            const rec = dataLookup.get(geoNorm) || {
              fraud_count: 0,
              risk_percentage: 0,
            };

            // return {
            //   color: "#000",
            //   weight: 1,
            //   fillColor: getColor(rec.risk_percentage),
            //   fillOpacity: 1,
            // };
            const risk = rec.risk_percentage || 0;

            const classes = ["province-heat"];
            if (risk >= 70) {
              classes.push("province-blink");
            }

            return {
              color: "#000",
              weight: 1,
              fillColor: getColor(risk),
              fillOpacity: 0.85,
              className: classes.join(" "),
            };
          },

          onEachFeature: (feature, layer) => {
            const geoNorm = normalize(feature.properties.PROVNAME);
            const rec = dataLookup.get(geoNorm) || {
              fraud_count: 0,
              risk_percentage: 0,
            };

            layer.bindTooltip(
              `<b>${feature.properties.PROVNAME}</b><br>
               Fraud Count: ${rec.fraud_count}<br>
               Risk %: ${rec.risk_percentage}`,
              { sticky: true }
            );

            layer.on("click", () =>
              onProvinceSelect(feature.properties.PROVNAME, rec)
            );
          },
        }).addTo(map);

        const bounds = provinceLayer.getBounds();
        if (bounds.isValid()) {
          map.fitBounds(bounds, { padding: [15, 15] });
        } else {
          map.setView([-6.315, 143.9555], 6);
        }

        // RESET BUTTON
                const reset = L.control({ position: "topright" });
                reset.onAdd = () => {
                  const div = L.DomUtil.create("div", "leaflet-bar leaflet-control");
                  div.innerHTML = `<a style="padding:6px;font-size:18px;cursor:pointer;">⟳</a>`;
                  div.onclick = () => map.fitBounds(provinceLayer.getBounds());
                  return div;
                };
                reset.addTo(map);
        
                
        
                // -------------------------
                // COLOR LEGEND (VERTICAL)
                // -------------------------
                // Create custom right-center control position
                L.Control.CustomPositions = Object.assign({}, L.Control.CustomPositions, {
                  rightcenter: "rightcenter",
                });
        
                // -------------------------
                // COLOR LEGEND (VERTICAL)
                // -------------------------
                const legend = L.control({ position: "topright" });
        
                legend.onAdd = function () {
                  const div = L.DomUtil.create("div", "info legend");
        
                  const grades = [100, 90, 80, 70, 60, 50, 40, 30, 20, 10, 0];
        
                  div.style.background = "#fff";
                  div.style.padding = "10px";
                  div.style.border = "1px solid #ccc";
                  div.style.borderRadius = "6px";
                  div.style.fontSize = "12px";
                  div.style.boxShadow = "0 2px 6px rgba(0,0,0,0.3)";
                  div.style.width = "120px";
        
                  div.innerHTML = `<div style="font-weight:bold; margin-bottom:6px;">Risk (%)</div>`;
        
                  grades.forEach((g, i) => {
                    if (i === grades.length - 1) return;
        
                    const from = grades[i];
                    const to = grades[i + 1];
        
                    const row = `
                      <div style="
                        display:flex;
                        align-items:center;
                        margin-bottom:4px;
                      ">
                        <span style="
                          display:inline-block;
                          width:18px;
                          height:18px;
                          background:${getColor(from)};
                          border:1px solid #777;
                          margin-right:6px;
                        "></span>
                        <span>${to} – ${from}</span>
                      </div>
                    `;
        
                    div.innerHTML += row;
                  });
        
                  return div;
                };
        
                legend.addTo(map);

      });

    return () => {
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
    };
  }, [staticData]);

  return (
    <div
      id={containerId}
      style={{ width: "100%", height: "550px", borderRadius: "8px" }}
    />
  );
}